"""Labs feature: publish a Luminary note as a post on the author's Astro blog.

Flow: GET /blog/config (repo health) -> POST /blog/draft (transform + preview)
-> optional POST /blog/suggest-description and /blog/preview/live -> POST
/blog/publish (write file + assets, local commit, no push -- the user pushes).
"""

import asyncio
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.repos.note_repo import NoteRepo, get_note_repo
from app.schemas.blog import (
    BlogAssetItem,
    BlogConfigResponse,
    BlogDraftRequest,
    BlogDraftResponse,
    BlogLivePreviewCleanupRequest,
    BlogLivePreviewRequest,
    BlogLivePreviewResponse,
    BlogPostDetail,
    BlogPostSummary,
    BlogPostUpdateRequest,
    BlogPublishRequest,
    BlogPublishResponse,
    BlogPushResponse,
    SuggestDescriptionRequest,
    SuggestDescriptionResponse,
)
from app.services import blog_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/blog", tags=["blog"])

_LIVE_PREVIEW_PORT = 4321
_LIVE_PREVIEW_HOST = "127.0.0.1"
_DESC_SYSTEM = (
    "You write a single concise meta description (one sentence, 15-25 words) "
    "for a blog post, given its content. Output ONLY the sentence -- no quotes, "
    "no markdown, no preamble."
)


_VALID_KINDS = ("blog", "thoughts")


def _check_kind(kind: str) -> str:
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"invalid kind: {kind}")
    return kind


def _repo() -> Path:
    return Path(get_settings().LUMINARY_BLOG_REPO_PATH).expanduser()


def _content_dir(kind: str) -> Path:
    # Both collections live under the content root (src/content/<kind>); derive
    # it from the configured blog subdir so the two stay in lockstep.
    return _repo() / Path(get_settings().LUMINARY_BLOG_CONTENT_SUBDIR).parent / kind


def _asset_root(kind: str) -> Path:
    return _repo() / Path(get_settings().LUMINARY_BLOG_ASSET_SUBDIR).parent / kind


def _images_root() -> Path:
    return Path(get_settings().DATA_DIR).expanduser() / "images"


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _fallback_title(content: str) -> str:
    first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    first = re.sub(r"^#+\s*", "", first)
    return first[:60] or "Untitled"


@router.get("/config", response_model=BlogConfigResponse)
async def get_blog_config(kind: str = "blog") -> BlogConfigResponse:
    _check_kind(kind)
    repo, content_dir = _repo(), _content_dir(kind)
    health = await blog_service.repo_health(repo, content_dir)
    ahead = (
        await blog_service.ahead_count(repo, health["branch"])
        if health["is_git_repo"] and health["branch"]
        else None
    )
    return BlogConfigResponse(
        repo_path=str(repo),
        content_subdir=str(_content_dir(kind).relative_to(repo)),
        url_base=get_settings().LUMINARY_BLOG_URL_BASE,
        existing_slugs=sorted(blog_service.existing_slugs(content_dir)),
        ahead=ahead,
        **health,
    )


@router.post("/draft", response_model=BlogDraftResponse)
async def create_draft(
    req: BlogDraftRequest,
    kind: str = "blog",
    repo: NoteRepo = Depends(get_note_repo),
) -> BlogDraftResponse:
    _check_kind(kind)
    note = await repo.get_or_404(req.note_id)
    title = (req.title or note.title or _fallback_title(note.content)).strip()
    slug = blog_service.slugify(req.slug or title)
    pub_date = req.pub_date or blog_service.format_pub_date(datetime.now(UTC))
    description = req.description or ""

    draft = blog_service.transform_note_to_blog(note.content, slug, kind)
    frontmatter = blog_service.render_frontmatter(
        title=title,
        description=description,
        pub_date=pub_date,
        updated_date=req.updated_date,
        hero_image=req.hero_image,
    )
    return BlogDraftResponse(
        slug=slug,
        title=title,
        description=description,
        pub_date=pub_date,
        frontmatter=frontmatter,
        markdown=draft.markdown,
        warnings=draft.warnings,
        assets=[BlogAssetItem(**a.__dict__) for a in draft.assets],
        collision=slug in blog_service.existing_slugs(_content_dir(kind)),
    )


@router.post("/suggest-description", response_model=SuggestDescriptionResponse)
async def suggest_description(
    req: SuggestDescriptionRequest,
    repo: NoteRepo = Depends(get_note_repo),
) -> SuggestDescriptionResponse:
    note = await repo.get_or_404(req.note_id)
    from app.services.llm import LLMUnavailableError, get_llm_service  # noqa: PLC0415

    body = blog_service.transform_note_to_blog(note.content, "preview").markdown
    try:
        raw = await get_llm_service().complete(
            messages=[
                {"role": "system", "content": _DESC_SYSTEM},
                {"role": "user", "content": f"Post content:\n{body[:2000]}\n\nDescription:"},
            ],
            temperature=0.4,
            max_tokens=60,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail="LLM unavailable") from exc
    desc = re.sub(r'^["\']|["\']$', "", raw.strip()).strip()
    return SuggestDescriptionResponse(description=desc)


def _write_assets(
    slug: str, note_content: str, mermaid_svgs: dict[str, str], kind: str
) -> list[Path]:
    """Recompute the asset manifest from the note and materialise each asset."""
    draft = blog_service.transform_note_to_blog(note_content, slug, kind)
    asset_dir = _asset_root(kind) / slug
    written: list[Path] = []
    for asset in draft.assets:
        dest = asset_dir / asset.dest_filename
        if asset.kind == "copy":
            blog_service.copy_disk_asset(_images_root(), asset.doc_id, asset.filename, dest)
            written.append(dest)
        elif asset.kind == "mermaid":
            svg = mermaid_svgs.get(asset.key or "")
            if not svg:
                raise HTTPException(
                    status_code=400,
                    detail=f"missing rendered SVG for {asset.key}",
                )
            blog_service.write_text_file(dest, svg)
            written.append(dest)
    return written


@router.post("/publish", response_model=BlogPublishResponse)
async def publish(
    req: BlogPublishRequest,
    kind: str = "blog",
    repo_dep: NoteRepo = Depends(get_note_repo),
) -> BlogPublishResponse:
    _check_kind(kind)
    note = await repo_dep.get_or_404(req.note_id)
    settings = get_settings()
    repo = _repo()

    # Honor a user-edited destination folder, but never let it escape the repo.
    subdir = req.subdir or str(_content_dir(kind).relative_to(repo))
    content_dir = (repo / subdir).resolve()
    if not _within(content_dir, repo):
        raise HTTPException(status_code=400, detail=f"destination escapes repo: {subdir}")

    health = await blog_service.repo_health(repo, content_dir)
    if not health["is_git_repo"]:
        raise HTTPException(status_code=400, detail=f"not a git repository: {repo}")

    slug = blog_service.slugify(req.slug)
    md_path = content_dir / f"{slug}.md"
    if md_path.exists() and not req.overwrite:
        raise HTTPException(status_code=409, detail=f"post already exists: {slug}.md")

    updated_date = req.updated_date
    if md_path.exists() and req.overwrite and not updated_date:
        updated_date = blog_service.format_pub_date(datetime.now(UTC))

    try:
        asset_files = _write_assets(slug, note.content, req.mermaid_svgs, kind)
        frontmatter = blog_service.render_frontmatter(
            title=req.title,
            description=req.description,
            pub_date=req.pub_date,
            updated_date=updated_date,
            hero_image=req.hero_image,
        )
        blog_service.write_text_file(md_path, f"{frontmatter}\n\n{req.markdown.strip()}\n")
        files = [md_path, *asset_files]
        sha = await blog_service.git_add_commit(repo, files, f"{kind}: {req.title}")
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return BlogPublishResponse(
        committed=True,
        commit_sha=sha,
        files=[str(f.relative_to(repo)) for f in files],
        pushed=False,
        push_hint=f"git -C {repo} push origin {settings.LUMINARY_BLOG_BRANCH}",
        url=_post_url(slug, kind),
    )


# -- published posts: list / read / edit / delete -------------------------


def _post_path(slug: str, kind: str) -> tuple[Path, Path, str]:
    """Resolve (repo, md_path, clean_slug); 404 if the post does not exist."""
    repo = _repo()
    clean = blog_service.slugify(slug)
    md_path = _content_dir(kind) / f"{clean}.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail=f"post not found: {clean}")
    return repo, md_path, clean


def _post_url(slug: str, kind: str) -> str:
    return f"{get_settings().LUMINARY_BLOG_URL_BASE}/{kind}/{slug}/"


@router.get("/posts", response_model=list[BlogPostSummary])
async def list_posts(kind: str = "blog") -> list[BlogPostSummary]:
    _check_kind(kind)
    return [
        BlogPostSummary(**p, url=_post_url(p["slug"], kind))
        for p in blog_service.list_posts(_content_dir(kind))
    ]


@router.get("/posts/{slug}", response_model=BlogPostDetail)
async def get_post(slug: str, kind: str = "blog") -> BlogPostDetail:
    _check_kind(kind)
    _, _, clean = _post_path(slug, kind)
    return BlogPostDetail(
        **blog_service.read_post(_content_dir(kind), clean), url=_post_url(clean, kind)
    )


@router.put("/posts/{slug}", response_model=BlogPublishResponse)
async def update_post(
    slug: str, req: BlogPostUpdateRequest, kind: str = "blog"
) -> BlogPublishResponse:
    _check_kind(kind)
    repo, md_path, clean = _post_path(slug, kind)
    settings = get_settings()
    asset_dir = _asset_root(kind) / clean
    try:
        # Pasted images arrive as __LUMINARY_IMG__ refs: copy them into the post's
        # asset dir, then drop any asset the edited body no longer references.
        body, written = blog_service.adopt_inline_assets(
            req.body, clean, _images_root(), asset_dir, kind
        )
        keep = blog_service.referenced_assets(body, clean, req.hero_image, kind=kind)
        removed = blog_service.prune_orphan_assets(asset_dir, keep)
        frontmatter = blog_service.render_frontmatter(
            title=req.title,
            description=req.description,
            pub_date=req.pub_date,
            updated_date=req.updated_date,
            hero_image=req.hero_image,
        )
        blog_service.write_text_file(md_path, f"{frontmatter}\n\n{body.strip()}\n")
        files = [md_path, *written, *removed]
        sha = await blog_service.git_add_commit(repo, files, f"{kind}: update {clean}")
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BlogPublishResponse(
        committed=True,
        commit_sha=sha,
        files=[str(f.relative_to(repo)) for f in files],
        removed_assets=[str(f.relative_to(repo)) for f in removed],
        pushed=False,
        push_hint=f"git -C {repo} push origin {settings.LUMINARY_BLOG_BRANCH}",
        url=_post_url(clean, kind),
    )


@router.delete("/posts/{slug}", response_model=BlogPublishResponse)
async def delete_post(slug: str, kind: str = "blog") -> BlogPublishResponse:
    _check_kind(kind)
    repo, md_path, clean = _post_path(slug, kind)
    settings = get_settings()
    asset_dir = _asset_root(kind) / clean
    files = [md_path]
    try:
        md_path.unlink()
        if asset_dir.is_dir():
            shutil.rmtree(asset_dir)
            files.append(asset_dir)
        sha = await blog_service.git_add_commit(repo, files, f"{kind}: delete {clean}")
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BlogPublishResponse(
        committed=True,
        commit_sha=sha,
        files=[str(f.relative_to(repo)) for f in files],
        pushed=False,
        push_hint=f"git -C {repo} push origin {settings.LUMINARY_BLOG_BRANCH}",
        url=f"{settings.LUMINARY_BLOG_URL_BASE}/{kind}/",
    )


@router.get("/asset/{kind}/{slug}/{filename}")
async def get_asset(kind: str, slug: str, filename: str) -> FileResponse:
    """Serve a published post's asset (public/<kind>/<slug>/<file>) so the edit
    preview can render images whose markdown uses site-absolute /<kind>/... paths."""
    _check_kind(kind)
    asset_root = _asset_root(kind)
    path = (asset_root / blog_service.slugify(slug) / filename).resolve()
    if not _within(path, asset_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(str(path))


@router.post("/push", response_model=BlogPushResponse)
async def push() -> BlogPushResponse:
    # Push is repo-wide (both collections live in one repo); the content dir is
    # only needed for the git-repo health check.
    repo, content_dir = _repo(), _content_dir("blog")
    health = await blog_service.repo_health(repo, content_dir)
    if not health["is_git_repo"]:
        raise HTTPException(status_code=400, detail=f"not a git repository: {repo}")
    branch = health["branch"] or get_settings().LUMINARY_BLOG_BRANCH
    try:
        output = await blog_service.git_push(repo, branch)
    except RuntimeError as exc:
        # 502: the local commit is fine; the remote push is what failed
        # (auth, non-fast-forward, offline). Surface git's message verbatim.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BlogPushResponse(pushed=True, branch=branch, output=output)


# -- optional live render via background `astro dev` -----------------------

_astro_proc: asyncio.subprocess.Process | None = None


async def _port_open(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(_LIVE_PREVIEW_HOST, port), timeout=1.0
        )
        writer.close()
        return True
    except (OSError, TimeoutError):
        return False


async def _ensure_astro_dev(repo: Path) -> None:
    global _astro_proc
    if await _port_open(_LIVE_PREVIEW_PORT):
        return
    if _astro_proc is None or _astro_proc.returncode is not None:
        # Force an IPv4 bind: astro defaults to localhost which can resolve to
        # IPv6 [::1], while our readiness check + preview URL use 127.0.0.1.
        _astro_proc = await asyncio.create_subprocess_exec(
            "npx",
            "astro",
            "dev",
            "--host",
            _LIVE_PREVIEW_HOST,
            "--port",
            str(_LIVE_PREVIEW_PORT),
            cwd=str(repo),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    for _ in range(60):
        if await _port_open(_LIVE_PREVIEW_PORT):
            return
        await asyncio.sleep(0.5)
    raise HTTPException(status_code=504, detail="astro dev did not start in time")


async def _wait_for_route(url: str, timeout: float = 25.0) -> None:
    import httpx  # noqa: PLC0415

    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)


def _preview_slug(slug: str) -> str:
    # NOT underscore-prefixed: Astro content collections silently ignore files
    # whose name starts with "_", which 404s the live preview route.
    return f"lmpreview-{blog_service.slugify(slug)}"


@router.post("/preview/live", response_model=BlogLivePreviewResponse)
async def live_preview(
    req: BlogLivePreviewRequest,
    kind: str = "blog",
    repo_dep: NoteRepo = Depends(get_note_repo),
) -> BlogLivePreviewResponse:
    _check_kind(kind)
    note = await repo_dep.get_or_404(req.note_id)
    repo = _repo()
    pslug = _preview_slug(req.slug)
    frontmatter = blog_service.render_frontmatter(
        title=req.title,
        description=req.description,
        pub_date=req.pub_date,
        updated_date=req.updated_date,
        hero_image=req.hero_image,
    )
    # The edited body references /<kind>/<real-slug>/...; rewrite to the preview
    # slug so its assets resolve under the preview asset dir.
    body = req.markdown.replace(
        f"/{kind}/{blog_service.slugify(req.slug)}/", f"/{kind}/{pslug}/"
    )
    blog_service.write_text_file(_content_dir(kind) / f"{pslug}.md", f"{frontmatter}\n\n{body}\n")
    try:
        _write_assets(pslug, note.content, req.mermaid_svgs, kind)
    except HTTPException:
        pass  # best-effort: a missing diagram should not block the text preview
    await _ensure_astro_dev(repo)
    url = f"http://{_LIVE_PREVIEW_HOST}:{_LIVE_PREVIEW_PORT}/{kind}/{pslug}/"
    # Astro's content watcher needs a moment to register the new file as a route;
    # wait until it actually renders so the opened tab isn't a transient 404.
    await _wait_for_route(url)
    return BlogLivePreviewResponse(url=url)


@router.post("/preview/live/cleanup", status_code=204)
async def live_preview_cleanup(req: BlogLivePreviewCleanupRequest, kind: str = "blog") -> None:
    _check_kind(kind)
    pslug = _preview_slug(req.slug)
    (_content_dir(kind) / f"{pslug}.md").unlink(missing_ok=True)
    shutil.rmtree(_asset_root(kind) / pslug, ignore_errors=True)
