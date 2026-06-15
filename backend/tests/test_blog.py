"""Tests for the labs blog-publishing feature: transform + publish-to-git."""

import subprocess
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import blog_service

SAMPLE = """# My Great Post

Some [[abcd-1234|linked note]] text that should lose the link.

![Diagram|large](__LUMINARY_IMG__/notes/scene.svg)
<!-- luminary:excalidraw=__LUMINARY_IMG__/notes/scene.excalidraw.json -->

```mermaid
graph TD; A-->B;
```

![pic](__LUMINARY_IMG__/doc1/pic.png)
"""


def test_slugify():
    assert blog_service.slugify("My Great Post! (v2)") == "my-great-post-v2"
    assert blog_service.slugify("   ") == "untitled"


def test_format_pub_date_strips_leading_zero():
    assert blog_service.format_pub_date(date(2026, 6, 5)) == "Jun 5 2026"
    assert blog_service.format_pub_date(date(2026, 6, 15)) == "Jun 15 2026"


def test_render_frontmatter_optional_fields_and_escaping():
    fm = blog_service.render_frontmatter(
        title='He said "hi"',
        description="d",
        pub_date="Jun 15 2026",
    )
    assert 'title: "He said \\"hi\\""' in fm
    assert "updatedDate" not in fm
    fm2 = blog_service.render_frontmatter(
        title="t", description="d", pub_date="Jun 15 2026",
        updated_date="Jun 16 2026", hero_image="/blog/x/h.png",
    )
    assert "updatedDate" in fm2 and "heroImage" in fm2


def test_transform_drops_links_strips_diagrams_registers_assets():
    draft = blog_service.transform_note_to_blog(SAMPLE, "myslug")

    assert "[[" not in draft.markdown
    assert "luminary:excalidraw" not in draft.markdown
    assert "__LUMINARY_IMG__" not in draft.markdown
    assert "```mermaid" not in draft.markdown

    assert "/blog/myslug/asset1.svg" in draft.markdown
    assert "/blog/myslug/asset2.png" in draft.markdown
    assert "/blog/myslug/diagram1.svg" in draft.markdown

    copy = [a for a in draft.assets if a.kind == "copy"]
    mermaid = [a for a in draft.assets if a.kind == "mermaid"]
    assert {(a.doc_id, a.filename) for a in copy} == {
        ("notes", "scene.svg"),
        ("doc1", "pic.png"),
    }
    assert len(mermaid) == 1
    assert mermaid[0].key == "mermaid-1"
    assert mermaid[0].dest_filename == "diagram1.svg"
    assert draft.warnings  # note-link + mermaid + image notices


async def test_push_and_ahead_count(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    repo = _init_repo(tmp_path)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    await blog_service.git_push(repo, branch)
    assert await blog_service.ahead_count(repo, branch) == 0

    f = repo / "src/content/blog/p.md"
    blog_service.write_text_file(f, "x")
    await blog_service.git_add_commit(repo, [f], "blog: p")
    assert await blog_service.ahead_count(repo, branch) == 1

    await blog_service.git_push(repo, branch)
    assert await blog_service.ahead_count(repo, branch) == 0


async def test_git_push_raises_on_failure(tmp_path):
    repo = _init_repo(tmp_path)  # no remote configured
    with pytest.raises(RuntimeError):
        await blog_service.git_push(repo, "master")


async def test_git_add_commit_no_push(tmp_path):
    repo = _init_repo(tmp_path)
    f = repo / "src/content/blog/post.md"
    blog_service.write_text_file(f, "hello")
    sha = await blog_service.git_add_commit(repo, [f], "blog: post")
    assert len(sha) == 40
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "blog: post" in log
    # never configured a remote -> nothing was pushed
    remotes = subprocess.run(
        ["git", "remote"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert remotes.strip() == ""


# -- router end-to-end -----------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def blog_repo(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.setenv("LUMINARY_BLOG_REPO_PATH", str(repo))
    get_settings.cache_clear()
    yield repo
    get_settings.cache_clear()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "site"
    (repo / "src/content/blog").mkdir(parents=True)
    (repo / "public/blog").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    (repo / "README.md").write_text("site")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_publish_flow_writes_commits_no_push(client, blog_repo):
    note_id = client.post(
        "/notes",
        json={"content": "# Post One\n\n```mermaid\ngraph TD; A-->B;\n```\n", "tags": []},
    ).json()["id"]

    cfg = client.get("/blog/config").json()
    assert cfg["is_git_repo"] is True

    draft = client.post("/blog/draft", json={"note_id": note_id}).json()
    assert draft["slug"] == "post-one"
    assert any(a["kind"] == "mermaid" for a in draft["assets"])
    assert "/blog/post-one/diagram1.svg" in draft["markdown"]

    resp = client.post(
        "/blog/publish",
        json={
            "note_id": note_id,
            "slug": draft["slug"],
            "title": draft["title"],
            "description": "A short description.",
            "pub_date": draft["pub_date"],
            "markdown": draft["markdown"],
            "mermaid_svgs": {"mermaid-1": "<svg xmlns='http://www.w3.org/2000/svg'></svg>"},
            "overwrite": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["committed"] is True
    assert data["pushed"] is False
    assert "push origin master" in data["push_hint"]

    assert (blog_repo / "src/content/blog/post-one.md").exists()
    assert (blog_repo / "public/blog/post-one/diagram1.svg").exists()

    # second publish without overwrite -> 409
    resp2 = client.post(
        "/blog/publish",
        json={
            "note_id": note_id,
            "slug": draft["slug"],
            "title": draft["title"],
            "description": "A short description.",
            "pub_date": draft["pub_date"],
            "markdown": draft["markdown"],
            "mermaid_svgs": {"mermaid-1": "<svg xmlns='http://www.w3.org/2000/svg'></svg>"},
            "overwrite": False,
        },
    )
    assert resp2.status_code == 409


def test_posts_list_get_update_delete_lifecycle(client, blog_repo):
    # Seed two posts directly in the content dir.
    blog_dir = blog_repo / "src/content/blog"
    (blog_dir / "alpha.md").write_text(
        '---\ntitle: "Alpha"\ndescription: "a"\npubDate: "Jun 1 2026"\n---\n\nbody A\n'
    )
    (blog_dir / "beta.md").write_text(
        '---\ntitle: "Beta"\ndescription: "b"\npubDate: "Feb 1 2026"\n---\n\nbody B\n'
    )
    # transient preview drafts must be hidden from the list
    (blog_dir / "lmpreview-x.md").write_text(
        '---\ntitle: "x"\ndescription: "x"\npubDate: "Jan 1 2026"\n---\n\nx\n'
    )
    # Published posts are committed (publish commits); mirror that so a delete
    # has a tracked file to stage as a removal.
    subprocess.run(["git", "add", "-A"], cwd=blog_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed posts"], cwd=blog_repo, check=True)

    posts = client.get("/blog/posts").json()
    slugs = [p["slug"] for p in posts]
    assert slugs == ["alpha", "beta"]  # date-sorted desc, preview excluded
    assert posts[0]["url"].endswith("/blog/alpha/")

    detail = client.get("/blog/posts/alpha").json()
    assert detail["title"] == "Alpha" and detail["body"].strip() == "body A"

    upd = client.put(
        "/blog/posts/alpha",
        json={
            "title": "Alpha v2",
            "description": "a2",
            "pub_date": "Jun 1 2026",
            "body": "new body",
        },
    )
    assert upd.status_code == 200 and upd.json()["pushed"] is False
    reread = client.get("/blog/posts/alpha").json()
    assert reread["title"] == "Alpha v2" and reread["body"].strip() == "new body"

    # delete commits the removal (no push); 404 afterwards
    dele = client.request("DELETE", "/blog/posts/beta")
    assert dele.status_code == 200 and dele.json()["committed"] is True
    assert not (blog_dir / "beta.md").exists()
    assert client.get("/blog/posts/beta").status_code == 404


def test_update_post_adopts_pasted_image_then_prunes_on_removal(client, blog_repo):
    blog_dir = blog_repo / "src/content/blog"
    (blog_dir / "gamma.md").write_text(
        '---\ntitle: "Gamma"\ndescription: "g"\npubDate: "Jun 1 2026"\n---\n\nbody\n'
    )
    subprocess.run(["git", "add", "-A"], cwd=blog_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed gamma"], cwd=blog_repo, check=True)

    # Mimic a pasted image landing in Luminary's local image store.
    images_root = Path(get_settings().DATA_DIR).expanduser() / "images" / "notes"
    images_root.mkdir(parents=True, exist_ok=True)
    (images_root / "shot.png").write_bytes(b"\x89PNG\r\n")

    add = client.put(
        "/blog/posts/gamma",
        json={
            "title": "Gamma",
            "description": "g",
            "pub_date": "Jun 1 2026",
            "body": "intro\n\n![pic](__LUMINARY_IMG__/notes/shot.png)\n",
        },
    )
    assert add.status_code == 200, add.text
    assert add.json()["removed_assets"] == []
    copied = blog_repo / "public/blog/gamma/shot.png"
    assert copied.is_file()

    reread = client.get("/blog/posts/gamma").json()
    assert "__LUMINARY_IMG__" not in reread["body"]
    assert "/blog/gamma/shot.png" in reread["body"]

    # Removing the image reference prunes the now-orphaned asset on save.
    rem = client.put(
        "/blog/posts/gamma",
        json={
            "title": "Gamma",
            "description": "g",
            "pub_date": "Jun 1 2026",
            "body": "intro only\n",
        },
    )
    assert rem.status_code == 200, rem.text
    assert rem.json()["removed_assets"] == ["public/blog/gamma/shot.png"]
    assert not copied.exists()


def test_thoughts_kind_routes_to_its_own_collection(client, blog_repo):
    note_id = client.post(
        "/notes", json={"content": "# A Thought\n\nshort musing\n", "tags": []}
    ).json()["id"]

    draft = client.post("/blog/draft?kind=thoughts", json={"note_id": note_id}).json()
    resp = client.post(
        "/blog/publish?kind=thoughts",
        json={
            "note_id": note_id,
            "slug": draft["slug"],
            "title": draft["title"],
            "description": "musings",
            "pub_date": draft["pub_date"],
            "markdown": draft["markdown"],
            "mermaid_svgs": {},
            "overwrite": False,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"].endswith("/thoughts/a-thought/")
    assert (blog_repo / "src/content/thoughts/a-thought.md").exists()
    assert not (blog_repo / "src/content/blog/a-thought.md").exists()

    # The thought shows under kind=thoughts but not under the default blog list.
    thoughts = client.get("/blog/posts?kind=thoughts").json()
    assert [p["slug"] for p in thoughts] == ["a-thought"]
    assert client.get("/blog/posts").json() == []

    # An invalid kind is rejected.
    assert client.get("/blog/posts?kind=bogus").status_code == 422


def test_adopt_and_prune_helpers(tmp_path):
    images_root = tmp_path / "images"
    (images_root / "notes").mkdir(parents=True)
    (images_root / "notes" / "deadbeefdeadbeefdeadbeef_photo.png").write_bytes(b"x")
    asset_dir = tmp_path / "public/blog/post"

    body, written = blog_service.adopt_inline_assets(
        "![a](__LUMINARY_IMG__/notes/deadbeefdeadbeefdeadbeef_photo.png)",
        "post",
        images_root,
        asset_dir,
    )
    # uuid prefix stripped, reference rewritten, file materialised once
    assert "/blog/post/photo.png" in body
    assert "__LUMINARY_IMG__" not in body
    assert [p.name for p in written] == ["photo.png"]
    assert (asset_dir / "photo.png").is_file()

    # an extra unreferenced file is pruned; the referenced one is kept
    (asset_dir / "stale.png").write_bytes(b"x")
    keep = blog_service.referenced_assets(body, "post")
    removed = blog_service.prune_orphan_assets(asset_dir, keep)
    assert [p.name for p in removed] == ["stale.png"]
    assert (asset_dir / "photo.png").is_file()
