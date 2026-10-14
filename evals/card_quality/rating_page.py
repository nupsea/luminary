"""Write a blind rating page for a card file. Local only: the page quotes the source.

    python evals/card_quality/rating_page.py --cards labels/step4/cards.jsonl \
        --out labels/step4/rate.html [--seed 4]

Cards are shuffled and shown without run, arm or verdict. Ratings save in the browser and are
exported as JSON keyed by card_id; nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import html
import json
import random
from pathlib import Path

REASONS = (
    ("thin", "Answer too thin"),
    ("wrong", "Answer looks wrong"),
    ("trivial", "Not worth learning"),
    ("unclear", "Question unclear"),
    ("other", "Other (note)"),
)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Card rating</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --card:#fff; --line:#e7e5e4; --accent:#2563eb; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --card:#292524; --line:#44403c; --accent:#60a5fa; }}
}}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; margin:0; padding:16px; }}
main {{ max-width:760px; margin:0 auto; }}
header {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line);
  display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; margin:16px 0; }}
.meta {{ color:var(--muted); font-size:13px; }}
.q {{ font-weight:600; margin:8px 0; }}
.choices label {{ margin-right:12px; white-space:nowrap; }}
details {{ margin-top:8px; color:var(--muted); font-size:14px; }}
textarea {{ width:100%; box-sizing:border-box; margin-top:8px; background:var(--bg); color:var(--fg);
  border:1px solid var(--line); border-radius:6px; }}
button {{ background:var(--accent); color:#fff; border:0; border-radius:6px; padding:6px 12px; cursor:pointer; }}
.done {{ border-color:var(--accent); }}
</style></head><body><main>
<header><strong>Rate {n} cards</strong><span id="count" class="meta"></span>
<button id="export">Export ratings</button></header>
<p class="meta">Keep a card if you would want to learn it as written. Discard otherwise and say why.
Answers are checked against the source separately; mark "looks wrong" only if you notice.</p>
{cards}
</main>
<script>
const KEY = "card-rating-{key}";
let state = {{}};
try {{ state = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}} paint(); }}
function paint() {{
  let done = 0;
  document.querySelectorAll(".card").forEach(el => {{
    const s = state[el.dataset.id] || {{}};
    el.querySelectorAll("input[type=radio]").forEach(r => r.checked = s[r.name.split(":")[1]] === r.value);
    el.querySelector("textarea").value = s.note || "";
    el.querySelector(".reasons").style.display = s.verdict === "discard" ? "block" : "none";
    const ok = s.verdict === "keep" || (s.verdict === "discard" && s.reason);
    el.classList.toggle("done", !!ok); if (ok) done++;
  }});
  document.getElementById("count").textContent = done + " of {n} rated";
}}
document.addEventListener("change", e => {{
  const el = e.target.closest(".card"); if (!el) return;
  const s = state[el.dataset.id] = state[el.dataset.id] || {{}};
  if (e.target.type === "radio") s[e.target.name.split(":")[1]] = e.target.value;
  if (e.target.tagName === "TEXTAREA") s.note = e.target.value;
  if (s.verdict === "keep") delete s.reason;
  save();
}});
document.getElementById("export").onclick = () => {{
  const blob = new Blob([JSON.stringify(state, null, 1)], {{type: "application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "ratings-{key}.json"; a.click();
}};
paint();
</script></body></html>
"""

CARD = """<div class="card" data-id="{id}">
<div class="meta">{i}. {doc} — {chapter}</div>
<div class="q">{question}</div>
<div>{answer}</div>
<div class="choices" style="margin-top:8px">
<label><input type="radio" name="{id}:verdict" value="keep"> Keep</label>
<label><input type="radio" name="{id}:verdict" value="discard"> Discard</label>
</div>
<div class="choices reasons" style="display:none;margin-top:4px">{reasons}</div>
<details><summary>Source passage</summary><p>{passage}</p></details>
<textarea rows="1" placeholder="Note (optional)"></textarea>
</div>"""


def render(cards: list[dict], key: str) -> str:
    blocks = []
    for i, c in enumerate(cards, 1):
        esc = {k: html.escape(str(c.get(k, ""))) for k in ("doc", "chapter", "question", "answer")}
        reasons = "".join(
            f'<label><input type="radio" name="{c["card_id"]}:reason" value="{v}"> {label}</label>'
            for v, label in REASONS
        )
        passage = html.escape(c.get("passage", "")).replace("\n\n", "</p><p>")
        blocks.append(
            CARD.format(id=c["card_id"], i=i, reasons=reasons, passage=passage, **esc)
        )
    return PAGE.format(n=len(cards), cards="\n".join(blocks), key=key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()
    cards = [json.loads(x) for x in args.cards.read_text().splitlines() if x.strip()]
    random.Random(args.seed).shuffle(cards)
    args.out.write_text(render(cards, key=args.out.stem))
    print(f"{len(cards)} cards -> {args.out}")


if __name__ == "__main__":
    main()
