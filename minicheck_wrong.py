"""bespoke-minicheck on every reviewed wrong option of runs 8 to 11: P(Yes) against the item's
passage, and against the five nearest document chunks the builder's elsewhere check reads."""
import asyncio, json, math, sys, urllib.request

from app.services.retriever import get_retriever

DOCS = {"DDIA": "dad8a693-b933-4935-a580-a03b1866255d", "moby-dick": "b573268f-0319-4236-a029-ac732cbddd89",
        "federalist_papers": "fa6e1ca4-ea86-414e-86dc-cc87637791d3"}
TRUE = {
    "Ensuring software and platforms are up to date with performance patches.",
    "It stops economic disputes between states.",
    "Ishmael needed to improve his health and well-being, so he chose sailing.",
}
OUT = sys.argv[1]


def p_yes(document: str, claim: str) -> float:
    body = json.dumps({"model": "bespoke-minicheck:latest", "prompt": f"Document: {document}\nClaim: {claim}",
                       "stream": False, "logprobs": True, "top_logprobs": 5,
                       "options": {"temperature": 0, "num_predict": 1, "num_ctx": 8192}}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", body, {"Content-Type": "application/json"})
    top = json.load(urllib.request.urlopen(req, timeout=300))["logprobs"][0]["top_logprobs"]
    yes = sum(math.exp(t["logprob"]) for t in top if t["token"].strip().lower() == "yes")
    no = sum(math.exp(t["logprob"]) for t in top if t["token"].strip().lower() == "no")
    return yes / (yes + no) if yes + no else 0.0


async def main():
    rows = []
    for run in (8, 9, 10, 11):
        items = json.load(open(f"partial/items_run{run}.json"))
        verdicts = json.load(open(f"partial/verdicts_run{run}.json"))
        for it in items:
            for o in it["options"]:
                if o["right"]:
                    continue
                hits = await asyncio.to_thread(get_retriever().vector_search, o["text"], [DOCS[it["document"]]], 5)
                near_text = "\n\n".join(h.text for h in hits)
                row = {"run": run, "item": it["item_id"], "verdict": verdicts.get(it["item_id"], ["?"])[0],
                       "tags": verdicts.get(it["item_id"], [None, None, []])[2], "label": "true" if o["text"] in TRUE else "false",
                       "text": o["text"], "passage": p_yes(it["passage"], o["text"]),
                       "near": p_yes(near_text, o["text"]) if near_text else None}
                rows.append(row)
                print(f"{row['label']:5} r{run} pass={row['passage']:.2f} near={row['near'] if row['near'] is None else round(row['near'],2)} | {o['text'][:80]}", flush=True)
    json.dump(rows, open(OUT, "w"), indent=1)

asyncio.run(main())
