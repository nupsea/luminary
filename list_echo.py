"""Each wrong option on a list question, by its content-word share with the list's untested items."""
import json
import sqlite3
import sys
from collections import defaultdict

from app.services.flashcard_units import _content
from app.services.quiz_material import _ITEM, _items, join_chunks

seen = set()
for db in sys.argv[1:]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    for item in con.execute("select * from quiz_items where kind='multi'"):
        if item["stem"] in seen:
            continue
        seen.add(item["stem"])
        ids = json.loads(item["source_chunk_ids"])
        texts = dict(con.execute(f"select id, text from chunks where id in ({','.join('?'*len(ids))})", ids).fetchall())
        passage = join_chunks([texts[i] for i in ids if i in texts])
        lines = passage.splitlines()
        lists = []
        for start, line in enumerate(lines):
            if _ITEM.match(line) and (start == 0 or not _ITEM.match(lines[start - 1])):
                lists.append(_items(lines[start:]))
        opts = con.execute("select * from quiz_options where item_id=? order by position", (item["id"],)).fetchall()
        keys = [o["evidence_quote"] for o in opts if o["is_correct"]]
        listed = next((l for l in lists if any(k and k[:30] in " ".join(l) for k in keys)), [])
        untested = [i for i in listed if not any(k and (k[:30] in i or i[:30] in k) for k in keys)]
        print(f"\n## {item['stem']}")
        for u in untested:
            print("   untested:", u[:90])
        for o in opts:
            if o["is_correct"]:
                continue
            stem = _content(item["stem"])
            words = _content(o["text"]) - stem
            share = max((len(words & (_content(u) - stem)) / len(words) for u in untested), default=0.0) if words else 0.0
            print(f"   {share:.2f}  {o['text'][:100]}")
