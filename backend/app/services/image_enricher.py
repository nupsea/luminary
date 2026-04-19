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
import numpy as np

logger = logging.getLogger(__name__)

_VISION_PROMPT = (
    "Classify this image as one of: architecture_diagram, sequence_diagram, "
    "er_diagram, flowchart, code_screenshot, table, chart, photo, other.\n"
    "Then describe what the image shows in 1-2 sentences.\n"
    'Reply ONLY with JSON: {"image_type": "...", "description": "..."}'
)

# Semaphore to limit concurrent LLM calls (avoids OOM on large PDFs)
_ENRICH_SEM = asyncio.Semaphore(1)


def _is_decorative(pil_image: object) -> bool:
    """Return True if the image is decorative (solid-color or extreme aspect ratio).

    Solid-color check: fewer than 5 unique RGB pixel values.
    Rule-line check: max(w, h) / min(w, h) > 10.
    """

    img = pil_image  # type: ignore[assignment]
    img_rgb = img.convert("RGB")  # type: ignore[attr-defined]
    pixels = np.array(img_rgb).reshape(-1, 3)
    unique_count = len(np.unique(pixels, axis=0))
    if unique_count < 5:
        return True
    w, h = img.size  # type: ignore[attr-defined]
    ratio = max(w, h) / max(min(w, h), 1)
    return ratio > 10.0


async def _call_vision_llm(image_path: Path, settings: object) -> dict:
    """Call the vision LLM and return parsed JSON response.

    Falls back to {"image_type": "other", "description": raw_text, ...} if JSON parse fails.
    Raises litellm.ServiceUnavailableError / APIConnectionError if no model is reachable.

    When VISION_MODEL is an Ollama model and Ollama is unreachable, automatically falls
    back to LITELLM_DEFAULT_MODEL (e.g. a cloud model) if it is not Ollama-based.
    """
    vision_model: str = settings.VISION_MODEL  # type: ignore[attr-defined]
    default_model: str = settings.LITELLM_DEFAULT_MODEL  # type: ignore[attr-defined]

    # Build list of models to try: primary first, then cloud fallback if primary is Ollama.
    models_to_try: list[str] = [vision_model]
    if vision_model.startswith("ollama/") and not default_model.startswith("ollama/"):
        models_to_try.append(default_model)

    # Resize large images to reduce inference time and avoid timeouts.
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image as _PILImage  # noqa: PLC0415

    img = _PILImage.open(image_path)
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    last_exc: Exception | None = None
    for model in models_to_try:
        try:
            # Pass api_base for Ollama models so Docker's host.docker.internal
            # routing is respected (OLLAMA_URL overrides LiteLLM's localhost default).
            extra_kwargs: dict = {}
            if model.startswith("ollama/"):
                extra_kwargs["api_base"] = settings.OLLAMA_URL  # type: ignore[attr-defined]
            response = await litellm.acompletion(
                model=model,
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
                timeout=300.0,
                **extra_kwargs,
            )
            if model != vision_model:
                logger.info(
                    "_call_vision_llm: VISION_MODEL (%s) unreachable; used fallback model %s",
                    vision_model,
                    model,
                )
            break
        except (litellm.APIConnectionError, litellm.ServiceUnavailableError) as exc:
            last_exc = exc
            logger.debug("_call_vision_llm: model %s unavailable (%s), trying next", model, exc)
            continue
    else:
        # All models exhausted — raise the last connection error so the job is marked failed.
        assert last_exc is not None
        raise last_exc
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

        logger.info("image_enricher: processing %d images for doc=%s", len(images), document_id)

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
                        logger.debug("image_enricher: decorative image_id=%s", img.id)
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
                    logger.info("image_enricher: analyzed image_id=%s type=%s", img.id, image_type)

                except (litellm.ServiceUnavailableError, litellm.APIConnectionError):
                    logger.warning(
                        "image_enricher: vision model(s) unreachable for image_id=%s "
                        "(VISION_MODEL=%s). In cloud mode, set VISION_MODEL to a "
                        "cloud vision model (e.g. anthropic/claude-3-5-sonnet-20241022) "
                        "or leave Ollama running locally.",
                        img.id,
                        settings.VISION_MODEL,
                    )
                    raise
                except Exception as exc:
                    logger.warning("image_enricher: failed to analyze image_id=%s: %s", img.id, exc)
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

    After enrich() completes, enqueues a 'diagram_extract' job if any qualifying
    diagram images (architecture_diagram, sequence_diagram, er_diagram, flowchart)
    were produced. Uses a deduplication check to avoid enqueueing multiple jobs on
    retry (checks for existing pending/running diagram_extract jobs).
    """
    logger.info("image_analyze_handler: starting doc=%s job=%s", document_id, job_id)
    svc = ImageEnricherService()
    await svc.enrich(document_id)
    logger.info("image_analyze_handler: done doc=%s job=%s", document_id, job_id)

    # Enqueue diagram_extract if qualifying diagram images now exist (S136)
    _QUALIFYING_DIAGRAM_TYPES = [
        "architecture_diagram",
        "sequence_diagram",
        "er_diagram",
        "flowchart",
    ]
    try:
        import uuid as _uuid  # noqa: PLC0415
        from datetime import UTC  # noqa: PLC0415
        from datetime import datetime as _dt

        from sqlalchemy import func as _func  # noqa: PLC0415
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.database import get_session_factory as _get_sf  # noqa: PLC0415
        from app.models import EnrichmentJobModel as _EJM  # noqa: PLC0415
        from app.models import ImageModel as _ImageModel  # noqa: PLC0415

        async with _get_sf()() as session:
            # Check if any qualifying diagram images exist for this document
            has_diagrams_result = await session.execute(
                _select(_ImageModel.id)
                .where(
                    _ImageModel.document_id == document_id,
                    _ImageModel.image_type.in_(_QUALIFYING_DIAGRAM_TYPES),
                    _ImageModel.description.is_not(None),
                )
                .limit(1)
            )
            has_diagrams = has_diagrams_result.scalar_one_or_none() is not None

        if not has_diagrams:
            logger.debug(
                "image_analyze_handler: no qualifying diagram images for doc=%s, "
                "skipping diagram_extract enqueue",
                document_id,
            )
            return

        async with _get_sf()() as session:
            # Deduplication: skip if a pending/running diagram_extract job already exists
            dup_result = await session.execute(
                _select(_func.count(_EJM.id)).where(
                    _EJM.document_id == document_id,
                    _EJM.job_type == "diagram_extract",
                    _EJM.status.in_(["pending", "running"]),
                )
            )
            dup_count = dup_result.scalar_one_or_none() or 0

        if dup_count > 0:
            logger.debug(
                "image_analyze_handler: diagram_extract already queued for doc=%s", document_id
            )
            return

        async with _get_sf()() as session:
            job = _EJM(
                id=str(_uuid.uuid4()),
                document_id=document_id,
                job_type="diagram_extract",
                status="pending",
                created_at=_dt.now(UTC),
            )
            session.add(job)
            await session.commit()
            logger.info("image_analyze_handler: enqueued diagram_extract for doc=%s", document_id)
    except Exception as exc:
        # Non-fatal: failure to enqueue diagram_extract should not fail image_analyze
        logger.warning(
            "image_analyze_handler: failed to enqueue diagram_extract for doc=%s: %s",
            document_id,
            exc,
        )
