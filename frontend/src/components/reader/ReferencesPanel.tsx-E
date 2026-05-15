/**
 * ReferencesPanel -- S138 + S194
 *
 * Shows web references for a document, grouped into three tiers:
 *  1. Verified (is_valid=true) -- green check badge
 *  2. Unchecked (is_valid=null) -- amber spinner during validation
 *  3. Unavailable (is_valid=false) -- collapsed accordion, strikethrough, not clickable
 *
 * Auto-triggers validation on mount if any refs have is_valid=null.
 */

import { useState, useEffect } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { ExternalLink, RefreshCw, CheckCircle2, AlertCircle, Loader2 } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"

import { apiGet, apiPost } from "@/lib/apiClient"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Local types: the generated WebReferenceItem types `source_quality`
// as plain `string` (loosened from the backend's literal), and
// `is_valid` / `last_checked_at` as `?: T | null | undefined` rather
// than `: T | null`. Both differences cascade into the UI's typed
// badge map and panel state, so we keep the narrower local shape.
// (audit #15: kept-local entry.)

type SourceQuality = "official_docs" | "spec" | "wiki" | "tutorial" | "blog" | "unknown"

interface WebReferenceItem {
  id: string
  section_id: string | null
  term: string
  url: string
  title: string
  excerpt: string
  source_quality: SourceQuality
  is_llm_suggested: boolean
  is_valid: boolean | null
  last_checked_at: string | null
  created_at: string
  is_outdated: boolean
}

interface DocumentReferencesResponse {
  document_id: string
  references: WebReferenceItem[]
}

// ---------------------------------------------------------------------------
// Quality badge helpers
// ---------------------------------------------------------------------------

const QUALITY_LABEL: Record<SourceQuality, string> = {
  official_docs: "Official",
  spec: "Spec",
  wiki: "Wiki",
  tutorial: "Tutorial",
  blog: "Blog",
  unknown: "Unknown",
}

const QUALITY_CLASS: Record<SourceQuality, string> = {
  official_docs: "bg-green-100 text-green-800",
  spec: "bg-blue-100 text-blue-800",
  wiki: "bg-gray-100 text-gray-800",
  tutorial: "bg-gray-100 text-gray-700",
  blog: "bg-gray-100 text-gray-600",
  unknown: "bg-gray-100 text-gray-500",
}

function QualityBadge({ quality }: { quality: SourceQuality }) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${QUALITY_CLASS[quality]}`}
    >
      {QUALITY_LABEL[quality]}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Validation status badge
// ---------------------------------------------------------------------------

function ValidationBadge({ isValid, isValidating }: { isValid: boolean | null; isValidating: boolean }) {
  if (isValid === true) {
    return (
      <span className="flex items-center gap-0.5 rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
        <CheckCircle2 size={9} />
        Verified
      </span>
    )
  }
  if (isValid === null) {
    return (
      <span className="flex items-center gap-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
        {isValidating ? <Loader2 size={9} className="animate-spin" /> : <AlertCircle size={9} />}
        {isValidating ? "Checking..." : "Unverified"}
      </span>
    )
  }
  // is_valid === false -- shown in unavailable section, no badge needed inline
  return null
}

// ---------------------------------------------------------------------------
// Single reference row
// ---------------------------------------------------------------------------

function ReferenceRow({
  ref: item,
  documentId,
  isValidating,
  unavailable,
}: {
  ref: WebReferenceItem
  documentId: string
  isValidating: boolean
  unavailable?: boolean
}) {
  const queryClient = useQueryClient()

  async function handleRefresh() {
    if (!item.section_id) return
    try {
      await apiPost(
        `/references/sections/${item.section_id}/refresh?document_id=${documentId}`,
      )
      void queryClient.invalidateQueries({ queryKey: ["doc-references", documentId] })
    } catch {
      // non-fatal
    }
  }

  return (
    <div className={`group flex flex-col gap-0.5 rounded-md border border-border p-2 text-xs ${unavailable ? "opacity-60" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        {unavailable ? (
          <span className="flex min-w-0 items-center gap-1 font-medium text-muted-foreground line-through">
            <ExternalLink size={11} className="shrink-0" />
            <span className="truncate">{item.title}</span>
          </span>
        ) : (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-w-0 items-center gap-1 font-medium text-primary hover:underline"
          >
            <ExternalLink size={11} className="shrink-0" />
            <span className="truncate">{item.title}</span>
          </a>
        )}
        <div className="flex shrink-0 items-center gap-1">
          <QualityBadge quality={item.source_quality} />
          <ValidationBadge isValid={item.is_valid} isValidating={isValidating} />
          {item.is_outdated && !unavailable && (
            <button
              onClick={() => void handleRefresh()}
              title="Re-run extraction for this section"
              className="flex items-center gap-0.5 rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700 hover:bg-orange-200"
            >
              <RefreshCw size={9} />
              Outdated?
            </button>
          )}
        </div>
      </div>
      {item.term && (
        <span className="text-[11px] text-muted-foreground">
          Term: <span className="font-medium">{item.term}</span>
        </span>
      )}
      {item.excerpt && !unavailable && (
        <p className="text-[11px] text-muted-foreground line-clamp-2">{item.excerpt}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface ReferencesPanelProps {
  documentId: string
}

export function ReferencesPanel({ documentId }: ReferencesPanelProps) {
  const queryClient = useQueryClient()
  const [unavailableOpen, setUnavailableOpen] = useState(false)

  // Fetch all refs including invalid
  const { data, isLoading, isError } = useQuery<DocumentReferencesResponse>({
    queryKey: ["doc-references", documentId],
    queryFn: () =>
      apiGet<DocumentReferencesResponse>(
        `/references/documents/${documentId}?include_invalid=true`,
      ),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  // Validation mutation
  const validateMutation = useMutation({
    mutationFn: () =>
      apiPost(`/references/documents/${documentId}/validate`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["doc-references", documentId] })
    },
  })

  // Refresh mutation (re-extract + validate)
  const refreshMutation = useMutation({
    mutationFn: () =>
      apiPost(`/references/documents/${documentId}/refresh`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["doc-references", documentId] })
    },
  })

  // Auto-trigger validation on mount if any refs have is_valid=null
  const references = data?.references ?? []
  const hasUnchecked = references.some((r) => r.is_valid === null)

  useEffect(() => {
    if (hasUnchecked && !validateMutation.isPending) {
      validateMutation.mutate()
    }
    // Only trigger once on mount when unchecked refs are detected
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUnchecked])

  const isValidating = validateMutation.isPending

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 p-1">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-1">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ))}
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        References unavailable. Please try again later.
      </div>
    )
  }

  // Empty state
  if (references.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No references generated yet. References are extracted automatically after ingestion
        completes for technical documents.
      </p>
    )
  }

  // Split into tiers
  const verified = references.filter((r) => r.is_valid === true)
  const unchecked = references.filter((r) => r.is_valid === null)
  const unavailable = references.filter((r) => r.is_valid === false)

  return (
    <div className="flex flex-col gap-4">
      {/* Refresh button */}
      <div className="flex items-center justify-end">
        <button
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
        >
          <RefreshCw size={11} className={refreshMutation.isPending ? "animate-spin" : ""} />
          Refresh references
        </button>
      </div>

      {/* Verified tier */}
      {verified.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-green-700">
            <CheckCircle2 size={11} />
            Verified ({verified.length})
          </h4>
          {verified.map((ref) => (
            <ReferenceRow key={ref.id} ref={ref} documentId={documentId} isValidating={false} />
          ))}
        </div>
      )}

      {/* Unchecked tier */}
      {unchecked.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-amber-700">
            {isValidating ? <Loader2 size={11} className="animate-spin" /> : <AlertCircle size={11} />}
            {isValidating ? `Checking (${unchecked.length})` : `Unverified (${unchecked.length})`}
          </h4>
          {unchecked.map((ref) => (
            <ReferenceRow key={ref.id} ref={ref} documentId={documentId} isValidating={isValidating} />
          ))}
        </div>
      )}

      {/* Unavailable tier (collapsed accordion) */}
      {unavailable.length > 0 && (
        <div className="flex flex-col gap-2">
          <button
            onClick={() => setUnavailableOpen((o) => !o)}
            className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
          >
            <span className={`transition-transform ${unavailableOpen ? "rotate-90" : ""}`}>
              &#9654;
            </span>
            Unavailable ({unavailable.length})
          </button>
          {unavailableOpen &&
            unavailable.map((ref) => (
              <ReferenceRow
                key={ref.id}
                ref={ref}
                documentId={documentId}
                isValidating={false}
                unavailable
              />
            ))}
        </div>
      )}

      {/* Validation/refresh error */}
      {(validateMutation.isError || refreshMutation.isError) && (
        <p className="text-xs text-red-500">
          {validateMutation.isError ? "Validation failed." : "Refresh failed."} Please try again.
        </p>
      )}
    </div>
  )
}
