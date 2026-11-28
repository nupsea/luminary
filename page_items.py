"""Merge exported runs and Claude's verdicts into one items.json for the rating page.

Usage: page_items.py <out.json> <label>:<items.json>:<verdicts.json> [...]
Verdicts are keyed by item id: [verdict, why, tags].
"""
import json
import sys

out = []
for arg in sys.argv[2:]:
    label, items_path, verdicts_path = arg.split(":")
    verdicts = json.load(open(verdicts_path))
    for item in json.load(open(items_path)):
        verdict, why, tags = verdicts[item["item_id"]]
        item.update(run=label, claude={"verdict": verdict, "why": why, "tags": tags})
        out.append(item)
for n, item in enumerate(out, 1):
    item["n"] = n
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(len(out), "items ->", sys.argv[1])
