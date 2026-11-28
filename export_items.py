"""Export the rated run's questions, with their source passages, as JSON for the rating page."""

import json
import sqlite3
import sys
from collections import defaultdict

# The builder's own join (overlap dropped), so an exported passage is the text the checks scored.
# Needs the quiz worktree's backend on PYTHONPATH.
from app.services.quiz_material import join_chunks

DB, RUNS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ids = [r["quiz_id"] for r in json.load(open(RUNS))["runs"]]
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
marks = ",".join("?" * len(ids))
questions = con.execute(f"select * from quiz_questions where quiz_id in ({marks})", ids).fetchall()
item_ids = [r["item_id"] for r in questions]
im = ",".join("?" * len(item_ids))
items = {r["id"]: r for r in con.execute(f"select * from quiz_items where id in ({im})", item_ids)}
options = defaultdict(list)
for o in con.execute(f"select * from quiz_options where item_id in ({im}) order by position", item_ids):
    options[o["item_id"]].append(o)
docs = dict(con.execute("select id, title from documents").fetchall())
headings = dict(con.execute("select id, heading from sections").fetchall())
out = []
for n, row in enumerate(sorted(questions, key=lambda r: (r["quiz_id"], r["position"])), 1):
    item = items[row["item_id"]]
    chunk_ids = json.loads(item["source_chunk_ids"])
    cm = ",".join("?" * len(chunk_ids))
    chunks = {c["id"]: c["text"] for c in con.execute(f"select id, text from chunks where id in ({cm})", chunk_ids)}
    out.append({
        "n": n,
        "item_id": item["id"],
        "document": docs.get(item["document_id"]),
        "section": headings.get(item["section_id"], ""),
        "level": item["difficulty"],
        "kind": item["kind"],
        "stem": item["stem"],
        "options": [
            {"text": o["text"], "right": bool(o["is_correct"]), "trap": o["trap"], "quote": o["evidence_quote"]}
            for o in options[item["id"]]
        ],
        "passage": join_chunks([chunks[c] for c in chunk_ids if c in chunks]),
    })
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
print(len(out), "items;", sum(len(i["passage"]) for i in out), "passage chars")
