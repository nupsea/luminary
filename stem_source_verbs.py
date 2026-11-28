"""Stems in the saved run databases that name their source as the actor ("the text uses")."""
import glob, re, sqlite3, os
PAT = re.compile(
    r"\bthe\s+(?:text|passage|excerpt|material|document|book|chapter|section|author|writer|narrator)\s+"
    r"(?:us|mak|giv|offer|compar|illustrat|provid|portray|depict|paint|draw|lay|focus|conclud|reveal|convey)\w*\b",
    re.I,
)
seen = set()
hit = 0
for db in sorted(glob.glob(os.path.expanduser("~/DEV/LM/lm-quiz-verify-data/luminary*.db"))):
    con = sqlite3.connect(db)
    for (stem,) in con.execute("select stem from quiz_items"):
        if stem in seen: continue
        seen.add(stem)
        m = PAT.search(stem)
        if m:
            hit += 1
            print(os.path.basename(db), "|", m.group(0), "|", stem)
# flashcard questions in the dev library, for false hits on the card side's vocabulary
con = sqlite3.connect(os.path.expanduser("~/DEV/LM/learning-mate/.luminary/luminary.db"))
cards = [q for (q,) in con.execute("select question from flashcards")]
fc = [(PAT.search(q).group(0), q) for q in cards if PAT.search(q)]
print(f"\nquiz stems {len(seen)}, hits {hit}; dev flashcards {len(cards)}, hits {len(fc)}")
for g, q in fc[:40]: print("  card |", g, "|", q)
