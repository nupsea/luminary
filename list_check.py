import sqlite3, sys
from app.services.quiz_material import join_chunks, pick_list, unfit_reason
con = sqlite3.connect(sys.argv[1])
for h in ("The Birth of NoSQL", "Operability: Making Life Easy for Operations", "Hardware Faults", "EXTRACTS."):
    texts = [r[0] for r in con.execute("select c.text from chunks c join sections s on s.id=c.section_id where s.heading=? order by chunk_index", (h,))]
    p = join_chunks(texts[:4])
    print(h, "|", unfit_reason(p), "|", pick_list(p, 2))
