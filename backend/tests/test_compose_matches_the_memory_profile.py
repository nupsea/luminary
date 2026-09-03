"""Compose must not hand Ollama a budget the backend has already declined.

`memory_profile` resolves a host under 16GB to `low`, which keeps ONE model
resident. Compose defaulted OLLAMA_MAX_LOADED_MODELS=2, so on a small container
the runtime was configured to hold two models while the app had already decided
it could hold one. `config.py` warns about exactly this class of disagreement,
citing I-31: a backend and a runtime that disagree about capacity leave the
extra capacity idle at best, and overcommit the host at worst.

Compose cannot measure the host, so like OLLAMA_NUM_PARALLEL the default is a
floor that a larger host raises -- never a guess that a smaller host has to
survive.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "docker-compose.yml").read_text()


def _default_for(var: str) -> str:
    match = re.search(rf"{var}=\$\{{{var}:-([^}}]+)\}}", COMPOSE)
    assert match, f"{var} is not set with an overridable default in compose"
    return match.group(1)


def test_compose_ships_one_resident_model():
    """One model, because two do not fit the 16GB floor -- measured.

    `qwen3.5:4b` at 3.29GB plus `qwen2.5vl:7b` at 8.77GB is 12.06GB, and with the
    backend's measured 3.27GB ingest peak that is 15.33GB of 16GB. One multimodal
    model serving chat AND figures is 3.45GB, making 6.72GB against the same peak.

    Deliberately NOT tied to `max_resident_models("standard")`: that is a
    permission the resolver reads, not a target for a container that cannot
    measure its host."""
    assert _default_for("OLLAMA_MAX_LOADED_MODELS") == "1"


def test_the_serving_width_default_matches_the_same_profile():
    """The two knobs are sized by the same reasoning and must not drift apart."""
    assert _default_for("OLLAMA_NUM_PARALLEL") == "1"


def test_python_output_is_unbuffered_in_the_container():
    """Buffered stdout makes `docker logs` lag the work it describes, which is
    how a bug report arrives with the interesting lines missing."""
    assert "PYTHONUNBUFFERED=1" in COMPOSE
