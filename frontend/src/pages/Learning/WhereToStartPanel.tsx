// Where to Start panel. Shown only for tech_book / tech_article
// documents; queries /study/start for the prerequisite-ordered concept list.

import { useQuery } from "@tanstack/react-query"
import { MapPin } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

import { fetchStartConcepts } from "./api"

interface WhereToStartPanelProps {
  documentId: string
  contentType: string
}

export function WhereToStartPanel({ documentId, contentType }: WhereToStartPanelProps) {
  const isTechDoc = contentType === "tech_book" || contentType === "tech_article"
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["start-concepts", documentId],
    queryFn: () => fetchStartConcepts(documentId),
    staleTime: 60_000,
    enabled: isTechDoc,
  })

  if (!isTechDoc) return null

  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-card mb-4">
        <p className="text-sm font-semibold px-4 py-2 border-b">Where to Start</p>
        <div className="flex flex-col gap-2 p-4">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 mb-4 text-xs text-amber-800">
        Could not load starting concepts.{" "}
        <button
          onClick={() => void refetch()}
          className="underline hover:no-underline"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data || data.concepts.length === 0) return null

  return (
    <div className="rounded-lg border border-border bg-card mb-4">
      <div className="flex items-center gap-2 px-4 py-2 border-b">
        <MapPin size={14} className="text-muted-foreground" />
        <p className="text-sm font-semibold">Where to Start</p>
      </div>
      <div className="flex flex-col gap-2 p-4">
        {data.concepts.map((c) => (
          <div key={c.concept} className="flex items-center justify-between text-sm">
            <span className="font-medium">{c.concept}</span>
            <span className="text-xs text-muted-foreground">{c.rationale}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
