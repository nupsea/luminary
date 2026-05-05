import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, BookOpen, Loader2, StickyNote, X, Highlighter, ChevronLeft, GitCompareArrows } from "lucide-react"
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { CONTENT_TYPE_ICONS, formatWordCount, isYouTubeDoc, relativeDate } from "@/components/library/utils"
import type { ContentType } from "@/components/library/types"
import { ExplanationSheet } from "@/components/ExplanationSheet"
import type { ExplainMode } from "@/components/FloatingToolbar"
import type { AnnotationItem, DocumentDetail } from "./types"
import { ChapterGoalsPanel } from "./ChapterGoalsPanel"
import { IngestionHealthPanel } from "@/components/library/IngestionHealthPanel"
import { SelectionActionBar } from "./SelectionActionBar"
import type { SourceRef } from "./SelectionActionBar"
import { NoteCreationDialog } from "./NoteCreationDialog"
import { NoteEditorDialog, type Note } from "@/components/NoteEditorDialog"
import { DocumentFlashcardDialog } from "./DocumentFlashcardDialog"
import { FeynmanDialog } from "./FeynmanDialog"
import { prefetchFeynmanSummary } from "./feynmanSummaryCache"
import { PDFViewer, type PDFViewerHandle } from "./PDFViewer"
import { EPUBViewer } from "./EPUBViewer"
import { ReadView } from "./ReadView"
import { resolveFromDom, resolvePdfFallback } from "./resolveSourceRefUtils"
import { YouTubeTranscriptView } from "./YouTubeTranscriptView"
import { useAppStore } from "@/store"

import { API_BASE } from "@/lib/config"

import { AudioMiniPlayer, VideoPlayer } from "./MediaPlayers"
import { InDocSearchBar, type DocumentSectionSearchResult } from "./InDocSearchBar"
import { ResumeBanner, type ReadingPosition } from "./ResumeBanner"
import { SectionListItem, type SectionHeatmapItem } from "./SectionListItem"
import { SummaryPanel } from "./SummaryPanel"

// ---------------------------------------------------------------------------
// Error Boundary (S200)
// ---------------------------------------------------------------------------

class DocumentReaderErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("DocumentReader Error Boundary caught:", error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-background text-foreground">
          <div className="p-4 rounded-full bg-destructive/10 text-destructive mb-4">
            <X size={32} />
          </div>
          <h2 className="text-xl font-bold mb-2">Something went wrong</h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-md">
            The document reader encountered a runtime error. Details: {this.state.error?.message}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Reload application
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

async function fetchDocument(id: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/documents/${id}`)
  if (!res.ok) throw new Error("Failed to fetch document")
  return res.json() as Promise<DocumentDetail>
}

// Minimal note shape used for the section indicator (section_id only)
interface NoteEntry {
  id: string
  section_id: string | null
}

// ---------------------------------------------------------------------------
// Reading progress tracking (S110)
// ---------------------------------------------------------------------------

async function postReadingProgress(documentId: string, sectionId: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/reading/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, section_id: sectionId }),
    })
  } catch {
    // Best-effort: network errors must never interrupt reading
  }
}

function useReadingProgress(documentId: string, sectionCount: number) {
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Track whether any progress was posted so we can invalidate the library
  // query on unmount and keep the progress bar in sync within the same session.
  const progressPosted = useRef(false)
  const qc = useQueryClient()

  useEffect(() => {
    if (sectionCount === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const sectionId = (entry.target as HTMLElement).dataset["sectionId"]
          if (!sectionId) continue

          if (entry.isIntersecting) {
            if (!timers.current.has(sectionId)) {
              const t = setTimeout(() => {
                timers.current.delete(sectionId)
                progressPosted.current = true
                void postReadingProgress(documentId, sectionId)
              }, 3000)
              timers.current.set(sectionId, t)
            }
          } else {
            const t = timers.current.get(sectionId)
            if (t !== undefined) {
              clearTimeout(t)
              timers.current.delete(sectionId)
            }
          }
        }
      },
      { threshold: 0.5 },
    )

    const elements = document.querySelectorAll("[data-section-id]")
    for (const el of elements) observer.observe(el)

    return () => {
      observer.disconnect()
      for (const t of timers.current.values()) clearTimeout(t)
      timers.current.clear()
      // Invalidate the library query so progress bars reflect this session.
      if (progressPosted.current) {
        void qc.invalidateQueries({ queryKey: ["documents"] })
        progressPosted.current = false
      }
    }
  }, [documentId, sectionCount, qc])
}

interface DocumentReaderProps {
  documentId: string
  onBack: () => void
  initialSectionId?: string
  initialChunkId?: string
  initialPage?: number  // S148: PDF page to navigate to on mount (from citation deep-link)
}

export function DocumentReader(props: DocumentReaderProps) {
  return (
    <DocumentReaderErrorBoundary>
      <DocumentReaderBase {...props} />
    </DocumentReaderErrorBoundary>
  )
}

function DocumentReaderBase({ documentId, onBack, initialSectionId, initialChunkId, initialPage }: DocumentReaderProps) {
  const qc = useQueryClient()

  const { data: doc, isLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => fetchDocument(documentId),
    staleTime: 60_000,
  })

  const sectionListRef = useRef<HTMLDivElement>(null)
  const readerContainerRef = useRef<HTMLDivElement>(null)
  const pdfViewerRef = useRef<PDFViewerHandle>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetText, setSheetText] = useState("")
  const [sheetMode, setSheetMode] = useState<ExplainMode>("plain")
  const [openNoteEditor, setOpenNoteEditor] = useState<string | null>(null) // section id
  const [leftTab, setLeftTab] = useState<"sections" | "pdfview" | "bookview" | "read">("sections")
  const [highlightsVisible, setHighlightsVisible] = useState(true)
  const [highlightsPanelOpen, setHighlightsPanelOpen] = useState(false)
  const [pdfCurrentPage, setPdfCurrentPage] = useState(1)
  const pageTimerRef = useRef<ReturnType<typeof setTimeout>>(null)
  
  const handlePageChange = useCallback((page: number) => {
    if (pageTimerRef.current) clearTimeout(pageTimerRef.current)
    pageTimerRef.current = setTimeout(() => {
      setPdfCurrentPage(page)
    }, 100)
  }, [])
  const highlightsPanelRef = useRef<HTMLDivElement>(null)
  const highlightsToggleRef = useRef<HTMLButtonElement>(null)
  const [readSectionId, setReadSectionId] = useState<string | null>(null)
  // S146: tracks whether the PDF View tab has been visited at least once (lazy-mount)
  const [pdfViewVisited, setPdfViewVisited] = useState(false)
  // S149: tracks whether the Book View tab has been visited at least once (lazy-mount)
  const [bookViewVisited, setBookViewVisited] = useState(false)
  // S143: tracks which section's goals are shown in ChapterGoalsPanel; null = show all
  const [activeSectionGoals, setActiveSectionGoals] = useState<string | null>(null)
  // S144: Feynman mode — section id to open dialog for; null = closed
  const [feynmanSection, setFeynmanSection] = useState<string | null>(null)
  // Unified "section the user is currently focused on" — set by every section
  // action (Read, Practice, Note, PDF jump, Goals, citation deep-link). Drives
  // the sticky banner in the sections tab and the active-row visual treatment.
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)

  // In-document navigation stack: every user-initiated navigation (tab change,
  // Read click, PDF jump, citation deep-link) pushes the current place. The
  // Back button (and Cmd/Ctrl+[) pops it.
  type ReaderPlace = {
    tab: "sections" | "pdfview" | "bookview" | "read"
    sectionId: string | null
    pdfPage: number | null
  }
  const historyRef = useRef<ReaderPlace[]>([])
  const currentPlaceRef = useRef<ReaderPlace>({ tab: "sections", sectionId: null, pdfPage: null })
  const [historyDepth, setHistoryDepth] = useState(0)
  // S197: noteCount for "Compare my notes" button visibility
  const [noteCount, setNoteCount] = useState(0)
  // S151: in-document Cmd+F search state
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<DocumentSectionSearchResult[]>([])
  const [searchHitIndex, setSearchHitIndex] = useState(0)
  const [listLimit, setListLimit] = useState(200)

  // S152: reading position — resume banner
  const [resumePosition, setResumePosition] = useState<ReadingPosition | null>(null)
  // ref tracking the last section_id we POSTed so we only POST when it changes
  const lastPostedSectionRef = useRef<string | null>(null)
  // throttle timer: one POST per 10 seconds max
  const positionThrottleRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // S147: SelectionActionBar dialog state
  const [selectionNoteOpen, setSelectionNoteOpen] = useState(false)
  const [selectionNoteText, setSelectionNoteText] = useState("")
  const [selectionNoteSourceRef, setSelectionNoteSourceRef] = useState<SourceRef | null>(null)
  const [selectionNoteHeading, setSelectionNoteHeading] = useState<string | undefined>(undefined)
  const [editingCreatedNote, setEditingCreatedNote] = useState<Note | null>(null)
  const [selectionFlashcardOpen, setSelectionFlashcardOpen] = useState(false)
  const [selectionFlashcardText, setSelectionFlashcardText] = useState("")
  const [selectionFlashcardSourceRef, setSelectionFlashcardSourceRef] = useState<SourceRef | null>(null)
  const [selectionFlashcardHeading, setSelectionFlashcardHeading] = useState<string | undefined>(undefined)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setStudySectionFilter = useAppStore((s) => s.setStudySectionFilter)
  const setChatPreload = useAppStore((s) => s.setChatPreload)

  // Audio mini-player state (S120) — only active for audio documents
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [audioPlaying, setAudioPlaying] = useState(false)
  const [audioCurrentTime, setAudioCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)

  // Video player state (S121) — only active for video documents
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const isAudio = doc?.content_type === "audio"
  const isVideo = doc?.content_type === "video"
  const isYouTube = isYouTubeDoc(doc ?? {})

  // S111: Pre-calculate section map for O(1) lookups in highlight loops
  const sectionMap = useMemo(() => {
    const m = new Map<string, SectionItem>()
    if (doc?.sections) {
      for (const s of doc.sections) m.set(s.id, s)
    }
    return m
  }, [doc?.sections])

  // Parent -> direct children (ids), and total-descendant count per parent.
  // Used by the collapsible hierarchy in the sections list.
  const sectionTree = useMemo(() => {
    const childrenOf = new Map<string, string[]>()
    const descendantCount = new Map<string, number>()
    const sections = doc?.sections ?? []
    for (const s of sections) {
      if (!s.parent_section_id) continue
      const arr = childrenOf.get(s.parent_section_id) ?? []
      arr.push(s.id)
      childrenOf.set(s.parent_section_id, arr)
    }
    // Walk parent chain to accumulate descendant counts.
    for (const s of sections) {
      let pid = s.parent_section_id
      while (pid) {
        descendantCount.set(pid, (descendantCount.get(pid) ?? 0) + 1)
        pid = sectionMap.get(pid)?.parent_section_id ?? null
      }
    }
    return { childrenOf, descendantCount }
  }, [doc?.sections, sectionMap])

  // Sections collapsed by default: any level<=2 parent that owns level>=3
  // descendants in a long doc. Keeps the dashboard scannable for tech books
  // without hiding structure for short articles.
  const [collapsedParents, setCollapsedParents] = useState<Set<string>>(new Set())
  const initialCollapsedKey = doc?.id
  const initialCollapsedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!doc?.sections || initialCollapsedRef.current === initialCollapsedKey) return
    initialCollapsedRef.current = initialCollapsedKey ?? null
    if (doc.sections.length <= 30) {
      setCollapsedParents(new Set())
      return
    }
    const next = new Set<string>()
    for (const s of doc.sections) {
      if (s.level > 2) continue
      const kids = sectionTree.childrenOf.get(s.id) ?? []
      const hasDeep = kids.some((cid) => (sectionMap.get(cid)?.level ?? 0) >= 3)
      if (hasDeep) next.add(s.id)
    }
    setCollapsedParents(next)
  }, [doc?.sections, initialCollapsedKey, sectionTree, sectionMap])

  const toggleCollapsed = useCallback((sid: string) => {
    setCollapsedParents((prev) => {
      const next = new Set(prev)
      if (next.has(sid)) next.delete(sid)
      else next.add(sid)
      return next
    })
  }, [])

  const isSectionHidden = useCallback(
    (sec: SectionItem): boolean => {
      let pid = sec.parent_section_id
      while (pid) {
        if (collapsedParents.has(pid)) return true
        pid = sectionMap.get(pid)?.parent_section_id ?? null
      }
      return false
    },
    [collapsedParents, sectionMap],
  )

  const audioUrl = (isAudio && !isYouTube) ? `${API_BASE}/documents/${documentId}/audio` : null
  const videoUrl = isVideo ? `${API_BASE}/documents/${documentId}/video` : null

  function handleAudioPlayPause() {
    const el = audioRef.current
    if (!el) return
    if (audioPlaying) {
      el.pause()
      setAudioPlaying(false)
    } else {
      void el.play()
      setAudioPlaying(true)
    }
  }

  function handleAudioSeek(t: number) {
    const el = audioRef.current
    if (!el) return
    el.currentTime = t
    setAudioCurrentTime(t)
  }

  function seekAndPlay(t: number) {
    const el = audioRef.current
    if (!el) return
    el.currentTime = t
    void el.play()
    setAudioPlaying(true)
  }

  function seekAndPlayVideo(t: number) {
    const el = videoRef.current
    if (!el) return
    el.currentTime = t
    void el.play()
  }

  // Scroll to initialSectionId once document sections are loaded (S114)
  useEffect(() => {
    if (!initialSectionId || !doc) return
    // Wait a tick for DOM to update after doc is available
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-section-id="${initialSectionId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [initialSectionId, doc])

  // S151: Explicit scroll when switching to Read tab via citation link
  useEffect(() => {
    if (leftTab === "read" && readSectionId) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`read-sec-${readSectionId}`)
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" })
        }
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [leftTab, readSectionId])

  // Keep activeSectionId in sync with whichever per-action state was most
  // recently touched. Priority: Feynman > Read > Goals > Note editor.
  useEffect(() => {
    const next = feynmanSection ?? readSectionId ?? activeSectionGoals ?? openNoteEditor
    if (next) setActiveSectionId(next)
  }, [feynmanSection, readSectionId, activeSectionGoals, openNoteEditor])

  // Mirror the current place into a ref so navigation handlers can read it
  // synchronously when pushing onto the history stack.
  useEffect(() => {
    currentPlaceRef.current = {
      tab: leftTab,
      sectionId: activeSectionId,
      pdfPage: leftTab === "pdfview" ? pdfCurrentPage : null,
    }
  }, [leftTab, activeSectionId, pdfCurrentPage])

  // Push the current place onto the history stack. Pass an override when the
  // caller knows the "place to return to" better than current state — e.g. a
  // Read button click should return to the clicked section, not to whatever
  // activeSectionId happened to be when the click fired.
  const pushHistory = useCallback((override?: Partial<ReaderPlace>) => {
    const base = { ...currentPlaceRef.current }
    historyRef.current.push({ ...base, ...override })
    setHistoryDepth(historyRef.current.length)
  }, [])

  // Scroll the active section card into view inside the sections list.
  // If any ancestor is collapsed, expand the chain first so the target row
  // actually exists in the DOM before we try to scroll to it. The retry loop
  // handles the case where the sections tab was just mounted and the row
  // hasn't appeared in the DOM yet.
  const scrollActiveSectionIntoView = useCallback((sid: string) => {
    const sec = sectionMap.get(sid)
    if (sec) {
      const ancestors: string[] = []
      let pid = sec.parent_section_id
      while (pid) {
        ancestors.push(pid)
        pid = sectionMap.get(pid)?.parent_section_id ?? null
      }
      const collapsedAncestors = ancestors.filter((a) => collapsedParents.has(a))
      if (collapsedAncestors.length > 0) {
        setCollapsedParents((prev) => {
          const next = new Set(prev)
          for (const a of collapsedAncestors) next.delete(a)
          return next
        })
      }
    }

    function attempt(tries: number) {
      const container = sectionListRef.current
      const el = container?.querySelector<HTMLElement>(
        `[data-section-id="${CSS.escape(sid)}"]`,
      )
      if (!container || !el) {
        if (tries < 20) requestAnimationFrame(() => attempt(tries + 1))
        return
      }
      // Center the row within the section list container directly instead of
      // relying on Element.scrollIntoView (which can choose the wrong scroll
      // ancestor, especially when a sticky banner sits at the top).
      const containerRect = container.getBoundingClientRect()
      const elRect = el.getBoundingClientRect()
      const target =
        container.scrollTop +
        (elRect.top - containerRect.top) -
        containerRect.height / 2 +
        elRect.height / 2
      container.scrollTo({ top: Math.max(0, target), behavior: "smooth" })
      el.classList.add("ring-2", "ring-primary", "transition-shadow")
      window.setTimeout(() => {
        el.classList.remove("ring-2", "ring-primary", "transition-shadow")
      }, 1500)
    }
    attempt(0)
  }, [sectionMap, collapsedParents])

  // When goBack switches tabs, the target tab's DOM is not yet mounted, so
  // scrolling has to wait until React commits the new tab. We park the
  // intended scroll target in a ref and let an effect fire it after render.
  const pendingScrollRef = useRef<string | null>(null)

  const goBack = useCallback(() => {
    const prev = historyRef.current.pop()
    setHistoryDepth(historyRef.current.length)
    if (!prev) return
    if (prev.sectionId) {
      setActiveSectionId(prev.sectionId)
      setReadSectionId(prev.sectionId)
      if (prev.tab === "sections") {
        pendingScrollRef.current = prev.sectionId
      }
    }
    if (prev.tab === "pdfview") {
      setPdfViewVisited(true)
      if (prev.pdfPage) {
        // Defer until the PDF view has had a chance to mount on tab switch.
        window.setTimeout(() => pdfViewerRef.current?.goToPage(prev.pdfPage as number), 50)
      }
    }
    if (prev.tab === "bookview") {
      setBookViewVisited(true)
    }
    setLeftTab(prev.tab)
  }, [])

  // Fire the pending scroll once the Sections tab has actually rendered.
  // scrollActiveSectionIntoView itself retries with RAF until the row exists
  // in the DOM, so no setTimeout is required here.
  useEffect(() => {
    if (leftTab !== "sections" || !pendingScrollRef.current) return
    const sid = pendingScrollRef.current
    pendingScrollRef.current = null
    scrollActiveSectionIntoView(sid)
  }, [leftTab, scrollActiveSectionIntoView])

  // Cmd/Ctrl+[ — Back. Cmd/Ctrl+] — Forward (not supported yet, no-op).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key === "[") {
        e.preventDefault()
        goBack()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [goBack])

  // Auto-switch to PDF view for PDF documents; Book view for EPUB; Read view for deep links
  useEffect(() => {
    if (!doc) return
    if (doc.format === "pdf") {
      setPdfViewVisited(true)
      setLeftTab("pdfview")
      if (initialSectionId) setReadSectionId(initialSectionId)
    } else if (initialSectionId || initialChunkId || initialPage) {
      if (initialSectionId) setReadSectionId(initialSectionId)
      setLeftTab("read")
    } else if (doc.format === "epub") {
      setBookViewVisited(true)
      setLeftTab("bookview")
    }
  }, [doc?.format, initialSectionId, initialPage]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch notes for this document so dot indicators persist across reloads (S106)
  const { data: docNotes, isError: notesError } = useQuery<NoteEntry[]>({
    queryKey: ["notes-for-doc", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/notes?document_id=${encodeURIComponent(documentId)}`)
      if (!res.ok) throw new Error("Failed to fetch notes")
      return res.json() as Promise<NoteEntry[]>
    },
    staleTime: 30_000,
  })

  // Fetch annotations for highlight reconstruction and panel (S111)
  const {
    data: docAnnotations,
  } = useQuery<AnnotationItem[]>({
    queryKey: ["annotations-for-doc", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/annotations?document_id=${encodeURIComponent(documentId)}`)
      if (!res.ok) throw new Error("Failed to fetch annotations")
      return res.json() as Promise<AnnotationItem[]>
    },
    staleTime: 30_000,
  })

  // Fetch objective progress for mini rings on section headers (S143)
  const { data: progressData } = useQuery<{
    by_chapter: { section_id: string; progress_pct: number }[]
  }>({
    queryKey: ["doc-progress", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/documents/${documentId}/progress`)
      if (!res.ok) return { by_chapter: [] }
      return res.json() as Promise<{ by_chapter: { section_id: string; progress_pct: number }[] }>
    },
    staleTime: 60_000,
  })

  const progressBySectionId = useMemo(
    () => new Map((progressData?.by_chapter ?? []).map((c) => [c.section_id, c.progress_pct])),
    [progressData],
  )

  // S151: derived set of section IDs that have a search hit (O(1) lookup)
  const searchHitSectionIds = useMemo(
    () => new Set(searchResults.map((r) => r.section_id)),
    [searchResults],
  )

  // S131: Group annotations by section for O(1) retrieval in section list
  const annotationsBySection = useMemo(() => {
    const m = new Map<string, AnnotationItem[]>()
    if (docAnnotations) {
      for (const ann of docAnnotations) {
        const list = m.get(ann.section_id) || []
        list.push(ann)
        m.set(ann.section_id, list)
      }
    }
    return m
  }, [docAnnotations])

  // S151: Pre-calculate search snippet map for O(1) retrieval
  const searchSnippetMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of searchResults) {
      if (r.snippet) m.set(r.section_id, r.snippet)
    }
    return m
  }, [searchResults])

  // S151: Cmd+F / Ctrl+F keydown listener — opens inline search bar
  useEffect(() => {
    function handleCmdF(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    document.addEventListener("keydown", handleCmdF)
    return () => document.removeEventListener("keydown", handleCmdF)
  }, [])

  // S151: Escape closes the search bar when it is open
  useEffect(() => {
    if (!searchOpen) return
    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSearchOpen(false)
        setSearchResults([])
        setSearchHitIndex(0)
      }
    }
    document.addEventListener("keydown", handleEsc)
    return () => document.removeEventListener("keydown", handleEsc)
  }, [searchOpen])

  // S151: close search bar when switching away from the sections tab
  useEffect(() => {
    if (leftTab !== "sections" && searchOpen) {
      setSearchOpen(false)
      setSearchResults([])
      setSearchHitIndex(0)
    }
  }, [leftTab, searchOpen])

  // S151: scroll current hit into view when hitIndex or results change
  useEffect(() => {
    if (searchResults.length === 0) return
    const targetId = searchResults[searchHitIndex]?.section_id
    if (!targetId) return
    const el = document.querySelector(`[data-section-id="${CSS.escape(targetId)}"]`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }, [searchHitIndex, searchResults])

  function handleStudyClick(sid: string) {
    setActiveDocument(documentId)
    setStudySectionFilter({ sectionId: sid, bloomLevelMin: 2 })
  }

  // Fetch FSRS fragility heatmap for section coloring (S116)
  const { data: heatmapData } = useQuery<Record<string, SectionHeatmapItem>>({
    queryKey: ["section-heatmap", documentId],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/study/section-heatmap?document_id=${encodeURIComponent(documentId)}`
      )
      if (!res.ok) return {}
      const data = (await res.json()) as { heatmap: Record<string, SectionHeatmapItem> }
      return data.heatmap
    },
    staleTime: 60_000,
  })

  // Map of section_id -> ISO timestamp of most recent Feynman session.
  // Powers the "last practiced" badge in the section list.
  const { data: lastPracticedBySection } = useQuery<Map<string, string>>({
    queryKey: ["feynman-sessions-by-section", documentId],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/feynman/sessions?document_id=${encodeURIComponent(documentId)}`
      )
      if (!res.ok) return new Map()
      const sessions = (await res.json()) as Array<{ section_id: string | null; created_at: string }>
      const byId = new Map<string, string>()
      // Sessions are returned in created_at desc; first hit per section wins.
      for (const s of sessions) {
        if (!s.section_id) continue
        if (!byId.has(s.section_id)) byId.set(s.section_id, s.created_at)
      }
      return byId
    },
    staleTime: 30_000,
  })

  // Derive the set of section IDs that have at least one note
  const notedSections = useMemo(
    () => new Set((docNotes ?? []).map((n) => n.section_id).filter((id): id is string => id !== null && id !== undefined)),
    [docNotes],
  )

  // Track reading progress via IntersectionObserver (3-second dwell per section)
  useReadingProgress(documentId, doc?.sections.length ?? 0)

  // S152: fetch saved reading position on mount; show ResumeBanner unless already dismissed this session
  useEffect(() => {
    if (!doc) return
    const dismissedKey = `resume-dismissed-${documentId}`
    if (sessionStorage.getItem(dismissedKey)) return
    void fetch(`${API_BASE}/documents/${documentId}/position`)
      .then((r) => {
        if (r.status === 404) return null
        if (!r.ok) return null
        return r.json() as Promise<ReadingPosition>
      })
      .then((pos) => {
        if (pos?.last_section_id) setResumePosition(pos)
      })
      .catch(() => {
        // banner failure is silent
      })
  }, [documentId, doc])

  // S152: IntersectionObserver — track the topmost visible section and throttle-POST position
  useEffect(() => {
    if (!doc || doc.sections.length === 0) return
    const sectionElements = Array.from(
      document.querySelectorAll<HTMLElement>("[data-section-id]"),
    )
    if (sectionElements.length === 0) return

    function postPosition(sectionId: string) {
      if (sectionId === lastPostedSectionRef.current) return
      if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
      positionThrottleRef.current = setTimeout(() => {
        const section = doc!.sections.find((s) => s.id === sectionId)
        void fetch(`${API_BASE}/documents/${documentId}/position`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            last_section_id: sectionId,
            last_section_heading: section?.heading ?? null,
            last_pdf_page: null,
            last_epub_chapter_index: null,
          }),
        }).catch(() => {})
        lastPostedSectionRef.current = sectionId
      }, 10_000)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        let topmost: HTMLElement | null = null
        let topmostTop = Infinity
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const top = entry.boundingClientRect.top
            if (top < topmostTop) {
              topmostTop = top
              topmost = entry.target as HTMLElement
            }
          }
        }
        if (topmost?.dataset.sectionId) {
          postPosition(topmost.dataset.sectionId)
        }
      },
      { threshold: 0.2 },
    )

    for (const el of sectionElements) observer.observe(el)
    return () => {
      observer.disconnect()
      if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
    }
  }, [documentId, doc?.sections.length])

  const handleResume = () => {
    if (!resumePosition?.last_section_id) return
    const el = document.querySelector(`[data-section-id="${CSS.escape(resumePosition.last_section_id)}"]`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
    setResumePosition(null)
    sessionStorage.setItem(`resume-dismissed-${documentId}`, "1")
  }

  const handleDismissResume = () => {
    setResumePosition(null)
    sessionStorage.setItem(`resume-dismissed-${documentId}`, "1")
  }

  const resolveSourceRef = useCallback(
    (node: Node) => {
      const fromDom = resolveFromDom(node)
      if (fromDom) return { sectionId: fromDom, documentId, documentTitle: doc?.title ?? "" }
      if (doc?.format === "pdf" && doc.sections.length > 0) {
        const fromPdf = resolvePdfFallback(doc.sections, pdfCurrentPage)
        if (fromPdf) return { sectionId: fromPdf, documentId, documentTitle: doc?.title ?? "", pageNumber: pdfCurrentPage }
      }
      return { sectionId: undefined, documentId, documentTitle: doc?.title ?? "" }
    },
    [doc, pdfCurrentPage, documentId],
  )

  const handleNoteSaved = useCallback(() => {
    setOpenNoteEditor(null)
    void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
    void qc.invalidateQueries({ queryKey: ["reader-notes"] })
    void qc.invalidateQueries({ queryKey: ["notes"] })
    void qc.invalidateQueries({ queryKey: ["notes-groups"] })
    void qc.invalidateQueries({ queryKey: ["collections"] })
  }, [qc, documentId])

  const handleExplain = useCallback((text: string, mode: ExplainMode) => {
    setSheetText(text)
    setSheetMode(mode)
    setSheetOpen(true)
  }, [])

  const handleSelectionAddToNote = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setSelectionNoteText(text)
    setSelectionNoteSourceRef(sourceRef)
    setSelectionNoteHeading(heading)
    setSelectionNoteOpen(true)
  }, [sectionMap])

  const handleSelectionCreateFlashcard = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setSelectionFlashcardText(text)
    setSelectionFlashcardSourceRef(sourceRef)
    setSelectionFlashcardHeading(heading)
    setSelectionFlashcardOpen(true)
  }, [sectionMap])

  const handleSelectionAskInChat = useCallback((text: string) => {
    setChatPreload({ text: `Explain this excerpt:\n\n> ${text}`, documentId, autoSubmit: true })
    window.dispatchEvent(new CustomEvent("luminary:navigate", { detail: { tab: "chat" } }))
  }, [documentId, setChatPreload])

  const handleSelectionHighlight = useCallback(async (text: string, sourceRef: SourceRef, color: AnnotationItem["color"]) => {
    try {
      const res = await fetch(`${API_BASE}/annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          section_id: sourceRef.sectionId,
          selected_text: text,
          color,
          page_number: sourceRef.pageNumber,
        }),
      })
      if (!res.ok) throw new Error("Failed to save highlight")
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlight saved")
    } catch (err) {
      toast.error("Could not save highlight")
    }
  }, [documentId, qc])

  const handleSelectionClip = useCallback(async (text: string, sourceRef: SourceRef) => {
    try {
      const res = await fetch(`${API_BASE}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          section_id: sourceRef.sectionId,
          content: `> ${text}`,
          tags: ["clipped"],
        }),
      })
      if (!res.ok) throw new Error("Failed to clip")
      void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
      toast.success("Clipped to notes")
    } catch (err) {
      toast.error("Could not clip to notes")
    }
  }, [documentId, qc])

  const navigateToHighlight = useCallback((ann: AnnotationItem) => {
    pushHistory()
    if (doc?.format === "pdf" && ann.page_number) {
      setLeftTab("pdfview")
      setPdfViewVisited(true)
      pdfViewerRef.current?.goToPage(ann.page_number)
    } else {
      setLeftTab("read")
      setReadSectionId(ann.section_id)
    }
    setHighlightsPanelOpen(false)
  }, [doc, pushHistory])

  const handleDeleteHighlight = useCallback(async (id: string) => {
    if (!confirm("Remove this highlight?")) return
    try {
      const res = await fetch(`${API_BASE}/annotations/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error("Delete failed")
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlight removed")
    } catch (err) {
      toast.error("Could not remove highlight")
    }
  }, [documentId, qc])

  useEffect(() => {
    if (leftTab === "pdfview") {
      if (doc?.format !== "pdf") {
        setLeftTab("sections")
      } else {
        setPdfViewVisited(true)
      }
    } else if (leftTab === "bookview") {
      if (doc?.format !== "epub") {
        setLeftTab("sections")
      } else {
        setBookViewVisited(true)
      }
    }
  }, [leftTab, doc?.format])

  useEffect(() => {
    if (!highlightsPanelOpen) return
    function handleClick(e: MouseEvent) {
      if (
        highlightsPanelRef.current?.contains(e.target as Node) ||
        highlightsToggleRef.current?.contains(e.target as Node)
      ) return
      setHighlightsPanelOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [highlightsPanelOpen])


  // S131: Use virtualization for the section list if it's very large.
  const renderedSectionItems = useMemo(() => {
    if (!doc?.sections) return null
    // Filter out sections whose ancestor is collapsed *before* slicing, so
    // virtualization counts visible rows (not raw section count).
    const visible = doc.sections.filter((s) => !isSectionHidden(s))
    const sectionsToRender = visible.slice(0, listLimit)

    return sectionsToRender.map((section) => {
      const hasNote = notedSections.has(section.id)
      const editorOpen = openNoteEditor === section.id
      const heatmapItem = heatmapData?.[section.id] ?? null
      
      return (
        <SectionListItem
          key={section.id}
          section={section}
          doc={doc}
          isAudio={isAudio}
          isVideo={isVideo}
          isYouTube={isYouTube}
          hasNote={hasNote}
          editorOpen={editorOpen}
          heatmapItem={heatmapItem}
          searchHit={searchHitSectionIds.has(section.id)}
          searchSnippet={searchSnippetMap.get(section.id)}
          progressPct={progressBySectionId.get(section.id)}
          annotations={annotationsBySection.get(section.id) ?? []}
          feynmanEnabled={doc.content_type === "tech_book" || doc.content_type === "tech_article"}
          isActive={activeSectionId === section.id}
          lastPracticedAt={lastPracticedBySection?.get(section.id)}
          childCount={sectionTree.descendantCount.get(section.id) ?? 0}
          isCollapsed={collapsedParents.has(section.id)}
          onToggleCollapsed={toggleCollapsed}
          onRead={(sid) => {
            // Push "Sections tab focused on the clicked section" as the
            // place-to-return-to, so Back scrolls back to that exact row.
            const sec = sectionMap.get(sid)
            if (doc.format === "pdf" && sec && sec.page_start > 0) {
              pushHistory({ tab: "sections", sectionId: sid, pdfPage: null })
              setReadSectionId(sid)
              setPdfViewVisited(true)
              setLeftTab("pdfview")
              pdfViewerRef.current?.goToPage(sec.page_start)
              return
            }
            pushHistory({ tab: "sections", sectionId: sid, pdfPage: null })
            setReadSectionId(sid)
            setLeftTab("read")
          }}
          onPdfJump={(p) => {
            // The page anchor lives on a specific section — return to it.
            pushHistory({ tab: "sections", sectionId: section.id, pdfPage: null })
            setPdfViewVisited(true)
            setLeftTab("pdfview")
            pdfViewerRef.current?.goToPage(p)
          }}
          onMediaJump={(t) => isAudio ? seekAndPlay(t) : seekAndPlayVideo(t)}
          onToggleNote={(sid) => setOpenNoteEditor(openNoteEditor === sid ? null : sid)}
          onSaved={handleNoteSaved}
          onCancel={() => setOpenNoteEditor(null)}
          onFeynman={setFeynmanSection}
          onPrefetchFeynman={(sid) => prefetchFeynmanSummary(doc.id, sid)}
          onShowGoals={(sid) => setActiveSectionGoals(activeSectionGoals === sid ? null : sid)}
        />
      )
    })
  }, [
    doc,
    isAudio,
    isVideo,
    isYouTube,
    notedSections,
    openNoteEditor,
    heatmapData,
    searchHitSectionIds,
    searchSnippetMap,
    progressBySectionId,
    annotationsBySection,
    activeSectionGoals,
    activeSectionId,
    lastPracticedBySection,
    sectionMap,
    sectionTree,
    collapsedParents,
    toggleCollapsed,
    isSectionHidden,
    handleNoteSaved,
    listLimit,
  ])

  if (isLoading) {
    return (
      <div className="flex h-full gap-6 p-6">
        <div className="flex w-3/5 flex-col gap-4">
          <div className="h-8 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
          <div className="flex-1 space-y-3">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded bg-muted" />
            ))}
          </div>
        </div>
        <div className="w-2/5">
          <div className="h-32 animate-pulse rounded bg-muted" />
        </div>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Document not found.</p>
      </div>
    )
  }

  const Icon = CONTENT_TYPE_ICONS[doc.content_type as ContentType] ?? CONTENT_TYPE_ICONS.notes

  const renderedHighlightItems = (docAnnotations ?? []).map((ann) => {
    const sectionHeading = sectionMap.get(ann.section_id)?.heading ?? ""
    return (
      <li key={ann.id} className="flex items-start gap-2 px-3 py-2 hover:bg-accent/50 group">
        <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", COLOR_CLASSES[ann.color] ?? COLOR_CLASSES.yellow)} />
        <button
          onClick={() => navigateToHighlight(ann)}
          className="min-w-0 flex-1 text-left"
        >
          <p className="truncate text-xs text-foreground" title={ann.selected_text}>
            {ann.selected_text.length > 50 ? `${ann.selected_text.slice(0, 50)}...` : ann.selected_text}
          </p>
          {sectionHeading && (
            <p className="truncate text-[10px] text-muted-foreground">{sectionHeading}</p>
          )}
        </button>
        <button
          onClick={() => void handleDeleteHighlight(ann.id)}
          title="Remove highlight"
          className="shrink-0 mt-0.5 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity"
        >
          <Trash2 size={12} />
        </button>
      </li>
    )
  })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Back button + Compare my notes (S197) */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft size={14} />
            Back to library
          </button>
          <span className="text-muted-foreground/40">·</span>
          <button
            onClick={goBack}
            disabled={historyDepth === 0}
            title={historyDepth === 0 ? "No previous view" : "Back to previous view (Cmd/Ctrl+[)"}
            className={cn(
              "flex items-center gap-1.5 text-sm transition-colors",
              historyDepth === 0
                ? "cursor-not-allowed text-muted-foreground/40"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <ChevronLeft size={14} />
            Back
          </button>
        </div>
        {noteCount >= 3 && (
          <button
            onClick={() => {
              setChatPreload({ text: "compare my notes with this book", documentId, autoSubmit: true })
              window.dispatchEvent(
                new CustomEvent("luminary:navigate", { detail: { tab: "chat" } })
              )
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
          >
            <GitCompareArrows size={14} />
            Compare my notes
          </button>
        )}
      </div>

      {/* Two-panel layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — 60%; relative for SelectionActionBar absolute positioning */}
        <div ref={readerContainerRef} className="relative flex w-3/5 flex-col overflow-hidden border-r border-border">
          {/* Document header — hidden in PDF/Book view to maximise canvas area */}
          {leftTab !== "pdfview" && leftTab !== "bookview" && leftTab !== "read" && (
            <>
              <div className="px-6 py-4">
                <h1 className="text-lg font-bold text-foreground">{doc.title}</h1>
                <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                  <Icon size={14} />
                  <span className="capitalize">{doc.content_type}</span>
                  <span>·</span>
                  <span>{formatWordCount(doc.word_count)}</span>
                  <span>·</span>
                  <span>{relativeDate(doc.created_at)}</span>
                </div>
                <div className="mt-3">
                  <IngestionHealthPanel documentId={documentId} stage={doc.stage} />
                </div>
              </div>

              {/* S152: Resume banner — shown once per session when a saved position exists */}
              {resumePosition && (
                <ResumeBanner
                  position={resumePosition}
                  onResume={handleResume}
                  onDismiss={handleDismissResume}
                />
              )}
            </>
          )}

          {/* Left panel tab bar — Sections / Read / PDF View (PDF only) / Book View (EPUB only) + highlight toggle */}
          <div className="flex border-b border-border">
            {(doc.format === "pdf"
              ? (["sections", "read", "pdfview"] as const)
              : doc.format === "epub"
                ? (["sections", "read", "bookview"] as const)
                : (["sections", "read"] as const)
            ).map((tab) => (
              <button
                key={tab}
                onClick={() => {
                  if (leftTab !== tab) {
                    pushHistory()
                    setLeftTab(tab)
                  }
                }}
                className={cn(
                  "flex-1 py-2 text-xs font-medium transition-colors",
                  leftTab === tab
                    ? "border-b-2 border-primary text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab === "pdfview"
                  ? "PDF View"
                  : tab === "bookview"
                    ? "Book View"
                    : tab === "read"
                      ? "Read"
                      : "Sections"}
              </button>
            ))}
            {/* Highlight visibility toggle + dropdown */}
            <div className="relative flex items-center">
              <button
                onClick={() => setHighlightsVisible((v) => !v)}
                title={highlightsVisible ? "Hide highlights" : "Show highlights"}
                className={cn(
                  "relative flex items-center justify-center px-2 py-2 text-xs transition-colors",
                  highlightsVisible
                    ? "text-yellow-600 dark:text-yellow-400"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Highlighter size={14} />
                {(docAnnotations ?? []).length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-bold text-primary-foreground">
                    {(docAnnotations ?? []).length}
                  </span>
                )}
              </button>
              {(docAnnotations ?? []).length > 0 && (
                <button
                  ref={highlightsToggleRef}
                  onClick={() => setHighlightsPanelOpen((v) => !v)}
                  title="Manage highlights"
                  className="flex items-center justify-center px-1 py-2 text-muted-foreground hover:text-foreground"
                >
                  <ChevronRight size={10} className={cn("transition-transform", highlightsPanelOpen && "rotate-90")} />
                </button>
              )}
              {/* Highlights dropdown panel */}
              {highlightsPanelOpen && (docAnnotations ?? []).length > 0 && (
                <div
                  ref={highlightsPanelRef}
                  className="absolute top-full right-0 z-50 mt-1 w-72 max-h-64 overflow-auto rounded-lg border border-border bg-background shadow-xl"
                >
                  <div className="px-3 py-2 border-b border-border">
                    <p className="text-xs font-medium text-foreground">{(docAnnotations ?? []).length} highlight{(docAnnotations ?? []).length !== 1 ? "s" : ""}</p>
                  </div>
                  <ul className="divide-y divide-border">
                    {renderedHighlightItems}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {/* S146: PDF View — lazy-mounted, hidden when not active to preserve page state */}
          {doc.format === "pdf" && pdfViewVisited && (() => {
            let targetPdfPage = initialPage
            if (!targetPdfPage && initialSectionId) {
              const sec = doc.sections.find((s) => s.id === initialSectionId)
              if (sec && sec.page_start > 0) targetPdfPage = sec.page_start
            }
            return (
              <div className={cn("flex-1 overflow-hidden", leftTab !== "pdfview" && "hidden")}>
                <PDFViewer ref={pdfViewerRef} documentId={documentId} sections={doc.sections} initialPage={targetPdfPage} annotations={docAnnotations ?? []} highlightsVisible={highlightsVisible} onPageChange={handlePageChange} />
              </div>
            )
          })()}

          {/* S149: Book View — lazy-mounted for EPUB documents */}
          {bookViewVisited && (
            <div className={cn("flex-1 overflow-hidden", leftTab !== "bookview" && "hidden")}>
              <EPUBViewer documentId={documentId} />
            </div>
          )}

          {/* Read View — full document content as markdown, or transcript for YouTube */}
          <div className={cn("flex-1 overflow-hidden", leftTab !== "read" && "hidden")}>
            {isYouTube ? (
              <YouTubeTranscriptView doc={doc} initialSectionId={readSectionId} initialChunkId={initialChunkId} />
            ) : (
              <ReadView
                documentId={documentId}
                initialSectionId={readSectionId}
                annotations={docAnnotations ?? []}
                highlightsVisible={highlightsVisible}
              />
            )}
          </div>

          {/* S147: SelectionActionBar — fires on selections in both section list and PDF viewer */}
          <SelectionActionBar
            containerRef={readerContainerRef}
            resolveSourceRef={resolveSourceRef}
            onExplain={handleExplain}
            onAddToNote={handleSelectionAddToNote}
            onCreateFlashcard={handleSelectionCreateFlashcard}
            onAskInChat={handleSelectionAskInChat}
            onHighlight={(text, sourceRef, color) => void handleSelectionHighlight(text, sourceRef, color)}
            onClip={(text, sourceRef) => void handleSelectionClip(text, sourceRef)}
          />

          {/* Section list */}
          <div
            ref={sectionListRef}
            className={cn(
              "relative flex-1 overflow-auto pb-6",
              (leftTab === "pdfview" || leftTab === "bookview" || leftTab === "read") && "hidden",
            )}
          >
            {leftTab === "sections" && (
              <>
                {/* Sticky "current section" banner — only shown when the user
                    has engaged with a section via any action. Lets them jump
                    back after the section list scrolls away from focus. */}
                {activeSectionId && sectionMap.has(activeSectionId) && (
                  <div className="sticky top-0 z-10 -mb-px border-b border-border bg-background/95 px-6 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/80">
                    <div className="flex items-center gap-2">
                      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Current
                      </span>
                      <button
                        type="button"
                        onClick={() => scrollActiveSectionIntoView(activeSectionId)}
                        className="flex-1 truncate text-left text-sm font-medium text-foreground hover:text-primary"
                        title="Jump to this section in the list"
                      >
                        {sectionMap.get(activeSectionId)?.heading || "(Untitled section)"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setActiveSectionId(null)}
                        className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
                        title="Clear current section"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                )}
                {notesError && (
                  <p className="mb-2 px-6 pt-3 text-xs text-muted-foreground">
                    Note indicators unavailable — could not load notes.
                  </p>
                )}
                <div className="px-6 pt-3">
                  {/* S151: Inline search bar — shown when Cmd+F is pressed */}
                  {searchOpen && (
                    <InDocSearchBar
                      documentId={documentId}
                      onResults={(results) => {
                        setSearchResults(results)
                        setSearchHitIndex(0)
                      }}
                      onClose={() => {
                        setSearchOpen(false)
                        setSearchResults([])
                        setSearchHitIndex(0)
                      }}
                      hitIndex={searchHitIndex}
                      totalHits={searchResults.length}
                      onPrev={() =>
                        setSearchHitIndex((i) =>
                          (i - 1 + searchResults.length) % searchResults.length,
                        )
                      }
                      onNext={() =>
                        setSearchHitIndex((i) => (i + 1) % searchResults.length)
                      }
                    />
                  )}
                  {doc.sections.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No sections detected.</p>
                  ) : (
                    <>
                      {sectionTree.childrenOf.size > 0 && (
                        <div className="mb-2 flex items-center justify-end gap-3 text-[11px] text-muted-foreground">
                          <button
                            type="button"
                            onClick={() => setCollapsedParents(new Set())}
                            className="hover:text-foreground"
                          >
                            Expand all
                          </button>
                          <span>·</span>
                          <button
                            type="button"
                            onClick={() => {
                              const next = new Set<string>()
                              for (const s of doc.sections) {
                                if ((sectionTree.childrenOf.get(s.id)?.length ?? 0) > 0) next.add(s.id)
                              }
                              setCollapsedParents(next)
                            }}
                            className="hover:text-foreground"
                          >
                            Collapse all
                          </button>
                        </div>
                      )}
                      <ul className="space-y-3">
                        {renderedSectionItems}
                      </ul>
                    </>
                  )}
                  {doc.sections.length > listLimit && (
                    <div className="mt-6 flex justify-center pb-10">
                      <button
                        onClick={() => setListLimit((prev) => prev + 500)}
                        className="flex items-center gap-2 rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-muted transition-colors shadow-sm"
                      >
                        <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
                        Load next 500 sections
                      </button>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right panel — 40%, sticky */}
        <div className="w-2/5 overflow-auto p-6">
          {/* Video player for video documents (S121) */}
          {isVideo && videoUrl && (
            <VideoPlayer videoRef={videoRef} videoUrl={videoUrl} />
          )}
          {/* Chapter Goals panel — only visible for tech_book/tech_article with extracted objectives */}
          <ChapterGoalsPanel
            documentId={documentId}
            sectionId={activeSectionGoals}
            onStudyClick={handleStudyClick}
          />
          <SummaryPanel
            documentId={documentId}
            contentType={doc.content_type}
            activeSectionId={readSectionId}
            onNoteCountKnown={setNoteCount}
            onScrollToSection={(sectionId) => {
              if (leftTab !== "read") {
                pushHistory()
                setReadSectionId(sectionId)
                setLeftTab("read")
              } else {
                const el = document.getElementById(`read-sec-${sectionId}`)
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            }}
          />
        </div>
      </div>

      {/* Audio mini-player — sticky bottom bar, audio documents only (S120) */}
      {isAudio && audioUrl && (
        <AudioMiniPlayer
          audioRef={audioRef}
          audioUrl={audioUrl}
          playing={audioPlaying}
          currentTime={audioCurrentTime}
          duration={audioDuration}
          onPlayPause={handleAudioPlayPause}
          onSeek={handleAudioSeek}
          onTimeUpdate={() => {
            if (audioRef.current) setAudioCurrentTime(audioRef.current.currentTime)
          }}
          onLoadedMetadata={() => {
            if (audioRef.current) setAudioDuration(audioRef.current.duration)
          }}
          onEnded={() => setAudioPlaying(false)}
        />
      )}

      {/* Feynman dialog (S144) */}
      {feynmanSection && (
        <FeynmanDialog
          documentId={documentId}
          sectionId={feynmanSection}
          concept={doc.sections.find((s) => s.id === feynmanSection)?.heading ?? ""}
          onClose={() => {
            const sid = feynmanSection
            setFeynmanSection(null)
            if (sid) {
              // Push so Back returns to whatever tab the dialog was opened from.
              if (leftTab !== "sections") pushHistory()
              setLeftTab("sections")
              scrollActiveSectionIntoView(sid)
            }
          }}
        />
      )}

      {/* S147: Note creation dialog — pre-filled with selected text blockquote */}
      <NoteCreationDialog
        open={selectionNoteOpen}
        selectedText={selectionNoteText}
        sourceRef={selectionNoteSourceRef}
        sectionHeading={selectionNoteHeading}
        onClose={() => setSelectionNoteOpen(false)}
        onSaved={(note: Note) => {
          void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
          void qc.invalidateQueries({ queryKey: ["reader-notes"] })
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          void qc.invalidateQueries({ queryKey: ["collections"] })
          setEditingCreatedNote(note)
        }}
      />

      {/* NoteEditorDialog -- opens after NoteCreationDialog saves for full editing */}
      <NoteEditorDialog
        note={editingCreatedNote}
        onClose={() => setEditingCreatedNote(null)}
        onSaved={(_updated) => {
          void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
          void qc.invalidateQueries({ queryKey: ["reader-notes"] })
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          void qc.invalidateQueries({ queryKey: ["collections"] })
          setEditingCreatedNote(null)
        }}
      />

      {/* S147: Flashcard generation dialog — scoped to selected text context */}
      <DocumentFlashcardDialog
        open={selectionFlashcardOpen}
        documentId={documentId}
        sectionId={selectionFlashcardSourceRef?.sectionId}
        sectionHeading={selectionFlashcardHeading}
        context={selectionFlashcardText}
        onClose={() => setSelectionFlashcardOpen(false)}
      />

      {/* Explanation sheet */}
      <ExplanationSheet
        open={sheetOpen}
        text={sheetText}
        documentId={documentId}
        mode={sheetMode}
        onClose={() => setSheetOpen(false)}
      />
    </div>
  )
}
