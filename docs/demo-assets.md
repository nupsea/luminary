---
description: How the README's demo GIFs are recorded and produced, and the library state they must be recorded against.
---

# Demo assets

The README's hero is a GIF, not a video. GitHub strips `<video>` tags from
Markdown and sanitizes animated SVG, so an animated GIF referenced with a normal
image tag is the only thing that reliably plays on the front page. A linked
YouTube tour sits underneath it for anyone who wants more.

## Before recording anything

The library on screen is the product's first impression, and the previous
screenshots shipped with three documents reading `Enrichment failed`, several at
`0 words`, and the same YouTube video listed three times.

- [ ] Every document `stage=complete`, no failure badges, no `0 words` rows.
- [ ] No duplicate titles.
- [ ] Rename filename-shaped titles — `audit_unseen_arxiv_2508.03858` and
      `Chess2405.16755v1` read as debris next to `Attention` and `moby-dick`.
- [ ] Decide what is in frame. The library is personal; anything in it is
      published.
- [ ] Light theme, default zoom, window at 1440×900. Larger windows produce a
      GIF whose text is unreadable once GitHub scales it into the README column.
- [ ] Hide the OS menu bar clock and any notification that could fire mid-take.

Check the first two from the API rather than by eye:

```bash
curl -s "http://localhost:7820/documents?limit=200" | python3 -c "
import sys,json,collections
items=json.load(sys.stdin).get('items',[])
print('stages:', dict(collections.Counter(i['stage'] for i in items)))
print('zero-word:', sum(1 for i in items if not i.get('word_count')))
titles=[i['title'] for i in items]
print('duplicates:', [t for t,n in collections.Counter(titles).items() if n>1])
"
```

## Hero: "it keeps working with the wifi off"

Roughly 12 seconds. It proves the one claim competitors cannot copy, needs no
narration, and survives being watched with sound off in a README column.

| Beat | Seconds | On screen |
|---|---|---|
| 1 | 0.0–1.5 | Ask tab, a document already in scope. Cursor moves to the macOS menu bar. |
| 2 | 1.5–3.0 | Wi-Fi menu opens, **Wi-Fi switched off**. The menu-bar icon visibly changes. Hold one beat on the off state. |
| 3 | 3.0–4.5 | Type a real question about the document. Keep it short enough to finish in a beat. |
| 4 | 4.5–9.0 | The answer **streams in**. Do not cut this — streaming tokens are what makes it read as live rather than staged. |
| 5 | 9.0–11.0 | Click a citation chip. The reader opens on the passage; the chip shows its section and page. |
| 6 | 11.0–12.0 | Hold on the source with the wifi icon still off in frame. Freeze. |

Two things make or break it. **The wifi icon must stay visible in every frame** —
crop to include the menu bar, or the whole point is unproven. And **beat 5 needs
the citation fix** (`fix/citation-section-and-page`): before it, chips render
with no section and `page 0`, which undersells exactly what the shot exists to
show.

Suggested question, because the answer is short and the document is recognisable:
against `Attention`, ask *"What problem does multi-head attention solve?"*

## Later shots, in priority order

Each is a separate short GIF, placed next to the section it illustrates rather
than at the top.

1. **The receipt.** Ask → answer → click citation → reader opens on the exact
   passage, section and page on the chip. Illustrates "every answer shows its
   receipts". ~10s.
2. **Do you actually know it?** Card appears → predict *Know it* → flip → wrong →
   the calibration graph moves. Nobody else measures whether your self-assessment
   is honest. ~12s.
3. **One source, four surfaces.** Paste a YouTube URL → transcript, summary,
   flashcards and search results appear. Shows ingest breadth. ~15s, needs a
   speed-up over the ingestion wait.
4. **A card that admits it.** A deck showing `verified` next to `unverifiable`.
   The strongest honesty shot and the riskiest — it shows the product declining
   to certify, which reads as a feature only with a caption.

## Producing the file

Record with QuickTime (File → New Screen Recording), stop, save. Then one
command:

```bash
scripts/make_gif.sh ~/Desktop/raw.mov offline
```

It writes `assets/images/offline.gif` and prints the Markdown to paste. Needs
`ffmpeg` (`brew install ffmpeg`).

Trim and tune with environment variables rather than re-recording:

```bash
START=2.5 DURATION=12 scripts/make_gif.sh ~/Desktop/raw.mov offline   # cut the lead-in
FPS=10 WIDTH=800      scripts/make_gif.sh ~/Desktop/raw.mov offline   # smaller file
```

| Variable | Default | Why |
|---|---|---|
| `FPS` | 12 | Enough for UI motion; roughly half the size of 24 |
| `WIDTH` | 900 | The README column. Wider is unreadable once GitHub scales it |
| `START` / `DURATION` | whole clip | Trim without re-recording |
| `MAX_MB` | 5 | Warn above this |

The script builds the palette from the clip's own frames rather than using
ffmpeg's default. A global palette banks colours the UI never uses and renders
small text mushy, which is the usual reason a UI GIF looks worse than the
recording.

Target 2–3 MB. Over 5 MB the script tells you and lists what to try, in order:
cut a beat, drop to 10 fps, then narrow to 800 px. **Do not cut the beat where
the answer streams in** — a GIF that jumps to a finished answer reads as staged.

## Keeping them honest

A demo asset is a claim about the product, and the same rule applies to it as to
a number: it must show what the product actually does on the day it ships.

- Re-record when the surface in the shot changes. A GIF of a superseded layout is
  worse than no GIF, because it is indistinguishable from the current one.
- Never speed up a model response to look faster than it is. Speeding up an
  *ingestion wait* is fine and should carry an on-screen label.
- The library in frame is real. Do not stage a document the product never
  ingested.
