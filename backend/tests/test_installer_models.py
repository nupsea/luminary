"""The installer must pull the model the backend will resolve to.

These are two independent decisions about the same thing, made in two languages,
and they were already disagreeing. The installer pulled `llama3.2` on every
profile and pulled no vision model at all, while the backend on a single-resident
host resolves every role to a multimodal generalist. The result on an 8GB laptop:
the model answering questions is not the model the backend asks for, and the
vision role points at something that was never downloaded.

Nothing can import a shell script, so this reads the constants out of both
installers and compares them to the registry. It is a text check, which is
weaker than a call -- but the alternative is no check, and the failure it catches
is silent on the machine that can least afford it.
"""

import re
from pathlib import Path

import pytest

from app import memory_profile
from app.model_registry import GENERALIST_PREFERENCE, REGISTRY, profile_for

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
_SH = _SCRIPTS / "install.sh"
_PS1 = _SCRIPTS / "install.ps1"
# The fourth sizing site, and the only one with no install step to ask in.
_SUPERVISOR = _REPO / "src-tauri" / "src" / "supervisor.rs"


def _assign(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"could not find {pattern!r} -- the installer was restructured"
    return match.group(1).strip().strip('"').strip("'")


@pytest.fixture(scope="module")
def sh() -> str:
    return _SH.read_text()


@pytest.fixture(scope="module")
def ps1() -> str:
    return _PS1.read_text()


def test_the_generalist_is_registered_and_multimodal():
    """The whole point of the single-resident default: one model, every role."""
    profile = profile_for(GENERALIST_PREFERENCE[0])
    assert profile is not None, "the generalist must be in the registry"
    assert profile.multimodal


def test_install_sh_pulls_the_registry_generalist(sh):
    assert _assign(sh, r'^PUBLIC_GENERALIST="([^"]+)"') == GENERALIST_PREFERENCE[0].removeprefix(
        "ollama/"
    )


def test_install_ps1_pulls_the_registry_generalist(ps1):
    assert _assign(ps1, r'^\$PublicGeneralist = "([^"]+)"') == GENERALIST_PREFERENCE[
        0
    ].removeprefix("ollama/")


def test_both_installers_agree_with_each_other(sh, ps1):
    """Two platforms, one decision. They drifted on the chat model before."""
    assert _assign(sh, r'^PUBLIC_GENERALIST="([^"]+)"') == _assign(
        ps1, r'^\$PublicGeneralist = "([^"]+)"'
    )
    assert _assign(sh, r'^DEFAULT_CHAT_MODEL="([^"]+)"') in ps1


def test_the_generalist_fits_the_class_the_public_profile_targets(sh):
    """`public` is chosen for anything under 24GB, so 8GB is the binding case."""
    model = f"ollama/{_assign(sh, r'^PUBLIC_GENERALIST=\"([^\"]+)\"')}"
    profile = REGISTRY[model]
    assert profile.min_ram_gb <= 8, (
        f"{model} asks for {profile.min_ram_gb}GB; the public profile installs on 8GB"
    )


def test_install_sh_pulls_the_performance_pair(sh):
    """`performance` is the only band with room for a text model that cannot read
    figures, so it is the only one that pulls two. Everywhere else one model does
    both -- which is what the backend resolves to, so pulling anything else
    downloads a model that never loads."""
    assert 'LARGE_TEXT_MODEL="qwen2.5:14b-instruct"' in sh
    assert 'CHAT_MODEL="$LARGE_TEXT_MODEL"' in sh
    assert 'VISION_MODEL="$PUBLIC_GENERALIST"' in sh, (
        "the reader on `performance` is the generalist: the large text model is "
        "not multimodal, so something else has to read figures"
    )
    assert "ollama pull qwen2.5vl:7b" not in sh, (
        "a banner telling the user to pull a second model is the advice that "
        "breaks a single-model host"
    )


def test_install_ps1_pulls_the_performance_pair(ps1):
    assert '$LargeTextModel = "qwen2.5:14b-instruct"' in ps1
    assert "$chatModel = $LargeTextModel" in ps1
    assert "$visionModel = $PublicGeneralist" in ps1


def test_the_large_text_model_is_the_registry_top_rank(sh):
    """The installer must pull what the backend will resolve to on that band."""
    from app.model_registry import TEXT_PREFERENCE

    declared = f"ollama/{_assign(sh, r'^LARGE_TEXT_MODEL=\"([^\"]+)\"')}"
    assert declared == TEXT_PREFERENCE[0]


def test_the_performance_pair_fits_the_band_it_targets(sh):
    """`performance` starts above 24GB, so 32GB is the binding case."""
    from app.model_registry import GENERALIST_PREFERENCE, fits_together

    text = REGISTRY[f"ollama/{_assign(sh, r'^LARGE_TEXT_MODEL=\"([^\"]+)\"')}"]
    reader = REGISTRY[GENERALIST_PREFERENCE[0]]
    assert fits_together((text, reader), 32), (
        f"{text.resident_gb + reader.resident_gb:.2f}GB does not fit a 32GB host "
        f"under the half-the-machine budget"
    )


def test_the_bands_agree_across_platforms(sh, ps1):
    """Two bands, two scripts, one boundary. `low` is retired: 16GB is the floor,
    and a smaller machine gets `standard` plus a warning rather than a narrowed
    profile. Two detectors disagreeing about the machine is worse than one that
    is occasionally wrong -- this catches exactly that, and did."""
    assert '[ "$_gb" -gt 24 ]; then echo "performance"' in sh
    assert 'echo "standard"' in sh
    assert '"$_gb" -lt 16 ]' in sh, "install.sh must warn under the floor"
    assert "$MemGB -gt 24" in ps1
    assert "$MemGB -lt 16" in ps1, "install.ps1 must warn under the floor"
    assert 'public' not in sh.split("_default_profile")[1][:400]


def test_the_desktop_shell_agrees_about_the_residency_band():
    """Four sites size the machine, not three -- and the fourth is Rust.

    `install.sh`, `install.ps1` and `bootstrap.sh` are shell and are read above.
    `supervisor.rs` is the sizing path for the drag-installed DMG, which has no
    install step, and it is invisible to every other test in this file. When the
    floor moved to 16GB the three shell sites followed and this one did not: it
    kept `gb >= 24 => 2, _ => 1`, so a 24GB Mac running the bundled app gave
    Ollama one slot while the backend resolved a text model plus a reader against
    it -- the pair chosen, then evicted on every switch between them.

    Read as text for the same reason the installers are: nothing here can call
    Rust. The band is what matters, so the band is what is asserted.
    """
    rust = _SUPERVISOR.read_text()
    start = rust.index("fn ollama_max_loaded_models")
    # To the function's own closing brace at column 0, not to the next `fn`:
    # the following item is `pub fn`, so a `\nfn ` split runs past this body and
    # into the test module, where a different knob's 24GB band would satisfy the
    # assertions below and this check would read the wrong span.
    body = rust[start : rust.index("\n}\n", start)]
    assert "total_memory_gb()" in body, "the residency band no longer reads host RAM"

    assert "gb >= 16 => 2" in body, (
        "the desktop shell must permit two resident models at the 16GB floor, "
        "matching memory_profile.MAX_RESIDENT -- it sized from 24GB while the "
        "backend resolved pairs at 16"
    )
    assert "gb >= 24" not in body, "the retired 24GB residency band is back"

    floor = memory_profile.PROFILE_MIN_RAM_GB["standard"]
    assert f"gb >= {floor} => 2" in body, (
        f"the shell's band and the profile floor ({floor}GB) have drifted apart"
    )
    assert memory_profile.MAX_RESIDENT["standard"] == 2, (
        "the shell permits two at the floor; the backend must agree or the "
        "extra slot sits idle behind a narrower semaphore (I-31)"
    )


def test_the_serving_width_band_agrees_across_every_install_path(sh, ps1):
    """One RAM boundary for `OLLAMA_NUM_PARALLEL`, in four languages.

    I-31, measured on an M3 Pro: a second slot costs a full `OLLAMA_NUM_CTX` KV
    cache and buys 55.5 -> 97.7 tok/s only once there are two callers, so the
    band is RAM (<24GB one slot) and the auto path never exceeds 2 -- 4 is opt-in
    through `.env`.

    **Sized from RAM, never from the profile name.** That is the whole point of
    this test. These values were keyed to the profile when `public` meant "under
    24GB" and took one slot, so the catch-all meant 24GB+ and took two. Retiring
    `public` left the 24GB+ line catching 16GB laptops, which silently began
    taking two slots -- the value never changed, the band under it did.
    `supervisor.rs` sized from RAM and was the only path that did not drift.
    """
    rust = _SUPERVISOR.read_text()
    start = rust.index("fn ollama_num_parallel")
    shell_of_rust = rust[start : rust.index("\n}\n", start)]
    bootstrap = _BOOTSTRAP.read_text()

    for name, text, pattern in (
        ("supervisor.rs", shell_of_rust, "gb >= 24 => 2"),
        ("install.sh", sh, '"$(_mem_gb)" -ge 24 ]'),
        ("install.ps1", ps1, "$MemGB -ge 24"),
        ("bootstrap.sh", bootstrap, '"$MEM_GB" -ge 24 ]'),
    ):
        assert pattern in text, (
            f"{name} must size OLLAMA_NUM_PARALLEL from RAM at the 24GB boundary "
            f"(I-31), not from the profile name -- {pattern!r} is missing"
        )

    # 4 is opt-in. `performance` is sized from RAM now, so a 4 keyed to it would
    # hand every 32GB machine a width the measured table never reached.
    for name, text in (("install.sh", sh), ("install.ps1", ps1), ("bootstrap.sh", bootstrap)):
        assert "NUM_PARALLEL=4" not in text.replace(" ", ""), (
            f"{name} sets a serving width of 4 automatically; I-31 caps the auto "
            f"path at 2 and makes 4 opt-in through .env"
        )
        assert "VISION_CONCURRENCY=4" not in text.replace(" ", ""), (
            f"{name} sets a vision concurrency of 4; I-31 sizes every semaphore "
            f"at the slot count, and the slot count never exceeds 2 automatically"
        )


def test_the_chat_model_is_chosen_after_the_profile_is_known(ps1):
    """PowerShell compares an undefined variable as 0, so a profile test evaluated
    before the profile exists takes the wrong branch silently. The band block has
    to be hoisted above the model pull that reads it."""
    defined = ps1.index('$LumProfile = "performance"')
    # Matched on the variable rather than the whole condition: the test read the
    # condition verbatim, so adding the RAM gate to it broke an ordering check
    # that had nothing to do with the gate.
    used = ps1.index('if ($LumProfile -eq "performance"')
    assert defined < used, "the profile block must be hoisted above the model pull"


# --- every path that names a model, not just the two installers --------------

_BOOTSTRAP = _SCRIPTS / "bootstrap.sh"
_START = _SCRIPTS / "start.sh"
_COMPOSE = _SCRIPTS.parent / "docker-compose.yml"

# A model name written outside the registry is a second way to configure the
# app, and the two disagree the moment either moves. `bootstrap.sh` pinned
# `LITELLM_DEFAULT_MODEL=ollama/llama3.2` into the user's .env -- a hard override
# that outlives every host-aware default the backend has -- and was never
# covered here because this file only read the two `install.*` scripts.
_LAUNCH_PATHS = (_BOOTSTRAP, _START, _COMPOSE)


def test_no_launch_path_pulls_a_literal_model_name():
    """Every pull goes through a variable the profile resolved.

    A literal tag on a `ollama pull` line is a second decision about which model
    the app runs, made where nothing can reconcile it with the registry: compose
    pulled `llama3.2` while the backend resolved a generalist, so the sidecar
    downloaded one model and the app asked for another.
    """
    known_bare = {model_id.split("/", 1)[-1].split(":", 1)[0] for model_id in REGISTRY}
    # Anything that looks like a model tag, plus the names we have shipped before.
    literal = re.compile(r"ollama pull\s+\"?([A-Za-z][A-Za-z0-9._:-]*)")

    offenders = []
    for path in _LAUNCH_PATHS:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for match in literal.finditer(line):
                tag = match.group(1)
                if tag.startswith("$") or "$" in tag:
                    continue  # resolved from the profile, which is the point
                if tag.split(":", 1)[0] in known_bare or tag == "llama3.2":
                    offenders.append(f"{path.name}:{number} pulls literal {tag!r}")

    assert not offenders, "\n".join(offenders)


def test_bootstrap_resolves_its_model_from_the_profile():
    """It must not fall back to a name: that name reaches the user's .env."""
    text = _BOOTSTRAP.read_text()
    assign = _assign(text, r'^CHAT_MODEL="\$\{LUMINARY_CHAT_MODEL:-(.*)\}"')
    assert assign == "", (
        f"bootstrap.sh defaults CHAT_MODEL to {assign!r}; it writes that into "
        "LITELLM_DEFAULT_MODEL, pinning a model on every machine it installs on"
    )
    assert _assign(text, r'^PUBLIC_GENERALIST="(.*)"') == GENERALIST_PREFERENCE[0].split("/", 1)[-1]


def test_bootstrap_uses_the_same_memory_bands_as_install_sh():
    """Two installers that band differently give the same laptop two setups."""
    boot = (_SCRIPTS / "bootstrap.sh").read_text()
    assert re.search(r"MEM_GB.*-gt 24", boot), "bootstrap.sh lost the performance band"
    assert re.search(r"MEM_GB.*-lt 16", boot), "bootstrap.sh lost the 16GB floor warning"
    for name, source in (("install.sh", _SH.read_text()), ("bootstrap.sh", boot)):
        assert "performance" in source and "standard" in source, f"{name} lost a profile"

def test_start_sh_does_not_assert_a_model_name():
    """A pre-flight warning that names the wrong model sends the user to pull it."""
    text = _START.read_text()
    assert not re.search(r'CHAT_MODEL="\$\{LUMINARY_CHAT_MODEL:-[a-z]', text), (
        "start.sh hardcodes a model name in its warning"
    )


def test_compose_pulls_the_configured_model_without_the_provider_prefix():
    """`ollama pull` rejects the `ollama/` prefix that LiteLLM requires."""
    text = _COMPOSE.read_text()
    assert "LITELLM_DEFAULT_MODEL" in text, "compose pulls a model nothing configures"
    assert "#ollama/" in text, (
        "compose passes the setting to `ollama pull` without stripping `ollama/`"
    )


# Compose interpolates every un-escaped `${...}` in the file itself, before any
# shell sees it, and accepts only `${NAME}` and `${NAME:-default}`. A shell
# parameter expansion left un-escaped is therefore not a shell expression at all
# -- it is a compose syntax error that fails the entire file. `${M#ollama/}`
# shipped exactly that way, and the assertion above stayed green because the
# substring it looks for is present in a file docker refuses to load.
_SHELL_EXPANSION_IN_COMPOSE = re.compile(r"(?<!\$)\$\{[A-Za-z_][A-Za-z0-9_]*[#%^,/]")


def test_compose_escapes_shell_expansions_it_does_not_want_interpolated():
    """A `$` meant for the container's shell must be written `$$`."""
    offenders = [
        line.strip()
        for line in _COMPOSE.read_text().splitlines()
        # Full-line comments only. Matching any line *containing* a `#` would
        # exempt every line this is meant to check, since `#` is the shell
        # expansion operator it looks for.
        if not line.lstrip().startswith("#") and _SHELL_EXPANSION_IN_COMPOSE.search(line)
    ]
    assert not offenders, (
        "compose will reject these with 'invalid interpolation format' -- "
        f"double the `$` to pass them to the shell: {offenders}"
    )


def test_compose_file_actually_loads():
    """The check the string assertions cannot make. Skipped without docker."""
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    proc = subprocess.run(
        ["docker", "compose", "--profile", "ai", "config"],
        cwd=_COMPOSE.parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"docker compose cannot load the file:\n{proc.stderr}"


def test_no_installer_writes_the_legacy_profile_alias():
    """Neither name may be written to .env any more: both are retired.

    They collide on a different axis -- `LUMINARY_MODE=public` curates surfaces
    and has nothing to do with memory -- so `public` survives only as a legacy
    alias. Writing it into a fresh install makes every new machine depend on a
    compatibility shim that exists for old ones.
    """
    from app.memory_profile import _LEGACY_ALIASES

    for path in (_SH, _PS1, _BOOTSTRAP):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "LUMINARY_MEMORY_PROFILE" not in line or line.strip().startswith("#"):
                continue
            for alias in _LEGACY_ALIASES:
                assert f'"{alias}"' not in line and f"={alias}" not in line, (
                    f"{path.name}:{number} writes the legacy profile name {alias!r}"
                )


def test_the_large_text_threshold_is_the_measured_feasibility_point():
    """Recomputed from the registry, not trusted as a written-down number.

    The installer banded `performance` at >24GB and pulled the 9.67GB text model
    there, but the backend keeps its resident set to half of RAM and the pair is
    12.88GB -- so 25GB downloads a model the app then refuses to load. 25 fails
    and 26 fits; those two cases are what fixes this constant.
    """
    from app.model_registry import fits_together, profile_for

    declared = int(_assign(_SH.read_text(), r"^LARGE_TEXT_MIN_RAM_GB=(\d+)"))
    pair = (profile_for("ollama/qwen2.5:14b-instruct"), profile_for("ollama/qwen3.5:4b"))
    assert all(p is not None for p in pair), "the performance pair left the registry"

    smallest = next(ram for ram in range(1, 257) if fits_together(pair, ram))
    assert declared == smallest, (
        f"install.sh pulls the large text model at {declared}GB but the pair "
        f"first fits at {smallest}GB"
    )
    assert not fits_together(pair, declared - 1), "the case below the line must fail"


def test_the_profile_comment_states_the_bands_the_code_uses():
    """The only place a reader sees all three bands together.

    It said `public (under 24GB), standard (24GB+)` for as long as the three-band
    split existed -- a reader checking the code against the comment would have
    concluded the code was wrong.
    """
    text = _SH.read_text()
    banner = next(
        (line for line in text.splitlines() if "standard=" in line and "performance=" in line),
        None,
    )
    assert banner, "the profile banner comment is gone"
    for band in ("16GB", "24GB"):
        assert band in banner, f"the banner does not mention {band}: {banner}"
    assert "under 24GB" not in banner, "the banner still states the pre-split bands"


def test_pinning_only_the_chat_model_still_leaves_a_figure_reader():
    """The vision default must not sit inside `if [ -z "$CHAT_MODEL" ]`.

    While it did, setting LUMINARY_CHAT_MODEL alone gave a multi-slot host no
    vision model, and figures failed quietly -- the mode the profile exists to
    prevent.
    """
    text = _SH.read_text()
    chat_block_start = text.index('if [ -z "$CHAT_MODEL" ]; then')
    chat_block_end = text.index("\nfi\n", chat_block_start)
    vision_default = text.index('VISION_MODEL="$PUBLIC_GENERALIST"')
    assert not (chat_block_start < vision_default < chat_block_end), (
        "the vision default is nested inside the chat-model block again"
    )


def test_an_unknown_profile_is_refused_rather_than_written_to_env():
    """The backend rejects it and re-sizes, so the two silently disagreed."""
    text = _SH.read_text()
    assert re.search(r"standard\|performance\)\s*;;", text), (
        "install.sh no longer validates LUMINARY_PROFILE against the known set"
    )


# --- the Windows installer must hold the same shape, not just the same strings --
#
# These four were all live in install.ps1 while this file passed 21/21 against
# it. `test_install_ps1_pulls_the_performance_pair` asserts that the assignment
# `$visionModel = $PublicGeneralist` is *present*; it cannot see that the
# assignment sat inside `if (-not $chatModel)` and so never ran when the chat
# model was pinned. Presence is not structure.


def test_ps1_vision_default_is_not_nested_in_the_chat_model_block():
    """Nested, pinning LUMINARY_CHAT_MODEL left a roomy host with no reader."""
    text = _PS1.read_text()
    block_start = text.index("if (-not $chatModel) {")
    # The block ends at the first line that closes it at column 0.
    block_end = text.index("\n}\n", block_start)
    assignment = text.index("$visionModel = $PublicGeneralist")
    assert not (block_start < assignment < block_end), (
        "install.ps1 nests the vision default inside the chat-model block again"
    )


def test_ps1_gates_the_large_text_model_on_actual_ram():
    """Keying on the profile alone pulled 9.67GB onto a machine that cannot load it.

    `LUMINARY_PROFILE=performance` on an 8GB box is a supported override, so the
    band cannot be the only condition.
    """
    text = _PS1.read_text()
    declared = int(_assign(text, r"^\$LargeTextMinRamGB = (\d+)"))
    sh_declared = int(_assign(_SH.read_text(), r"^LARGE_TEXT_MIN_RAM_GB=(\d+)"))
    assert declared == sh_declared, (
        f"install.ps1 gates at {declared}GB and install.sh at {sh_declared}GB"
    )
    assert "$MemGB -ge $LargeTextMinRamGB" in text, (
        "install.ps1 declares the threshold but does not test actual RAM against it"
    )


def test_ps1_refuses_an_unknown_profile():
    """`switch` has a `default` arm, so an unknown value was taken silently and
    written to backend/.env. PowerShell's `switch` is also case-insensitive, so
    `Performance` installed a performance profile on Windows and exited 1 on
    macOS -- the same input, two different products."""
    text = _PS1.read_text()
    assert "-cin @(" in text, "install.ps1 does not validate LUMINARY_PROFILE case-sensitively"
    assert '"standard", "performance"' in text


def test_ps1_guards_the_vision_pull_on_ollama_being_present():
    """The chat pull is guarded and the vision pull was not, so on the branch the
    script explicitly tolerates -- ollama off the PATH -- it invoked a missing
    command under `$ErrorActionPreference = "Stop"`."""
    text = _PS1.read_text()
    pull = text.index("ollama pull $visionModel")
    guard = text.rindex('Test-CommandExists "ollama"', 0, pull)
    condition = text.rindex("if (", 0, pull)
    assert guard > condition - 200, "the vision pull is not guarded by a Test-CommandExists check"


def _run_platform_guard(sh: str, os_name: str, arch: str):
    """Run install.sh's real OS/ARCH-detection-through-guard block verbatim,
    with `uname` shadowed rather than the block reimplemented, so this proves
    the actual file's logic and not a paraphrase of it."""
    import subprocess

    start = sh.index("_info()  { printf")
    end = sh.index("fi\n", sh.index("Native install isn't supported")) + len("fi\n")
    block = sh[start:end]
    harness = f'uname() {{ case "$1" in -s) echo {os_name};; -m) echo {arch};; esac; }}\n' + block
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=10)


def test_intel_mac_is_refused_with_docker_guidance(sh):
    """The only guard against a native install on Intel Macs (no macOS x86_64
    lancedb wheel) had no test until now -- covered by regex elsewhere in this
    file, never actually run."""
    proc = _run_platform_guard(sh, "Darwin", "x86_64")
    assert proc.returncode == 1, (
        f"expected exit 1 on Darwin/x86_64, got {proc.returncode}: {proc.stderr}"
    )
    assert "Intel Mac" in proc.stderr
    assert "docker compose --profile ai up" in proc.stderr


def test_apple_silicon_mac_is_not_caught_by_the_intel_guard(sh):
    """The guard above must be precise to x86_64 -- proves it does not also
    block the architecture the fallback message never mentions."""
    proc = _run_platform_guard(sh, "Darwin", "arm64")
    assert proc.returncode == 0, f"Darwin/arm64 should not be blocked, got: {proc.stderr}"


def test_install_sh_checks_for_curl_and_make(sh):
    """Every other dependency (uv, node, ollama) has a `_have` guard with a
    clear error; curl and make did not, so a bare Ubuntu/Debian container died
    on a raw "command not found" for curl, and a bare Fedora/Arch container got
    all the way through the real install before dying the same way on `make
    build`. Verified live in Docker across all four distros.
    """
    assert re.search(r"_have curl \|\|", sh), (
        "install.sh does not check for curl before the first curl-dependent step"
    )
    assert re.search(r"_have make \|\|", sh), (
        "install.sh does not check for make before calling `make build`"
    )
    # The curl guard must come before uv's install, the earliest curl use.
    assert sh.index("_have curl ||") < sh.index("curl -LsSf https://astral.sh/uv/install.sh")


def test_install_sh_records_the_models_it_pulled(sh):
    """`start.sh` reads `LITELLM_DEFAULT_MODEL` out of the .env this writes.

    It was never written, so the pre-flight's `sed` found nothing, `CHAT_MODEL`
    came back empty, and the guard that skips the check when it cannot tell
    skipped it on every machine installed this way -- the primary path.
    """
    assert re.search(r'_upsert_env LITELLM_DEFAULT_MODEL "ollama/\$CHAT_MODEL"', sh), (
        "install.sh does not record the chat model it pulled"
    )
    assert re.search(r"_upsert_env VISION_MODEL", sh), (
        "install.sh does not record the vision model it pulled"
    )


def test_install_ps1_records_the_models_it_pulled(ps1):
    """Mirrors `test_install_sh_records_the_models_it_pulled` for Windows.

    install.ps1 pulled $chatModel/$visionModel with `ollama pull` but never
    wrote them into backend\\.env, unlike install.sh and bootstrap.sh -- the
    backend fell back to its own hardcoded default and could disagree with
    what this script had just downloaded.
    """
    assert re.search(r'Set-EnvLine \$EnvLines "LITELLM_DEFAULT_MODEL" "ollama/\$chatModel"', ps1), (
        "install.ps1 does not record the chat model it pulled"
    )
    assert re.search(r'Set-EnvLine \$EnvLines "VISION_MODEL"', ps1), (
        "install.ps1 does not record the vision model it pulled"
    )


@pytest.mark.parametrize("script", ["sh", "ps1", "bootstrap"])
def test_every_installer_accepts_the_backends_name_for_the_small_profile(script):
    """`low` and `public` named the retired one-model profile. Both must still be
    ACCEPTED -- an installed .env carries one, and refusing it fails the upgrade --
    and both now resolve to `standard`."""
    text = {"sh": _SH, "ps1": _PS1, "bootstrap": _SCRIPTS / "bootstrap.sh"}[script].read_text()
    assert "low" in text and re.search(r'(-ceq "low"|low\|public\))', text), (
        f"{script} does not accept `low` as a name for the small profile"
    )


def test_bootstrap_gates_the_large_text_model_on_actual_ram():
    """`LUMINARY_PROFILE=performance` is a supported override, so the profile
    alone does not mean the machine can hold the 9.67GB model."""
    text = (_SCRIPTS / "bootstrap.sh").read_text()
    assert "LARGE_TEXT_MIN_RAM_GB" in text, "bootstrap.sh pulls the large model ungated"
    assert re.search(r'MEM_GB" -ge "\$LARGE_TEXT_MIN_RAM_GB', text), (
        "bootstrap.sh names the threshold but does not compare RAM against it"
    )
    assert _assign(text, r"^LARGE_TEXT_MIN_RAM_GB=(\d+)") == _assign(
        _SH.read_text(), r"^LARGE_TEXT_MIN_RAM_GB=(\d+)"
    ), "bootstrap.sh and install.sh disagree about the band"


def test_bootstrap_refuses_an_unknown_profile():
    text = (_SCRIPTS / "bootstrap.sh").read_text()
    assert re.search(r"_die \"LUMINARY_PROFILE=", text), (
        "bootstrap.sh writes an unvalidated profile into .env, where the backend rejects it"
    )


def test_bootstrap_does_not_write_a_key_the_template_already_sets():
    """The template sets these uncommented, so appending duplicated them and a
    user editing the first occurrence saw no effect."""
    text = (_SCRIPTS / "bootstrap.sh").read_text()
    assert re.search(r"grep -vE '\^\(LITELLM_DEFAULT_MODEL\|VISION_MODEL", text), (
        "bootstrap.sh appends model keys without stripping the template's copies"
    )
