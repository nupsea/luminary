"""Vision LLM image analysis service

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
import logging
import uuid
from datetime import UTC
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image as _PILImage
from sqlalchemy import func, select

from app import config as _config_module  # indirect: get_settings is patched
from app import database as _database_module  # indirect: get_session_factory is patched
from app.models import ChunkModel, DocumentModel, EnrichmentJobModel, ImageModel
from app.services import embedder as _embedder_module  # indirect: get_embedding_service is patched
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.llm import LLMUnavailableError, get_llm_service
from app.services.llm_json import parse_llm_json_object

logger = logging.getLogger(__name__)

# Transcription-first prompting: forcing the model to commit to the labels it
# can actually read before describing anchors the description in legible
# content and measurably curbs invented node names on dense diagrams.
_VISION_PROMPT = (
    "You are analyzing an image extracted from a document.\n"
    "Step 1 -- transcribe the text labels that are legible in the image, "
    "exactly as written. Never guess or invent labels; omit any you cannot "
    "read clearly.\n"
    "Step 2 -- classify the image as one of: architecture_diagram, "
    "sequence_diagram, er_diagram, flowchart, code_screenshot, table, chart, "
    "photo, other.\n"
    "Step 3 -- describe what the image shows and what it is for. For "
    "diagrams, describe the structure: which labeled components exist and how "
    "they connect or flow.\n"
    "The image is the primary evidence. Any document context provided may be "
    "vague, incomplete, or unrelated -- weigh it against what you see. When "
    "the image is clear, describe it confidently even if the context says "
    "little; use the context to supply names the image alone cannot (such as "
    "what a figure or system is called), and only when it matches what you "
    "see.\n"
    'Reply ONLY with JSON: {"image_type": "...", "labels": ["..."], '
    '"description": "..."}'
)

_CONTEXT_TMPL = "Document context:\n{context}\n\n"

_MAX_PART_CHARS = 500
_MAX_LABELS = 40

# Bounds concurrent vision LLM calls across ALL documents (avoids OOM on large
# PDFs). Sized lazily from ENRICHMENT_VISION_CONCURRENCY so a machine/profile with
# headroom can batch several image_analyze calls (paired with OLLAMA_NUM_PARALLEL);
# the default of 1 preserves the original one-at-a-time behaviour.
_ENRICH_SEM: asyncio.Semaphore | None = None


def _get_enrich_sem() -> asyncio.Semaphore:
    global _ENRICH_SEM  # noqa: PLW0603
    if _ENRICH_SEM is None:
        try:
            n = int(_config_module.get_settings().ENRICHMENT_VISION_CONCURRENCY)
        except (TypeError, ValueError):
            n = 1
        _ENRICH_SEM = asyncio.Semaphore(max(1, n))
    return _ENRICH_SEM


# One color covering more than this fraction of pixels means a near-blank capture
# (e.g. an all-white figure box) that anti-aliasing pushed past the 5-color floor.
# Kept conservative so sparse-but-real line-art diagrams — well below this on their
# background color — are still analyzed.
_DECORATIVE_DOMINANT_FRAC = 0.99


def _is_decorative(pil_image: object) -> bool:
    """Return True if the image is decorative (no informational content).

    - Solid-color: fewer than 5 unique RGB pixel values.
    - Near-blank: a single color covers >99% of pixels.
    - Rule-line: max(w, h) / min(w, h) > 10.
    """

    img = pil_image  # type: ignore[assignment]
    img_rgb = img.convert("RGB")  # type: ignore[attr-defined]
    pixels = np.array(img_rgb).reshape(-1, 3)
    _colors, counts = np.unique(pixels, axis=0, return_counts=True)
    if len(counts) < 5:
        return True
    if counts.max() / counts.sum() > _DECORATIVE_DOMINANT_FRAC:
        return True
    w, h = img.size  # type: ignore[attr-defined]
    ratio = max(w, h) / max(min(w, h), 1)
    return ratio > 10.0


async def _load_image_contexts(document_id: str, images: list) -> dict[str, str]:
    """Assemble the textual evidence available for each image -- document
    title, the text anchored to it, and other text from the same page -- as
    labeled sections. Every available source is passed; the vision prompt
    instructs the model to weigh them against the image rather than trust
    any single one."""
    async with _database_module.get_session_factory()() as session:
        title = (
            await session.execute(
                select(DocumentModel.title).where(DocumentModel.id == document_id)
            )
        ).scalar_one_or_none() or ""

        chunk_ids = {img.chunk_id for img in images if img.chunk_id}
        chunk_text_by_id: dict[str, str] = {}
        if chunk_ids:
            rows = await session.execute(
                select(ChunkModel.id, ChunkModel.text).where(ChunkModel.id.in_(chunk_ids))
            )
            chunk_text_by_id = dict(rows.all())

        # ImageModel.page is 0-based; ChunkModel.page_number is 1-based.
        pages = {img.page + 1 for img in images}
        page_text: dict[int, str] = {}
        if pages:
            rows = await session.execute(
                select(ChunkModel.page_number, ChunkModel.text)
                .where(
                    ChunkModel.document_id == document_id,
                    ChunkModel.page_number.in_(pages),
                )
                .order_by(ChunkModel.page_number, ChunkModel.chunk_index)
            )
            for page_number, text in rows.all():
                page_text.setdefault(page_number, text)

    contexts: dict[str, str] = {}
    for img in images:
        parts: list[str] = []
        if title:
            parts.append(f"Title: {title}")
        anchored = chunk_text_by_id.get(img.chunk_id or "") or ""
        if anchored:
            parts.append(
                "Text anchored to this image (may include its caption): "
                + anchored[:_MAX_PART_CHARS]
            )
        same_page = page_text.get(img.page + 1) or ""
        if same_page and same_page != anchored:
            parts.append("Other text on the same page: " + same_page[:_MAX_PART_CHARS])
        contexts[img.id] = "\n".join(parts)
    return contexts


def _merge_labels(parsed: dict) -> str:
    """Fold the transcribed labels into the stored description so FTS search
    and diagram extraction see the labels the model actually read."""
    description = str(parsed.get("description") or "")
    labels = parsed.get("labels")
    if isinstance(labels, list):
        clean = [str(label).strip() for label in labels if str(label).strip()]
        if clean:
            description = (
                f"{description} Visible labels: {', '.join(clean[:_MAX_LABELS])}.".strip()
            )
    return description


async def _call_vision_llm(image_path: Path, settings: object, context: str = "") -> dict:
    """Call the vision LLM and return parsed JSON response.

    Falls back to {"image_type": "other", "description": raw_text, ...} if JSON parse fails.
    Raises LLMUnavailableError if no model is reachable.

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


    img = _PILImage.open(image_path)
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    last_exc: Exception | None = None
    raw = ""
    for model in models_to_try:
        try:
            api_base: str | None = None
            if model.startswith("ollama/"):
                # OLLAMA_URL overrides LiteLLM's localhost default (Docker host routing).
                api_base = settings.OLLAMA_URL  # type: ignore[attr-defined]
            raw = (
                await get_llm_service().complete(
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        _CONTEXT_TMPL.format(context=context) if context else ""
                                    )
                                    + _VISION_PROMPT,
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    model=model,
                    temperature=0.0,
                    timeout=300.0,
                    api_base=api_base,
                )
            ).strip()
            if model != vision_model:
                logger.info(
                    "_call_vision_llm: VISION_MODEL (%s) unreachable; used fallback model %s",
                    vision_model,
                    model,
                )
            break
        except LLMUnavailableError as exc:
            last_exc = exc
            logger.debug("_call_vision_llm: model %s unavailable (%s), trying next", model, exc)
            continue
    else:
        assert last_exc is not None
        raise last_exc

    parsed = parse_llm_json_object(raw)
    if parsed is not None:
        return parsed
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
        from sqlalchemy import text as _text
        from sqlalchemy import update as _update


        settings = _config_module.get_settings()
        data_dir = Path(settings.DATA_DIR).expanduser()

        # Load all ImageModel rows with description=null for this document
        async with _database_module.get_session_factory()() as session:
            result = await session.execute(
                select(ImageModel).where(
                    ImageModel.document_id == document_id,
                    ImageModel.description.is_(None),
                )
            )
            images = list(result.scalars().all())

        if not images:
            logger.info("image_enricher: no un-described images for doc=%s", document_id)
            return 0

        logger.info("image_enricher: processing %d images for doc=%s", len(images), document_id)

        try:
            contexts = await _load_image_contexts(document_id, images)
        except Exception as exc:
            logger.warning("image_enricher: context load failed, analyzing blind: %s", exc)
            contexts = {}

        processed = 0
        embedder = _embedder_module.get_embedding_service()
        lancedb_svc = _vector_store_module.get_lancedb_service()

        for img in images:
            abs_path = data_dir / img.path
            if not abs_path.exists():
                logger.warning(
                    "image_enricher: image file not found path=%s doc=%s", img.path, document_id
                )
                continue

            async with _get_enrich_sem():
                try:

                    pil_img = _PILImage.open(str(abs_path))

                    if _is_decorative(pil_img):
                        image_type = "decorative"
                        description = "Decorative image"
                        logger.debug("image_enricher: decorative image_id=%s", img.id)
                    else:
                        parsed = await _call_vision_llm(
                            abs_path, settings, contexts.get(img.id, "")
                        )
                        image_type = parsed.get("image_type") or "other"
                        description = _merge_labels(parsed) or ""

                    # Embed description before any DB writes so a CPU/OOM failure
                    # does not leave the SQLite row updated without an FTS5 entry.
                    vector = embedder.encode([description])[0]

                    # Update SQLite (image_type + description) and insert FTS5 entry
                    # in a single session/transaction so both succeed or both roll back.
                    # If this commit fails, description stays null and the image will
                    # be retried on the next image_analyze job.
                    async with _database_module.get_session_factory()() as session:
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

                except LLMUnavailableError:
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

    # Enqueue diagram_extract if qualifying diagram images now exist
    _QUALIFYING_DIAGRAM_TYPES = [
        "architecture_diagram",
        "sequence_diagram",
        "er_diagram",
        "flowchart",
    ]
    try:
        from datetime import datetime as _dt



        async with _database_module.get_session_factory()() as session:
            # Check if any qualifying diagram images exist for this document
            has_diagrams_result = await session.execute(
                select(ImageModel.id)
                .where(
                    ImageModel.document_id == document_id,
                    ImageModel.image_type.in_(_QUALIFYING_DIAGRAM_TYPES),
                    ImageModel.description.is_not(None),
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

        async with _database_module.get_session_factory()() as session:
            # Deduplication: skip if a pending/running diagram_extract job already exists
            dup_result = await session.execute(
                select(func.count(EnrichmentJobModel.id)).where(
                    EnrichmentJobModel.document_id == document_id,
                    EnrichmentJobModel.job_type == "diagram_extract",
                    EnrichmentJobModel.status.in_(["pending", "running"]),
                )
            )
            dup_count = dup_result.scalar_one_or_none() or 0

        if dup_count > 0:
            logger.debug(
                "image_analyze_handler: diagram_extract already queued for doc=%s", document_id
            )
            return

        async with _database_module.get_session_factory()() as session:
            job = EnrichmentJobModel(
                id=str(uuid.uuid4()),
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
