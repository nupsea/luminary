// blogApi — typed client for the labs blog-publishing endpoints (/blog/*).
// Shapes mirror backend/app/schemas/blog.py; not in the generated OpenAPI types.

import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/apiClient"

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

export const getBlogConfig = (): Promise<BlogConfig> => apiGet<BlogConfig>("/blog/config")

export const createBlogDraft = (req: BlogDraftRequest): Promise<BlogDraft> =>
  apiPost<BlogDraft>("/blog/draft", req)

export const suggestBlogDescription = (noteId: string): Promise<{ description: string }> =>
  apiPost<{ description: string }>("/blog/suggest-description", { note_id: noteId })

export const publishBlog = (req: BlogPublishRequest): Promise<BlogPublishResult> =>
  apiPost<BlogPublishResult>("/blog/publish", req)

export const blogLivePreview = (req: BlogLivePreviewRequest): Promise<{ url: string }> =>
  apiPost<{ url: string }>("/blog/preview/live", req)

export const blogLivePreviewCleanup = (slug: string): Promise<void> =>
  apiPost<void>("/blog/preview/live/cleanup", { slug })

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

export const listBlogPosts = (): Promise<BlogPostSummary[]> =>
  apiGet<BlogPostSummary[]>("/blog/posts")

export const getBlogPost = (slug: string): Promise<BlogPostDetail> =>
  apiGet<BlogPostDetail>(`/blog/posts/${slug}`)

export const updateBlogPost = (
  slug: string,
  req: BlogPostUpdateRequest,
): Promise<BlogPublishResult> => apiPut<BlogPublishResult>(`/blog/posts/${slug}`, req)

export const deleteBlogPost = (slug: string): Promise<BlogPublishResult> =>
  apiDelete<BlogPublishResult>(`/blog/posts/${slug}`)

export const pushBlog = (): Promise<BlogPushResult> =>
  apiPost<BlogPushResult>("/blog/push")
