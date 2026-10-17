"""Every path under DATA_DIR is resolved through app/storage.py.

A second library gets its own root by changing `library_root` alone; a direct
`DATA_DIR` join anywhere else would keep writing into the first library's folder.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
# config.py defines it, storage.py resolves it; main.py reports the configured value.
ALLOWED = {"config.py", "storage.py", 'main.py:"DATA_DIR": settings.DATA_DIR'}
READ = re.compile(r"\.DATA_DIR\b")


def test_no_module_joins_data_dir_itself():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if READ.search(line) and f"{rel}:{line.strip().rstrip(',')}" not in ALLOWED:
                offenders.append(f"app/{rel}:{n}: {line.strip()}")
    assert not offenders, "resolve through app.storage instead:\n" + "\n".join(offenders)


def test_the_check_sees_a_direct_join():
    line = 'root = Path(get_settings().DATA_DIR).expanduser() / "raw"'
    assert READ.search(line)


def test_both_roots_are_data_dir_today(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.storage import library_root, machine_root

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert library_root() == machine_root() == tmp_path
    finally:
        get_settings.cache_clear()
