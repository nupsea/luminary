"""Miss, with confidence, the banked item tied to a card; show what reached the learner record."""

import asyncio
import sqlite3
import sys

from httpx import ASGITransport, AsyncClient

from app.main import app

DB, DOC, SECTION, CARD = sys.argv[1:5]


async def main() -> None:
    con = sqlite3.connect(DB)
    before = con.execute("select fsrs_state, reps, lapses, due_date from flashcards where id=?", (CARD,)).fetchone()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:7820", timeout=120) as c:
        quiz = (await c.post("/study/quizzes", json={"document_id": DOC, "scope_type": "section", "scope_ref": SECTION, "difficulty": "easy", "question_kinds": "multi", "question_count": 1})).json()
        while quiz["status"] == "building":
            await asyncio.sleep(1)
            quiz = (await c.get(f"/study/quizzes/{quiz['id']}")).json()
        q = quiz["questions"][0]
        ids = [o["id"] for o in q["options"]]
        right = dict(con.execute(f"select id, is_correct from quiz_options where id in ({','.join('?' * len(ids))})", ids).fetchall())
        wrong = [i for i in ids if not right[i]][:1]
        resp = (await c.post(f"/study/quizzes/{quiz['id']}/answers", json={"position": 0, "selected_option_ids": wrong, "confidence": "sure"})).json()
        print("item", q["item_id"], "outcome", resp["outcome"], "card_reset", resp["card_reset"])
    after = con.execute("select fsrs_state, reps, lapses, due_date from flashcards where id=?", (CARD,)).fetchone()
    print("card before", before, "\ncard after ", after)
    print("misconceptions", con.execute("select error_type, substr(user_answer,1,60), substr(correction_note,1,60) from misconceptions where flashcard_id=? order by detected_at desc limit 1", (CARD,)).fetchall())
    print("schedule log", con.execute("select kind, rating, state from card_state_events where flashcard_id=? order by id desc limit 2", (CARD,)).fetchall())


asyncio.run(main())
