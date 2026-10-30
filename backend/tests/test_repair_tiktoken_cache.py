"""scripts/desktop/repair_tiktoken_cache.py: a stage ships the bytes tiktoken pins (I-72)."""

import hashlib
import importlib.util
import os
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "repair_tiktoken_cache",
    Path(__file__).resolve().parents[2] / "scripts" / "desktop" / "repair_tiktoken_cache.py",
)
repair_tiktoken_cache = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(repair_tiktoken_cache)

RANKS = b"IQ== 0\nIg== 1\nIw== 2\n"
NAME = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"


def _site(tmp_path: Path, cached: bytes) -> Path:
    site = tmp_path / "site"
    (site / "tiktoken_ext").mkdir(parents=True)
    pinned = hashlib.sha256(RANKS).hexdigest()
    (site / "tiktoken_ext" / "openai_public.py").write_text(
        f'load_tiktoken_bpe("https://x/cl100k_base.tiktoken", expected_hash="{pinned}")\n',
        encoding="utf-8",
    )
    tokenizers = site / "litellm" / "litellm_core_utils" / "tokenizers"
    tokenizers.mkdir(parents=True)
    (tokenizers / NAME).write_bytes(cached)
    (tokenizers / "anthropic_tokenizer.json").write_bytes(b'{"a": 1}\r\n')
    return site


def _cached(site: Path) -> Path:
    return site / "litellm" / "litellm_core_utils" / "tokenizers" / NAME


def test_a_crlf_copy_is_restored_to_the_pinned_bytes(tmp_path):
    site = _site(tmp_path, RANKS.replace(b"\n", b"\r\n"))

    assert repair_tiktoken_cache.repair(site) == (1, [])
    assert _cached(site).read_bytes() == RANKS


def test_the_repair_leaves_a_hardlinked_cache_entry_as_downloaded(tmp_path):
    crlf = RANKS.replace(b"\n", b"\r\n")
    site = _site(tmp_path, crlf)
    uv_cache_entry = tmp_path / "uv-cache-entry"
    os.link(_cached(site), uv_cache_entry)

    repair_tiktoken_cache.repair(site)

    assert uv_cache_entry.read_bytes() == crlf
    assert _cached(site).read_bytes() == RANKS


def test_a_correct_file_is_not_rewritten(tmp_path):
    site = _site(tmp_path, RANKS)
    inode = _cached(site).stat().st_ino

    assert repair_tiktoken_cache.repair(site) == (0, [])
    assert _cached(site).stat().st_ino == inode


def test_a_file_matching_no_pinned_hash_fails_the_stage(tmp_path):
    site = _site(tmp_path, b"something else\r\n")

    fixed, problems = repair_tiktoken_cache.repair(site)
    assert fixed == 0 and len(problems) == 1 and NAME in problems[0]


def test_files_that_are_not_tiktoken_caches_are_left_alone(tmp_path):
    site = _site(tmp_path, RANKS)
    repair_tiktoken_cache.repair(site)

    tokenizer = site / "litellm" / "litellm_core_utils" / "tokenizers" / "anthropic_tokenizer.json"
    assert tokenizer.read_bytes() == b'{"a": 1}\r\n'
