"""Fetch the local models before anything tries to construct one.

``from_pretrained`` downloads and builds in a single call, and every loader
holds ``MODEL_LOAD_LOCK`` across it because torch construction mutates
process-global state. That lock is correct, but it also serialised ~1.4GB of
purely network-bound work behind a single worker.

Downloading is not torch work, so it does not need the lock. Pre-fetching into
the same HuggingFace cache the loaders already read means they then construct
from disk, serially and unchanged, while the downloads themselves overlap.

This is also where an offline first run is caught: without it, an unreachable
hub surfaced as ~75 seconds of undifferentiated spinner before failing.
"""

import concurrent.futures
import logging
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_MB = 1024**2
_HUB_HOST = "huggingface.co"


# snapshot_download takes a whole repo, where from_pretrained takes only what it
# needs. These repos carry the same weights in several frameworks -- the
# cross-encoder alone publishes 1.2GB of ONNX, OpenVINO and Flax variants beside
# a 127MB torch checkpoint. Without this, pre-fetching doubles the download it
# was meant to speed up.
_OTHER_FRAMEWORKS = (
    "onnx/*",
    "*.onnx",
    "*.onnx_data",
    "openvino/*",
    "*.msgpack",
    "*.h5",
    "*.tflite",
    "*.ot",
)
# Where a repo publishes both, safetensors is what the loaders pick.
_DUPLICATE_TORCH_WEIGHTS = ("pytorch_model.bin",)


@dataclass(frozen=True)
class ModelSpec:
    """A model the app fetches for itself."""

    key: str
    repo_id: str
    slug: str
    size_bytes: int
    ignore: tuple[str, ...] = _OTHER_FRAMEWORKS


def _reranker_slug() -> str:
    # Must match retriever_strategies, which derives its cache dir the same way.
    return get_settings().RERANK_MODEL.rsplit("/", 1)[-1].lower()


def specs() -> tuple[ModelSpec, ...]:
    return (
        ModelSpec(
            "embedder",
            "BAAI/bge-small-en-v1.5",
            "bge-small",
            133 * _MB,
            ignore=_OTHER_FRAMEWORKS + _DUPLICATE_TORCH_WEIGHTS,
        ),
        ModelSpec(
            "reranker",
            get_settings().RERANK_MODEL,
            _reranker_slug(),
            128 * _MB,
            ignore=_OTHER_FRAMEWORKS + _DUPLICATE_TORCH_WEIGHTS,
        ),
        # GLiNER publishes only a torch checkpoint, so excluding it would leave
        # nothing to load.
        ModelSpec("ner", "urchade/gliner_multi_pii-v1", "gliner", 1126 * _MB),
    )


def spec_for(key: str) -> ModelSpec | None:
    return next((s for s in specs() if s.key == key), None)


def cache_dir(spec: ModelSpec) -> Path:
    return Path(get_settings().DATA_DIR).expanduser() / "models" / spec.slug


def is_cached(spec: ModelSpec) -> bool:
    """Whether the loaders would find this model on disk.

    Mirrors the HuggingFace cache layout the loaders read via ``cache_folder``
    and ``cache_dir``: ``models--org--name/snapshots/<rev>/``.
    """
    root = cache_dir(spec) / f"models--{spec.repo_id.replace('/', '--')}" / "snapshots"
    if not root.is_dir():
        return False
    return any(any(rev.iterdir()) for rev in root.iterdir() if rev.is_dir())


def hub_reachable(timeout: float = 5.0) -> bool:
    """Fast reachability probe, so an offline run fails in seconds not minutes."""
    import os  # noqa: PLC0415

    if os.environ.get("HF_HUB_OFFLINE", "").strip() not in ("", "0"):
        return False
    try:
        with socket.create_connection((_HUB_HOST, 443), timeout=timeout):
            return True
    except OSError:
        return False


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _download(spec: ModelSpec) -> None:
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    target = cache_dir(spec)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec.repo_id,
        cache_dir=str(target),
        ignore_patterns=list(spec.ignore),
    )


def prefetch(to_fetch: list[ModelSpec], status) -> dict[str, str]:
    """Download the given models concurrently. Returns key -> error for failures.

    Progress is sampled from the cache directory rather than from download
    callbacks, which snapshot_download does not expose per-file. Approximate,
    but it is the difference between a moving bar and a frozen one.
    """
    if not to_fetch:
        return {}

    # tqdm keeps a class-level lock that is not safe to initialise from several
    # threads at once: concurrent snapshot_download calls raced on it and one
    # download died with "type object 'tqdm' has no attribute '_lock'". We
    # report progress ourselves, so the bars are pure liability here.
    try:
        from huggingface_hub.utils import disable_progress_bars  # noqa: PLC0415

        disable_progress_bars()
    except Exception:
        logger.debug("Could not disable hub progress bars", exc_info=True)

    stop = threading.Event()

    def _report() -> None:
        while not stop.wait(1.0):
            for spec in to_fetch:
                status.set_progress(
                    spec.key, _dir_size(cache_dir(spec)), spec.size_bytes
                )

    reporter = threading.Thread(target=_report, name="prefetch-progress", daemon=True)
    reporter.start()

    errors: dict[str, str] = {}
    started = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(to_fetch), thread_name_prefix="prefetch"
        ) as pool:
            futures = {pool.submit(_download, s): s for s in to_fetch}
            for future in concurrent.futures.as_completed(futures):
                spec = futures[future]
                try:
                    future.result()
                    status.set_progress(spec.key, spec.size_bytes, spec.size_bytes)
                except Exception as exc:
                    errors[spec.key] = str(exc)
                    logger.warning("Prefetch failed for %s: %s", spec.repo_id, exc)
    finally:
        stop.set()

    logger.info(
        "Model prefetch finished",
        extra={
            "models": [s.key for s in to_fetch],
            "seconds": round(time.perf_counter() - started, 1),
            "failed": list(errors),
        },
    )
    return errors
