import asyncio, re, sqlite3, sys
from app.services import quiz_nli
from app.services.quiz_material import join_chunks
con = sqlite3.connect(sys.argv[1])
texts = [r[0] for r in con.execute("select c.text from chunks c join sections s on s.id=c.section_id where s.heading='The Birth of NoSQL' order by chunk_index")]
passage = join_chunks(texts)
hyp = "A need for free and open source software caused a desire to overthrow the dominance of commercial products instead."
async def main():
    w = quiz_nli.windows(passage)
    print("current windows", len(w), round(await quiz_nli.entailment(w, hyp), 3))
    bullets = re.sub(r"\s*•\s*", ". • ", passage)
    w2 = quiz_nli.windows(bullets)
    print("bullet-split", len(w2), round(await quiz_nli.entailment(w2, hyp), 3))
    lines = [l.strip() for l in re.split(r"•", passage) if l.strip()]
    print("per bullet", [round(await quiz_nli.entailment([l], hyp), 2) for l in lines])
asyncio.run(main())
