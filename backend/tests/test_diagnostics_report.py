"""The environment block that ships with a bug report (nupsea/luminary#41).

Issues arrived with a version and an OS name, which was never enough to
reproduce anything, so answering one always cost a round trip.
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import diagnostics


@pytest.fixture
def no_ollama(monkeypatch):
    async def _unreachable():
        return ["ollama    not reachable"]

    monkeypatch.setattr(diagnostics, "_ollama", _unreachable)


async def test_the_block_carries_what_reproducing_needs(no_ollama):
    text = await diagnostics.environment_report()
    for field in ("version", "os", "kernel", "python", "chat", "vision", "ollama"):
        assert f"{field} " in text, f"missing {field!r} in:\n{text}"


async def test_the_account_name_never_reaches_the_tracker(no_ollama):
    """This block is pasted into a public issue."""
    text = await diagnostics.environment_report()
    home = str(Path.home())
    user = Path.home().name

    assert home not in text
    if len(user) >= 3:
        assert user not in text, f"leaked the account name:\n{text}"


def test_home_paths_are_replaced_rather_than_dropped():
    """The shape of the path is still useful; the name in it is not."""
    home = str(Path.home())
    scrubbed = diagnostics._scrub(f"library   {home}/.luminary")
    assert scrubbed == "library   ~/.luminary"


async def test_installed_models_are_listed(monkeypatch):
    async def _with_models():
        return [
            "ollama    running — 0.32.5",
            "          llama3.2:latest",
            "          qwen2.5vl:7b",
        ]

    monkeypatch.setattr(diagnostics, "_ollama", _with_models)
    text = await diagnostics.environment_report()
    assert "llama3.2:latest" in text
    assert "qwen2.5vl:7b" in text


async def test_an_unreachable_ollama_is_stated_not_omitted(no_ollama):
    """Silence would read as "no models", which is a different bug."""
    assert "not reachable" in await diagnostics.environment_report()


async def test_endpoint_returns_the_block(no_ollama):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/setup/report")

    assert resp.status_code == 200
    assert "version " in resp.json()["environment"]


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAA",
        "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAA",
        "ghp_AAAAAAAAAAAAAAAAAAAAAAAA",
        "hf_AAAAAAAAAAAAAAAAAAAAAAAA",
        "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_key_shapes_never_reach_a_report(secret):
    assert secret not in diagnostics.redact(f"litellm error: key {secret} was rejected")


@pytest.mark.parametrize(
    "line",
    [
        "OPENAI_API_KEY=hunter2trustno1",
        '"password": "hunter2trustno1"',
        "Authorization: Bearer hunter2trustno1",
    ],
)
def test_credential_values_are_redacted(line):
    assert "hunter2trustno1" not in diagnostics.redact(line)


def test_email_addresses_are_redacted():
    assert "someone@example.org" not in diagnostics.redact("reply to someone@example.org")


def test_signed_download_links_lose_their_query_string():
    line = (
        "GET https://cdn.example.com/blob/sha256-abc?X-Amz-Signature=deadbeef&X-Amz-Credential=me"
    )
    out = diagnostics.redact(line)
    assert "deadbeef" not in out
    assert "https://<host>/blob/sha256-abc?<redacted>" in out


def test_the_computer_name_is_scrubbed_but_words_containing_it_are_not(monkeypatch):
    monkeypatch.setattr(diagnostics.platform, "node", lambda: "app.local")
    out = diagnostics.redact("host app started the Application")
    assert out == "host <user> started the Application"


def test_the_log_tail_is_the_end_of_the_file_the_shell_names(tmp_path, monkeypatch):
    log = tmp_path / "luminary.log"
    log.write_text("\n".join(f"line {n}" for n in range(1000)))
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(log))
    tail = diagnostics.log_tail(3)
    assert tail == "line 997\nline 998\nline 999"


def test_no_log_file_is_an_empty_tail(monkeypatch):
    monkeypatch.delenv("LUMINARY_LOG_FILE", raising=False)
    assert diagnostics.log_tail() == ""


async def test_the_endpoint_redacts_the_problem_and_the_log(no_ollama, tmp_path, monkeypatch):
    log = tmp_path / "luminary.log"
    key = "sk-" + "A" * 24
    log.write_text(f"[ollama] pull failed for {Path.home()}/x with key {key}\n")
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(log))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(
            "/setup/report",
            params={"problem": "Chat model download failed", "detail": "token=abc123456"},
        )

    body = resp.json()
    assert body["problem"] == "Chat model download failed"
    assert "abc123456" not in body["detail"]
    assert "sk-AAAA" not in body["log"]
    assert str(Path.home()) not in body["log"]
    assert body["log"].startswith("[ollama] pull failed")
    assert "@" in body["email"]


@pytest.fixture
def company_laptop(monkeypatch):
    monkeypatch.setattr(diagnostics.platform, "node", lambda: "LT-4471.emea.acme-industries.com")
    monkeypatch.setenv("USERDOMAIN", "ACMEIND")
    monkeypatch.setenv("USERDNSDOMAIN", "EMEA.ACME-INDUSTRIES.COM")
    monkeypatch.setenv("USERNAME", "jdoe")


@pytest.mark.parametrize(
    "line",
    [
        r"open C:\Users\jdoe\OneDrive - Acme Industries\Berlin Office\plan.pdf failed",
        r'{"message": "copy C:\\Users\\jdoe\\OneDrive - Acme Industries\\Q3\\plan.pdf"}',
        r"cannot reach \\fs01.acme-industries.com\berlin\share",
        "proxy http://jdoe:pw@proxy.berlin.acme-industries.com:8080 refused",
        "connect to 10.42.7.19 timed out",
        "dial tcp: lookup proxy.berlin.acme-industries.com: i/o timeout",
        "LT-4471 joined ACMEIND as jdoe",
    ],
)
def test_a_work_computer_names_no_person_company_or_place(company_laptop, line):
    out = diagnostics.redact(line).lower()
    for leak in ("jdoe", "acme", "berlin", "lt-4471", "10.42.7.19", "pw@", "q3"):
        assert leak not in out, f"{leak!r} leaked: {out}"


def test_luminary_paths_keep_the_part_that_explains_a_failure(company_laptop):
    home = str(Path.home())
    out = diagnostics.redact(f"blob at {home}/.ollama/models/blobs/sha256-ab-partial: no space")
    assert out == "blob at ~/.ollama/models/…: no space"
    out = diagnostics.redact(r"C:\Users\jdoe\AppData\Local\sh.luminary.app\models\x.bin")
    assert out == "…\\sh.luminary.app\\models\\…"


def test_the_model_servers_and_the_local_engine_are_kept():
    line = "GET https://registry.ollama.ai/v2/library/qwen3.5 from 127.0.0.1"
    assert diagnostics.redact(line) == line


def test_the_timezone_offset_is_dropped():
    line = "time=2026-09-24T15:57:37.559+10:00 level=INFO"
    assert diagnostics.redact(line) == "time=2026-09-24T15:57:37.559 level=INFO"


async def test_document_and_collection_names_are_removed(no_ollama, tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.database as db_module
    from app.database import make_engine
    from app.db_init import create_all_tables
    from app.models import CollectionModel, DocumentModel

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    async with factory() as session:
        session.add(
            DocumentModel(
                id="d1",
                title="Merger Terms Draft",
                format="pdf",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path="/x/project-falcon-v2.pdf",
                stage="complete",
                tags=[],
            )
        )
        session.add(CollectionModel(id="c1", name="Board Papers"))
        await session.commit()

    log = tmp_path / "luminary.log"
    log.write_text(
        "[backend] ingested 'Merger Terms Draft' from project-falcon-v2.pdf into Board Papers\n"
    )
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(log))
    report = await diagnostics.problem_report("x")
    await engine.dispose()

    assert report["log"] == "[backend] ingested '<document>' from <document> into <document>"


async def test_an_unreadable_library_drops_the_lines_that_could_name_a_document(
    no_ollama, tmp_path, monkeypatch
):
    async def _unreadable():
        return None

    monkeypatch.setattr(diagnostics, "_library_names", _unreadable)
    log = tmp_path / "luminary.log"
    log.write_text("[backend] ingested 'Merger Terms Draft'\n[ollama] pull stalled\n")
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(log))
    report = await diagnostics.problem_report("x")
    assert report["log"] == "[ollama] pull stalled"


@pytest.fixture
def opened(monkeypatch):
    calls: list[Path] = []

    def _fake_open(path):
        calls.append(path)
        return True

    monkeypatch.setattr(diagnostics, "_open_in_editor", _fake_open)
    return calls


async def test_the_report_opens_as_a_text_file_saying_how_to_send_it(
    no_ollama, opened, tmp_path, monkeypatch
):
    log = tmp_path / "luminary.log"
    log.write_text(f"[ollama] pull stalled in {Path.home()}/Documents/x\n")
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(log))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/setup/report/open", json={"problem": "Chat model download failed", "detail": "0 MB"}
        )

    body = resp.json()
    assert resp.status_code == 200
    assert body["opened"] is True
    saved = Path(body["path"])
    assert opened == [saved]
    assert saved.parent == tmp_path
    text = saved.read_text(encoding="utf-8")
    assert text == body["text"]
    assert text.startswith("Luminary problem report")
    assert diagnostics.REPORT_EMAIL in text
    assert diagnostics.REPORT_ISSUES in text
    assert "What happened: Chat model download failed" in text
    assert "[ollama] pull stalled in <path>" in text
    assert str(Path.home()) not in text


async def test_no_editor_still_saves_the_file_and_returns_the_text(
    no_ollama, tmp_path, monkeypatch
):
    monkeypatch.setattr(diagnostics, "_open_in_editor", lambda path: False)
    monkeypatch.setenv("LUMINARY_LOG_FILE", str(tmp_path / "luminary.log"))
    report = await diagnostics.open_problem_report("x")
    assert report["opened"] is False
    assert Path(report["path"]).read_text(encoding="utf-8") == report["text"]


async def test_a_hosted_server_never_opens_or_writes_a_report(no_ollama, opened, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("LUMINARY_MODE", "public")
    get_settings.cache_clear()
    try:
        report = await diagnostics.open_problem_report("x")
    finally:
        monkeypatch.delenv("LUMINARY_MODE")
        get_settings.cache_clear()
    assert report == {"text": report["text"], "path": None, "opened": False}
    assert opened == []


def test_a_missing_editor_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert diagnostics._open_in_editor(tmp_path / "r.txt") is False
