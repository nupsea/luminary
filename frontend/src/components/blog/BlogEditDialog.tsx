/**
 * BlogEditDialog — view/edit a published post in the site repo, then commit the
 * change locally (the user pushes). Also supports deleting the post (with a
 * confirm), which commits the file + asset-dir removal.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ExternalLink, Loader2, Save, Trash2 } from "lucide-react"
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
  deleteBlogPost,
  getBlogPost,
  updateBlogPost,
  type BlogPublishResult,
} from "@/lib/blogApi"
import { MarkdownSplitEditor } from "@/components/notes/MarkdownSplitEditor"
import { createImagePasteHandler } from "@/lib/noteEditorUtils"
import { BlogPreview } from "./BlogPreview"
import { PushBlogButton } from "./PushBlogButton"

const inputCls =
  "w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.body) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      /* non-JSON */
    }
    return `HTTP ${err.status}`
  }
  return err instanceof Error ? err.message : fallback
}

interface BlogEditDialogProps {
  slug: string
  open: boolean
  onClose: () => void
  onChanged: () => void
}

export function BlogEditDialog({ slug, open, onClose, onChanged }: BlogEditDialogProps) {
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [pubDate, setPubDate] = useState("")
  const [updatedDate, setUpdatedDate] = useState("")
  const [heroImage, setHeroImage] = useState("")
  const [body, setBody] = useState("")
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [result, setResult] = useState<BlogPublishResult | null>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["blog-post", slug],
    queryFn: () => getBlogPost(slug),
    enabled: open,
  })

  // Make image refs resolve in the in-app preview: published assets live at
  // /blog/<slug>/… (served by the backend asset endpoint); freshly pasted ones
  // are still __LUMINARY_IMG__/… in Luminary's image store until saved.
  const previewBody = useMemo(
    () =>
      body
        .replaceAll(`/blog/${slug}/`, `${API_BASE}/blog/asset/${slug}/`)
        .replaceAll("__LUMINARY_IMG__/", `${API_BASE}/images/local/`),
    [body, slug],
  )

  useEffect(() => {
    if (!data) return
    setTitle(data.title)
    setDescription(data.description)
    setPubDate(data.pub_date)
    setUpdatedDate(data.updated_date ?? "")
    setHeroImage(data.hero_image ?? "")
    setBody(data.body)
  }, [data])

  async function handleSave() {
    setSaving(true)
    try {
      const res = await updateBlogPost(slug, {
        title,
        description,
        pub_date: pubDate,
        updated_date: updatedDate || undefined,
        hero_image: heroImage || undefined,
        body,
      })
      setResult(res)
      onChanged()
      // Refetch so the editor shows canonical /blog/<slug>/ refs for any images
      // adopted on save (replacing the transient __LUMINARY_IMG__ paste refs).
      void qc.invalidateQueries({ queryKey: ["blog-post", slug] })
      const removed = res.removed_assets?.length ?? 0
      toast.success(
        removed > 0
          ? `Saved & committed locally — removed ${removed} unused image${removed > 1 ? "s" : ""}`
          : "Saved & committed locally",
      )
    } catch (err) {
      toast.error(errorMessage(err, "Save failed"))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await deleteBlogPost(slug)
      onChanged()
      toast.success(`Deleted ${slug} (committed locally)`)
      onClose()
    } catch (err) {
      toast.error(errorMessage(err, "Delete failed"))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="flex h-[92vh] max-h-[92vh] w-[94vw] max-w-[1500px] flex-col overflow-hidden p-0">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-xl">Edit blog post</DialogTitle>
          <DialogDescription>
            Edit the post, then commit to your site repo. Pushing stays manual.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-1 gap-4 overflow-hidden px-6 py-4">
          <div className="flex w-[380px] shrink-0 flex-col gap-4 overflow-y-auto pr-2">
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </div>
            ) : isError ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                {errorMessage(error, "Failed to load post")}
              </div>
            ) : (
              <>
                <Field label="Title">
                  <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
                </Field>
                <Field label="Description">
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    className={`${inputCls} resize-none`}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Publish date">
                    <input value={pubDate} onChange={(e) => setPubDate(e.target.value)} className={inputCls} />
                  </Field>
                  <Field label="Updated date (optional)">
                    <input value={updatedDate} onChange={(e) => setUpdatedDate(e.target.value)} placeholder="—" className={inputCls} />
                  </Field>
                </div>
                <Field label="Hero image URL (optional)">
                  <input value={heroImage} onChange={(e) => setHeroImage(e.target.value)} placeholder="/blog/…/hero.png" className={inputCls} />
                </Field>
                <p className="break-all rounded bg-muted/50 px-2 py-1 font-mono text-[11px] text-muted-foreground">
                  src/content/blog/{slug}.md
                </p>
              </>
            )}
          </div>

          <div className="flex flex-1 flex-col overflow-hidden rounded-lg bg-slate-100 p-3">
            <MarkdownSplitEditor
              layout="splitter"
              content={body}
              onContentChange={setBody}
              textareaRef={bodyRef}
              onPaste={createImagePasteHandler(
                () => bodyRef.current,
                () => body,
                setBody,
                (path) => `![image](${path})`,
              )}
              editorLabel="Body markdown"
              placeholder="Write your post in Markdown... (paste an image to add it)"
              textareaClassName="w-full flex-1 resize-none rounded-md border border-slate-300 bg-white p-3 font-mono text-sm leading-relaxed text-slate-900 focus:outline-none focus:ring-2 focus:ring-primary"
              previewClassName="flex-1 overflow-auto"
              preview={
                <BlogPreview
                  title={title}
                  description={description}
                  pubDate={pubDate}
                  updatedDate={updatedDate || undefined}
                  heroImage={heroImage || undefined}
                  markdown={previewBody}
                />
              }
            />
          </div>
        </div>

        <DialogFooter className="flex items-center justify-between gap-3 border-t border-border bg-muted/10 p-4">
          <div className="flex items-center gap-2">
            {confirmDelete ? (
              <>
                <span className="text-xs text-destructive">Delete this post?</span>
                <button
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                  className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Yes, delete
                </button>
                <button onClick={() => setConfirmDelete(false)} className="rounded-md border border-input px-3 py-1.5 text-xs hover:bg-accent">
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-3.5 w-3.5" /> Delete
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {result && (
              <span className="flex items-center gap-1.5 text-xs font-medium text-green-700">
                <Check className="h-3.5 w-3.5" /> Committed {result.commit_sha.slice(0, 8)}
              </span>
            )}
            {result && <PushBlogButton compact />}
            {data && (
              <a
                href={data.url}
                target="_blank"
                rel="noopener"
                className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
              >
                <ExternalLink className="h-4 w-4" /> Live URL
              </a>
            )}
            <button onClick={onClose} className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent">
              Close
            </button>
            <button
              onClick={() => void handleSave()}
              disabled={saving || isLoading}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save &amp; Commit
            </button>
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
