// blogApi — typed client for the labs blog-publishing endpoints (/blog/*).
// Shapes mirror backend/app/schemas/blog.py; not in the generated OpenAPI types.

import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/apiClient"

// Two publishable collections on the Astro site, sharing one mechanism.
export type BlogKind = "blog" | "thoughts"

export const KIND_SINGULAR: Record<BlogKind, string> = { blog: "Blog", thoughts: "Thought" }
export const KIND_PLURAL: Record<BlogKind, string> = { blog: "Blogs", thoughts: "Thoughts" }

const q = (kind: BlogKind) => `?kind=${kind}`

export interface BlogConfig {
  repo_path: string
  content_subdir: string
  is_git_repo: boolean
  content_dir_exists: boolean
  branch: string | null
  dirty: boolean
  ahead?: number | null
  existing_slugs: string[]
  url_base: string
}

export interface BlogPushResult {
  pushed: boolean
  branch: string
  output: string
}

export interface BlogAsset {
  kind: "copy" | "mermaid"
  dest_filename: string
  key?: string | null
  doc_id?: string | null
  filename?: string | null
}

export interface BlogDraft {
  slug: string
  title: string
  description: string
  pub_date: string
  frontmatter: string
  markdown: string
  warnings: string[]
  assets: BlogAsset[]
  collision: boolean
}

export interface BlogDraftRequest {
  note_id: string
  title?: string
  description?: string
  pub_date?: string
  slug?: string
  updated_date?: string
  hero_image?: string
}

export interface BlogPublishRequest {
  note_id: string
  slug: string
  subdir?: string
  title: string
  description: string
  pub_date: string
  updated_date?: string
  hero_image?: string
  markdown: string
  mermaid_svgs: Record<string, string>
  overwrite: boolean
}

export interface BlogPublishResult {
  committed: boolean
  commit_sha: string
  files: string[]
  removed_assets?: string[]
  pushed: boolean
  push_hint: string
  url: string
}

export interface BlogLivePreviewRequest {
  note_id: string
  slug: string
  title: string
  description: string
  pub_date: string
  updated_date?: string
  hero_image?: string
  markdown: string
  mermaid_svgs: Record<string, string>
}

export const getBlogConfig = (kind: BlogKind = "blog"): Promise<BlogConfig> =>
  apiGet<BlogConfig>(`/blog/config${q(kind)}`)

export const createBlogDraft = (
  req: BlogDraftRequest,
  kind: BlogKind = "blog",
): Promise<BlogDraft> => apiPost<BlogDraft>(`/blog/draft${q(kind)}`, req)

export const suggestBlogDescription = (noteId: string): Promise<{ description: string }> =>
  apiPost<{ description: string }>("/blog/suggest-description", { note_id: noteId })

export const publishBlog = (
  req: BlogPublishRequest,
  kind: BlogKind = "blog",
): Promise<BlogPublishResult> => apiPost<BlogPublishResult>(`/blog/publish${q(kind)}`, req)

export const blogLivePreview = (
  req: BlogLivePreviewRequest,
  kind: BlogKind = "blog",
): Promise<{ url: string }> => apiPost<{ url: string }>(`/blog/preview/live${q(kind)}`, req)

export const blogLivePreviewCleanup = (slug: string, kind: BlogKind = "blog"): Promise<void> =>
  apiPost<void>(`/blog/preview/live/cleanup${q(kind)}`, { slug })

// -- published-post management --------------------------------------------

export interface BlogPostSummary {
  slug: string
  title: string
  description: string
  pub_date: string
  updated_date?: string | null
  url: string
}

export interface BlogPostDetail extends BlogPostSummary {
  hero_image?: string | null
  body: string
}

export interface BlogPostUpdateRequest {
  title: string
  description: string
  pub_date: string
  updated_date?: string
  hero_image?: string
  body: string
}

export const listBlogPosts = (kind: BlogKind = "blog"): Promise<BlogPostSummary[]> =>
  apiGet<BlogPostSummary[]>(`/blog/posts${q(kind)}`)

export const getBlogPost = (slug: string, kind: BlogKind = "blog"): Promise<BlogPostDetail> =>
  apiGet<BlogPostDetail>(`/blog/posts/${slug}${q(kind)}`)

export const updateBlogPost = (
  slug: string,
  req: BlogPostUpdateRequest,
  kind: BlogKind = "blog",
): Promise<BlogPublishResult> => apiPut<BlogPublishResult>(`/blog/posts/${slug}${q(kind)}`, req)

export const deleteBlogPost = (slug: string, kind: BlogKind = "blog"): Promise<BlogPublishResult> =>
  apiDelete<BlogPublishResult>(`/blog/posts/${slug}${q(kind)}`)

export const pushBlog = (): Promise<BlogPushResult> =>
  apiPost<BlogPushResult>("/blog/push")
