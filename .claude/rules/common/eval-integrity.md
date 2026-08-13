# Eval integrity

An eval number is a claim about the product, and it gets spent — on a model choice, a merge, a
plan written on top of it. Three rules hold everywhere; the full procedure is the
`eval-integrity` skill.

- **A metric that could not be computed is a failure, never a pass.** A judge that failed to
  load or a `/qa` that timed out yields `None`. Requested-but-uncomputed must fail the gate;
  not-requested is a skip. Never fabricate a default to fill the gap — no `or 0.0`, no `or 1.0`,
  no neutral score for a missing verdict.

- **Fix the pipeline, not the corpus.** A defect found in eval data is a defect in ingestion —
  scraped web content is a first-class ingest path, so a corrupt eval corpus means a corrupt
  user library. Never clean eval data with a side script.

- **Read the corpus the way ingestion reads it**, via
  `app.services.source_text.read_source_text`. A generator reading the raw file writes
  questions about text that never becomes a chunk.

Before quoting a number: which dataset, is it clean, was the metric computed or defaulted, and
what is the comparison. Floors are collapse detectors, not quality bars.
