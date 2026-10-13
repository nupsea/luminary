import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { apiGet, apiPut } from "@/lib/apiClient"
import { parseTerms } from "@/lib/transcriptVocabulary"

interface TranscriptVocabulary {
  terms: string[]
}

const QUERY_KEY = ["transcript-vocabulary"]

export function TranscriptVocabularySettings() {
  const queryClient = useQueryClient()
  // null = untouched; the stored list shows until the learner edits it.
  const [draft, setDraft] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiGet<TranscriptVocabulary>("/settings/transcript-vocabulary"),
    staleTime: 60_000,
  })
  const mutation = useMutation({
    mutationFn: (terms: string[]) =>
      apiPut<TranscriptVocabulary>("/settings/transcript-vocabulary", { terms }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(QUERY_KEY, fresh)
      setDraft(null)
      toast.success("Vocabulary saved")
    },
    onError: () => toast.error("Could not save the vocabulary"),
  })

  const stored = data?.terms ?? []
  const text = draft ?? stored.join("\n")
  const changed = draft !== null && parseTerms(draft).join("\n") !== stored.join("\n")

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground">Transcript vocabulary</h3>
      <p className="text-xs text-muted-foreground">
        Names and terms speech recognition gets wrong, one per line ("LanceDB", "Kimi K3").
        Every audio or video import is checked against them. Fixing a term in a transcript adds it
        here.
      </p>
      {isLoading && <div className="h-24 animate-pulse rounded-md bg-muted" />}
      {error && <p className="text-xs text-destructive">Could not load the vocabulary.</p>}
      {!isLoading && !error && (
        <>
          <textarea
            value={text}
            onChange={(e) => setDraft(e.target.value)}
            rows={5}
            placeholder="No terms yet"
            aria-label="Transcript vocabulary, one term per line"
            className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {stored.length === 0 ? "No terms yet" : `${stored.length} saved`}
            </span>
            <button
              onClick={() => draft !== null && mutation.mutate(parseTerms(draft))}
              disabled={!changed || mutation.isPending}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </>
      )}
    </section>
  )
}
