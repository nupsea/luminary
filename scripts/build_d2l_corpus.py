"""One-time corpus-acquisition helper (NOT part of the eval harness).

Assembles a clean, heading-structured eval corpus from the Dive into Deep
Learning source (https://github.com/d2l-ai/d2l-en, CC-BY-SA 4.0). This is
input-prep, tied to D2L's repo layout; the measurement harness in evals/ stays
document-agnostic and never imports this.

Selects concept-rich, prose-heavy chapters/sections, strips MyST/Sphinx
directives, code cells, display math and figures, and emits a single Markdown
file whose `#`/`##` headings map onto Luminary's SectionModel (chapter = level
1, section = level 2). Markdown over plain text on purpose: BookParser._parse_md
detects headings structurally and drops code fences, which the .txt regex path
cannot do for synthesized technical prose.

Usage:
    python scripts/build_d2l_corpus.py \
        --src /path/to/d2l-en \
        --out DATA/books/d2l_dive_into_deep_learning.md

Provenance is pinned in DATA/books/D2L_ATTRIBUTION.md.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# (chapter_dir, [section files in reading order]). The first file supplies the
# chapter's `#` title; remaining files are demoted to `##` sections.
SELECTION: list[tuple[str, list[str]]] = [
    ("chapter_introduction", ["index.md"]),
    (
        "chapter_linear-regression",
        ["index.md", "linear-regression.md", "generalization.md", "weight-decay.md"],
    ),
    (
        "chapter_multilayer-perceptrons",
        [
            "index.md",
            "mlp.md",
            "backprop.md",
            "numerical-stability-and-init.md",
            "generalization-deep.md",
            "dropout.md",
        ],
    ),
    (
        "chapter_convolutional-neural-networks",
        [
            "index.md",
            "why-conv.md",
            "conv-layer.md",
            "padding-and-strides.md",
            "channels.md",
            "pooling.md",
            "lenet.md",
        ],
    ),
    (
        "chapter_recurrent-neural-networks",
        ["index.md", "sequence.md", "text-sequence.md", "language-model.md", "rnn.md", "bptt.md"],
    ),
    (
        "chapter_attention-mechanisms-and-transformers",
        [
            "index.md",
            "queries-keys-values.md",
            "attention-pooling.md",
            "attention-scoring-functions.md",
            "bahdanau-attention.md",
            "multihead-attention.md",
            "self-attention-and-positional-encoding.md",
            "transformer.md",
            "large-pretraining-transformers.md",
        ],
    ),
    (
        "chapter_optimization",
        [
            "index.md",
            "optimization-intro.md",
            "convexity.md",
            "gd.md",
            "sgd.md",
            "minibatch-sgd.md",
            "momentum.md",
            "adagrad.md",
            "rmsprop.md",
            "adam.md",
        ],
    ),
]

_FENCE_RE = re.compile(r"^```")
_DISPLAY_MATH_RE = re.compile(r"^\$\$")
_DIRECTIVE_LINE_RE = re.compile(r"^\s*:[a-z_]+:")  # :label:, :begin_tab:, :width:, ...
_IMAGE_RE = re.compile(r"^\s*!\[")
_ROLE_RE = re.compile(r":[a-z_]+:`[^`]*`")  # inline :numref:`x`, :cite:`y`, :eqref:`z`
_TABLE_RE = re.compile(r"^\s*\|")
_HTML_RE = re.compile(r"^\s*<")


def _clean_lines(text: str) -> list[str]:
    out: list[str] = []
    in_fence = False
    in_math = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _DISPLAY_MATH_RE.match(line.strip()):
            in_math = not in_math
            continue
        if in_math:
            continue
        if (
            _DIRECTIVE_LINE_RE.match(line)
            or _IMAGE_RE.match(line)
            or _TABLE_RE.match(line)
            or _HTML_RE.match(line)
        ):
            continue
        line = _ROLE_RE.sub("", line)
        out.append(line.rstrip())
    return out


def _demote_headings(lines: list[str], by: int) -> list[str]:
    if by <= 0:
        return lines
    bump = "#" * by
    out = []
    for line in lines:
        m = re.match(r"^(#{1,6})(\s+\S)", line)
        out.append(f"{bump}{line}" if m else line)
    return out


def _collapse_blanks(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def build(src: Path, out: Path) -> None:
    parts: list[str] = []
    for chapter_dir, files in SELECTION:
        for i, fname in enumerate(files):
            path = src / chapter_dir / fname
            if not path.exists():
                raise FileNotFoundError(f"missing D2L source file: {path}")
            lines = _clean_lines(path.read_text(encoding="utf-8"))
            if i > 0:
                lines = _demote_headings(lines, by=1)
            parts.append("\n".join(lines).strip())
    body = _collapse_blanks("\n\n".join(p for p in parts if p))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    chapters = sum(1 for ln in body.splitlines() if re.match(r"^#\s+\S", ln))
    sections = sum(1 for ln in body.splitlines() if re.match(r"^##\s+\S", ln))
    print(f"wrote {out} — {len(body):,} chars, {chapters} chapters, {sections} sections")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path, help="path to a d2l-en checkout")
    ap.add_argument("--out", required=True, type=Path, help="output .md path")
    args = ap.parse_args()
    build(args.src, args.out)


if __name__ == "__main__":
    main()
