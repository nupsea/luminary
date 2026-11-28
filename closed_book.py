"""Ask a small model each item without its passage, three shuffles each: a test-wise guess rate."""
import json, random, sys, urllib.request

MODEL, ITEMS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
items = json.load(open(ITEMS))
rng = random.Random(7)

def ask(prompt):
    body = json.dumps({"model": MODEL, "stream": False, "think": False,
                       "options": {"temperature": 0, "num_predict": 8},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))["message"]["content"]

out = []
for it in items:
    hits = 0
    for _ in range(3):
        opts = list(enumerate(it["options"]))
        rng.shuffle(opts)
        letters = "ABCDE"
        lines = "\n".join(f"{letters[i]}. {o['text']}" for i, (_, o) in enumerate(opts))
        n_right = sum(o["right"] for o in it["options"])
        ask_for = "the one best answer" if n_right == 1 else f"all {n_right} right answers"
        reply = ask(f"{it['stem']}\n\n{lines}\n\nReply with only the letter of {ask_for}, e.g. 'B' or 'A,C'.")
        picked = {c for c in reply.upper() if c in letters[: len(opts)]}
        right = {letters[i] for i, (_, o) in enumerate(opts) if o["right"]}
        hits += picked == right
    out.append({"n": it["n"], "hits": hits, "claude": it["claude"]["verdict"], "tags": it["claude"]["tags"]})
    print(it["n"], hits, it["claude"]["verdict"], it["claude"]["tags"], flush=True)
json.dump(out, open(OUT, "w"))
