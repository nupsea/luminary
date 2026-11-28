"""The untested-item drop on run 8's operations question, as the builder would call it."""
import json
import sqlite3
import sys

from app.services.quiz_material import join_chunks, untested_items
from app.services.quiz_parsers import ParsedOption, drop_reason

con = sqlite3.connect(sys.argv[1])
con.row_factory = sqlite3.Row
item = con.execute("select * from quiz_items where id=?", (sys.argv[2],)).fetchone()
ids = json.loads(item["source_chunk_ids"])
texts = dict(con.execute(f"select id, text from chunks where id in ({','.join('?' * len(ids))})", ids).fetchall())
passage = join_chunks([texts[i] for i in ids])
opts = con.execute("select * from quiz_options where item_id=? order by position", (item["id"],)).fetchall()
keys = [o["evidence_quote"] for o in opts if o["is_correct"]]
rights = [o["text"] for o in opts if o["is_correct"]]
untested = untested_items(passage, keys)
print("untested:", untested)
for o in opts:
    if not o["is_correct"]:
        option = ParsedOption(text=o["text"], correct=False, quote=None, mistake=None) if "mistake" in ParsedOption.__dataclass_fields__ else ParsedOption(text=o["text"], correct=False, quote=None)
        print(drop_reason(option, rights, passage, stem=item["stem"], untested=untested), "|", o["text"])
