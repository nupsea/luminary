"""Score every option of the 25 rated-run items with bart-large-mnli against its passage.

Per option: the highest entailment and contradiction over passage windows of three sentences,
so a long passage does not dilute a one-sentence statement.
"""
import json, re, sys
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

torch.set_num_threads(4)
NAME = "facebook/bart-large-mnli"
tok = AutoTokenizer.from_pretrained(NAME)
model = AutoModelForSequenceClassification.from_pretrained(NAME).eval()
labels = {v.lower(): k for k, v in model.config.id2label.items()}

def sentences(text):
    text = re.sub(r"\s+", " ", text.replace("‐", "-"))
    parts = [p.strip() for p in re.split(r"(?<=[.!?”\"])\s+(?=[“\"A-Z(])", text) if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

def windows(text, size=3):
    s = sentences(text)
    return [" ".join(s[i:i + size]) for i in range(max(1, len(s) - size + 1))]

@torch.no_grad()
def score(premises, hyp):
    enc = tok(premises, [hyp] * len(premises), return_tensors="pt", padding=True, truncation="only_first", max_length=512)
    p = model(**enc).logits.softmax(-1)
    return float(p[:, labels["entailment"]].max()), float(p[:, labels["contradiction"]].max())

if __name__ != "__main__": items = []
else: items = json.load(open(sys.argv[1]))
true_wrong = {(2, 3), (10, 2), (10, 4), (19, 1), (19, 2), (19, 3), (21, 3), (21, 4)}  # (item n, option index) Claude judged true
rows = []
for it in items:
    w = windows(it["passage"])
    for oi, o in enumerate(it["options"]):
        e, c = score(w, o["text"])
        kind = "RIGHT" if o["right"] else ("WRONG*TRUE" if (it["n"], oi) in true_wrong else "wrong")
        rows.append((it["n"], oi, kind, e, c, o["text"][:80]))
        print(f"{it['n']:>2}.{oi} {kind:10} ent {e:.2f} con {c:.2f}  {o['text'][:90]}", flush=True)
if __name__ == "__main__": json.dump(rows, open(sys.argv[2], "w"))
