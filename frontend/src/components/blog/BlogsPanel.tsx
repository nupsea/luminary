/**
 * BlogsPanel — lists the published posts in the site repo (GET /blog/posts).
 * Each post can be opened for editing (BlogEditDialog) or deleted in place
 * (both commit locally; the user pushes). Shown in the Notes page "Blogs" view.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Loader2, Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Skeleton } from "@/components/ui/skeleton"
import { deleteBlogPost, listBlogPosts, type BlogPostSummary } from "@/lib/blogApi"
import { BlogEditDialog } from "./BlogEditDialog"
import { PushBlogButton } from "./PushBlogButton"

function formatDate(value: string): string {
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })
}

export function BlogsPanel() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["blog-posts"],
    queryFn: listBlogPosts,
  })

  const deleteMut = useMutation({
    mutationFn: (slug: string) => deleteBlogPost(slug),
    onSuccess: (_res, slug) => {
      setConfirming(null)
      void qc.invalidateQueries({ queryKey: ["blog-posts"] })
      void qc.invalidateQueries({ queryKey: ["blog-config"] })
      toast.success(`Deleted ${slug} (committed locally)`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Delete failed"),
  })

  const posts = data ?? []

  let content: React.ReactNode
  if (isLoading) {
    content = (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    )
  } else if (isError) {
    content = (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        Could not load blog posts.{" "}
        <button onClick={() => void refetch()} className="font-medium underline">
          Retry
        </button>
      </div>
    )
  } else if (posts.length === 0) {
    content = (
      <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No published blog posts yet. Use the <span className="font-medium text-primary">Blog</span>{" "}
        button on a note to publish one.
      </div>
    )
  } else {
    content = (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {posts.map((post: BlogPostSummary) => (
          <div
            key={post.slug}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
          >
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="flex-1">{formatDate(post.pub_date)}</span>
              <a
                href={post.url}
                target="_blank"
                rel="noopener"
                className="hover:text-foreground"
                title="Open live URL"
              >
                <ExternalLink size={13} />
              </a>
              <button
                onClick={() => setEditing(post.slug)}
                className="hover:text-foreground"
                title="Edit post"
              >
                <Pencil size={13} />
              </button>
              <button
                onClick={() => setConfirming(post.slug)}
                className="hover:text-destructive"
                title="Delete post"
              >
                <Trash2 size={13} />
              </button>
            </div>

            <button onClick={() => setEditing(post.slug)} className="text-left">
              <h3 className="text-lg font-semibold leading-snug text-foreground hover:text-primary">
                {post.title}
              </h3>
            </button>
            <p className="line-clamp-3 text-sm text-muted-foreground">{post.description}</p>
            <code className="mt-auto truncate rounded bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground">
              {post.slug}.md
            </code>

            {confirming === post.slug && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Delete this post?</span>
                <button
                  onClick={() => deleteMut.mutate(post.slug)}
                  disabled={deleteMut.isPending}
                  className="inline-flex items-center gap-1 rounded bg-destructive px-2 py-0.5 font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  {deleteMut.isPending && deleteMut.variables === post.slug && (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  )}
                  Yes
                </button>
                <button
                  onClick={() => setConfirming(null)}
                  className="rounded border border-border px-2 py-0.5 hover:bg-accent"
                >
                  No
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {posts.length} post{posts.length === 1 ? "" : "s"} in your site repo
        </span>
        <PushBlogButton />
      </div>

      {content}

      {editing && (
        <BlogEditDialog
          slug={editing}
          open={!!editing}
          onClose={() => setEditing(null)}
          onChanged={() => {
            void qc.invalidateQueries({ queryKey: ["blog-posts"] })
            void qc.invalidateQueries({ queryKey: ["blog-config"] })
          }}
        />
      )}
    </div>
  )
}
