import { useQuery } from "@tanstack/react-query"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { apiGet } from "@/lib/apiClient"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import type { AnnotationItem, SectionContentItem } from "./types"

const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "bg-yellow-200/60 dark:bg-yellow-500/30",
  green: "bg-green-200/60 dark:bg-green-500/30",
  blue: "bg-blue-200/60 dark:bg-blue-500/30",
  pink: "bg-pink-200/60 dark:bg-pink-500/30",
}

// Memoized individual section item in TOC to prevent full list re-renders on scroll
const TocItem = memo(({
  section,
  isActive,
  onClick
}: {
  section: SectionContentItem;
  isActive: boolean;
  onClick: (id: string) => void
}) => {
  return (
    <li key={section.section_id}>
      <button
        className={cn(
          "w-full text-left text-xs px-2 py-1 rounded hover:bg-accent truncate transition-colors",
          isActive ? "bg-accent text-foreground font-medium" : "text-muted-foreground"
        )}
        style={{ paddingLeft: `${(section.level - 1) * 8 + 8}px` }}
        onClick={() => onClick(section.section_id)}
        title={section.heading}
      >
        {section.heading || "(Untitled)"}
      </button>
    </li>
  )
})
TocItem.displayName = "TocItem"

interface LazySectionProps {
  section: SectionContentItem
  annotations: AnnotationItem[]
  highlightsVisible: boolean
}

const HeadingTag = (level: number) => {
  if (level <= 1) return "h2"
  if (level === 2) return "h3"
  if (level === 3) return "h4"
  return "h5"
}

// LazySection renders heavy Markdown content only when it is near the viewport.
// This allows 'bulky' books with 1000s of sections to load instantly and stay responsive.
const LazySection = memo(({ section, annotations, highlightsVisible }: LazySectionProps) => {
  const [isVisible, setIsVisible] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: "600px" } // Load early before user scrolls to it
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const Tag = HeadingTag(section.level)
  const highlighted = useMemo(() => {
    if (!isVisible) return "" // defer processing
    return applyHighlights(section.content, highlightsVisible ? annotations : [])
  }, [isVisible, section.content, annotations, highlightsVisible])

  return (
    <div
      ref={containerRef}
      id={`read-sec-${section.section_id}`}
      data-section-id={section.section_id}
      className="mb-10 pb-8 border-b border-border last:border-b-0 min-h-[100px]"
    >
      <Tag className="mb-3 font-semibold text-foreground text-xl">
        {section.heading || "(Untitled section)"}
      </Tag>
      {isVisible ? (
        <div className="leading-relaxed anim-fade-in">
          <MarkdownRenderer>{highlighted}</MarkdownRenderer>
        </div>
      ) : (
        <div className="space-y-2 py-4">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-[90%]" />
          <Skeleton className="h-4 w-[95%]" />
        </div>
      )}
    </div>
  )
})
LazySection.displayName = "LazySection"

const fetchSectionContent = (documentId: string): Promise<SectionContentItem[]> =>
  apiGet<SectionContentItem[]>(`/sections/${documentId}/content`)

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

  // Sort annotations by start_offset to process them in reading order.
  const sorted = [...annotations].sort((a, b) => a.start_offset - b.start_offset)

  // Find all occurrences, handle duplicates via simple incremental search
  const marks: { start: number; end: number; color: string }[] = []
  const usedStarts = new Set<number>()

  for (const ann of sorted) {
    // Strategy 1: Trust the offsets if they are non-zero and point to the right text
    if (ann.start_offset > 0 || ann.end_offset > 0) {
      const slice = content.slice(ann.start_offset, ann.end_offset)
      if (normalizeWs(slice) === normalizeWs(ann.selected_text)) {
        marks.push({ start: ann.start_offset, end: ann.end_offset, color: ann.color })
        usedStarts.add(ann.start_offset)
        continue
      }
    }

    // Strategy 2: Incremental fuzzy search (find the next occurrence if multiple "the" exist)
    let searchPos = 0
    let bestMatch: [number, number] | null = null

    while (searchPos < content.length) {
      const match = fuzzyIndexOf(content.slice(searchPos), ann.selected_text)
      if (!match) break
      const startInContent = searchPos + match[0]
      if (!usedStarts.has(startInContent)) {
        bestMatch = [startInContent, match[1]]
        break
      }
      searchPos = startInContent + 1
    }

    if (bestMatch) {
      marks.push({ start: bestMatch[0], end: bestMatch[0] + bestMatch[1], color: ann.color })
      usedStarts.add(bestMatch[0])
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
  const [listLimit, setListLimit] = useState(200)

  const { data: sections, isLoading, error } = useQuery({
    queryKey: ["section-content", documentId],
    queryFn: () => fetchSectionContent(documentId),
    staleTime: 60_000,
  })

  // Pre-group annotations by section_id to avoid O(N*M) lookups in render loops
  const annotationsBySection = useMemo(() => {
    const map = new Map<string, AnnotationItem[]>()
    for (const ann of annotations) {
      const list = map.get(ann.section_id) || []
      list.push(ann)
      map.set(ann.section_id, list)
    }
    return map
  }, [annotations])

  // Scroll to initial section
  useEffect(() => {
    if (!initialSectionId || !sections) return
    const timer = setTimeout(() => {
      const el = document.getElementById(`read-sec-${initialSectionId}`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    }, 200) // Slightly longer to ensure layout calculation is done
    return () => clearTimeout(timer)
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

  return (
    <div className="flex h-full">
      {/* TOC sidebar */}
      <div className="w-56 flex-shrink-0 border-r overflow-y-auto p-2 scrollbar-thin">
        <p className="text-xs font-semibold uppercase text-muted-foreground mb-3 px-2 tracking-wider">
          Contents
        </p>
        <ul className="space-y-0.5">
          {sections.slice(0, listLimit).map((sec) => (
            <TocItem
              key={sec.section_id}
              section={sec}
              isActive={activeSection === sec.section_id}
              onClick={scrollToSection}
            />
          ))}
          {sections.length > listLimit && (
            <li className="mt-2 text-center text-[10px] text-muted-foreground italic">
              (TOC truncated)
            </li>
          )}
        </ul>
      </div>

      {/* Reading content */}
      <div ref={contentRef} className="flex-1 overflow-auto px-8 py-6 scroll-smooth">
        <div className="max-w-3xl mx-auto">
          {sections.slice(0, listLimit).map((section) => (
            <LazySection
              key={section.section_id}
              section={section}
              annotations={annotationsBySection.get(section.section_id) || []}
              highlightsVisible={highlightsVisible}
            />
          ))}
          
          {sections.length > listLimit && (
            <div className="mt-12 mb-20 flex justify-center">
              <button
                onClick={() => setListLimit(prev => prev + 500)}
                className="flex items-center gap-2 rounded-md border border-border bg-background px-6 py-2 text-sm font-medium text-foreground hover:bg-muted transition-colors shadow-sm"
              >
                <Loader2 size={14} className="animate-spin text-muted-foreground" />
                Load next 500 sections
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
