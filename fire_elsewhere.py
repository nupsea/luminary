"""The builder's wrong_true_elsewhere check, as it calls it, on chosen wrong options."""
import asyncio

from app.services import quiz_nli
from app.services.quiz_builder import _Writer

FED = "fa6e1ca4-ea86-414e-86dc-cc87637791d3"
DDIA = "dad8a693-b933-4935-a580-a03b1866255d"
MOBY = "b573268f-0319-4236-a029-ac732cbddd89"
CASES = [
    ("true", FED, "It stops economic disputes between states."),
    ("true?", FED, "It ensures peace and stability in international relations."),
    ("true", DDIA, "Ensuring software and platforms are up to date with performance patches."),
    ("false", FED, "It defends states from environmental disasters alone."),
    ("false", FED, "Congress used military force to resolve disputes."),
    ("false", FED, "Congress declared the Western territory as federal land."),
    ("false", DDIA, "It keeps queues artificially long, skewing measurements of real-world performance."),
    ("false", DDIA, "Published tweets are far more numerous than home timeline reads, making this an efficient strategy."),
    ("false", MOBY, "The landlord suggested staying in a tent outside for the night."),
]


async def main():
    for label, doc, text in CASES:
        writer = _Writer(llm=None, model=None, document_id=doc)
        windows = await writer.elsewhere(text)
        score = await quiz_nli.entailment(windows, text)
        print(f"{label:6} {score:.2f} drop={score >= quiz_nli.ENTAILED} windows={len(windows)} | {text[:70]}", flush=True)

asyncio.run(main())
