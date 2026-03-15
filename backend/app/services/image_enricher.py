"""Vision LLM image analysis service (S134).

Processes ImageModel rows with description=null, calling a vision LLM (llava:13b)
to classify each image and generate a text description.  Descriptions are embedded
and stored in LanceDB image_vectors_v1 and indexed in the images_fts FTS5 table.

Pre-filter: images with <5 unique colors (solid-color) or aspect ratio >10:1 (rule
lines) are classified as 'decorative' without any LLM call.

Offline degradation: if the vision model is unreachable (ServiceUnavailableError),
the exception propagates so the EnrichmentQueueWorker marks the job 'failed'.
The document remains fully accessible without image analysis.
"""

import asyncio
import base64
import json
import logging
from pathlib import Path

import litellm

logger = logging.getLogger(__name__)

_VISION_PROMPT = (
    "Task 1: Classify this image as one of: architecture_diagram, "
    "sequence_diagram, er_diagram, flowchart, code_screenshot, table, "
    "chart, photo, decorative, other. "
    "Task 2: List every labeled component visible and any connections between them. "
    "Task 3: Extract any visible text verbatim. "
    "Respond in JSON: "
    '{"image_type": "...", "components": [...], "text": "...", "description": "..."}'
)

# Semaphore to limit concurrent LLM calls (avoids OOM on large PDFs)
_ENRICH_SEM = asyncio.Semaphore(3)


def _is_decorative(pil_image: object) -> bool:
    """Return True if the image is decorative (solid-color or extreme aspect ratio).

    Solid-color check: fewer than 5 unique RGB pixel values.
    Rule-line check: max(w, h) / min(w, h) > 10.
    """

    img = pil_image  # type: ignore[assignment]
    img_rgb = img.convert("RGB")  # type: ignore[attr-defined]
    pixels = list(img_rgb.getdata())
    if len(set(pixels)) < 5:
        return True
    w, h = img.size  # type: ignore[attr-defined]
    ratio = max(w, h) / max(min(w, h), 1)
    return ratio > 10.0


async def _call_vision_llm(image_path: Path, settings: object) -> dict:
    """Call the vision LLM and return parsed JSON response.

    Falls back to {"image_type": "other", "description": raw_text, ...} if JSON parse fails.
    Raises litellm.ServiceUnavailableError if the vision model is unreachable.
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    response = await litellm.acompletion(
        model=settings.VISION_MODEL,  # type: ignore[attr-defined]
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        temperature=0.0,
    )
    raw = (response.choices[0].message.content or "").strip()

    # Strip optional markdown code fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("not a dict")
        return parsed
    except (json.JSONDecodeError, ValueError):
        logger.warning("_call_vision_llm: JSON parse failed, using raw text as description")
        return {
            "image_type": "other",
            "description": raw,
            "components": [],
            "text": "",
        }


class ImageEnricherService:
    """Processes un-described ImageModel rows for a document using a vision LLM."""

    async def enrich(self, document_id: str) -> int:
        """Analyze all ImageModel rows with description=null for document_id.

        Returns the count of images successfully analyzed (decorative or LLM-described).
        """
        from sqlalchemy import select as _select  # noqa: PLC0415
        from sqlalchemy import text as _text
        from sqlalchemy import update as _update

        from app.config import get_settings as _get_settings  # noqa: PLC0415
        from app.database import get_session_factory  # noqa: PLC0415
        from app.models import ImageModel  # noqa: PLC0415
        from app.services.embedder import get_embedding_service  # noqa: PLC0415
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        settings = _get_settings()
        data_dir = Path(settings.DATA_DIR).expanduser()

        # Load all ImageModel rows with description=null for this document
        async with get_session_factory()() as session:
            result = await session.execute(
                _select(ImageModel).where(
                    ImageModel.document_id == document_id,
                    ImageModel.description.is_(None),
                )
            )
            images = list(result.scalars().all())

        if not images:
            logger.info("image_enricher: no un-described images for doc=%s", document_id)
            return 0

        logger.info(
            "image_enricher: processing %d images for doc=%s", len(images), document_id
        )

        processed = 0
        embedder = get_embedding_service()
        lancedb_svc = get_lancedb_service()

        for img in images:
            abs_path = data_dir / img.path
            if not abs_path.exists():
                logger.warning(
                    "image_enricher: image file not found path=%s doc=%s", img.path, document_id
                )
                continue

            async with _ENRICH_SEM:
                try:
                    from PIL import Image as _PILImage  # noqa: PLC0415

                    pil_img = _PILImage.open(str(abs_path))

                    if _is_decorative(pil_img):
                        image_type = "decorative"
                        description = "Decorative image"
                        logger.debug(
                            "image_enricher: decorative image_id=%s", img.id
                        )
                    else:
                        parsed = await _call_vision_llm(abs_path, settings)
                        image_type = parsed.get("image_type") or "other"
                        description = parsed.get("description") or ""

                    # Embed description before any DB writes so a CPU/OOM failure
                    # does not leave the SQLite row updated without an FTS5 entry.
                    vector = embedder.encode([description])[0]

                    # Update SQLite (image_type + description) and insert FTS5 entry
                    # in a single session/transaction so both succeed or both roll back.
                    # If this commit fails, description stays null and the image will
                    # be retried on the next image_analyze job.
                    async with get_session_factory()() as session:
                        await session.execute(
                            _update(ImageModel)
                            .where(ImageModel.id == img.id)
                            .values(image_type=image_type, description=description)
                        )
                        await session.execute(
                            _text(
                                "INSERT INTO images_fts(image_id, document_id, body) "
                                "VALUES (:image_id, :document_id, :body)"
                            ),
                            {"image_id": img.id, "document_id": document_id, "body": description},
                        )
                        await session.commit()

                    # Store vector in LanceDB (outside SQLite transaction — LanceDB
                    # has no cross-store atomicity with SQLite; failure here is logged
                    # and caught below so the image is still keyword-searchable via FTS5).
                    lancedb_svc.upsert_image_vector(img.id, document_id, description, vector)

                    processed += 1
                    logger.info(
                        "image_enricher: analyzed image_id=%s type=%s", img.id, image_type
                    )

                except litellm.ServiceUnavailableError:
                    logger.warning(
                        "image_enricher: vision model unavailable for image_id=%s "
                        "-- Ollama is unreachable, start with: ollama serve",
                        img.id,
                    )
                    raise
                except Exception as exc:
                    logger.warning(
                        "image_enricher: failed to analyze image_id=%s: %s", img.id, exc
                    )
                    continue

        logger.info(
            "image_enricher: enrichment complete doc=%s processed=%d total=%d",
            document_id,
            processed,
            len(images),
        )
        return processed


async def image_analyze_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='image_analyze'.

    Called by EnrichmentQueueWorker for each image_analyze job.
    Delegates to ImageEnricherService.enrich().
    Non-fatal wrapper: ServiceUnavailableError propagates to mark job 'failed'.
    """
    logger.info(
        "image_analyze_handler: starting doc=%s job=%s", document_id, job_id
    )
    svc = ImageEnricherService()
    await svc.enrich(document_id)
    logger.info(
        "image_analyze_handler: done doc=%s job=%s", document_id, job_id
    )
