import { useQuery, useQueryClient } from "@tanstack/react-query"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Loader2, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { apiGet, apiPost } from "@/lib/apiClient"
import { renderPage } from "@/lib/pageRender"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import type { components } from "@/types/api"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"
import { ReaderSettings } from "./ReaderSettings"
import {
  profileSpec,
  readingProfile,
  resolveReadingLayout,
  type ResolvedLayout,
} from "./readingProfile"
import { hasAuthoredHeading, sectionTitle, usableSections } from "./sectionTitle"
import { parseSpeakerTurns, type SpeakerTurn } from "./speakerTurns"
import { useReaderPreferences } from "./useReaderPreferences"
import type { AnnotationItem, SectionContentItem } from "./types"

type DocumentImage = components["schemas"]["ImageItem"]

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
        title={sectionTitle(section)}
      >
        {sectionTitle(section)}
      </button>
    </li>
  )
})
TocItem.displayName = "TocItem"

interface LazySectionProps {
  section: SectionContentItem
  annotations: AnnotationItem[]
  highlightsVisible: boolean
  images?: DocumentImage[]
  spec: ResolvedLayout
  isLast: boolean
}

// Figures live in the images table with a vision-generated description; the
// reader previously rendered only text, so diagrams never appeared at all.
const SectionFigures = memo(({ images }: { images: DocumentImage[] }) => {
  if (images.length === 0) return null
  return (
    <div className="mt-6 space-y-6">
      {images.map((img) => (
        <figure key={img.id} className="rounded-lg border border-border bg-muted/20 p-3">
          <img
            src={`${API_BASE}/images/${img.id}/raw`}
            alt={img.description || "Figure from this document"}
            loading="lazy"
            className="mx-auto max-h-[520px] w-auto max-w-full rounded"
          />
          {img.description && (
            <figcaption className="mt-2 text-xs leading-relaxed text-muted-foreground">
              {img.description}
            </figcaption>
          )}
        </figure>
      ))}
    </div>
  )
})
SectionFigures.displayName = "SectionFigures"

const HeadingTag = (level: number) => {
  if (level <= 1) return "h2"
  if (level === 2) return "h3"
  if (level === 3) return "h4"
  return "h5"
}

// "opener" ignores depth: the heading marks a pause, not a rank.
const HEADING_CLASS: Record<ResolvedLayout["headingStyle"], (level: number) => string> = {
  opener: () => "mb-8 mt-4 text-center text-2xl font-semibold tracking-wide text-foreground",
  hierarchy: (level: number) =>
    cn(
      "mb-3 font-semibold text-foreground",
      level <= 1 ? "text-xl" : level === 2 ? "text-lg" : "text-base",
    ),
}

const SpeakerTurns = memo(({ turns }: { turns: SpeakerTurn[] }) => (
  <div className="space-y-4">
    {turns.map((turn, i) => (
      <div key={i} className="anim-fade-in">
        {turn.speaker && (
          <p className="mb-0.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {turn.speaker}
          </p>
        )}
        <div className="whitespace-pre-line leading-relaxed text-foreground/90">{turn.text}</div>
      </div>
    ))}
  </div>
))
SpeakerTurns.displayName = "SpeakerTurns"

// LazySection renders heavy Markdown content only when it is near the viewport.
// This allows 'bulky' books with 1000s of sections to load instantly and stay responsive.
const LazySection = memo(({ section, annotations, highlightsVisible, images = [], spec, isLast }: LazySectionProps) => {
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
  const showHeading = hasAuthoredHeading(section)
  const highlighted = useMemo(() => {
    if (!isVisible) return "" // defer processing
    return applyHighlights(section.content, highlightsVisible ? annotations : [])
  }, [isVisible, section.content, annotations, highlightsVisible])

  // Highlights are <mark> HTML the turn splitter would show as literal tags.
  const turns = useMemo(() => {
    if (!isVisible || !spec.speakerTurns) return null
    if (highlighted !== section.content) return null
    return parseSpeakerTurns(section.content)
  }, [isVisible, spec.speakerTurns, highlighted, section.content])

  return (
    <div
      ref={containerRef}
      id={`read-sec-${section.section_id}`}
      data-section-id={section.section_id}
      className={cn(
        "min-h-[100px]",
        spec.dividers && !isLast ? "mb-10 border-b border-border pb-8" : "mb-12",
      )}
    >
      {showHeading && (
        <Tag className={HEADING_CLASS[spec.headingStyle](section.level)}>
          {section.heading}
        </Tag>
      )}
      {isVisible ? (
        <div className="leading-relaxed anim-fade-in">
          {turns ? (
            <SpeakerTurns turns={turns} />
          ) : (
            // `prose` sets an absolute font-size, so size must be handed to
            // this element rather than inherited.
            <MarkdownRenderer className={cn(spec.family, "text-[length:var(--reader-size)]")}>
              {highlighted}
            </MarkdownRenderer>
          )}
          <SectionFigures images={images} />
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

const fetchDocumentImages = (documentId: string): Promise<DocumentImage[]> =>
  apiGet<{ items: DocumentImage[] }>(`/documents/${documentId}/images`).then((r) => r.items)

// ImageModel.page is the 0-based pymupdf page index, while SectionModel.page_start
// is 1-based. Without this the figures land a page off, in the wrong section.
const imageDisplayPage = (image: DocumentImage) => image.page + 1

function imagesForSection(
  section: SectionContentItem,
  images: DocumentImage[],
): DocumentImage[] {
  if (!section.page_start) return []
  const end = section.page_end || section.page_start
  return images.filter((img) => {
    const page = imageDisplayPage(img)
    return page >= section.page_start && page <= end
  })
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
  /** Drives the reading profile. Omitted only by callers that have no document
   *  loaded yet, which fall back to the article profile. */
  contentType?: string | null
  structureType?: string | null
  /** What the importer captured and what it could not. Undefined means fidelity
   *  was never measured for this document, which is not the same as clean. */
  extractionReport?: ExtractionReport | null
  /** Needed to re-render the page on a re-import; absent for non-URL sources. */
  sourceUrl?: string | null
}

export function ReadView({
  documentId,
  initialSectionId,
  annotations = [],
  highlightsVisible = true,
  contentType,
  structureType,
  extractionReport,
  sourceUrl,
}: ReadViewProps) {
  const profile = useMemo(
    () => readingProfile({ content_type: contentType, structure_type: structureType }),
    [contentType, structureType],
  )
  const { prefs, update: updatePref, reset: resetPrefs } = useReaderPreferences()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const spec = useMemo(
    () => resolveReadingLayout(profileSpec(profile), prefs),
    [profile, prefs],
  )
  const contentRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const [activeSection, setActiveSection] = useState<string | null>(null)
  const [listLimit, setListLimit] = useState(200)
  const toc = useResizablePanel({
    storageKey: "luminary-read-toc",
    defaultWidth: 224,
    minWidth: 160,
    maxWidth: 480,
    side: "right",
  })

  const { data: sections, isLoading, error } = useQuery({
    queryKey: ["section-content", documentId],
    queryFn: () => fetchSectionContent(documentId),
    staleTime: 60_000,
  })

  const tocEntries = useMemo(() => usableSections(sections ?? []), [sections])

  // Sections predating `sections.body` are served from chunks (I-29); the text
  // cannot be repaired in place, so say so rather than let it pass as authored.
  const degradedCount = useMemo(
    () => (sections ?? []).filter((s) => s.content_source === "chunks").length,
    [sections],
  )

  // Figures are supplementary: a failure here must not block the text, so this
  // query has no error branch and simply yields no images.
  const { data: docImages } = useQuery({
    queryKey: ["document-images", documentId],
    queryFn: () => fetchDocumentImages(documentId),
    staleTime: 300_000,
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

  // An image inside a section's page range renders once, under that section.
  // Sections without page ranges (non-paginated formats) get none.
  const imagesBySection = useMemo(() => {
    const map = new Map<string, DocumentImage[]>()
    if (!sections || !docImages?.length) return map
    const claimed = new Set<string>()
    for (const section of sections) {
      const matched = imagesForSection(section, docImages).filter((i) => !claimed.has(i.id))
      if (matched.length) {
        matched.forEach((i) => claimed.add(i.id))
        map.set(section.section_id, matched)
      }
    }
    return map
  }, [sections, docImages])

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

  // Extend the rendered window when its tail comes into view.
  useEffect(() => {
    const el = loadMoreRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setListLimit((prev) => prev + 200)
      },
      { rootMargin: "800px" },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [listLimit, sections])

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
      {toc.collapsed ? (
        <button
          type="button"
          onClick={toc.toggle}
          aria-label="Show contents"
          title="Show contents"
          className="flex h-full w-8 shrink-0 items-start justify-center border-r pt-3 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <PanelLeftOpen size={16} />
        </button>
      ) : (
      <div
        className="shrink-0 border-r overflow-y-auto p-2 scrollbar-thin"
        style={{ width: toc.width }}
      >
        <div className="mb-3 flex items-center justify-between px-2">
          <p className="text-xs font-semibold uppercase text-muted-foreground tracking-wider">
            Contents
          </p>
          <button
            type="button"
            onClick={toc.toggle}
            aria-label="Hide contents"
            title="Hide contents"
            className="text-muted-foreground hover:text-foreground"
          >
            <PanelLeftClose size={14} />
          </button>
        </div>
        <ul className="space-y-0.5">
          {tocEntries.slice(0, listLimit).map((sec) => (
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
      )}
      {!toc.collapsed && (
        <PanelResizer
          onPointerDown={toc.onPointerDown}
          dragging={toc.dragging}
          label="Resize contents panel"
        />
      )}

      {/* Reading content */}
      <div
        ref={contentRef}
        className={cn(
          "relative flex-1 overflow-auto px-8 py-6 scroll-smooth",
          spec.tinted && "bg-[#faf6ec] dark:bg-[#1b1917]",
        )}
      >
        <div className="sticky top-0 z-40 flex justify-end">
          <ReaderSettings
            open={settingsOpen}
            onOpenChange={setSettingsOpen}
            profile={profile}
            effectiveMeasureCh={spec.measureCh}
            prefs={prefs}
            onUpdate={updatePref}
            onReset={resetPrefs}
          />
        </div>
        {/* Measure in ch so line length holds at every text size. */}
        <div
          className="mx-auto -mt-6 w-full text-[length:var(--reader-size)] [&_p]:leading-[var(--reader-leading)]"
          style={{
            maxWidth: `${spec.measureCh}ch`,
            ["--reader-size" as string]: `${spec.fontScale}rem`,
            ["--reader-leading" as string]: spec.lineHeight,
          }}
        >
          <ImportFidelityNotice
            report={extractionReport}
            documentId={documentId}
            sourceUrl={sourceUrl}
          />
          {degradedCount > 0 && (
            <div className="mb-8 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                {degradedCount} of {sections.length} sections were stored before Luminary kept
                full section text, so their paragraph breaks are approximate.
              </p>
              <ReimportAction documentId={documentId} sourceUrl={sourceUrl} />
            </div>
          )}
          {sections.slice(0, listLimit).map((section, i) => (
            <LazySection
              key={section.section_id}
              section={section}
              annotations={annotationsBySection.get(section.section_id) || []}
              highlightsVisible={highlightsVisible}
              images={imagesBySection.get(section.section_id)}
              spec={spec}
              isLast={i === Math.min(sections.length, listLimit) - 1}
            />
          ))}
          
          {/* The window bounds the DOM only; reaching its end extends it. */}
          {sections.length > listLimit && (
            <div ref={loadMoreRef} className="mb-20 mt-12 flex justify-center">
              <Loader2 size={16} className="animate-spin text-muted-foreground" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


/** The importer's own account of what it could not capture.
 *
 *  A partial import that looks complete is the failure this exists to prevent:
 *  the reader has no way to know a diagram was dropped, and no original to
 *  compare against the way a PDF always has. Only `dropped` and `notes` are
 *  rendered -- a clean import says nothing at all.
 */
export interface ExtractionReport {
  captured?: Record<string, number>
  dropped?: Record<string, number>
  notes?: string[]
  complete?: boolean
}

function ImportFidelityNotice({
  report,
  documentId,
  sourceUrl,
}: {
  report?: ExtractionReport | null
  documentId: string
  sourceUrl?: string | null
}) {
  if (!report) return null
  const dropped = Object.entries(report.dropped ?? {}).filter(([, n]) => n > 0)
  const notes = report.notes ?? []
  if (dropped.length === 0 && notes.length === 0) return null

  return (
    <div className="mb-8 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
      {dropped.length > 0 && (
        <p>
          This import is missing{" "}
          {dropped
            .map(([kind, n]) => `${n} ${kind}${n === 1 ? "" : "s"}`)
            .join(" and ")}{" "}
          the page contained. The text around them came through in full.
        </p>
      )}
      {notes.map((note) => (
        <p key={note} className={dropped.length > 0 ? "mt-1" : undefined}>
          {note}
        </p>
      ))}
      <ReimportAction documentId={documentId} sourceUrl={sourceUrl} />
    </div>
  )
}

interface ReparseResponse {
  status: string
  source: string
  anchored: Record<string, number>
  detail: string
}

/** Re-run the importer over this document.
 *
 *  Two steps on purpose. The first call only reports what the rebuild would
 *  strand -- highlights and clips anchored to sections that are about to be
 *  replaced -- because that is a cost the reader has to agree to, not one to
 *  discover afterwards.
 */
function ReimportAction({ documentId, sourceUrl }: { documentId: string; sourceUrl?: string | null }) {
  const queryClient = useQueryClient()
  const [preview, setPreview] = useState<ReparseResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const call = async (confirm: boolean) => {
    setBusy(true)
    setError(null)
    try {
      // The same render the original import used. Without it a page whose
      // content its scripts produce comes back static, and the re-import the
      // fidelity notice offers would cost the reader the figures it named.
      const rendered = confirm && sourceUrl ? await renderPage(sourceUrl) : null
      const res = await apiPost<ReparseResponse>(`/documents/${documentId}/reparse`, {
        confirm,
        ...(rendered?.html ? { rendered_html: rendered.html } : {}),
      })
      if (confirm) {
        setPreview(null)
        await queryClient.invalidateQueries({ queryKey: ["document", documentId] })
      } else {
        setPreview(res)
      }
    } catch {
      setError("Could not start the re-import.")
    } finally {
      setBusy(false)
    }
  }

  const anchored = Object.entries(preview?.anchored ?? {}).filter(([, n]) => n > 0)

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {!preview ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void call(false)}
          className="self-start text-xs font-medium text-foreground underline-offset-2 hover:underline disabled:opacity-50"
        >
          {busy ? "Checking…" : "Re-import this document"}
        </button>
      ) : (
        <>
          <p>{preview.detail}</p>
          {anchored.length > 0 && (
            <p>
              Anchored to the current sections:{" "}
              {anchored.map(([kind, n]) => `${n} ${kind}`).join(", ")}.
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void call(true)}
              className="text-xs font-semibold text-foreground underline-offset-2 hover:underline disabled:opacity-50"
            >
              {busy ? "Starting…" : "Re-import now"}
            </button>
            <button
              type="button"
              onClick={() => setPreview(null)}
              className="text-xs text-muted-foreground underline-offset-2 hover:underline"
            >
              Cancel
            </button>
          </div>
        </>
      )}
      {error && <p className="text-destructive">{error}</p>}
    </div>
  )
}
