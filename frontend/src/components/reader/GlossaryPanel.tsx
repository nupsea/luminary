import { Loader2, RefreshCw, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

interface GlossaryTerm {
  id: string
  term: string
  definition: string
  first_mention_section_id: string | null
  category: string | null
  created_at: string | null
  updated_at: string | null
}

const CATEGORY_COLORS: Record<string, string> = {
  character: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  place: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  concept: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  technical: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  event: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  general: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
}

type GlossarySortKey = "term" | "category"

interface GlossaryPanelProps {
  documentId: string
  onScrollToSection?: (sectionId: string) => void
}

export function GlossaryPanel({ documentId, onScrollToSection }: GlossaryPanelProps) {
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [filter, setFilter] = useState("")
  const [sortKey, setSortKey] = useState<GlossarySortKey>("term")
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    async function fetchCached() {
      try {
        const res = await fetch(`${API_BASE}/explain/glossary/${documentId}/cached`)
        if (res.ok) {
          const data = (await res.json()) as GlossaryTerm[]
          if (!cancelled) setTerms(data.length > 0 ? data : null)
        }
      } catch {
        // ignore fetch error on initial load
      } finally {
        if (!cancelled) setInitialLoading(false)
      }
    }
    void fetchCached()
    return () => { cancelled = true }
  }, [documentId])

  async function generateGlossary() {
    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_BASE}/explain/glossary/${documentId}`, { method: "POST" })
      if (res.ok) {
        const data = (await res.json()) as GlossaryTerm[]
        setTerms(data)
      } else {
        const body = await res.json().catch(() => ({ detail: "Unknown error" })) as { detail?: string }
        if (res.status === 503) {
          setError("Ollama unavailable -- start it to generate glossary")
        } else if (res.status === 422) {
          setError(body.detail ?? "Glossary generation failed -- try again")
        } else {
          setError(body.detail ?? `Error ${res.status}`)
        }
      }
    } catch {
      setError("Network error -- check your connection")
    } finally {
      setLoading(false)
    }
  }

  async function deleteTerm(termId: string) {
    try {
      const res = await fetch(`${API_BASE}/explain/glossary/${documentId}/terms/${termId}`, { method: "DELETE" })
      if (res.ok || res.status === 204) {
        setTerms((prev) => prev ? prev.filter((t) => t.id !== termId) : prev)
      }
    } catch {
      // ignore
    }
  }

  const filterLower = filter.toLowerCase()
  const filtered = (terms ?? [])
    .filter((t) =>
      t.term.toLowerCase().includes(filterLower) ||
      t.definition.toLowerCase().includes(filterLower),
    )
    .sort((a, b) => {
      if (sortKey === "category") {
        return (a.category ?? "general").localeCompare(b.category ?? "general") || a.term.localeCompare(b.term)
      }
      return a.term.localeCompare(b.term)
    })

  if (initialLoading) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    )
  }

  const hasTerms = terms !== null && terms.length > 0

  if (!hasTerms) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Extract domain-specific terms from this document.
        </p>
        <button
          onClick={() => void generateGlossary()}
          disabled={loading}
          className="flex items-center gap-1.5 self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? "Extracting..." : "Generate Glossary"}
        </button>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search terms and definitions..."
          className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          onClick={() => void generateGlossary()}
          disabled={loading}
          title="Regenerate glossary"
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Regenerate
        </button>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Sort:</span>
        <button
          onClick={() => setSortKey("term")}
          className={cn("px-1.5 py-0.5 rounded", sortKey === "term" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
        >
          Term
        </button>
        <button
          onClick={() => setSortKey("category")}
          className={cn("px-1.5 py-0.5 rounded", sortKey === "category" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
        >
          Category
        </button>
      </div>
      {error && <p className="text-sm text-red-500">{error}</p>}
      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filter ? "No matching terms." : "No terms extracted."}
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-1.5 pr-3 font-medium">Term</th>
              <th className="pb-1.5 pr-3 font-medium">Definition</th>
              <th className="pb-1.5 pr-3 font-medium">Category</th>
              <th className="pb-1.5 font-medium">Section</th>
              <th className="pb-1.5 w-6"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.map((t) => (
              <tr key={t.id}>
                <td className="py-1.5 pr-3 font-medium text-foreground align-top">{t.term}</td>
                <td className="py-1.5 pr-3 text-foreground/80 align-top">{t.definition}</td>
                <td className="py-1.5 pr-3 align-top">
                  {t.category && (
                    <span className={cn("inline-block rounded px-1.5 py-0.5 text-[10px] font-medium", CATEGORY_COLORS[t.category] ?? CATEGORY_COLORS.general)}>
                      {t.category}
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-1 align-top">
                  {t.first_mention_section_id && onScrollToSection ? (
                    <button
                      onClick={() => onScrollToSection(t.first_mention_section_id!)}
                      className="text-primary hover:underline text-[10px]"
                    >
                      Go
                    </button>
                  ) : (
                    <span className="text-muted-foreground">--</span>
                  )}
                </td>
                <td className="py-1.5 align-top">
                  <button
                    onClick={() => void deleteTerm(t.id)}
                    className="text-muted-foreground hover:text-red-500 transition-colors sm:opacity-0 sm:group-hover:opacity-100"
                    title="Remove term"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
