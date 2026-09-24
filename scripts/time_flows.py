#!/usr/bin/env python3
"""Time the flows a reader waits on, against a running Luminary, for cross-host parity.

Ingests one book into an EMPTY library, waits until its background model work has
settled, then times Ask, flashcard generation and a teach-back evaluation. Timing
during that backlog measured where each call landed against it, not the host.

Every host must serve the same model: an answer served by any other model than
--expect-model fails the run instead of being timed.

    python3 scripts/time_flows.py --base http://127.0.0.1:7820 --label m3-pro

Standard library only, so it runs on a machine with just the installed app.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BOOK = REPO / "DATA/books/frankenstein.txt"
# Tied to the default book; pass --question for any other.
DEFAULT_QUESTIONS = (
    "Why does Victor Frankenstein abandon the creature?",
    "What does the creature learn from watching the De Lacey family?",
    "How does Walton's voyage frame the story?",
)


class RunFailed(Exception):
    pass


def _request(
    base: str,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 900,
):
    # --base is refused unless http(s) in main().
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})  # noqa: S310
    try:
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as e:
        raise RunFailed(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}") from e


def _json(base: str, method: str, path: str, payload: object | None = None, timeout: float = 900):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if body else {}
    with _request(base, method, path, body, headers, timeout) as resp:
        return json.loads(resp.read())


def _multipart(book: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{book.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    return head + book.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), boundary


def check_engine(base: str, expect_model: str) -> None:
    # Cards and teach-back carry no receipt, so the settings are their only witness.
    llm = _json(base, "GET", "/settings/llm")
    chat = llm["local_chat_model"].removeprefix("ollama/")
    if llm["mode"] != "private" or chat != expect_model.removeprefix("ollama/"):
        raise RunFailed(
            f"engine is {llm['mode']} / {llm['local_chat_model']!r}; set Local (private) and "
            f"{expect_model} in Settings first"
        )


def ingest(base: str, book: Path, t0: float, limit_s: float) -> tuple[str, dict[str, float]]:
    body, boundary = _multipart(book)
    with _request(
        base,
        "POST",
        "/documents/ingest",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    ) as resp:
        started = json.loads(resp.read())
    if started["status"] == "duplicate":
        # A deduplicated upload returns at once and would time as a 0s ingest.
        raise RunFailed(f"the library already holds {book.name}; run against an empty library")
    doc_id = started["document_id"]
    stages: dict[str, float] = {}
    while True:
        status = _json(base, "GET", f"/documents/{doc_id}/status")
        elapsed = time.monotonic() - t0
        stages.setdefault(status["stage"], round(elapsed, 1))
        if status["stage"] == "error":
            raise RunFailed(f"ingest failed: {status['error_message']}")
        if status["done"]:
            return doc_id, stages
        if elapsed > limit_s:
            raise RunFailed(f"ingest not complete after {limit_s:.0f}s; stages {stages}")
        time.sleep(2)


def admission(base: str) -> dict:
    return _json(base, "GET", "/monitoring/metrics")["llm_admission"]


def settle(base: str, t0: float, quiet_s: float, limit_s: float) -> float:
    """Seconds from upload until no background model call has run or waited for quiet_s.

    "complete" is not idle: section summaries and tagging run for minutes after it.
    """
    quiet_since = None
    while True:
        now = time.monotonic()
        state = admission(base)
        if state["background_inflight"] or state["background_waiting"]:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= quiet_s:
            return round(quiet_since - t0, 1)
        if now - t0 > limit_s:
            raise RunFailed(f"background work still running {limit_s:.0f}s after upload")
        time.sleep(2)


def check_uncontended(before: dict, after: dict) -> None:
    forced = after["forced_admissions"] - before["forced_admissions"]
    if forced:
        # The starvation guard pushed background calls into a timed flow.
        raise RunFailed(f"{forced} background call(s) forced into the timed flows")


def ask(base: str, doc_id: str, question: str, expect_model: str) -> dict:
    payload = {"question": question, "document_ids": [doc_id], "scope": "single"}
    t0 = time.monotonic()
    first_token = None
    final = None
    with _request(
        base, "POST", "/qa", json.dumps(payload).encode(), {"Content-Type": "application/json"}
    ) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "error" or ("error" in event and "token" not in event):
                raise RunFailed(f"/qa error for {question!r}: {event}")
            if "token" in event and first_token is None:
                first_token = time.monotonic() - t0
            if event.get("done"):
                final = event
    total = time.monotonic() - t0
    receipt = (final or {}).get("receipt") or {}
    served = receipt.get("model")
    if served != expect_model:
        raise RunFailed(f"answer served by {served!r}, not {expect_model!r}")
    if first_token is None:
        raise RunFailed(f"/qa streamed no answer for {question!r}")
    return {
        "question": question,
        "ttft_s": round(first_token, 2),
        "total_s": round(total, 2),
        "not_found": bool(final.get("not_found")),
    }


def flashcards(base: str, doc_id: str, count: int) -> tuple[list[dict], float]:
    t0 = time.monotonic()
    cards = _json(base, "POST", "/flashcards/generate", {"document_id": doc_id, "count": count})
    elapsed = time.monotonic() - t0
    if not cards:
        # Zero cards is a failed generation, not a fast one.
        raise RunFailed("flashcard generation returned no cards")
    return cards, round(elapsed, 2)


def teachback(base: str, card: dict) -> float:
    # Timed only: the explanation is the card's own answer, so the score means nothing.
    t0 = time.monotonic()
    _json(
        base,
        "POST",
        "/study/teachback",
        {"flashcard_id": card["id"], "user_explanation": card["answer"]},
    )
    return round(time.monotonic() - t0, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:7820")
    ap.add_argument("--label", required=True, help="host name for the report, e.g. m3-pro")
    ap.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    ap.add_argument("--question", action="append", help="repeatable; defaults fit the default book")
    ap.add_argument("--expect-model", default="ollama/qwen3.5:4b")
    ap.add_argument("--cards", type=int, default=5)
    ap.add_argument("--ingest-limit", type=float, default=3600, help="upload to settled, seconds")
    ap.add_argument("--quiet", type=float, default=30, help="idle seconds that count as settled")
    ap.add_argument("--out", type=Path, help="write the report as JSON")
    args = ap.parse_args()
    if not args.base.startswith(("http://", "https://")):
        ap.error("--base must be an http(s) URL")
    if args.question is None and args.book.resolve() != DEFAULT_BOOK:
        ap.error("--question is required with a book other than the default")
    questions = args.question or list(DEFAULT_QUESTIONS)

    report: dict = {
        "label": args.label,
        "platform": platform.platform(),
        "book": args.book.name,
        "model": args.expect_model,
    }
    try:
        check_engine(args.base, args.expect_model)
        t0 = time.monotonic()
        doc_id, stages = ingest(args.base, args.book, t0, args.ingest_limit)
        report["ingest_stages_s"] = stages
        report["settled_s"] = settle(args.base, t0, args.quiet, args.ingest_limit)
        before = admission(args.base)
        report["ask"] = [ask(args.base, doc_id, q, args.expect_model) for q in questions]
        cards, report["flashcards_s"] = flashcards(args.base, doc_id, args.cards)
        report["flashcards_delivered"] = len(cards)
        report["teachback_s"] = teachback(args.base, cards[0])
        check_uncontended(before, admission(args.base))
    except RunFailed as e:
        report["failed"] = str(e)
        print(json.dumps(report, indent=2))
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    report["ask_median_ttft_s"] = statistics.median(a["ttft_s"] for a in report["ask"])
    report["ask_median_total_s"] = statistics.median(a["total_s"] for a in report["ask"])
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
