"""Right options scored as 'question + answer' against the passage, beside the bare option."""
import json, sys
sys.path.insert(0, "nli")
from check_25 import windows, score  # noqa: E402  (loads the model once)
items = json.load(open(sys.argv[1]))
for it in items:
    w = windows(it["passage"])
    for oi, o in enumerate(it["options"]):
        if not o["right"]:
            continue
        bare, _ = score(w, o["text"])
        joined, _ = score(w, f"{it['stem']} {o['text']}")
        print(f"{it['n']:>2}.{oi} bare {bare:.2f} with-stem {joined:.2f}  {o['text'][:80]}", flush=True)
