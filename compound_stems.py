"""Stems asking two questions at once ("what X, and why Y"), against Claude's verdicts where there are any."""
import glob, json, os, re, sqlite3
PAT = re.compile(r",?\s+and\s+(?:what|why|how|which|who|whom|where|when)\b", re.I)
verdicts = {}
for f in glob.glob("partial/verdicts_run*.json"):
    verdicts.update(json.load(open(f)))
seen = set()
for db in sorted(glob.glob(os.path.expanduser("~/DEV/LM/lm-quiz-verify-data/luminary*.db"))):
    for iid, stem in sqlite3.connect(db).execute("select id, stem from quiz_items"):
        if stem in seen: continue
        seen.add(stem)
        if PAT.search(stem):
            print(os.path.basename(db)[10:-3], "|", (verdicts.get(iid) or ["-"])[0], "|", stem)
print(len(seen), "stems")
