"""Give an idle GLiNER model's memory back.

The backend holds 2,433MB at rest with no ingest running, and GLiNER is 1,417MB
of it -- more than the embedder and the reranker together. With the 16GB floor
and two resident Ollama models (3.45GB chat + 7.31GB reader) that is 13.2GB of a
16GB machine before the ingest peak, which is what made the experience fall flat
on hosts smaller than the maintainer's.

Only GLiNER is reaped, deliberately. It is used by ingestion and the reindex
script and nothing else -- the chat graph's `_extract_entities_from_question` is
a regex -- so the 6.29s reload is paid by a background job that already takes
minutes, never by someone waiting for an answer. The reranker is a tenth of the
memory and sits on live retrieval, so releasing it would trade 303MB for a
user-visible stall.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

# How often to look. Well under the idle threshold so the release lands near it
# rather than up to a full period late.
_CHECK_INTERVAL_SECONDS = 30


async def reap_idle_models(
    *,
    interval_seconds: float = _CHECK_INTERVAL_SECONDS,
    iterations: int | None = None,
) -> None:
    """Release the entity model once it has been idle past the threshold.

    Runs until cancelled. `iterations` bounds it for tests; production passes
    None. Never raises: a reaper that kills its own task stops reaping silently,
    and the symptom would be memory growth with nothing in the log.
    """
    settings = get_settings()
    threshold = settings.NER_IDLE_RELEASE_SECONDS
    if threshold <= 0:
        logger.info("Idle model release disabled (NER_IDLE_RELEASE_SECONDS=0)")
        return

    seen = 0
    while iterations is None or seen < iterations:
        seen += 1
        await asyncio.sleep(interval_seconds)
        try:
            from app.services.ner import get_entity_extractor  # noqa: PLC0415

            extractor = get_entity_extractor()
            idle = extractor.idle_seconds()
            if idle >= threshold and extractor.release():
                logger.info(
                    "Released the entity model after %.0fs idle; ~1.4GB returned, "
                    "the next ingestion reloads it in about 6s",
                    idle,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("Idle model reaper skipped a pass", exc_info=True)
