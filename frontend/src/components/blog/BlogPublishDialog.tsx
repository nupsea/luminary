/**
 * BlogPublishDialog — full-mode feature: turn a note into a post on the author's
 * Astro site. Shows a faithful in-app preview (matching the site's prose / Inter
 * / slate styling), an optional live `astro dev` render, then writes the post +
 * assets into the site repo and makes a LOCAL commit. The user pushes manually.
 *
 * Mermaid blocks are rendered to SVG client-side; Excalidraw SVGs and local
 * images are copied from disk by the backend. Note-links are dropped.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  ExternalLink,
  Loader2,
  Sparkles,
  UploadCloud,
} from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError } from "@/lib/apiClient"
import { API_BASE } from "@/lib/config"
import {
  blogLivePreview,
  blogLivePreviewCleanup,
  createBlogDraft,
  getBlogConfig,
  publishBlog,
  suggestBlogDescription,
  KIND_SINGULAR,
  type BlogDraft,
  type BlogKind,
  type BlogPublishResult,
} from "@/lib/blogApi"
import { renderMermaidSvgs, svgToDataUri } from "@/lib/blogMermaid"
import { MarkdownSplitEditor } from "@/components/notes/MarkdownSplitEditor"
import { BlogPreview } from "./BlogPreview"
import { PushBlogButton } from "./PushBlogButton"

interface BlogPublishDialogProps {
  open: boolean
  onClose: () => void
  noteId: string
  noteContent: string
  kind?: BlogKind
}

const inputCls =
  "w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.body) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      /* non-JSON body */
    }
    return `HTTP ${err.status}`
  }
  return err instanceof Error ? err.message : fallback
}

export function BlogPublishDialog({
  open,
  onClose,
  noteId,
  noteContent,
  kind = "blog",
}: BlogPublishDialogProps) {
  const kindLabel = KIND_SINGULAR[kind]
  const [draft, setDraft] = useState<BlogDraft | null>(null)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [slug, setSlug] = useState("")
  const [pubDate, setPubDate] = useState("")
  const [updatedDate, setUpdatedDate] = useState("")
  const [heroImage, setHeroImage] = useState("")
  const [subdir, setSubdir] = useState("")
  const [body, setBody] = useState("")

  const [mermaidSvgs, setMermaidSvgs] = useState<Record<string, string>>({})
  const [loadingDraft, setLoadingDraft] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [overwriteOk, setOverwriteOk] = useState(false)
  const [result, setResult] = useState<BlogPublishResult | null>(null)
  const [livePreviewing, setLivePreviewing] = useState(false)
  const livePreviewSlugRef = useRef<string | null>(null)

  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ["blog-config", kind],
    queryFn: () => getBlogConfig(kind),
    enabled: open,
    staleTime: 10_000,
  })
  const qc = useQueryClient()

  // Load the transformed draft + render mermaid diagrams when the dialog opens.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadingDraft(true)
    setDraftError(null)
    setResult(null)
    void (async () => {
      try {
        const d = await createBlogDraft({ note_id: noteId }, kind)
        if (cancelled) return
        setDraft(d)
        setTitle(d.title)
        setDescription(d.description)
        setSlug(d.slug)
        setPubDate(d.pub_date)
        setBody(d.markdown)
        setMermaidSvgs(await renderMermaidSvgs(noteContent))
      } catch (err) {
        if (!cancelled) setDraftError(errorMessage(err, "Failed to build draft"))
      } finally {
        if (!cancelled) setLoadingDraft(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, noteId, noteContent, kind])

  // Default the destination folder to the site's content collection dir.
  useEffect(() => {
    if (config?.content_subdir && !subdir) setSubdir(config.content_subdir)
  }, [config, subdir])

  function updateSlug(next: string) {
    const cleaned = next.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "")
    setBody((prev) => prev.replaceAll(`/${kind}/${slug}/`, `/${kind}/${cleaned}/`))
    setSlug(cleaned)
    setOverwriteOk(false)
  }

  const collision = !!config && config.existing_slugs.includes(slug)

  // Build a preview body whose asset refs resolve in-app: copied assets point at
  // Luminary's local image server, mermaid diagrams at their rendered SVG.
  const previewMarkdown = useMemo(() => {
    if (!draft) return body
    let md = body
    for (const a of draft.assets) {
      const token = `/${kind}/${slug}/${a.dest_filename}`
      if (a.kind === "copy" && a.doc_id && a.filename) {
        md = md.replaceAll(token, `${API_BASE}/images/local/${a.doc_id}/${a.filename}`)
      } else if (a.kind === "mermaid" && a.key && mermaidSvgs[a.key]) {
        md = md.replaceAll(token, svgToDataUri(mermaidSvgs[a.key]))
      }
    }
    return md
  }, [draft, body, slug, mermaidSvgs, kind])

  const repoReady = !!config && config.is_git_repo && config.content_dir_exists
  const valid =
    title.trim() && description.trim() && pubDate.trim() && slug.trim() && repoReady
  const canPublish = valid && !publishing && (!collision || overwriteOk)

  async function handleSuggest() {
    setSuggesting(true)
    try {
      const { description: d } = await suggestBlogDescription(noteId)
      setDescription(d)
    } catch (err) {
      toast.error(errorMessage(err, "Suggestion failed"))
    } finally {
      setSuggesting(false)
    }
  }

  async function handleLivePreview() {
    setLivePreviewing(true)
    try {
      const { url } = await blogLivePreview(
        {
          note_id: noteId,
          slug,
          title,
          description,
          pub_date: pubDate,
          updated_date: updatedDate || undefined,
          hero_image: heroImage || undefined,
          markdown: body,
          mermaid_svgs: mermaidSvgs,
        },
        kind,
      )
      livePreviewSlugRef.current = slug
      window.open(url, "_blank", "noopener")
    } catch (err) {
      toast.error(errorMessage(err, "Live preview failed"))
    } finally {
      setLivePreviewing(false)
    }
  }

  async function handlePublish() {
    setPublishing(true)
    try {
      const res = await publishBlog(
        {
          note_id: noteId,
          slug,
          subdir: subdir || undefined,
          title,
          description,
          pub_date: pubDate,
          updated_date: updatedDate || undefined,
          hero_image: heroImage || undefined,
          markdown: body,
          mermaid_svgs: mermaidSvgs,
          overwrite: collision,
        },
        kind,
      )
      setResult(res)
      void qc.invalidateQueries({ queryKey: ["blog-posts"] })
      void qc.invalidateQueries({ queryKey: ["blog-config"] })
      toast.success("Committed locally — ready to push")
    } catch (err) {
      toast.error(errorMessage(err, "Publish failed"))
    } finally {
      setPublishing(false)
    }
  }

  function handleClose() {
    if (livePreviewSlugRef.current) {
      void blogLivePreviewCleanup(livePreviewSlugRef.current, kind).catch(() => {})
      livePreviewSlugRef.current = null
    }
    setDraft(null)
    setOverwriteOk(false)
    setResult(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="flex h-[92vh] max-h-[92vh] w-[94vw] max-w-[1500px] flex-col overflow-hidden p-0">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-xl">Publish as {kindLabel.toLowerCase()}</DialogTitle>
          <DialogDescription>
            Preview the post, then commit it to your site repo. Pushing stays manual.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-1 gap-4 overflow-hidden px-6 py-4">
          {/* Left: metadata form */}
          <div className="flex w-[380px] shrink-0 flex-col gap-4 overflow-y-auto pr-2">
            {configLoading || loadingDraft ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Building draft…
              </div>
            ) : draftError ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                {draftError}
              </div>
            ) : (
              <>
                {config && !repoReady && (
                  <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      {config.is_git_repo
                        ? `Blog content dir missing under ${config.repo_path}`
                        : `Not a git repo: ${config.repo_path}`}
                    </span>
                  </div>
                )}

                <Field label="Title">
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className={inputCls}
                  />
                </Field>

                <Field label="Description">
                  <div className="flex flex-col gap-1.5">
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      placeholder="One-line summary shown on the site"
                      className={`${inputCls} resize-none`}
                    />
                    <button
                      onClick={() => void handleSuggest()}
                      disabled={suggesting}
                      className="inline-flex w-fit items-center gap-1.5 rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-accent disabled:opacity-50"
                    >
                      {suggesting ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      Suggest
                    </button>
                  </div>
                </Field>

                <Field label="Slug">
                  <input
                    value={slug}
                    onChange={(e) => updateSlug(e.target.value)}
                    className={inputCls}
                  />
                  {collision && (
                    <p className="mt-1 text-xs text-amber-700">
                      A post with this slug exists — publishing overwrites it.
                    </p>
                  )}
                </Field>

                <Field label="Destination folder (under repo)">
                  <input
                    value={subdir}
                    onChange={(e) => setSubdir(e.target.value)}
                    className={inputCls}
                  />
                  <p className="mt-1 break-all rounded bg-muted/50 px-2 py-1 font-mono text-[11px] text-muted-foreground">
                    {config?.repo_path}/{subdir || config?.content_subdir}/{slug || "…"}.md
                  </p>
                  {config && subdir && subdir !== config.content_subdir && (
                    <p className="mt-1 text-xs text-amber-700">
                      Note: the site only renders posts under {config.content_subdir}.
                    </p>
                  )}
                </Field>

                <div className="grid grid-cols-2 gap-3">
                  <Field label="Publish date">
                    <input
                      value={pubDate}
                      onChange={(e) => setPubDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Updated date (optional)">
                    <input
                      value={updatedDate}
                      onChange={(e) => setUpdatedDate(e.target.value)}
                      placeholder="—"
                      className={inputCls}
                    />
                  </Field>
                </div>

                <Field label="Hero image URL (optional)">
                  <input
                    value={heroImage}
                    onChange={(e) => setHeroImage(e.target.value)}
                    placeholder="/blog/…/hero.png"
                    className={inputCls}
                  />
                </Field>

                {draft && draft.warnings.length > 0 && (
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                    <p className="mb-1 font-semibold">Conversion notes</p>
                    <ul className="list-disc space-y-0.5 pl-4">
                      {draft.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Right pane: body editor + faithful preview, side by side */}
          <div className="flex flex-1 flex-col overflow-hidden rounded-lg bg-slate-100 p-3">
            {loadingDraft ? (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Rendering preview…
              </div>
            ) : (
              <MarkdownSplitEditor
                layout="splitter"
                content={body}
                onContentChange={setBody}
                editorLabel="Body markdown"
                placeholder="Write your post in Markdown..."
                editorClassName="min-h-0 w-full flex-1 overflow-hidden rounded-md border border-slate-300 bg-white text-slate-900"
                previewClassName="flex-1 overflow-auto"
                preview={
                  <BlogPreview
                    title={title}
                    description={description}
                    pubDate={pubDate}
                    updatedDate={updatedDate || undefined}
                    heroImage={heroImage || undefined}
                    markdown={previewMarkdown}
                  />
                }
              />
            )}
          </div>
        </div>

        <DialogFooter className="flex items-center justify-between gap-3 border-t border-border bg-muted/10 p-4">
          {result ? (
            <div className="flex w-full flex-col gap-1 text-sm">
              <span className="flex items-center gap-1.5 font-medium text-green-700">
                <Check className="h-4 w-4" /> Committed {result.commit_sha.slice(0, 8)} — use Push to deploy
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {collision && (
                <label className="flex items-center gap-1.5 text-xs text-amber-700">
                  <input
                    type="checkbox"
                    checked={overwriteOk}
                    onChange={(e) => setOverwriteOk(e.target.checked)}
                  />
                  Confirm overwrite
                </label>
              )}
            </div>
          )}
          <div className="flex items-center gap-2">
            {result && <PushBlogButton compact />}
            <button
              onClick={handleClose}
              className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
            >
              {result ? "Done" : "Cancel"}
            </button>
            {!result && (
              <>
                <button
                  onClick={() => void handleLivePreview()}
                  disabled={!valid || livePreviewing}
                  title="Render the real Astro page in a new tab"
                  className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
                >
                  {livePreviewing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ExternalLink className="h-4 w-4" />
                  )}
                  Open real render
                </button>
                <button
                  onClick={() => void handlePublish()}
                  disabled={!canPublish}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {publishing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <UploadCloud className="h-4 w-4" />
                  )}
                  Approve &amp; Commit
                </button>
              </>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-semibold text-foreground">{label}</span>
      {children}
    </label>
  )
}
