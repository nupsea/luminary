// Sortable library table view (alternative to the card grid). Sort state
// is local; the parent owns row-click navigation.

import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { STATUS_LABELS, STATUS_VARIANTS, formatDate } from "@/components/library/utils"
import type { DocumentListItem } from "@/components/library/types"

type TableSortCol = "title" | "created_at"

interface LibraryTableProps {
  items: DocumentListItem[]
  isLoading: boolean
  isError: boolean
  onRowClick: (id: string) => void
  onRetry: () => void
}

export function LibraryTable({ items, isLoading, isError, onRowClick, onRetry }: LibraryTableProps) {
  const [sortCol, setSortCol] = useState<TableSortCol | null>(null)
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")

  function handleColClick(col: TableSortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortCol(col)
      setSortDir("asc")
    }
  }

  function SortIcon({ col }: { col: TableSortCol }) {
    if (sortCol !== col) return <ChevronsUpDown size={12} className="ml-1 inline text-muted-foreground/50" />
    return sortDir === "asc"
      ? <ChevronUp size={12} className="ml-1 inline text-foreground" />
      : <ChevronDown size={12} className="ml-1 inline text-foreground" />
  }

  const sorted = [...items].sort((a, b) => {
    if (!sortCol) return 0
    const dir = sortDir === "asc" ? 1 : -1
    if (sortCol === "title") return a.title.localeCompare(b.title) * dir
    return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir
  })

  if (isError) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span className="flex-1">Could not load library. Check that the backend is running.</span>
        <button
          onClick={onRetry}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <button
              onClick={() => handleColClick("title")}
              className="flex items-center text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Title
              <SortIcon col="title" />
            </button>
          </TableHead>
          <TableHead>Content Type</TableHead>
          <TableHead>Format</TableHead>
          <TableHead>
            <button
              onClick={() => handleColClick("created_at")}
              className="flex items-center text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Ingested At
              <SortIcon col="created_at" />
            </button>
          </TableHead>
          <TableHead className="text-right">Chunks</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading
          ? Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell><Skeleton className="h-4 w-48" /></TableCell>
                <TableCell><Skeleton className="h-4 w-20" /></TableCell>
                <TableCell><Skeleton className="h-4 w-12" /></TableCell>
                <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                <TableCell><Skeleton className="h-4 w-10" /></TableCell>
                <TableCell><Skeleton className="h-4 w-20" /></TableCell>
              </TableRow>
            ))
          : sorted.length === 0
          ? (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No documents yet. Upload your first document to get started.
                </TableCell>
              </TableRow>
            )
          : sorted.map((doc) => (
              <TableRow
                key={doc.id}
                className="cursor-pointer"
                onClick={() => onRowClick(doc.id)}
              >
                <TableCell className="font-medium text-foreground">
                  {doc.title}
                </TableCell>
                <TableCell>
                  <Badge variant="gray" className="capitalize">
                    {doc.content_type}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground capitalize">
                  {doc.format}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatDate(doc.created_at)}
                </TableCell>
                <TableCell className="text-right text-xs text-muted-foreground">
                  {doc.chunk_count}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
                    {STATUS_LABELS[doc.learning_status]}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
      </TableBody>
    </Table>
  )
}
