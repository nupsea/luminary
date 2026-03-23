import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { API_BASE } from "@/lib/config"
import type { AnnotationItem, SectionContentItem } from "./types"

const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "bg-yellow-200/60 dark:bg-yellow-500/30",
  green: "bg-green-200/60 dark:bg-green-500/30",
  blue: "bg-blue-200/60 dark:bg-blue-500/30",
  pink: "bg-pink-200/60 dark:bg-pink-500/30",
}

async function fetchSectionContent(documentId: string): Promise<SectionContentItem[]> {
  const res = await fetch(`${API_BASE}/sections/${documentId}/content`)
  if (!res.ok) throw new Error("Failed to fetch section content")
  return res.json() as Promise<SectionContentItem[]>
}

/** Normalize whitespace for fuzzy matching: collapse runs to single space, trim. */
function normalizeWs(s: string): string {
  return s.replace(/\s+/g, " ").trim()
}

/** Find `needle` in `haystack` with whitespace-normalized fallback.
 *  Returns [startIndex, matchLength] in the original haystack, or null. */
function fuzzyIndexOf(haystack: string, needle: string): [number, number] | null {
  // Exact match first
  const exact = haystack.indexOf(needle)
  if (exact >= 0) return [exact, needle.length]

  // Whitespace-normalized match
  const normNeedle = normalizeWs(needle)
  if (!normNeedle) return null
  const normHaystack = normalizeWs(haystack)
  const normIdx = normHaystack.indexOf(normNeedle)
  if (normIdx < 0) return null

  // Map normalized index back to original haystack position.
  // Walk both strings in parallel, skipping extra whitespace in the original.
  let hi = 0 // position in original haystack
  let ni = 0 // position in normalized haystack
  // Advance to normIdx in normalized space
  while (ni < normIdx && hi < haystack.length) {
    if (/\s/.test(haystack[hi])) {
      hi++
      // consume the single space in normalized
      if (ni < normHaystack.length && normHaystack[ni] === " ") ni++
      // skip remaining whitespace in original
      while (hi < haystack.length && /\s/.test(haystack[hi])) hi++
    } else {
      hi++
      ni++
    }
  }
  const startInOriginal = hi
  // Now advance normNeedle.length chars in normalized space
  let endNi = ni
  while (endNi < ni + normNeedle.length && hi < haystack.length) {
    if (/\s/.test(haystack[hi])) {
      hi++
      if (endNi < normHaystack.length && normHaystack[endNi] === " ") endNi++
      while (hi < haystack.length && /\s/.test(haystack[hi])) hi++
    } else {
      hi++
      endNi++
    }
  }
  return [startInOriginal, hi - startInOriginal]
}

/** Apply highlight marks to plain text by matching annotation selected_text substrings. */
function applyHighlights(content: string, annotations: AnnotationItem[]): string {
  if (annotations.length === 0) return content

  // Find all occurrences, sort by position, merge overlaps
  const marks: { start: number; end: number; color: string }[] = []
  for (const ann of annotations) {
    const match = fuzzyIndexOf(content, ann.selected_text)
    if (match) {
      marks.push({ start: match[0], end: match[0] + match[1], color: ann.color })
    }
  }
  if (marks.length === 0) return content

  marks.sort((a, b) => a.start - b.start)

  // Build result with <mark> tags
  let result = ""
  let cursor = 0
  for (const m of marks) {
    if (m.start < cursor) continue // skip overlapping
    result += content.slice(cursor, m.start)
    const cls = HIGHLIGHT_COLORS[m.color] ?? HIGHLIGHT_COLORS.yellow
    result += `<mark class="${cls} rounded-sm px-0.5">${content.slice(m.start, m.end)}</mark>`
    cursor = m.end
  }
  result += content.slice(cursor)
  return result
}

interface ReadViewProps {
  documentId: string
  initialSectionId?: string | null
  annotations?: AnnotationItem[]
  highlightsVisible?: boolean
}

export function ReadView({ documentId, initialSectionId, annotations = [], highlightsVisible = true }: ReadViewProps) {
  const contentRef = useRef<HTMLDivElement>(null)
  const [activeSection, setActiveSection] = useState<string | null>(null)

  const { data: sections, isLoading, error } = useQuery({
    queryKey: ["section-content", documentId],
    queryFn: () => fetchSectionContent(documentId),
  })

  // Scroll to initial section
  useEffect(() => {
    if (!initialSectionId || !sections) return
    const el = document.getElementById(`read-sec-${initialSectionId}`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [initialSectionId, sections])

  // Set initial active section once data loads
  useEffect(() => {
    if (!sections || sections.length === 0) return
    if (!activeSection) {
      setActiveSection(initialSectionId ?? sections[0].section_id)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections])

  // Track which section is visible via IntersectionObserver
  useEffect(() => {
    if (!sections || sections.length === 0) return
    const container = contentRef.current
    if (!container) return

    // Collect all section elements and their top positions for scroll-based tracking
    const sectionEls = Array.from(container.querySelectorAll("[data-section-id]")) as HTMLElement[]
    if (sectionEls.length === 0) return

    function onScroll() {
      const containerOffset = container!.getBoundingClientRect().top
      let current = sectionEls[0]
      for (const el of sectionEls) {
        const elTop = el.getBoundingClientRect().top - containerOffset
        if (elTop <= 40) {
          current = el
        } else {
          break
        }
      }
      const id = current.dataset.sectionId
      if (id) setActiveSection(id)
    }

    container.addEventListener("scroll", onScroll, { passive: true })
    return () => container.removeEventListener("scroll", onScroll)
  }, [sections])

  const scrollToSection = useCallback((sectionId: string) => {
    const el = document.getElementById(`read-sec-${sectionId}`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <p className="px-6 py-4 text-sm text-destructive">
        Failed to load document content.
      </p>
    )
  }

  if (!sections || sections.length === 0) {
    return (
      <p className="px-6 py-4 text-sm text-muted-foreground">
        No content available.
      </p>
    )
  }

  const HeadingTag = (level: number) => {
    if (level <= 1) return "h2"
    if (level === 2) return "h3"
    if (level === 3) return "h4"
    return "h5"
  }

  return (
    <div className="flex h-full">
      {/* TOC sidebar */}
      <div className="w-56 flex-shrink-0 border-r overflow-y-auto p-2">
        <p className="text-xs font-semibold uppercase text-muted-foreground mb-2 px-1">
          Contents
        </p>
        <ul className="space-y-0.5">
          {sections.map((sec) => {
            const isActive = activeSection === sec.section_id
            return (
              <li key={sec.section_id}>
                <button
                  className={`w-full text-left text-xs px-2 py-1 rounded hover:bg-accent truncate ${
                    isActive ? "bg-accent text-foreground font-medium" : "text-muted-foreground"
                  }`}
                  style={{ paddingLeft: `${(sec.level - 1) * 8 + 8}px` }}
                  onClick={() => scrollToSection(sec.section_id)}
                  title={sec.heading}
                >
                  {sec.heading || "(Untitled)"}
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Reading content */}
      <div ref={contentRef} className="flex-1 overflow-auto px-8 py-6">
        <div className="max-w-3xl mx-auto">
          {sections.map((section) => {
            const Tag = HeadingTag(section.level)
            const sectionAnnotations = highlightsVisible ? annotations.filter((a) => a.section_id === section.section_id) : []
            const highlighted = applyHighlights(section.content, sectionAnnotations)
            const hasHighlights = highlighted !== section.content
            return (
              <div
                key={section.section_id}
                id={`read-sec-${section.section_id}`}
                data-section-id={section.section_id}
                className="mb-10 pb-8 border-b border-border last:border-b-0"
              >
                <Tag className="mb-3 font-semibold text-foreground">
                  {section.heading || "(Untitled section)"}
                </Tag>
                {hasHighlights ? (
                  <div
                    className="prose prose-sm dark:prose-invert max-w-none leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: highlighted }}
                  />
                ) : (
                  <div className="leading-relaxed">
                    <MarkdownRenderer>{section.content}</MarkdownRenderer>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
