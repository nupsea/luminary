"""A build run's accepted questions as Markdown for review, plus the gate counters."""
import json, sqlite3, sys
from collections import defaultdict

DB, RUNS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
runs = json.load(open(RUNS))
ids = [r["quiz_id"] for r in runs["runs"]]
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
m = ",".join("?" * len(ids))
qs = con.execute(f"select * from quiz_questions where quiz_id in ({m}) order by quiz_id, position", ids).fetchall()
items = {r["id"]: r for r in con.execute(f"select * from quiz_items where id in ({','.join('?'*len(qs))})", [q["item_id"] for q in qs])} if qs else {}
opts = defaultdict(list)
for o in con.execute(f"select * from quiz_options where item_id in ({','.join('?'*len(items))}) order by position", list(items)) if items else []:
    opts[o["item_id"]].append(o)
docs = dict(con.execute("select id, title from documents"))
heads = dict(con.execute("select id, heading from sections"))
with open(OUT, "w") as fh:
    fh.write("## Runs\n\n")
    for r in runs["runs"]:
        fh.write(f"- {r['doc']} {r['level']}: {r['status']}, {r['built']} built, first {r['first_question_s']}s, total {r['total_s']}s {r['error'] or ''}\n")
    fh.write("\n## Counters\n\n")
    for k, v in sorted(runs["stats"].get("counts", runs["stats"]).items()):
        if k.startswith("quiz"):
            fh.write(f"- {k}: {v}\n")
    for n, q in enumerate(qs, 1):
        it = items[q["item_id"]]
        fh.write(f"\n### {n}. {docs.get(it['document_id'])} / {heads.get(it['section_id'],'')} / {it['difficulty']} {it['kind']} / {it['support_check']} / {it['origin']}\n\n**{it['stem']}**\n\n")
        for o in opts[it["id"]]:
            if o["is_correct"]:
                fh.write(f"- RIGHT: {o['text']}\n  - key: {o['evidence_quote']}\n")
            else:
                fh.write(f"- wrong ({o['trap']}, sim {o['key_similarity']:.2f}): {o['text']}\n")
print(len(qs), "questions ->", OUT)
