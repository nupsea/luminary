import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { apiPost, detailFromError } from "@/lib/apiClient"
import { fixResultMessage, type TranscriptFixResult } from "@/lib/transcriptVocabulary"

interface TranscriptFixFormProps {
  documentId: string
  initialHeard: string
  onClose: () => void
}

/** Replace a misheard term throughout this transcript, and optionally remember it. */
export function TranscriptFixForm({ documentId, initialHeard, onClose }: TranscriptFixFormProps) {
  const queryClient = useQueryClient()
  const [heard, setHeard] = useState(initialHeard)
  const [term, setTerm] = useState("")
  const [remember, setRemember] = useState(true)

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<TranscriptFixResult>(`/documents/${documentId}/transcript/corrections`, {
        heard,
        term,
        remember,
      }).catch((err: unknown) => {
        throw detailFromError(err, "Could not correct the transcript")
      }),
    onSuccess: (result) => {
      const message = fixResultMessage(heard.trim(), term.trim(), result)
      if (result.occurrences === 0) {
        toast.info(message)
        return
      }
      toast.success(message)
      void queryClient.invalidateQueries({ queryKey: ["document-chunks", documentId] })
      void queryClient.invalidateQueries({ queryKey: ["document", documentId] })
      void queryClient.invalidateQueries({ queryKey: ["transcript-vocabulary"] })
      onClose()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const ready = heard.trim() !== "" && term.trim() !== "" && heard.trim() !== term.trim()

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) mutation.mutate()
      }}
      className="mt-3 flex flex-wrap items-end gap-2 rounded-md border border-border bg-background p-3"
    >
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        As transcribed
        <input
          value={heard}
          onChange={(e) => setHeard(e.target.value)}
          placeholder="LANs-dv"
          className="w-40 rounded border border-border bg-background px-2 py-1 text-sm text-foreground"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Should be
        <input
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="LanceDB"
          autoFocus={initialHeard !== ""}
          className="w-40 rounded border border-border bg-background px-2 py-1 text-sm text-foreground"
        />
      </label>
      <label className="flex items-center gap-1.5 pb-1.5 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
          className="h-3.5 w-3.5 accent-primary"
        />
        Remember for future imports
      </label>
      <div className="ml-auto flex gap-2 pb-0.5">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border px-2.5 py-1 text-xs text-foreground hover:bg-accent"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!ready || mutation.isPending}
          className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {mutation.isPending ? "Replacing…" : "Replace everywhere"}
        </button>
      </div>
    </form>
  )
}
