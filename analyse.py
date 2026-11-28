"""Read a build run back out of the copied library: the numbers docs/quiz.md reports."""

import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

DB, RUNS, ITEMS_OUT = sys.argv[1], sys.argv[2], sys.argv[3]
runs = json.load(open(RUNS))
ids = [r["quiz_id"] for r in runs["runs"]]
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

q = f"select * from quiz_questions where quiz_id in ({','.join('?' * len(ids))})"
questions = con.execute(q, ids).fetchall()
item_ids = [r["item_id"] for r in questions]
marks = ",".join("?" * len(item_ids))
items = {r["id"]: r for r in con.execute(f"select * from quiz_items where id in ({marks})", item_ids)}
options = defaultdict(list)
for o in con.execute(f"select * from quiz_options where item_id in ({marks}) order by position", item_ids):
    options[o["item_id"]].append(o)
docs = dict(con.execute("select id, title from documents").fetchall())
headings = dict(con.execute("select id, heading from sections").fetchall())

print("== runs")
for r in runs["runs"]:
    print(f"  {r['doc']:10} {r['level']:6} {r['status']:6} built {r['built']}  first {r['first_question_s']}s  total {r['total_s']}s  {r['error'] or ''}")

print("== gate counters")
counts = runs["stats"].get("counts", runs["stats"])
for k, v in sorted(counts.items()):
    if k.startswith("quiz") or k.startswith("parse"):
        print(f"  {k}: {v}")

by_level = defaultdict(list)
for item in items.values():
    for o in options[item["id"]]:
        if o["key_similarity"] is not None:
            by_level[item["difficulty"]].append(o["key_similarity"])
print("== key_similarity of wrong options to the nearest right one")
for level in ("easy", "medium", "hard"):
    v = sorted(by_level[level])
    if v:
        q1, med, q3 = statistics.quantiles(v, n=4)
        print(f"  {level:6} n={len(v):3} min {v[0]:.3f} q1 {q1:.3f} median {med:.3f} q3 {q3:.3f} max {v[-1]:.3f}")

print("== right-answer position (single items, as shown)")
pos = Counter()
for row in questions:
    item = items[row["item_id"]]
    if item["kind"] != "single":
        continue
    right = next(o["id"] for o in options[item["id"]] if o["is_correct"])
    pos[json.loads(row["option_order"]).index(right)] += 1
print("  ", dict(sorted(pos.items())))

print("== right option is the longest (single items)")
singles = [i for i in items.values() if i["kind"] == "single"]
longest = sum(
    1
    for i in singles
    if max(options[i["id"]], key=lambda o: len(o["text"]))["is_correct"]
)
print(f"  {longest}/{len(singles)} (chance 1/4)")
ratios = sorted(
    len(next(o for o in options[i["id"]] if o["is_correct"])["text"])
    / max(len(o["text"]) for o in options[i["id"]] if not o["is_correct"])
    for i in singles
)
if ratios:
    print(f"  right/longest-wrong length ratio: max {ratios[-1]:.2f}, median {statistics.median(ratios):.2f}")

print("== items")
print("  kinds", Counter(i["kind"] for i in items.values()))
print("  support_check", Counter(i["support_check"] for i in items.values()))
print("  origin", Counter(i["origin"] for i in items.values()))
print("  tied to a card", sum(1 for i in items.values() if i["flashcard_id"]), "of", len(items))
print("  traps", Counter(o["trap"] for i in items for o in options[i] if o["trap"]))

with open(ITEMS_OUT, "w") as fh:
    for n, row in enumerate(sorted(questions, key=lambda r: (r["quiz_id"], r["position"])), 1):
        item = items[row["item_id"]]
        fh.write(
            f"### {n}. {docs.get(item['document_id'])} - {headings.get(item['section_id'], '')}"
            f" - {item['difficulty']} {item['kind']} ({item['support_check']})\n\n{item['stem']}\n\n"
        )
        for o in options[item["id"]]:
            mark = "RIGHT" if o["is_correct"] else f"wrong/{o['trap']} sim={o['key_similarity']:.2f}"
            fh.write(f"- [{mark}] {o['text']}\n")
            if o["evidence_quote"]:
                fh.write(f"  - quote: \"{o['evidence_quote']}\"\n")
        chunks = json.loads(item["source_chunk_ids"])
        fh.write(f"\nPassage chunks: {len(chunks)}\n\n")
print("items written to", ITEMS_OUT)
