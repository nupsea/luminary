// Two-phase suggestion pills: instant cached chips first, then LLM refresh in background.

import { useQuery, useQueryClient } from "@tanstack/react-query"

import { fetchCachedSuggestions, fetchSuggestions, markSuggestionAsked } from "./api"
import type { SuggestionsResponse } from "./types"

interface SuggestionPillsProps {
  documentId: string | null
  onSuggest: (text: string) => void
}

export function SuggestionPills({ documentId, onSuggest }: SuggestionPillsProps) {
  const qc = useQueryClient()

  const { data: cached } = useQuery<SuggestionsResponse>({
    queryKey: ["chat-suggestions-cached", documentId],
    queryFn: () => fetchCachedSuggestions(documentId),
    staleTime: 30_000,
  })

  const { data: fresh } = useQuery<SuggestionsResponse>({
    queryKey: ["chat-suggestions", documentId],
    queryFn: async () => {
      const data = await fetchSuggestions(documentId)
      qc.setQueryData(["chat-suggestions-cached", documentId], data)
      return data
    },
    staleTime: 0,
  })

  const data = fresh ?? cached
  const hasSuggestions = data && data.suggestions.length > 0
  const isInitialLoading = !cached && !fresh

  if (isInitialLoading) {
    return (
      <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
      </div>
    )
  }
  if (!hasSuggestions) return null

  return (
    <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
      {data.suggestions.map((s) => (
        <button
          key={s.id || s.text}
          onClick={() => {
            if (s.id) markSuggestionAsked(s.id)
            onSuggest(s.text)
          }}
          className="truncate max-w-[240px] rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs text-primary hover:bg-primary/10 transition-colors"
        >
          {s.text}
        </button>
      ))}
    </div>
  )
}
