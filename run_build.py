"""Build quizzes on a copy of the dev library through the real routes, the real model and the
real embedder; record timings and the gate counters. No lifespan, so no startup jobs run."""

import asyncio
import json
import logging
import sys
import time

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import llm_output_stats

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("app.services.quiz_builder").setLevel(logging.INFO)
logging.getLogger("app.services.quiz_service").setLevel(logging.INFO)

DOCS = {
    "DDIA": "dad8a693-b933-4935-a580-a03b1866255d",
    "moby-dick": "b573268f-0319-4236-a029-ac732cbddd89",
    "federalist": "fa6e1ca4-ea86-414e-86dc-cc87637791d3",
    "sutton-barto": "109f17f3-332a-479b-9d5b-ff5f7c01a2c5",
}
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 8
OUT = sys.argv[2] if len(sys.argv) > 2 else "build_runs.json"
# Optional "doc:level,doc:level" to run only those.
ONLY = [tuple(p.split(":")) for p in sys.argv[3].split(",")] if len(sys.argv) > 3 else None


async def main() -> None:
    runs = []
    before = llm_output_stats.snapshot()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:7820", timeout=60
    ) as client:
        for name, doc_id in DOCS.items():
            for level in ("easy", "medium", "hard"):
                if ONLY and (name, level) not in ONLY:
                    continue
                start = time.monotonic()
                resp = await client.post(
                    "/study/quizzes",
                    json={
                        "document_id": doc_id,
                        "difficulty": level,
                        "question_kinds": "mixed",
                        "question_count": COUNT,
                        "mode": "exam",
                    },
                )
                resp.raise_for_status()
                quiz_id = resp.json()["id"]
                first = None
                while True:
                    quiz = (await client.get(f"/study/quizzes/{quiz_id}")).json()
                    if quiz["questions"] and first is None:
                        first = round(time.monotonic() - start, 1)
                    if quiz["status"] != "building":
                        break
                    await asyncio.sleep(2)
                run = {
                    "doc": name,
                    "level": level,
                    "quiz_id": quiz_id,
                    "status": quiz["status"],
                    "error": quiz["error"],
                    "built": len(quiz["questions"]),
                    "first_question_s": first,
                    "total_s": round(time.monotonic() - start, 1),
                }
                runs.append(run)
                print(json.dumps(run), flush=True)
    stats = llm_output_stats.delta(before, llm_output_stats.snapshot())
    with open(OUT, "w") as fh:
        json.dump({"runs": runs, "stats": stats}, fh, indent=2)
    print(json.dumps(stats.get("counts", stats), indent=1), flush=True)


asyncio.run(main())
