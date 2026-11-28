"""Entailment both ways between two wrong options: repeats against distinct claims."""
import asyncio

from app.services import quiz_nli
from measure_wrong_pairs import DISTINCT, REPEATS


async def main():
    for label, pairs in (("repeat", REPEATS), ("distinct", DISTINCT)):
        for a, b in pairs:
            ab = await quiz_nli.entailment([a], b)
            ba = await quiz_nli.entailment([b], a)
            print(f"{label:8} {ab:.2f} {ba:.2f} min {min(ab, ba):.2f}  {a[:45]} | {b[:45]}")

asyncio.run(main())
