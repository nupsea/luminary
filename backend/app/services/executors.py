"""A thread pool for model loading that cannot block interpreter exit.

Model loads used the default executor, which is a bad fit twice over.

They are long: a cold first run downloads well over a gigabyte of weights inside
``from_pretrained``. Sharing the default pool means ingestion and embedding work
queues up behind that.

Worse, they are unkillable. ``concurrent.futures.thread`` registers an
``atexit`` hook that joins every worker thread, and those threads are not
daemons, so a SIGTERM arriving mid-download does not end the process -- it waits
for the download to finish first. A desktop app that takes minutes to quit
reads as a hang, and a supervisor that then SIGKILLs it can leave the Kuzu lock
held against the next launch.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def get_model_executor() -> ThreadPoolExecutor:
    """Single-worker pool for HuggingFace/torch model construction.

    One worker, because ``MODEL_LOAD_LOCK`` already serialises these -- extra
    threads would only queue on the lock while holding memory.
    """
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-load")
    return _executor


def shutdown_model_executor() -> None:
    """Stop queued loads and release the interpreter's hold on running ones."""
    global _executor
    if _executor is None:
        return

    try:
        from concurrent.futures import thread as _thread_mod  # noqa: PLC0415

        for worker in list(getattr(_executor, "_threads", ())):
            # Dropping the thread from this registry is what stops the atexit
            # hook joining it. A load already inside from_pretrained cannot be
            # interrupted, so the alternative is waiting out the download.
            _thread_mod._threads_queues.pop(worker, None)
    except Exception:
        logger.debug("Could not detach model-load threads from the exit hook", exc_info=True)

    _executor.shutdown(wait=False, cancel_futures=True)
    _executor = None
