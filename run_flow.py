"""An adaptive practice quiz on DDIA, answered right, right, wrong (sure), right; then finish,
retake and to-card. Prints what each step returned and what reached the learner record."""

import asyncio
import json
import sqlite3
import sys

from httpx import ASGITransport, AsyncClient

from app.main import app

DOC = "dad8a693-b933-4935-a580-a03b1866255d"
DB = sys.argv[1]
PLAN = [("right", "sure"), ("right", "think"), ("wrong", "sure"), ("right", "guess")]


def truth(option_ids: list[str]) -> dict[str, bool]:
    con = sqlite3.connect(DB)
    marks = ",".join("?" * len(option_ids))
    rows = con.execute(f"select id, is_correct from quiz_options where id in ({marks})", option_ids)
    return {i: bool(c) for i, c in rows}


async def main() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:7820", timeout=120
    ) as c:
        quiz = (
            await c.post(
                "/study/quizzes",
                json={"document_id": DOC, "difficulty": "adaptive", "question_count": 4},
            )
        ).json()
        qid = quiz["id"]
        for position, (pick, confidence) in enumerate(PLAN):
            while True:
                quiz = (await c.get(f"/study/quizzes/{qid}")).json()
                if len(quiz["questions"]) > position or quiz["status"] != "building":
                    break
                await asyncio.sleep(1)
            if len(quiz["questions"]) <= position:
                print("stopped:", quiz["status"], quiz["error"])
                break
            q = quiz["questions"][position]
            right = truth([o["id"] for o in q["options"]])
            hidden = all(o["is_correct"] is None for o in q["options"])
            chosen = [o["id"] for o in q["options"] if right[o["id"]] == (pick == "right")]
            chosen = chosen if pick == "right" else chosen[:1]
            resp = await c.post(
                f"/study/quizzes/{qid}/answers",
                json={"position": position, "selected_option_ids": chosen, "confidence": confidence},
            )
            body = resp.json()
            print(
                json.dumps(
                    {
                        "pos": position,
                        "level": q["level"],
                        "kind": q["kind"],
                        "select_count": q["select_count"],
                        "hidden_before": hidden,
                        "status": resp.status_code,
                        "outcome": body.get("outcome"),
                        "card_reset": body.get("card_reset"),
                        "retake": body.get("retake"),
                        "revealed": body["question"]["revealed"],
                        "quotes": sum(1 for o in body["question"]["options"] if o["quote"]),
                    }
                )
            )
        done = (await c.post(f"/study/quizzes/{qid}/finish")).json()
        print("results:", json.dumps(done["results"]))
        retake = await c.post(f"/study/quizzes/{qid}/retake")
        print("retake:", retake.status_code, [q["position"] for q in retake.json()["questions"]])
        single = next(
            (q for q in done["questions"] if q["kind"] == "single"), done["questions"][0]
        )
        card = await c.post(f"/study/quiz-items/{single['item_id']}/to-card")
        print("to-card:", card.status_code, card.json())
        con = sqlite3.connect(DB)
        session = con.execute("select session_id from quizzes where id=?", (qid,)).fetchone()[0]
        print(
            "study session:",
            con.execute(
                "select mode, cards_reviewed, cards_correct, ended_at is not null "
                "from study_sessions where id=?",
                (session,),
            ).fetchone(),
        )
        print(
            "review events in the quiz session:",
            con.execute(
                "select rating, count(*) from review_events where session_id=? group by rating",
                (session,),
            ).fetchall(),
        )


asyncio.run(main())
