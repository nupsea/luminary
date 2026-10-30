"""Restore litellm's bundled tiktoken files to the bytes tiktoken pins (I-72).

    repair_tiktoken_cache.py SITE_PACKAGES

litellm's win_amd64 wheel ships them with CRLF line endings. tiktoken then fails its
sha256 check at `import litellm`, deletes the file, downloads it from
openaipublic.blob.core.windows.net and writes it into the install directory; offline,
the import fails. A file is replaced only when converting it to LF yields a hash
tiktoken itself pins; any other mismatch fails the stage.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


def pinned_hashes(site: Path) -> set[str]:
    source = (site / "tiktoken_ext" / "openai_public.py").read_text(encoding="utf-8")
    return set(re.findall(r'expected_hash="([0-9a-f]{64})"', source))


def repair(site: Path) -> tuple[int, list[str]]:
    known = pinned_hashes(site)
    fixed, problems = 0, []
    # tiktoken names a cached file by the sha1 of its URL.
    for f in sorted((site / "litellm" / "litellm_core_utils" / "tokenizers").glob("[0-9a-f]" * 40)):
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() in known:
            continue
        lf = data.replace(b"\r\n", b"\n")
        if hashlib.sha256(lf).hexdigest() not in known:
            problems.append(f"{f.name}: matches no hash tiktoken pins, with or without CRLF")
            continue
        # Unlink first: uv hardlinks into its cache on Windows, which must stay as downloaded.
        f.unlink()
        f.write_bytes(lf)
        fixed += 1
    return fixed, problems


def main() -> int:
    fixed, problems = repair(Path(sys.argv[1]))
    for p in problems:
        print(f"tiktoken cache: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"    {fixed} tiktoken cache file(s) restored to the bytes tiktoken pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
