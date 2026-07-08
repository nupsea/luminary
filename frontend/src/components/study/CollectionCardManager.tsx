// Card management for a collection: view, edit, and delete the flashcards
// generated across a collection's documents and notes -- the collection
// counterpart to the per-document FlashcardManager. Self-contained so the
// CollectionStudyDashboard just drops it in.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, Layers, Loader2 } from "lucide-react"
import { toast } from "sonner"

import {
  bulkDeleteFlashcards,
  deleteAllFlashcardsForCollection,
  deleteFlashcard,
  fetchFlashcardSearch,
  updateFlashcard,
} from "@/pages/Study/api"
import type { FlashcardSearchResponse } from "@/pages/Study/types"
import { FlashcardCard } from "@/pages/Study/FlashcardCard"
import { endOpenSessionsForScope } from "@/lib/studySessionService"

const PAGE_SIZE = 20

export function CollectionCardManager({ collectionId }: { collectionId: string }) {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState<null | "selected" | "all">(null)

  const { data, isLoading, isError } = useQuery<FlashcardSearchResponse>({
    queryKey: ["collection-cards", collectionId, page],
    queryFn: () =>
      fetchFlashcardSearch({ collection_id: collectionId, page, page_size: PAGE_SIZE }),
  })

  const cards = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["collection-cards", collectionId] })
    qc.invalidateQueries({ queryKey: ["collection-dashboard", collectionId] })
  }

  const clearSelection = () => setSelectedIds(new Set())
  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const updateMutation = useMutation({
    mutationFn: (a: { id: string; data: { question?: string; answer?: string } }) =>
      updateFlashcard(a.id, a.data),
    onSuccess: invalidate,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteFlashcard,
    onSuccess: invalidate,
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: bulkDeleteFlashcards,
    onSuccess: (res) => {
      invalidate()
      clearSelection()
      setSelectionMode(false)
      setConfirmDelete(null)
      toast.success(`Deleted ${res.deleted} card${res.deleted === 1 ? "" : "s"}`)
    },
    onError: () => toast.error("Failed to delete selected cards"),
  })

  const deleteAllMutation = useMutation({
    mutationFn: async () => {
      const res = await deleteAllFlashcardsForCollection(collectionId)
      // Drop any in-progress session so it can't resume with deleted cards.
      await endOpenSessionsForScope(null, collectionId)
      return res
    },
    onSuccess: (res) => {
      invalidate()
      clearSelection()
      setSelectionMode(false)
      setConfirmDelete(null)
      setPage(1)
      toast.success(`Deleted ${res.deleted} card${res.deleted === 1 ? "" : "s"} from this collection`)
    },
    onError: () => toast.error("Failed to delete collection cards"),
  })

  const deleting = bulkDeleteMutation.isPending || deleteAllMutation.isPending

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-semibold text-foreground">
          <Layers size={18} className="text-primary" />
          Manage cards
          <span className="text-xs font-normal text-muted-foreground">
            {total} card{total === 1 ? "" : "s"} in this collection
          </span>
        </h3>
      </div>

      {/* Selection + delete toolbar (parity with the per-document manager) */}
      {total > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-muted/30 px-4 py-2 text-sm">
          {!selectionMode ? (
            <button
              onClick={() => setSelectionMode(true)}
              className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              Select cards
            </button>
          ) : (
            <>
              <span className="text-xs font-medium text-muted-foreground">
                {selectedIds.size} selected
              </span>
              <button
                onClick={() => setSelectedIds(new Set(cards.map((c) => c.id)))}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Select all on page
              </button>
              <button
                onClick={clearSelection}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Clear
              </button>
              <button
                onClick={() => setConfirmDelete("selected")}
                disabled={selectedIds.size === 0 || deleting}
                className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                Delete selected ({selectedIds.size})
              </button>
              <button
                onClick={() => {
                  setSelectionMode(false)
                  clearSelection()
                }}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Done
              </button>
            </>
          )}
          <button
            onClick={() => setConfirmDelete("all")}
            disabled={deleting}
            className="ml-auto rounded border border-red-300 bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
          >
            Delete all ({total})
          </button>
        </div>
      )}

      {/* Confirmation banner -- destructive, so it always asks first */}
      {confirmDelete && (
        <div className="flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
          <AlertCircle size={16} />
          <span className="flex-1">
            {confirmDelete === "selected"
              ? `Permanently delete ${selectedIds.size} selected card${selectedIds.size === 1 ? "" : "s"}? This cannot be undone.`
              : `Permanently delete ALL ${total} cards in this collection? This cannot be undone.`}
          </span>
          <button
            onClick={() =>
              confirmDelete === "selected"
                ? bulkDeleteMutation.mutate(Array.from(selectedIds))
                : deleteAllMutation.mutate()
            }
            disabled={deleting}
            className="flex items-center gap-1 rounded bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleting && <Loader2 size={12} className="animate-spin" />}
            Confirm delete
          </button>
          <button
            onClick={() => setConfirmDelete(null)}
            className="rounded border border-red-300 px-3 py-1 text-xs font-medium hover:bg-red-100 dark:hover:bg-red-900/40"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Card grid with loading / error / empty states (I-10) */}
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : isError ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
          Could not load this collection's cards.
        </div>
      ) : cards.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card/20 py-12 text-center">
          <Layers size={28} className="text-muted-foreground opacity-30" />
          <p className="text-sm text-muted-foreground">
            No cards yet. Use the generator to create some for this collection.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {cards.map((c) => (
            <FlashcardCard
              key={c.id}
              card={c}
              onUpdate={(id, d) => updateMutation.mutate({ id, data: d })}
              onDelete={(id) => deleteMutation.mutate(id)}
              isUpdating={updateMutation.isPending}
              isDeleting={deleteMutation.isPending}
              selectionMode={selectionMode}
              selected={selectedIds.has(c.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-2 flex justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded-full bg-secondary px-3 py-1 text-xs font-bold uppercase text-primary hover:bg-secondary/80 disabled:opacity-40"
          >
            Prev
          </button>
          <span className="flex items-center text-xs font-bold">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="rounded-full bg-secondary px-3 py-1 text-xs font-bold uppercase text-primary hover:bg-secondary/80 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
