#!/usr/bin/env python3
"""Measure what a model costs and what it can do, one model at a time.

`ModelProfile.resident_bytes` and `min_ram_gb` decide whether a model is offered
on someone's laptop, so a guessed value is worse than no entry at all. Everything
this prints is either read from the runtime or measured against it:

  resident_bytes    Ollama's own `/api/ps` figure after a real generation at the
                    deployed context window. Weights plus one KV cache, which is
                    what `resident_bytes` is defined as -- and the KV cache is
                    why the measurement must happen at `OLLAMA_NUM_CTX` rather
                    than at whatever default a bare `/api/generate` would use.
  max_context       `/api/show`. The model's advertised window, which is a
                    capability and not a budget (I-27) -- recorded so a
                    deployment choice can be made against it, never adopted.
  multimodal        `/api/show` capabilities.
  supports_json_
  schema            probed: ask for prose with `format=json` and see whether the
                    runtime constrains it. What a model *does*, not what a name
                    suggests.
  thinking_default  probed: generate with no `think` flag and look for a
                    reasoning trace. `think=False` is unconditional in the app
                    for this reason, so this records which models it matters for.

`min_ram_gb` is the one derived number, and it is policy rather than
measurement: twice the resident size, rounded up to a common RAM tier. The
model gets half the machine and the other half carries the OS, the backend
(measured at 4.7GB peak during ingest), the embedder, the entity model and page
cache. That rule reproduces all three hand-written registry entries, which is
the only evidence available that it matches what a human would have chosen.

Run with the machine otherwise idle, and expect one model load per candidate::

    uv run python ../scripts/model_footprint.py --models llama3.2,phi4-mini
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_GB = 1024**3

# Common physical RAM sizes. A machine is not built with 13GB, so a threshold
# between tiers would only ever be rounded up by reality anyway.
RAM_TIERS = (8, 16, 24, 32, 48, 64, 96, 128)

# The model gets half the machine; see the module docstring for what the other
# half carries.
_HEADROOM_MULTIPLIER = 2


def min_ram_for(resident_bytes: int) -> int:
    needed = (resident_bytes / _GB) * _HEADROOM_MULTIPLIER
    for tier in RAM_TIERS:
        if tier >= needed:
            return tier
    return RAM_TIERS[-1]


def _unload(client: httpx.Client, ollama: str, model: str) -> None:
    """Ask the runtime to drop a model now, so the next measurement is clean."""
    with contextlib.suppress(httpx.HTTPError):
        client.post(
            f"{ollama}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=60.0,
        )


def _loaded(client: httpx.Client, ollama: str) -> list[dict[str, Any]]:
    resp = client.get(f"{ollama}/api/ps", timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("models") or []


def _clear(client: httpx.Client, ollama: str) -> None:
    for entry in _loaded(client, ollama):
        _unload(client, ollama, entry["name"])


def _show(client: httpx.Client, ollama: str, model: str) -> dict[str, Any]:
    resp = client.post(f"{ollama}/api/show", json={"model": model}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def _generate(
    client: httpx.Client,
    ollama: str,
    model: str,
    prompt: str,
    num_ctx: int,
    *,
    fmt: str | None = None,
    think: bool | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx},
        "keep_alive": "5m",
    }
    if fmt:
        body["format"] = fmt
    if think is not None:
        body["think"] = think
    resp = client.post(f"{ollama}/api/generate", json=body, timeout=600.0)
    resp.raise_for_status()
    return resp.json()


def _max_context(show: dict[str, Any]) -> int | None:
    info = show.get("model_info") or {}
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


def measure(client: httpx.Client, ollama: str, model: str, num_ctx: int) -> dict[str, Any]:
    """One model, loaded alone, measured at the deployed context window."""
    print(f"\n>>> {model}")
    _clear(client, ollama)

    show = _show(client, ollama, model)
    details = show.get("details") or {}
    capabilities = show.get("capabilities") or []

    started = time.monotonic()
    _generate(client, ollama, model, "Name one primary colour. Answer in one word.", num_ctx)
    load_s = round(time.monotonic() - started, 1)

    stem = model.split(":", maxsplit=1)[0]
    resident = next((e for e in _loaded(client, ollama) if e["name"].startswith(stem)), None)
    if resident is None:
        raise RuntimeError(f"{model} was not resident after a generation; cannot measure it")

    # Ask for prose while demanding JSON. A runtime that honours the constraint
    # cannot answer in prose whatever the model would prefer.
    #
    # Probed with think=False, which is what every call in the app sets (I-27).
    # Without it this measures nothing on a thinking model: qwen3.5:4b put the
    # whole JSON object into the `thinking` field and returned an empty
    # `response`, which reads as "does not support JSON" and is really the
    # empty-answer failure that made think=False mandatory in the first place.
    forced = _generate(
        client,
        ollama,
        model,
        "Say hello in one friendly sentence.",
        num_ctx,
        fmt="json",
        think=False,
    )
    answer = (forced.get("response") or "").strip()
    json_ok = answer.startswith(("{", "["))

    # Separately, and deliberately without the flag: does this model think unless
    # told not to? That is what decides whether think=False is load-bearing for it.
    unflagged = _generate(client, ollama, model, "Name one primary colour.", num_ctx)
    thinking = bool(unflagged.get("thinking")) or "<think>" in (unflagged.get("response") or "")
    thinking_empties_response = thinking and not (unflagged.get("response") or "").strip()

    size = int(resident.get("size") or 0)
    entry = {
        "model": model,
        "resident_bytes": size,
        "resident_gb": round(size / _GB, 2),
        "size_vram_gb": round(int(resident.get("size_vram") or 0) / _GB, 2),
        "min_ram_gb": min_ram_for(size),
        "measured_at_num_ctx": num_ctx,
        "max_context": _max_context(show),
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "family": details.get("family"),
        "capabilities": capabilities,
        "multimodal": "vision" in capabilities,
        "supports_json_schema": json_ok,
        "thinking_default": thinking,
        # The dangerous case: it thought AND returned nothing. Every prompt in
        # this app is direct-answer shaped, so a model that does this without
        # think=False produces an empty answer rather than a slow one.
        "thinking_empties_response": thinking_empties_response,
        "cold_load_and_generate_s": load_s,
    }
    _unload(client, ollama, model)
    return entry


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 92}")
    print("  Measured model footprints")
    print(f"{'=' * 92}")
    header = (
        f"  {'model':<26} {'resident':>9} {'min_ram':>8} {'params':>8} "
        f"{'quant':>9} {'max_ctx':>9} {'json':>5} {'think':>6}"
    )
    print(header)
    for r in rows:
        print(
            f"  {r['model']:<26} {r['resident_gb']:>8.2f}G {r['min_ram_gb']:>7}G "
            f"{r['parameter_size'] or '-'!s:>8} {r['quantization'] or '-'!s:>9} "
            f"{r['max_context'] or '-'!s:>9} {'yes' if r['supports_json_schema'] else 'no':>5} "
            f"{'yes' if r['thinking_default'] else 'no':>6}"
        )
    print(f"{'=' * 92}")
    print("  resident = Ollama /api/ps after a real generation at the deployed num_ctx")
    print("  min_ram  = policy: 2x resident, rounded to a RAM tier (see module docstring)")
    print("  max_ctx  = the model's advertised window: a capability, not a budget (I-27)\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", required=True, help="comma-separated Ollama model names")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument(
        "--num-ctx",
        type=int,
        default=8192,
        help="the deployed OLLAMA_NUM_CTX; the KV cache is part of what is measured",
    )
    ap.add_argument("--out", default=".luminary/model_footprints.jsonl")
    args = ap.parse_args()

    ollama = args.ollama.rstrip("/")
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    rows: list[dict[str, Any]] = []
    with httpx.Client() as client:
        try:
            client.get(f"{ollama}/api/tags", timeout=10.0).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Ollama not reachable at {ollama}: {exc}", file=sys.stderr)
            return 1

        for model in models:
            try:
                rows.append(measure(client, ollama, model, args.num_ctx))
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"  FAILED {model}: {exc}", file=sys.stderr)

        _clear(client, ollama)

    if not rows:
        print("nothing measured", file=sys.stderr)
        return 1

    _print_table(rows)

    out = Path(args.out)
    if not out.is_absolute():
        out = Path(__file__).resolve().parent.parent / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"  appended {len(rows)} row(s) to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
