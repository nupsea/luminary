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

It is the only code that downloads these models. Loaders read the cache and
raise `ModelNotDownloaded` when it is empty (`require_snapshot`).
"""

import argparse
import concurrent.futures
import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.exceptions import ModelNotDownloaded

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
# What `AutoTokenizer.from_pretrained` reads from a repo, and never its weights.
_TOKENIZER_FILES = (
    "config.json",
    "tokenizer*",
    "special_tokens_map.json",
    "added_tokens.json",
    "*.model",
    "vocab*",
    "merges.txt",
)


@dataclass(frozen=True)
class ModelSpec:
    """A model the app fetches for itself."""

    key: str
    repo_id: str
    slug: str
    size_bytes: int
    ignore: tuple[str, ...] = _OTHER_FRAMEWORKS


EMBEDDER_REPO = "BAAI/bge-small-en-v1.5"


def _reranker_slug() -> str:
    # Must match retriever_strategies, which derives its cache dir the same way.
    return get_settings().RERANK_MODEL.rsplit("/", 1)[-1].lower()


# Download sizes for the entity models worth switching between. Used only to set
# expectations on the setup screen, so an unknown model gets a mid-range guess
# rather than blocking the switch.
_NER_SIZES_MB: dict[str, int] = {
    "urchade/gliner_multi_pii-v1": 1126,
    "urchade/gliner_multi-v2.1": 1126,
    "urchade/gliner_medium-v2.1": 604,
    "urchade/gliner_small-v2.1": 336,
}
_NER_SIZE_DEFAULT_MB = 600


def _ner_repo() -> str:
    return get_settings().NER_MODEL


def _ner_size_bytes() -> int:
    return _NER_SIZES_MB.get(_ner_repo(), _NER_SIZE_DEFAULT_MB) * _MB


def specs() -> tuple[ModelSpec, ...]:
    return (
        ModelSpec(
            "embedder",
            EMBEDDER_REPO,
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
        ModelSpec("ner", _ner_repo(), "gliner", _ner_size_bytes()),
    )


def spec_for(key: str) -> ModelSpec | None:
    return next((s for s in specs() if s.key == key), None)


def models_root() -> Path:
    return Path(get_settings().DATA_DIR).expanduser() / "models"


def cache_dir(spec: ModelSpec, root: Path | None = None) -> Path:
    return (root or models_root()) / spec.slug


def _snapshot(root: Path, repo_id: str) -> Path | None:
    """The non-empty ``models--org--name/snapshots/<rev>/`` the loaders read."""
    snapshots = root / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir():
        return None
    return next((rev for rev in snapshots.iterdir() if rev.is_dir() and any(rev.iterdir())), None)


def tokenizer_base(root: Path, repo_id: str) -> str | None:
    """The encoder repo a GLiNER checkpoint builds its tokenizer from, read from its
    ``gliner_config.json``; None for any other model.
    """
    snap = _snapshot(root, repo_id)
    config = snap / "gliner_config.json" if snap else None
    if config is None or not config.is_file():
        return None
    try:
        return json.loads(config.read_text(encoding="utf-8")).get("model_name") or None
    except (OSError, ValueError):
        return None


def snapshot_present(root: Path, repo_id: str) -> bool:
    """Whether a cache-only load of ``repo_id`` from ``root`` has what it reads."""
    if _snapshot(root, repo_id) is None:
        return False
    base = tokenizer_base(root, repo_id)
    return base is None or _snapshot(root, base) is not None


# repo_id -> set when setup's download of it finishes, successfully or not.
_in_flight: dict[str, threading.Event] = {}
_in_flight_lock = threading.Lock()


def require_snapshot(root: Path, repo_id: str) -> None:
    """Raise `ModelNotDownloaded` unless a cache-only load can succeed.

    Waits for an in-flight setup download of this model. Call it outside
    MODEL_LOAD_LOCK, or every other model's load stalls behind the download.
    """
    if snapshot_present(root, repo_id):
        return
    with _in_flight_lock:
        pending = _in_flight.get(repo_id)
    if pending is not None:
        logger.info("Waiting for setup to finish downloading %s", repo_id)
        pending.wait()
    if not snapshot_present(root, repo_id):
        raise ModelNotDownloaded(
            f"{repo_id} is not downloaded. Luminary fetches it during setup; "
            "retry setup to download it.",
            model=repo_id,
        )


def wait_for_downloads() -> None:
    """Block until no setup download is in flight: forcing the hub offline is
    process-wide and would fail them."""
    with _in_flight_lock:
        pending = list(_in_flight.values())
    for done in pending:
        done.wait()


def is_cached(spec: ModelSpec) -> bool:
    return snapshot_present(cache_dir(spec), spec.repo_id)


def hub_reachable(timeout: float = 5.0) -> bool:
    """Fast reachability probe, so an offline run fails in seconds not minutes."""
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


def _download(spec: ModelSpec, root: Path | None = None) -> None:
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    done = threading.Event()
    with _in_flight_lock:
        _in_flight[spec.repo_id] = done
    try:
        target = cache_dir(spec, root)
        target.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=spec.repo_id,
            cache_dir=str(target),
            ignore_patterns=list(spec.ignore),
        )
        if base := tokenizer_base(target, spec.repo_id):
            snapshot_download(
                repo_id=base,
                cache_dir=str(target),
                allow_patterns=list(_TOKENIZER_FILES),
            )
    finally:
        with _in_flight_lock:
            _in_flight.pop(spec.repo_id, None)
        done.set()


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
                status.set_progress(spec.key, _dir_size(cache_dir(spec)), spec.size_bytes)

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


def main(argv: list[str] | None = None) -> int:
    """Download whatever is missing. ``--models-dir`` targets another cache, such as
    the test suite's (`tests/conftest.py`)."""
    parser = argparse.ArgumentParser(prog="python -m app.services.model_prefetch")
    parser.add_argument("--models-dir", type=Path, default=None)
    root = parser.parse_args(argv).models_dir
    root = root.expanduser() if root else models_root()

    missing = [s for s in specs() if not snapshot_present(cache_dir(s, root), s.repo_id)]
    for spec in missing:
        print(f"downloading {spec.repo_id} into {cache_dir(spec, root)}")
        _download(spec, root)
    print(f"models ready in {root} ({len(missing)} downloaded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
