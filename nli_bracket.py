"""An NLI model's bracket on the reviewed wrong options of runs 8 to 11, scored as the pipeline does.

Usage: nli_bracket.py <repo_id> <cache_dir> <out.json>
Each wrong option is scored against its passage's three-sentence windows and against the windows of
the document's five nearest chunks (`quiz_nli.windows`, max over windows). A model is usable when a
threshold drops every true option and no false one. Needs DATA_DIR (the verify library) and the
archive's partial/items_run*.json.
"""

import asyncio
import json
import sys

import torch
from app.services.quiz_nli import windows
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.services.retriever import get_retriever

REPO, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
DOCS = {"DDIA": "dad8a693-b933-4935-a580-a03b1866255d", "moby-dick": "b573268f-0319-4236-a029-ac732cbddd89",
        "federalist_papers": "fa6e1ca4-ea86-414e-86dc-cc87637791d3"}
# The three wrong options the review found true (results.md, runs 8, 9 and 11).
TRUE = {
    "Ensuring software and platforms are up to date with performance patches.",
    "It stops economic disputes between states.",
    "Ishmael needed to improve his health and well-being, so he chose sailing.",
}
THRESHOLDS = (0.3, 0.5, 0.7, 0.8, 0.9)

tok = AutoTokenizer.from_pretrained(REPO, cache_dir=CACHE, local_files_only=True)
model = AutoModelForSequenceClassification.from_pretrained(REPO, cache_dir=CACHE, local_files_only=True).eval()
ENTAIL = {v.lower(): k for k, v in model.config.id2label.items()}["entailment"]


def entailment(premises: list[str], hypothesis: str) -> float:
    if not premises:
        return 0.0
    best = 0.0
    for i in range(0, len(premises), 16):
        batch = premises[i : i + 16]
        enc = tok(batch, [hypothesis] * len(batch), return_tensors="pt", padding=True,
                  truncation="only_first", max_length=512)
        with torch.no_grad():
            best = max(best, float(model(**enc).logits.softmax(-1)[:, ENTAIL].max()))
    return best


async def main():
    rows = []
    for run in (8, 9, 10, 11):
        for it in json.load(open(f"partial/items_run{run}.json")):
            for o in it["options"]:
                if o["right"]:
                    continue
                hits = await asyncio.to_thread(get_retriever().vector_search, o["text"], [DOCS[it["document"]]], 5)
                near = [w for h in hits for w in windows(h.text)]
                rows.append({"run": run, "item": it["item_id"], "label": "true" if o["text"] in TRUE else "false",
                             "text": o["text"], "passage": entailment(windows(it["passage"]), o["text"]),
                             "near": entailment(near, o["text"])})
                r = rows[-1]
                print(f"{r['label']:5} r{run} pass={r['passage']:.2f} near={r['near']:.2f} | {o['text'][:70]}", flush=True)
    found = {r["text"] for r in rows if r["label"] == "true"}
    assert found == TRUE, f"true options missing from the items: {TRUE - found}"
    print(f"\n{REPO}: {len(rows)} wrong options")
    for t in THRESHOLDS:
        caught = sum(max(r["passage"], r["near"]) >= t for r in rows if r["label"] == "true")
        dropped = sum(max(r["passage"], r["near"]) >= t for r in rows if r["label"] == "false")
        print(f"  at {t}: true caught {caught}/3, false dropped {dropped}/{len(rows) - 3}")
    json.dump(rows, open(OUT, "w"), indent=1)


asyncio.run(main())
