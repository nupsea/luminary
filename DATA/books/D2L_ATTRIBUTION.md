# Attribution — `d2l_dive_into_deep_learning.md`

This file is a derivative work assembled for Luminary's evaluation harness.

## Source

- **Work:** *Dive into Deep Learning*
- **Authors:** Aston Zhang, Zachary C. Lipton, Mu Li, Alexander J. Smola
- **Origin:** https://github.com/d2l-ai/d2l-en
- **Pinned commit:** `23d7a5aecceee57d1292c56e90cce307f183bb0a`
- **Project site:** https://d2l.ai

## License

The book text is licensed under **Creative Commons Attribution-ShareAlike 4.0
International (CC-BY-SA 4.0)** — https://creativecommons.org/licenses/by-sa/4.0/.

Per ShareAlike, **this derivative is also distributed under CC-BY-SA 4.0.**

## Changes made (per CC-BY-SA "indicate if changes were made")

This is **not** the complete book. It was produced by
`scripts/build_d2l_corpus.py` from the pinned commit by:

- Selecting a concept-rich, prose-heavy subset: the Introduction plus the
  Linear Regression, Multilayer Perceptrons, Convolutional Neural Networks,
  Recurrent Neural Networks, Attention & Transformers, and Optimization
  chapters (concept sections only; pure code/implementation/Kaggle sections
  omitted).
- Stripping executable code cells, display math, figures, tables, and
  MyST/Sphinx directives (`:label:`, `:numref:`, `:cite:`, tab blocks, …).
- Demoting per-section headings so each chapter is a single `#` heading with
  `##` sections, for clean structural parsing.

The prose itself is unmodified. To reproduce:

```bash
git clone https://github.com/d2l-ai/d2l-en && \
  git -C d2l-en checkout 23d7a5aecceee57d1292c56e90cce307f183bb0a
python scripts/build_d2l_corpus.py \
  --src ./d2l-en --out DATA/books/d2l_dive_into_deep_learning.md
```
