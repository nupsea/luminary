"""docker-compose.yml must parse on the Compose people actually have.

0.7.7 shipped `required: false` under `depends_on`. It is valid Compose Spec and
`docker compose config` accepted it on the machine it was written on (v2.29.7),
but Compose only understands it from roughly v2.20, and older ones reject the
whole file:

    services.app.depends_on.ollama Additional property required is not allowed

Reproduced against v2.17.3: the released file fails, this one validates. The
lesson is not about `required` specifically -- it is that validating a compose
file against a single local binary is not validating it. This asserts the
`depends_on` long form stays inside the keys that have been understood since
Compose v2.0.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text())

# Understood by every Compose v2. `required` and `restart` came later.
LONG_FORM_KEYS = {"condition"}


def _long_form_depends_on():
    for name, service in (COMPOSE.get("services") or {}).items():
        dep = service.get("depends_on")
        if isinstance(dep, dict):
            for target, spec in dep.items():
                if isinstance(spec, dict):
                    yield name, target, spec


def test_depends_on_uses_only_long_understood_keys():
    for service, target, spec in _long_form_depends_on():
        extra = set(spec) - LONG_FORM_KEYS
        assert not extra, (
            f"{service}.depends_on.{target} uses {sorted(extra)}, which older "
            f"Compose rejects outright -- it fails the whole file, not just the key"
        )


def test_the_documented_profile_still_orders_the_model_pull():
    """The ordering fix must survive the compatibility fix: the app has to wait
    for ollama-pull, or a first run warms against an empty Ollama again."""
    app = COMPOSE["services"]["app"]["depends_on"]
    assert app["ollama-pull"]["condition"] == "service_completed_successfully"
    assert app["ollama"]["condition"] == "service_started"
