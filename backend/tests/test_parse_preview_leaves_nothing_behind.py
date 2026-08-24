"""`POST /documents/parse` previews a parse; it must not accumulate files.

It wrote the upload to DATA_DIR/raw/<uuid>.<ext> and returned. No document row
was ever created for that id, so nothing referenced the file and nothing would
ever delete it: every call left an orphan, out of sight of the library that is
supposed to own the user's content. It also skipped the extension allowlist its
two sibling upload routes apply.
"""

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _raw_dir(tmp_data: Path) -> Path:
    return tmp_data / "raw"


@pytest.mark.asyncio
async def test_a_preview_does_not_leave_the_file_behind(tmp_path, monkeypatch):
    from app import config as config_module

    settings = config_module.Settings().model_copy(update={"DATA_DIR": str(tmp_path)})
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    app.dependency_overrides[config_module.get_settings] = lambda: settings
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/documents/parse",
                files={"file": ("note.txt", io.BytesIO(b"Alice met a rabbit."), "text/plain")},
            )
        assert resp.status_code == 200, resp.text
        leftovers = list(_raw_dir(tmp_path).glob("*")) if _raw_dir(tmp_path).exists() else []
        assert leftovers == [], f"preview left {leftovers} with no document row behind them"
    finally:
        app.dependency_overrides.pop(config_module.get_settings, None)


@pytest.mark.asyncio
async def test_a_preview_applies_the_same_extension_allowlist(tmp_path, monkeypatch):
    from app import config as config_module

    settings = config_module.Settings().model_copy(update={"DATA_DIR": str(tmp_path)})
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    app.dependency_overrides[config_module.get_settings] = lambda: settings
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/documents/parse",
                files={"file": ("payload.sh", io.BytesIO(b"#!/bin/sh\n"), "text/plain")},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(config_module.get_settings, None)
