/**
 * PushBlogButton — push the site repo's local commits to origin from within
 * Luminary. Outward-facing, so it shows the pending-commit count and requires a
 * confirm. Push uses the repo's existing git/SSH auth; no secrets are handled.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, UploadCloud } from "lucide-react"
import { toast } from "sonner"

import { ApiError } from "@/lib/apiClient"
import { getBlogConfig, pushBlog } from "@/lib/blogApi"

function pushError(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.body) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      /* non-JSON */
    }
  }
  return err instanceof Error ? err.message : "Push failed"
}

export function PushBlogButton({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const { data: config } = useQuery({
    queryKey: ["blog-config"],
    queryFn: getBlogConfig,
    staleTime: 5_000,
  })

  const mut = useMutation({
    mutationFn: pushBlog,
    onSuccess: (res) => {
      setConfirming(false)
      toast.success(`Pushed to origin/${res.branch}`, { description: res.output.slice(0, 200) })
      void qc.invalidateQueries({ queryKey: ["blog-config"] })
    },
    onError: (err) => toast.error(pushError(err)),
  })

  const ahead = config?.ahead
  const branch = config?.branch ?? "master"
  const nothingToPush = ahead === 0

  if (confirming) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">
          Push {ahead ?? ""} commit{ahead === 1 ? "" : "s"} to origin/{branch}?
        </span>
        <button
          onClick={() => mut.mutate()}
          disabled={mut.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UploadCloud className="h-3.5 w-3.5" />}
          Push
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="rounded-md border border-input px-3 py-1.5 hover:bg-accent"
        >
          Cancel
        </button>
      </div>
    )
  }

  const label =
    ahead == null ? "Push to GitHub" : nothingToPush ? "Up to date" : `Push ${ahead} commit${ahead === 1 ? "" : "s"}`

  return (
    <button
      onClick={() => setConfirming(true)}
      disabled={nothingToPush}
      title={nothingToPush ? "Nothing to push" : `Push local commits to origin/${branch}`}
      className={
        compact
          ? "inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
          : "inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      }
    >
      {nothingToPush ? <Check className="h-4 w-4" /> : <UploadCloud className="h-4 w-4" />}
      {label}
    </button>
  )
}
