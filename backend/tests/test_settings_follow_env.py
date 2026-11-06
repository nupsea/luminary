"""Settings cached while one test's DATA_DIR is set must not outlive that test (#211).

A task that read settings during `memory_db`'s teardown cached that test's `tmp_path`, and
later tests in the worker opened `luminary.db` there: outside the session directory that
`settle_inherited_work` cleans, and still held by the earlier test's connections.
"""

import asyncio
import os
from pathlib import Path

from app.config import get_settings


async def test_a_late_reader_runs_during_teardown(memory_db):
    get_settings()

    async def read_settings_late():
        while get_settings.cache_info().currsize:
            await asyncio.sleep(0)
        get_settings()

    asyncio.get_running_loop().create_task(read_settings_late())


def test_the_next_test_sees_its_own_data_dir():
    assert Path(get_settings().DATA_DIR).resolve() == Path(os.environ["DATA_DIR"]).resolve()
