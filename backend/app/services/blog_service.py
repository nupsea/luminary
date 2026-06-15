"""Transform a Luminary note into a publishable Astro blog post.

Pure transform plus filesystem/git helpers for the labs "publish note as blog"
feature. The target is the user's personal Astro content collection at
``<repo>/src/content/blog/<slug>.md`` with co-located assets under
``<repo>/public/blog/<slug>/`` (served at ``/blog/<slug>/...``).

The transform strips constructs that have no meaning on the public site:
wiki note-links are dropped, Excalidraw scene comments are removed, locally
mirrored images / Excalidraw SVGs are registered for copying out of the data
dir, and ``mermaid`` fenced blocks are registered for client-side SVG render.
All registered assets are rewritten to ``/blog/<slug>/<file>`` references.
"""

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

# [[<uuid>|display text]] wiki-link between Luminary notes -- no public target.
_NOTE_LINK_RE = re.compile(r"\[\[[0-9a-fA-F-]+\|[^\]]+\]\]")
# Excalidraw scene pointer emitted alongside the rendered SVG in note markdown.
_EXCALIDRAW_COMMENT_RE = re.compile(r"[ \t]*<!--\s*luminary:excalidraw=[^>]*-->")
# Locally mirrored asset reference: __LUMINARY_IMG__/<doc_id>/<filename>.
_LUMINARY_IMG_RE = re.compile(r"__LUMINARY_IMG__/([^/\s)\"']+)/([^\s)\"']+)")
# ```mermaid ... ``` fenced block (whole block captured for replacement).
_MERMAID_BLOCK_RE = re.compile(r"(?ms)^[ \t]*```mermaid[ \t]*\n(.*?)^[ \t]*```[ \t]*$")


@dataclass
class BlogAsset:
    """One asset the post depends on, destined for public/blog/<slug>/<dest>."""

    kind: str  # "copy" (from disk) | "mermaid" (rendered SVG supplied by client)
    dest_filename: str
    # copy assets: located at <images_root>/<doc_id>/<filename>
    doc_id: str | None = None
    filename: str | None = None
    # mermaid assets: client sends the rendered SVG under this key
    key: str | None = None


@dataclass
class BlogDraft:
    markdown: str
    assets: list[BlogAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower().strip()).strip("-")
    return slug or "untitled"


def format_pub_date(when: date | datetime) -> str:
    # Matches the site's existing posts, e.g. "Jun 15 2026". %-d is non-portable,
    # so strip a leading zero from the day manually.
    return when.strftime("%b %d %Y").replace(" 0", " ", 1)


def existing_slugs(content_dir: Path) -> set[str]:
    if not content_dir.is_dir():
        return set()
    return {p.stem for p in content_dir.glob("*.md")}


def _is_published_slug(slug: str) -> bool:
    # Hide Astro-ignored ("_") files and our transient live-preview drafts.
    return not slug.startswith("_") and not slug.startswith("lmpreview-")


def _meta_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return format_pub_date(value)
    return str(value)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split `---`-delimited YAML frontmatter from the markdown body."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            if isinstance(meta, dict):
                return meta, parts[2].lstrip("\n")
    return {}, text


def _summarize_post(path: Path) -> dict:
    meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    return {
        "slug": path.stem,
        "title": str(meta.get("title") or path.stem),
        "description": str(meta.get("description") or ""),
        "pub_date": _meta_str(meta.get("pubDate")) or "",
        "updated_date": _meta_str(meta.get("updatedDate")),
    }


def list_posts(content_dir: Path) -> list[dict]:
    if not content_dir.is_dir():
        return []
    posts = [
        _summarize_post(p)
        for p in content_dir.glob("*.md")
        if _is_published_slug(p.stem)
    ]

    def _date_key(p: dict) -> datetime:
        try:
            return datetime.strptime(p["pub_date"], "%b %d %Y")
        except (ValueError, TypeError):
            return datetime.min

    posts.sort(key=_date_key, reverse=True)
    return posts


def read_post(content_dir: Path, slug: str) -> dict:
    meta, body = parse_frontmatter((content_dir / f"{slug}.md").read_text(encoding="utf-8"))
    return {
        "slug": slug,
        "title": str(meta.get("title") or slug),
        "description": str(meta.get("description") or ""),
        "pub_date": _meta_str(meta.get("pubDate")) or "",
        "updated_date": _meta_str(meta.get("updatedDate")),
        "hero_image": _meta_str(meta.get("heroImage")),
        "body": body,
    }


def _yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_frontmatter(
    *,
    title: str,
    description: str,
    pub_date: str,
    updated_date: str | None = None,
    hero_image: str | None = None,
) -> str:
    lines = [
        "---",
        f"title: {_yaml_str(title)}",
        f"description: {_yaml_str(description)}",
        f"pubDate: {_yaml_str(pub_date)}",
    ]
    if updated_date:
        lines.append(f"updatedDate: {_yaml_str(updated_date)}")
    if hero_image:
        lines.append(f"heroImage: {_yaml_str(hero_image)}")
    lines.append("---")
    return "\n".join(lines)


def transform_note_to_blog(content: str, slug: str) -> BlogDraft:
    """Clean note markdown for the public site and register external assets."""
    warnings: list[str] = []
    assets: list[BlogAsset] = []

    note_links = len(_NOTE_LINK_RE.findall(content))
    text = _NOTE_LINK_RE.sub("", content)
    if note_links:
        warnings.append(
            f"{note_links} note-link(s) removed (no target on the public site)"
        )

    excalidraw_comments = len(_EXCALIDRAW_COMMENT_RE.findall(text))
    text = _EXCALIDRAW_COMMENT_RE.sub("", text)

    diagram_n = 0

    def _mermaid_sub(match: re.Match[str]) -> str:
        nonlocal diagram_n
        diagram_n += 1
        dest = f"diagram{diagram_n}.svg"
        assets.append(
            BlogAsset(kind="mermaid", dest_filename=dest, key=f"mermaid-{diagram_n}")
        )
        return f"![diagram](/blog/{slug}/{dest})"

    text = _MERMAID_BLOCK_RE.sub(_mermaid_sub, text)
    if diagram_n:
        warnings.append(
            f"{diagram_n} mermaid diagram(s) will be rendered to SVG and copied alongside the post"
        )

    asset_n = 0

    def _img_sub(match: re.Match[str]) -> str:
        nonlocal asset_n
        asset_n += 1
        doc_id, filename = match.group(1), match.group(2)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
        dest = f"asset{asset_n}.{ext}"
        assets.append(
            BlogAsset(kind="copy", dest_filename=dest, doc_id=doc_id, filename=filename)
        )
        return f"/blog/{slug}/{dest}"

    text = _LUMINARY_IMG_RE.sub(_img_sub, text)
    if asset_n:
        kind = "image/diagram" if excalidraw_comments else "image"
        warnings.append(f"{asset_n} embedded {kind}(s) will be copied alongside the post")

    return BlogDraft(markdown=text.strip() + "\n", assets=assets, warnings=warnings)


# -- filesystem / git ------------------------------------------------------


def copy_disk_asset(images_root: Path, doc_id: str, filename: str, dest: Path) -> None:
    src = images_root / doc_id / filename
    if not src.is_file():
        raise FileNotFoundError(f"asset not found on disk: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode().strip(), err.decode().strip()


async def repo_health(repo: Path, content_dir: Path) -> dict:
    if not (repo / ".git").exists():
        return {
            "is_git_repo": False,
            "branch": None,
            "dirty": False,
            "content_dir_exists": content_dir.is_dir(),
        }
    _, branch, _ = await _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    _, status, _ = await _git(["status", "--porcelain"], repo)
    return {
        "is_git_repo": True,
        "branch": branch or None,
        "dirty": bool(status.strip()),
        "content_dir_exists": content_dir.is_dir(),
    }


async def ahead_count(repo: Path, branch: str) -> int | None:
    """Commits on local HEAD not yet on origin/<branch>. None if undeterminable
    (e.g. no remote-tracking ref yet)."""
    code, out, _ = await _git(["rev-list", "--count", f"origin/{branch}..HEAD"], repo)
    if code != 0:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


async def git_push(repo: Path, branch: str) -> str:
    """Push local <branch> to origin. Raises RuntimeError with git's stderr on
    failure (auth, non-fast-forward, etc.). Uses the repo's configured remote +
    the user's existing git/SSH credentials -- no secrets handled here."""
    code, out, err = await _git(["push", "origin", branch], repo)
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or "git push failed")
    return (f"{out}\n{err}").strip() or "pushed"


async def git_add_commit(repo: Path, files: list[Path], message: str) -> str:
    """Stage exactly ``files`` (never `git add .`) and commit. Returns the sha.

    Does not push -- the user pushes manually.
    """
    rel = [str(f.relative_to(repo)) for f in files]
    # -A so the same path stages new files, edits, AND deletions (used by delete).
    code, _, err = await _git(["add", "-A", "--", *rel], repo)
    if code != 0:
        raise RuntimeError(f"git add failed: {err}")
    code, _, err = await _git(["commit", "-m", message], repo)
    if code != 0:
        raise RuntimeError(f"git commit failed: {err}")
    _, sha, _ = await _git(["rev-parse", "HEAD"], repo)
    return sha
