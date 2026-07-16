"""Pydantic schemas for the blog-publishing router (full mode)."""

from pydantic import BaseModel


class BlogConfigResponse(BaseModel):
    repo_path: str
    content_subdir: str
    is_git_repo: bool
    content_dir_exists: bool
    branch: str | None
    dirty: bool
    ahead: int | None = None
    existing_slugs: list[str]
    url_base: str


class BlogPushResponse(BaseModel):
    pushed: bool
    branch: str
    output: str


class BlogDraftRequest(BaseModel):
    note_id: str
    title: str | None = None
    description: str | None = None
    pub_date: str | None = None
    slug: str | None = None
    updated_date: str | None = None
    hero_image: str | None = None


class BlogAssetItem(BaseModel):
    kind: str
    dest_filename: str
    key: str | None = None
    doc_id: str | None = None
    filename: str | None = None


class BlogDraftResponse(BaseModel):
    slug: str
    title: str
    description: str
    pub_date: str
    frontmatter: str
    markdown: str
    warnings: list[str]
    assets: list[BlogAssetItem]
    collision: bool


class SuggestDescriptionRequest(BaseModel):
    note_id: str


class SuggestDescriptionResponse(BaseModel):
    description: str


class BlogPublishRequest(BaseModel):
    note_id: str
    slug: str
    # Destination folder relative to the repo root. Defaults to the site's
    # content collection dir when omitted. Must stay inside the repo.
    subdir: str | None = None
    title: str
    description: str
    pub_date: str
    updated_date: str | None = None
    hero_image: str | None = None
    markdown: str
    # block key -> rendered SVG string, for mermaid diagrams rendered client-side
    mermaid_svgs: dict[str, str] = {}
    overwrite: bool = False


class BlogPublishResponse(BaseModel):
    committed: bool
    commit_sha: str
    files: list[str]
    removed_assets: list[str] = []
    pushed: bool = False
    push_hint: str
    url: str


class BlogLivePreviewRequest(BaseModel):
    note_id: str
    slug: str
    title: str
    description: str
    pub_date: str
    updated_date: str | None = None
    hero_image: str | None = None
    markdown: str
    mermaid_svgs: dict[str, str] = {}


class BlogLivePreviewResponse(BaseModel):
    url: str


class BlogLivePreviewCleanupRequest(BaseModel):
    slug: str


class BlogPostSummary(BaseModel):
    slug: str
    title: str
    description: str
    pub_date: str
    updated_date: str | None = None
    url: str


class BlogPostDetail(BlogPostSummary):
    hero_image: str | None = None
    body: str


class BlogPostUpdateRequest(BaseModel):
    title: str
    description: str
    pub_date: str
    updated_date: str | None = None
    hero_image: str | None = None
    body: str
