"""The installers must opt out on the same values the backend does.

`anonymous_telemetry.is_telemetry_opted_out` accepts 1/true/yes. The install
scripts accepted only the literal "1", so `DO_NOT_TRACK=true` opted a user out
of the application while the installer still reported. Opt-out that depends on
which spelling you used is not opt-out.
"""

import subprocess
from pathlib import Path

import pytest

from app.services.anonymous_telemetry import is_telemetry_opted_out

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SHELL_INSTALLERS = [SCRIPTS / "install.sh", SCRIPTS / "bootstrap.sh"]

OPTED_OUT = [
    {"DO_NOT_TRACK": "1"},
    {"DO_NOT_TRACK": "true"},
    {"DO_NOT_TRACK": "TRUE"},
    {"DO_NOT_TRACK": "yes"},
    {"LUMINARY_TELEMETRY_DISABLED": "1"},
    {"LUMINARY_TELEMETRY_DISABLED": "true"},
    {"LUMINARY_TELEMETRY": "0"},
    {"LUMINARY_TELEMETRY": "false"},
    {"LUMINARY_TELEMETRY": "no"},
]

STILL_ON = [
    {},
    {"DO_NOT_TRACK": "0"},
    {"DO_NOT_TRACK": ""},
    {"LUMINARY_TELEMETRY": "1"},
]


def _script_says_opted_out(script: Path, env: dict[str, str]) -> bool:
    """Run the script's own `_opted_out` and report its verdict.

    The helper is sourced out of the real file rather than copied, so this
    cannot drift from what the installer actually does.
    """
    text = script.read_text()
    start = text.index("_lower()")
    end = text.index("_send_telemetry()")
    helper = text[start:end]
    proc = subprocess.run(
        ["bash", "-c", f"{helper}\nif _opted_out; then echo OUT; else echo ON; fi"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip() == "OUT"


@pytest.mark.parametrize("script", SHELL_INSTALLERS, ids=lambda p: p.name)
@pytest.mark.parametrize("env", OPTED_OUT, ids=lambda e: "-".join(f"{k}={v}" for k, v in e.items()))
def test_installer_opts_out(script: Path, env: dict[str, str]) -> None:
    assert _script_says_opted_out(script, env) is True


def _env_id(env: dict[str, str]) -> str:
    return "-".join(f"{k}={v}" for k, v in env.items()) or "unset"


@pytest.mark.parametrize("script", SHELL_INSTALLERS, ids=lambda p: p.name)
@pytest.mark.parametrize("env", STILL_ON, ids=_env_id)
def test_installer_stays_on_without_an_opt_out(script: Path, env: dict[str, str]) -> None:
    assert _script_says_opted_out(script, env) is False


@pytest.mark.parametrize("env", OPTED_OUT, ids=lambda e: "-".join(f"{k}={v}" for k, v in e.items()))
def test_backend_agrees_with_the_installers(env: dict[str, str], monkeypatch) -> None:
    """The parity itself, asserted against the backend's own function."""
    for var in ("DO_NOT_TRACK", "LUMINARY_TELEMETRY_DISABLED", "LUMINARY_TELEMETRY"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    assert is_telemetry_opted_out() is True


def test_installers_post_to_a_route_that_exists() -> None:
    """The local forward must name a path the app actually serves.

    `_API_PREFIX` is "/api" only under LUMINARY_MODE=public (Docker); a normal
    install runs `full`, where the route is unprefixed. The scripts posted only
    to the /api path, which 404s on every non-Docker install -- silently, since
    the call discards its output.
    """
    from app.main import app

    served = {r.path for r in app.routes}
    assert "/monitoring/telemetry/event" in served

    for script in [*SHELL_INSTALLERS, SCRIPTS / "install.ps1"]:
        text = script.read_text()
        assert "/monitoring/telemetry/event" in text, f"{script.name} names no unprefixed path"
