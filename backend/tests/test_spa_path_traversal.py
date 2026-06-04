import urllib.parse

import pytest

from app.main import resolve_spa_asset


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html></html>")
    (d / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("top secret")
    return d


def test_serves_real_asset(dist):
    assert resolve_spa_asset(dist, "assets/app.js") == (dist / "assets" / "app.js").resolve()


def test_empty_path_falls_back(dist):
    assert resolve_spa_asset(dist, "") is None


def test_missing_file_falls_back(dist):
    assert resolve_spa_asset(dist, "does-not-exist.js") is None


@pytest.mark.parametrize(
    "attack",
    [
        "../secret.txt",
        "../../secret.txt",
        "assets/../../secret.txt",
        urllib.parse.unquote("..%2f..%2fsecret.txt"),
    ],
)
def test_traversal_escapes_are_rejected(dist, attack):
    assert resolve_spa_asset(dist, attack) is None
