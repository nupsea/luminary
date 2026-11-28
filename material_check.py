import json, sqlite3, sys
from app.services.quiz_material import unfit_reason, join_chunks, pick_keys
items = json.load(open(sys.argv[1]))
con = sqlite3.connect(sys.argv[2])
for it in items:
    ids = [r[0] for r in con.execute("select source_chunk_ids from quiz_items where id=?", (it["item_id"],))]
    chunk_ids = json.loads(ids[0])
    texts = [con.execute("select text from chunks where id=?", (c,)).fetchone()[0] for c in chunk_ids]
    joined = join_chunks(texts)
    keys = pick_keys(joined, 1, set())
    print(it["n"], unfit_reason(joined), len("\n\n".join(texts)), "->", len(joined), "|", (keys[0][:110] if keys else None))
