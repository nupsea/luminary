"""NLI entailment and contradiction of a list question's wrong option by its nearest untested item."""
import torch

from app.services import quiz_nli

PAIRS = [
    ("true", "Keeping software and platforms up to date, including security patches",
     "Ensuring software and platforms are up to date with performance patches."),
    ("false", "Keeping software and platforms up to date, including security patches",
     "Ensuring software updates and security patches are user-installed."),
    ("garbled", "Tracking down the cause of problems, such as system failures or degraded performance",
     "Monitoring the cause of problems when systems are operating smoothly."),
    ("false", "On yet lower levels, hardware engineers have figured out how to represent bytes in terms of electrical currents, pulses of light, magnetic fields, and more.",
     "API developers represent electrical currents, pulses of light, magnetic fields in terms of bytes."),
    ("false", "When you want to store those data structures, you express them in terms of a general-purpose data model, such as JSON or XML documents, tables in a relational database, or a graph model.",
     "Application developers decide how to represent JSON/XML/relational/graph data as bytes."),
]
nli = quiz_nli._get()
nli._load()
labels = {v.lower(): k for k, v in nli._model.config.id2label.items()}
for kind, premise, option in PAIRS:
    enc = nli._tokenizer([premise], [option], return_tensors="pt", truncation="only_first")
    with torch.no_grad():
        p = nli._model(**enc).logits.softmax(-1)[0]
    print(f"{kind:8} entail {p[labels['entailment']]:.2f} neutral {p[labels['neutral']]:.2f} contra {p[labels['contradiction']]:.2f}  {option[:60]}")
