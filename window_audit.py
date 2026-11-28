import asyncio, sys
from collections import Counter
from app.database import get_session_factory
from app.services import quiz_builder
from app.services.quiz_material import join_chunks, unfit_reason, _LICENCE

DOCS = {"DDIA": "dad8a693-b933-4935-a580-a03b1866255d", "moby-dick": "b573268f-0319-4236-a029-ac732cbddd89"}

async def main():
    async with get_session_factory()() as s:
        for name, doc in DOCS.items():
            chunks = await quiz_builder.scope_chunks(s, doc, None)
            runs = []
            for c in sorted(chunks, key=lambda c: c.chunk_index):
                if runs and quiz_builder._continues(runs[-1], c): runs[-1].append(c)
                else: runs.append([c])
            reasons = Counter()
            for run in runs:
                text = join_chunks([c.text or "" for c in run])
                if len(text) < 300: reasons["short"] += 1; continue
                r = unfit_reason(text); reasons[r or "fit"] += 1
                if r == "licence" and reasons["licence"] <= 4:
                    m = _LICENCE.search(text); print(name, "LICENCE:", repr(text[max(0,m.start()-80):m.end()+60]))
            print(name, dict(reasons))
asyncio.run(main())
