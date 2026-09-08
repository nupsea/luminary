import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ChevronLeft, ChevronRight, GitCompareArrows, Highlighter, MessageSquare, PanelRightClose, PanelRightOpen, RefreshCw, Search, Sparkles, StickyNote, Target, Trash2, X } from "lucide-react"
import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useBackNavigation } from "@/hooks/useBackNavigation"
import { toast } from "sonner"

import type { ExplainMode } from "@/components/FloatingToolbar"
import { IngestionHealthPanel } from "@/components/library/IngestionHealthPanel"
import type { ContentType } from "@/components/library/types"
import { CONTENT_TYPE_ICONS, formatWordCount, isYouTubeDoc, relativeDate } from "@/components/library/utils"
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/apiClient"
import { API_BASE } from "@/lib/config"
import { useTimeOnTask } from "@/lib/useTimeOnTask"
import { cn, stripMarkdown } from "@/lib/utils"
import { useAppStore } from "@/store"

import { ChapterGoalsPanel } from "./ChapterGoalsPanel"
import { DocumentFlashcardPanel } from "./DocumentFlashcardPanel"
import { isSurfaceVisible } from "@/lib/surfaceManifest"

// Full-mode only, folded at BUILD time. FEYNMAN_VISIBLE below gates rendering,
// which hid the button but still compiled the panel and its /feynman/* calls
// into the public Learning chunk. LUMINARY_MODE is a vite `define`, so a public
// build folds this to null and drops the dynamic import.
// Compared against `import.meta.env.VITE_LUMINARY_MODE`, NOT the exported
// LUMINARY_MODE constant. vite `define` substitutes the env expression
// textually before parsing, so this folds to `"public" === "full"` -> false and
// Rollup drops the branch with its dynamic import. LUMINARY_MODE is the return
// value of resolveMode(), which Rollup cannot constant-fold -- using it here
// emits a separate chunk that still ships. Measured both ways.
const loadLastPracticed =
  import.meta.env.VITE_LUMINARY_MODE === "full"
    ? (documentId: string) =>
        import("./feynmanSessions").then((m) => m.lastPracticedBySection(documentId))
    : null

const FeynmanPanel =
  import.meta.env.VITE_LUMINARY_MODE === "full"
    ? lazy(() => import("./FeynmanPanel").then((m) => ({ default: m.FeynmanPanel })))
    : null

import { EPUBViewer } from "./EPUBViewer"
import { ExplanationPanel } from "./ExplanationPanel"
import { prefetchFeynmanSummary } from "./feynmanSummaryCache"
import { COLOR_CLASSES } from "./highlightColors"
import { readerLandingTab } from "./hooks/readerLandingTab"
import { useReaderHistory, type ReaderPlace } from "./hooks/useReaderHistory"
import { useReaderKeyboardShortcuts } from "./hooks/useReaderKeyboardShortcuts"
import { useReaderTabs } from "./hooks/useReaderTabs"
import { useReadingProgress } from "./hooks/useReadingProgress"
import { useSectionListCollapse } from "./hooks/useSectionListCollapse"
import { useSelectionWorkflow } from "./hooks/useSelectionWorkflow"
import { InDocSearchBar, type DocumentSectionSearchResult } from "./InDocSearchBar"
import { orderHitsByDocument } from "./searchHighlight"
import { AudioMiniPlayer, VideoPlayer } from "./MediaPlayers"
import { NoteComposer } from "@/components/notes/NoteComposer"
import { PDFViewer, type PDFViewerHandle } from "./PDFViewer"
import { ReadView } from "./ReadView"
import { resolveChunkFromDom, resolveFromDom, resolvePdfFallback } from "./resolveSourceRefUtils"
import { ResumeBanner, type ReadingPosition } from "./ResumeBanner"
import { SectionListItem, type SectionHeatmapItem } from "./SectionListItem"
import { SelectionActionBar } from "./SelectionActionBar"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"
import { SummaryPanel } from "./SummaryPanel"
import { ChatConversation } from "@/pages/Chat/ChatConversation"
import { docThreadKey } from "@/store/chatThreads"
import type { AnnotationItem, DocumentDetail, SectionItem } from "./types"
import { YouTubeTranscriptView } from "./YouTubeTranscriptView"

// The Feynman session talks to the `feynman` router, which only full mode mounts.
// Gated on content type alone, the button shipped in public builds and answered 404.
const FEYNMAN_VISIBLE = isSurfaceVisible("feynman")

// Error Boundary

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

const fetchDocument = (id: string): Promise<DocumentDetail> =>
  apiGet<DocumentDetail>(`/documents/${id}`)

// Minimal note shape: the section indicator needs the location, the docked
// Notes tab needs enough to show a row.
interface NoteEntry {
  id: string
  section_id: string | null
  content: string
  title?: string | null
}

// Which face of the docked panel is showing.
type PanelTab = "insights" | "ask" | "note" | "practice" | "explain"

const PANEL_TABS: { id: PanelTab; label: string }[] = [
  { id: "insights", label: "Insights" },
  { id: "ask", label: "Ask AI" },
  { id: "note", label: "Notes" },
  { id: "practice", label: "Practice" },
  { id: "explain", label: "Explain" },
]


interface DocumentReaderProps {
  documentId: string
  onBack: () => void
  initialSectionId?: string
  initialChunkId?: string
  /** A note to open in the panel, handed back by the full note page. */
  initialNoteId?: string
  /** The cited passage as words, marked in whichever view renders this document. */
  initialCitationWords?: string[]
  initialPage?: number  // PDF page to navigate to on mount (from citation deep-link)
  initialSearch?: string  // opens the in-doc search bar prefilled (from Map entity deep-link)
}

export function DocumentReader(props: DocumentReaderProps) {
  return (
    <DocumentReaderErrorBoundary>
      <DocumentReaderBase {...props} />
    </DocumentReaderErrorBoundary>
  )
}

const EMPTY_WORDS: string[] = []

function DocumentReaderBase({ documentId, onBack, initialSectionId, initialChunkId, initialNoteId, initialCitationWords = EMPTY_WORDS, initialPage, initialSearch }: DocumentReaderProps) {
  const qc = useQueryClient()

  // Reading time exists nowhere else: opening a document and reading it for
  // twenty minutes is one request, so the server would record it as an instant.
  useTimeOnTask("document", documentId)

  const { data: doc, isLoading, isError, refetch } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => fetchDocument(documentId),
    staleTime: 60_000,
  })

  const sectionListRef = useRef<HTMLDivElement>(null)
  const readerContainerRef = useRef<HTMLDivElement>(null)
  const insights = useResizablePanel({
    storageKey: "luminary-reader-insights",
    defaultWidth: 460,
    minWidth: 280,
    maxWidth: 900,
  })
  const pdfViewerRef = useRef<PDFViewerHandle>(null)

  // A deep link names a passage, which only the Read view can scroll to.
  const hasDeepLink = Boolean(initialSectionId || initialChunkId || initialPage)
  // A page is not a passage: it means something in the PDF viewer and nothing in
  // the Read view, so only a named section or chunk overrides the format.
  const hasPassageLink = Boolean(initialSectionId || initialChunkId)

  // Arriving from a citation, the source gets the room.
  //
  // The insights panel takes roughly a third of the width, and the page is fitted
  // to what is left -- so a cited PDF opened at about 118%, which on a paper is
  // text too small to read, and widening it would only have traded that for
  // sideways scrolling. Collapsing the panel gives the page the width instead, and
  // fit-width follows it.
  //
  // Transient, and deliberately not written to the panel's stored state: the
  // reader did not ask for their layout to change, so reopening it once puts
  // everything back and it stays back.
  const [insightsRestored, setInsightsRestored] = useState(false)
  const citationOwnsScroll = initialCitationWords.length > 0
  const focusOnCitation = citationOwnsScroll && !insightsRestored
  const insightsCollapsed = insights.collapsed || focusOnCitation
  const toggleInsights = useCallback(() => {
    setInsightsRestored(true)
    // Only actually toggle when the panel is where the reader last left it;
    // otherwise this click is undoing the citation focus, not collapsing.
    if (!focusOnCitation) insights.toggle()
  }, [focusOnCitation, insights])

  const {
    leftTab,
    setLeftTab,
    pdfViewVisited,
    setPdfViewVisited,
    bookViewVisited,
    setBookViewVisited,
  } = useReaderTabs({ format: doc?.format, hasDeepLink, hasPassageLink })

  // The explanation the panel is holding. Empty means the face is idle, which
  // is also what unmounts the stream.
  const [explainText, setExplainText] = useState("")
  const [explainMode, setExplainMode] = useState<ExplainMode>("plain")
  const [openNoteEditor, setOpenNoteEditor] = useState<string | null>(null) // section id
  const [docNoteOpen, setDocNoteOpen] = useState(false) // note on the document, no section
  const [openNoteId, setOpenNoteId] = useState<string | null>(initialNoteId ?? null)
  const [highlightsVisible, setHighlightsVisible] = useState(true)
  const [highlightsPanelOpen, setHighlightsPanelOpen] = useState(false)
  const [pdfCurrentPage, setPdfCurrentPage] = useState(1)
  const pageTimerRef = useRef<ReturnType<typeof setTimeout>>(null)
  
  const handlePageChange = useCallback((page: number) => {
    pdfPageRef.current = page
    if (pageTimerRef.current) clearTimeout(pageTimerRef.current)
    pageTimerRef.current = setTimeout(() => {
      setPdfCurrentPage(page)
    }, 100)
  }, [])
  const highlightsPanelRef = useRef<HTMLDivElement>(null)
  const highlightsToggleRef = useRef<HTMLButtonElement>(null)
  const [readSectionId, setReadSectionId] = useState<string | null>(null)
  // tracks which section's goals are shown in ChapterGoalsPanel; null = show all
  const [activeSectionGoals, setActiveSectionGoals] = useState<string | null>(null)
  // Feynman mode — section id the docked session is for; null = no session
  const [feynmanSection, setFeynmanSection] = useState<string | null>(null)
  // Unified "section the user is currently focused on" — set by every section
  // action (Read, Practice, Note, PDF jump, Goals, citation deep-link). Drives
  // the sticky banner in the sections tab and the active-row visual treatment.
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)

  // in-document Cmd+F search state
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<DocumentSectionSearchResult[]>([])
  const [searchHitIndex, setSearchHitIndex] = useState(0)
  const [listLimit, setListLimit] = useState(200)
  // Initial query pushed into the in-doc search bar when the Tags tab fires
  // a tag click. Cleared on consumption so subsequent ⌘F opens fresh.
  const [pendingSearchQuery, setPendingSearchQuery] = useState<string>("")
  // The settled term, lifted out of the search bar so the Read view can mark
  // it in the prose. Jumping to a hit that is not visibly marked is why search
  // read as broken there: the section list at least shows a snippet.
  const [searchTerm, setSearchTerm] = useState<string>("")

  // reading position — resume banner
  const [resumePosition, setResumePosition] = useState<ReadingPosition | null>(null)
  // Saved PDF page from the position API (used for PDFViewer initialPage)
  const [savedPdfPage, setSavedPdfPage] = useState<number | null>(null)
  // ref tracking the last section_id we POSTed so we only POST when it changes
  const lastPostedSectionRef = useRef<string | null>(null)
  // Last PDF page included in a throttled position POST
  const lastPostedPdfPageRef = useRef<number | null>(null)
  // Live PDF page for position POSTs (updated immediately on page change)
  const pdfPageRef = useRef(1)
  // throttle timer: one POST per 10 seconds max
  const positionThrottleRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setStudySectionFilter = useAppStore((s) => s.setStudySectionFilter)
  const navigate = useNavigate()
  const { canGoBack, backLabel: hookBackLabel, goBack: goBackToSource } = useBackNavigation()
  // DocumentReader falls back to onBack (library list) when no from state is set
  const backLabel = canGoBack ? hookBackLabel : "Back to library"
  const backAction = canGoBack ? goBackToSource : onBack
  const setChatPreload = useAppStore((s) => s.setChatPreload)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const setPendingStudyStart = useAppStore((s) => s.setPendingStudyStart)

  // Header "Delete" -> removes the open document without a trip back to the library.
  const [confirmDelete, setConfirmDelete] = useState(false)
  const deleteDocumentMutation = useMutation({
    mutationFn: () => apiDelete(`/documents/${documentId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents"] })
      void qc.invalidateQueries({ queryKey: ["documents-recent"] })
      toast.success("Document deleted")
      // The document this view is bound to no longer exists, so leave it.
      onBack()
    },
    onError: () => toast.error("Failed to delete document. Please try again."),
  })

  // Audio mini-player state — only active for audio documents
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [audioPlaying, setAudioPlaying] = useState(false)
  const [audioCurrentTime, setAudioCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)

  // Video player state — only active for video documents
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const isAudio = doc?.content_type === "audio"
  const isVideo = doc?.content_type === "video"
  const isYouTube = isYouTubeDoc(doc ?? {})

  // Pre-calculate section map for O(1) lookups in highlight loops
  const docFormat = doc?.format
  const docSections = doc?.sections
  const sectionMap = useMemo(() => {
    const m = new Map<string, SectionItem>()
    if (docSections) {
      for (const s of docSections) m.set(s.id, s)
    }
    return m
  }, [docSections])

  // Reading position of each section, so search hits can be stepped through in
  // document order rather than the relevance order the endpoint returns.
  const sectionOrder = useMemo(() => {
    const m = new Map<string, number>()
    ;(docSections ?? []).forEach((s, i) => m.set(s.id, i))
    return m
  }, [docSections])

  // Insights is what the panel has always held; every other face is a workflow
  // that used to open over the passage it is about -- this document's own
  // conversation, its note composer, its flashcards and Feynman session, and an
  // explanation of a selection.
  // Arriving with a note is arriving at the note: the panel opens on it.
  const [insightsTab, setInsightsTab] = useState<PanelTab>(initialNoteId ? "note" : "insights")
  // Where a transient face returns the panel when it closes. One ref for all of
  // them: the last face to take over is the one that has somewhere to go back to.
  const tabBefore = useRef<PanelTab>("insights")
  const showPanel = useCallback((tab: PanelTab) => {
    setInsightsRestored(true)
    if (insightsTab !== tab) tabBefore.current = insightsTab
    setInsightsTab(tab)
  }, [insightsTab, setInsightsRestored, setInsightsTab])
  const openAsk = useCallback(() => { showPanel("ask") }, [showPanel])
  const openNotes = useCallback(() => { showPanel("note") }, [showPanel])
  const openPractice = useCallback(() => { showPanel("practice") }, [showPanel])
  const selection = useSelectionWorkflow({
    documentId,
    sectionMap,
    setChatPreload,
    openAsk,
    openNote: openNotes,
    openPractice,
  })

  // What the docked composer is holding: a selected passage, a section's own
  // note button, or a blank note on the document. The selection comes first --
  // it is the only one of the three that carries text, and a capture that
  // arrives while the composer is open appends rather than being dropped.
  const noteCaptureOpen =
    selection.noteOpen || openNoteEditor !== null || docNoteOpen || openNoteId !== null
  const noteCaptureKey = selection.noteOpen
    ? `sel-${selection.noteCaptureId}`
    : openNoteEditor
      ? `sec-${openNoteEditor}`
      : docNoteOpen
        ? "doc"
        : openNoteId
          ? `note-${openNoteId}`
          : null
  const { noteOpen, noteText, noteHeading, noteSourceRef, closeNote } = selection
  const noteCaptureContent = useMemo(() => {
    if (!noteOpen) return ""
    const parts = [noteSourceRef?.documentTitle, noteHeading].filter(Boolean)
    const attribution = parts.length > 0 ? parts.join(", ") : ""
    return `> "${noteText}"\n>\n> -- ${attribution}`
  }, [noteOpen, noteText, noteHeading, noteSourceRef])
  const closeNoteCapture = useCallback(() => {
    closeNote()
    setOpenNoteEditor(null)
    setDocNoteOpen(false)
    setOpenNoteId(null)
    setInsightsTab(tabBefore.current)
  }, [closeNote, setOpenNoteEditor, setDocNoteOpen, setOpenNoteId, setInsightsTab])

  const {
    sectionTree,
    collapsedParents,
    setCollapsedParents,
    toggleCollapsed,
    isSectionHidden,
  } = useSectionListCollapse(doc?.sections, sectionMap, doc?.id)

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

  // Scroll to initialSectionId once document sections are loaded.
  //
  // A citation owns the scroll instead. Both this and the Read-tab effect below
  // put the section *heading* at the top of the port, which for a chapter-length
  // section leaves the cited passage off screen -- and being armed by the same
  // navigation, they fire last and undo the centring. The passage is inside this
  // section anyway, so landing on it lands here.
  useEffect(() => {
    if (!initialSectionId || !doc || citationOwnsScroll) return
    // Wait a tick for DOM to update after doc is available
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-section-id="${initialSectionId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [initialSectionId, doc, citationOwnsScroll])

  // Explicit scroll when switching to the Read tab from a section.
  //
  // Suppressed only for the section the reader arrived at with a citation; any
  // section they pick afterwards scrolls normally.
  useEffect(() => {
    if (leftTab === "read" && readSectionId && !(citationOwnsScroll && readSectionId === initialSectionId)) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`read-sec-${readSectionId}`)
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" })
        }
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [leftTab, readSectionId, initialSectionId, citationOwnsScroll])

  // Keep activeSectionId in sync with whichever per-action state was most
  // recently touched. Priority: Feynman > Read > Goals > Note editor.
  useEffect(() => {
    const next = feynmanSection ?? readSectionId ?? activeSectionGoals ?? openNoteEditor
    if (next) setActiveSectionId(next)
  }, [feynmanSection, readSectionId, activeSectionGoals, openNoteEditor])


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

  const navigateToPlace = useCallback((prev: ReaderPlace) => {
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
  }, [setLeftTab, setPdfViewVisited, setBookViewVisited])

  const { historyDepth, pushHistory, goBack } = useReaderHistory({
    currentPlace: {
      tab: leftTab,
      sectionId: activeSectionId,
      pdfPage: leftTab === "pdfview" ? pdfCurrentPage : null,
    },
    navigateTo: navigateToPlace,
  })

  // Reading a section: from its row in the list, or from a note that was taken
  // there. Pushes "Sections tab focused on this section" as the
  // place-to-return-to, so Back scrolls back to that exact row.
  const goToSection = useCallback((sid: string) => {
    const sec = sectionMap.get(sid)
    pushHistory({ tab: "sections", sectionId: sid, pdfPage: null })
    setReadSectionId(sid)
    if (docFormat === "pdf" && sec && sec.page_start > 0) {
      setPdfViewVisited(true)
      setLeftTab("pdfview")
      pdfViewerRef.current?.goToPage(sec.page_start)
      return
    }
    setLeftTab("read")
  }, [sectionMap, pushHistory, setLeftTab, setPdfViewVisited, docFormat])

  // Fire the pending scroll once the Sections tab has actually rendered.
  // scrollActiveSectionIntoView itself retries with RAF until the row exists
  // in the DOM, so no setTimeout is required here.
  useEffect(() => {
    if (leftTab !== "sections" || !pendingScrollRef.current) return
    const sid = pendingScrollRef.current
    pendingScrollRef.current = null
    scrollActiveSectionIntoView(sid)
  }, [leftTab, scrollActiveSectionIntoView])


  // The tab a document opens on: its own viewer for PDF and EPUB, the Read
  // view for a deep link and for every other format.
  useEffect(() => {
    if (!doc) return
    const tab = readerLandingTab(doc.format, hasDeepLink)
    if (initialSectionId) setReadSectionId(initialSectionId)
    if (tab === "pdfview") setPdfViewVisited(true)
    if (tab === "bookview") setBookViewVisited(true)
    setLeftTab(tab)
  }, [doc?.format, initialSectionId, initialPage]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch notes for this document so dot indicators persist across reloads
  const { data: docNotes, isError: notesError, isLoading: notesLoading } = useQuery<NoteEntry[]>({
    queryKey: ["notes-for-doc", documentId],
    queryFn: () => apiGet<NoteEntry[]>("/notes", { document_id: documentId }),
    staleTime: 30_000,
  })

  // Auto-collection for this document: used to lock the collection chip
  // when capturing a note from a selection.
  const { data: autoCollection } = useQuery<{ id: string } | null>({
    queryKey: ["auto-collection-by-doc", documentId],
    queryFn: async () => {
      try {
        return await apiGet<{ id: string }>(`/collections/by-document/${documentId}`)
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null
        throw err
      }
    },
    staleTime: 60_000,
  })

  // Fetch annotations for highlight reconstruction and panel
  const {
    data: docAnnotations,
  } = useQuery<AnnotationItem[]>({
    queryKey: ["annotations-for-doc", documentId],
    queryFn: () =>
      apiGet<AnnotationItem[]>("/annotations", { document_id: documentId }),
    staleTime: 30_000,
  })

  // Fetch objective progress for mini rings on section headers
  const { data: progressData } = useQuery<{
    by_chapter: { section_id: string; progress_pct: number }[]
  }>({
    queryKey: ["doc-progress", documentId],
    queryFn: async () => {
      try {
        return await apiGet<{
          by_chapter: { section_id: string; progress_pct: number }[]
        }>(`/documents/${documentId}/progress`)
      } catch {
        return { by_chapter: [] }
      }
    },
    staleTime: 60_000,
  })

  const progressBySectionId = useMemo(
    () => new Map((progressData?.by_chapter ?? []).map((c) => [c.section_id, c.progress_pct])),
    [progressData],
  )

  // derived set of section IDs that have a search hit (O(1) lookup)
  const searchHitSectionIds = useMemo(
    () => new Set(searchResults.map((r) => r.section_id)),
    [searchResults],
  )

  // Group annotations by section for O(1) retrieval in section list
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

  // Pre-calculate search snippet map for O(1) retrieval
  const searchSnippetMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of searchResults) {
      if (r.snippet) m.set(r.section_id, r.snippet)
    }
    return m
  }, [searchResults])

  const closeReaderSearch = useCallback(() => {
    setSearchOpen(false)
    setSearchResults([])
    setSearchHitIndex(0)
    setSearchTerm("")
  }, [])

  // The search belongs to the document, not to one tab. The bar is rendered
  // once above both panes, so Sections and Read each keep it where the reader
  // already is -- opening it used to switch tabs to reach it. The PDF viewer
  // owns Cmd+F on its own tab, so a bare keypress there is left alone; a
  // query-carrying open (deep link, tag click) still needs somewhere to land,
  // so it moves off pdfview/bookview.
  const openReaderSearch = useCallback((query?: string) => {
    if (leftTab === "pdfview" && query === undefined) return
    if (leftTab !== "sections" && leftTab !== "read") setLeftTab("read")
    if (query !== undefined) setPendingSearchQuery(query)
    setSearchOpen(true)
  }, [leftTab, setLeftTab])

  useReaderKeyboardShortcuts({
    onBack: goBack,
    onOpenSearch: openReaderSearch,
    onCloseSearch: closeReaderSearch,
    searchOpen,
  })

  useEffect(() => {
    if (leftTab !== "sections" && leftTab !== "read" && searchOpen) closeReaderSearch()
  }, [leftTab, searchOpen, closeReaderSearch])

  // Map entity deep-link (?search=) -> open the in-doc search bar prefilled
  // once the document is loaded. Idempotent (no ref guard) so StrictMode's
  // double-invoke is harmless; pendingSearchQuery is cleared on consumption.
  useEffect(() => {
    const query = initialSearch?.trim()
    if (!query || !doc) return
    openReaderSearch(query)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSearch, doc])

  // Tags-tab click -> open in-doc search with the tag's surface form prefilled.
  // Listens on window so the panel doesn't need a prop drilled through SummaryPanel.
  // Depends on openReaderSearch (re-registers on tab change) so the tab-landing
  // check inside it never reads a leftTab captured at mount.
  useEffect(() => {
    function onDocSearch(e: Event) {
      const detail = (e as CustomEvent<{ query?: string }>).detail
      const query = detail?.query?.trim()
      if (!query) return
      openReaderSearch(query)
    }
    window.addEventListener("luminary:doc-search", onDocSearch)
    return () => window.removeEventListener("luminary:doc-search", onDocSearch)
  }, [openReaderSearch])

  // Scroll the current hit into view when hitIndex or results change.
  //
  // The pane matters. ReadView stays mounted and CSS-hidden on every tab, and
  // it renders `data-section-id` *earlier in the DOM* than the section list, so
  // a bare `document.querySelector` always resolved to the hidden Read pane --
  // which is why stepping through hits on the Sections tab appeared to do
  // nothing at all. Each tab is therefore addressed by its own handle:
  // `read-sec-<id>` belongs only to ReadView, and the section list is queried
  // through its own container ref.
  // On Read the hit is handed to ReadView as its target (below), which widens
  // its own window and scrolls -- a hit past the rendered window has no element
  // to scroll to yet. Only the section list is scrolled from here.
  useEffect(() => {
    if (leftTab !== "sections" || searchResults.length === 0) return
    const targetId = searchResults[searchHitIndex]?.section_id
    if (targetId) scrollActiveSectionIntoView(targetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchHitIndex, searchResults, leftTab])

  // The section ReadView should show: a search hit while searching, otherwise
  // whatever a citation or resume link pointed at.
  const searchHitSectionId = searchResults[searchHitIndex]?.section_id ?? null
  const readTargetSectionId =
    searchOpen && searchHitSectionId ? searchHitSectionId : readSectionId

  function handleStudyClick(sid: string) {
    setActiveDocument(documentId)
    setStudySectionFilter({ sectionId: sid, bloomLevelMin: 2 })
    void navigate("/study", { state: { from: "/library" } })
  }

  // Fetch FSRS fragility heatmap for section coloring
  const { data: heatmapData } = useQuery<Record<string, SectionHeatmapItem>>({
    queryKey: ["section-heatmap", documentId],
    queryFn: async () => {
      try {
        const data = await apiGet<{
          heatmap: Record<string, SectionHeatmapItem>
        }>("/study/section-heatmap", { document_id: documentId })
        return data.heatmap
      } catch {
        return {}
      }
    },
    staleTime: 60_000,
  })

  // Map of section_id -> ISO timestamp of most recent Feynman session.
  // Powers the "last practiced" badge in the section list.
  const { data: lastPracticedBySection } = useQuery<Map<string, string>>({
    queryKey: ["feynman-sessions-by-section", documentId],
    queryFn: () =>
      loadLastPracticed ? loadLastPracticed(documentId) : new Map<string, string>(),
    enabled: !!loadLastPracticed,
    staleTime: 30_000,
  })

  // Derive the set of section IDs that have at least one note
  const notedSections = useMemo(
    () => new Set((docNotes ?? []).map((n) => n.section_id).filter((id): id is string => id !== null && id !== undefined)),
    [docNotes],
  )

  // Track reading progress via IntersectionObserver (3-second dwell per section)
  useReadingProgress(documentId, doc?.sections.length ?? 0, readerContainerRef)

  // fetch saved reading position on mount; show ResumeBanner unless already dismissed this session
  useEffect(() => {
    if (!doc) return
    const dismissedKey = `resume-dismissed-${documentId}`
    if (sessionStorage.getItem(dismissedKey)) return
    void apiGet<ReadingPosition>(`/documents/${documentId}/position`)
      .then((pos) => {
        if (!pos) return
        if (pos.last_pdf_page != null) setSavedPdfPage(pos.last_pdf_page)
        if (pos.last_section_id || pos.last_pdf_page != null) setResumePosition(pos)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) return
        // banner failure is silent
      })
  }, [documentId, doc])

  // IntersectionObserver — track the topmost visible section and throttle-POST position
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
        const pdfPage = doc!.format === "pdf" ? pdfPageRef.current : null
        void apiPost(`/documents/${documentId}/position`, {
          last_section_id: sectionId,
          last_section_heading: section?.heading ?? null,
          last_pdf_page: pdfPage,
          last_epub_chapter_index: null,
        }).catch(() => {})
        lastPostedSectionRef.current = sectionId
        if (pdfPage != null) lastPostedPdfPageRef.current = pdfPage
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

  // Persist PDF page turns (same 10s throttle as section position posts)
  useEffect(() => {
    if (!doc || doc.format !== "pdf") return
    if (pdfCurrentPage === lastPostedPdfPageRef.current) return
    if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
    positionThrottleRef.current = setTimeout(() => {
      const sectionId = lastPostedSectionRef.current
      const section = sectionId ? doc.sections.find((s) => s.id === sectionId) : undefined
      void apiPost(`/documents/${documentId}/position`, {
        last_section_id: sectionId,
        last_section_heading: section?.heading ?? null,
        last_pdf_page: pdfCurrentPage,
        last_epub_chapter_index: null,
      }).catch(() => {})
      lastPostedPdfPageRef.current = pdfCurrentPage
    }, 10_000)
    return () => {
      if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
    }
  }, [documentId, doc, pdfCurrentPage])

  const handleResume = () => {
    if (resumePosition?.last_pdf_page != null && doc?.format === "pdf") {
      setPdfViewVisited(true)
      setLeftTab("pdfview")
      window.setTimeout(() => pdfViewerRef.current?.goToPage(resumePosition.last_pdf_page as number), 50)
      setResumePosition(null)
      sessionStorage.setItem(`resume-dismissed-${documentId}`, "1")
      return
    }
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
      // The chunk, when the view has one: a transcript renders chunk by chunk,
      // and the moment a note came from lives on that row.
      const chunkId = resolveChunkFromDom(node)
      const fromDom = resolveFromDom(node)
      if (fromDom) return { sectionId: fromDom, documentId, documentTitle: doc?.title ?? "", chunkId }
      if (doc?.format === "pdf" && doc.sections.length > 0) {
        const fromPdf = resolvePdfFallback(doc.sections, pdfCurrentPage)
        if (fromPdf) return { sectionId: fromPdf, documentId, documentTitle: doc?.title ?? "", pageNumber: pdfCurrentPage }
      }
      return { sectionId: undefined, documentId, documentTitle: doc?.title ?? "" }
    },
    [doc, pdfCurrentPage, documentId],
  )

  const handleExplain = useCallback((text: string, mode: ExplainMode) => {
    setExplainText(text)
    setExplainMode(mode)
    showPanel("explain")
  }, [setExplainText, setExplainMode, showPanel])

  const closeExplain = useCallback(() => {
    setExplainText("")
    setInsightsTab(tabBefore.current)
  }, [setExplainText, setInsightsTab])

  // A section's Practice button opens the session in the panel, not over it.
  const openFeynman = useCallback((sectionId: string) => {
    setFeynmanSection(sectionId)
    showPanel("practice")
  }, [setFeynmanSection, showPanel])

  const closeFeynman = useCallback(() => {
    const sid = feynmanSection
    setFeynmanSection(null)
    setInsightsTab(tabBefore.current)
    if (sid) {
      // Push so Back returns to whatever tab the session was opened from.
      if (leftTab !== "sections") pushHistory()
      setLeftTab("sections")
      scrollActiveSectionIntoView(sid)
    }
  }, [feynmanSection, leftTab, pushHistory, setLeftTab, scrollActiveSectionIntoView,
      setFeynmanSection, setInsightsTab])

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
      await apiDelete(`/annotations/${id}`)
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlight removed")
    } catch {
      toast.error("Could not remove highlight")
    }
  }, [documentId, qc])

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


  // Use virtualization for the section list if it's very large.
  const renderedSectionItems = useMemo(() => {
    if (!doc?.sections) return null
    // Filter out sections whose ancestor is collapsed *before* slicing, so
    // virtualization counts visible rows (not raw section count).
    const visible = doc.sections.filter((s) => !isSectionHidden(s))
    const sectionsToRender = visible.slice(0, listLimit)

    return sectionsToRender.map((section) => {
      const hasNote = notedSections.has(section.id)
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
          heatmapItem={heatmapItem}
          searchHit={searchHitSectionIds.has(section.id)}
          searchSnippet={searchSnippetMap.get(section.id)}
          progressPct={progressBySectionId.get(section.id)}
          annotations={annotationsBySection.get(section.id) ?? []}
          feynmanEnabled={FEYNMAN_VISIBLE && (doc.content_type === "tech_book" || doc.content_type === "tech_article")}
          isActive={activeSectionId === section.id}
          lastPracticedAt={lastPracticedBySection?.get(section.id)}
          childCount={sectionTree.descendantCount.get(section.id) ?? 0}
          isCollapsed={collapsedParents.has(section.id)}
          onToggleCollapsed={toggleCollapsed}
          onRead={goToSection}
          onPdfJump={(p) => {
            // The page anchor lives on a specific section — return to it.
            pushHistory({ tab: "sections", sectionId: section.id, pdfPage: null })
            setPdfViewVisited(true)
            setLeftTab("pdfview")
            pdfViewerRef.current?.goToPage(p)
          }}
          onMediaJump={(t) => isAudio ? seekAndPlay(t) : seekAndPlayVideo(t)}
          onToggleNote={(sid) => {
            setOpenNoteEditor(openNoteEditor === sid ? null : sid)
            if (openNoteEditor !== sid) openNotes()
          }}
          onFeynman={openFeynman}
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
    listLimit,
    goToSection,
    openNotes,
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

  if (isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-muted-foreground">
          Couldn't load this document. The backend may be starting up or unreachable.
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={() => void refetch()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Retry
          </button>
          <button
            onClick={onBack}
            className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
          >
            Back to library
          </button>
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
      {/* Back button + Compare my notes */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <button
            onClick={backAction}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft size={14} />
            {backLabel}
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
        <div className="flex items-center gap-2">
          {/* In-context actions for this document: study, generate questions, chat */}
          <button
            onClick={() => {
              // Land directly in a session scoped to this document -- skip the
              // launcher popup. Study.tsx auto-starts from pendingStudyStart once
              // the doc scope resolves.
              setActiveCollectionId(null)
              setActiveDocument(documentId)
              setPendingStudyStart({ documentId, mode: "flashcard" })
              navigate("/study", { state: { from: "/library" } })
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            title="Study this document"
          >
            <Target size={14} />
            Study
          </button>
          <button
            onClick={() => { selection.closeFlashcard(); openPractice() }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            title="Generate questions from this document"
          >
            <Sparkles size={14} />
            Generate questions
          </button>
          <button
            // The conversation about this document is docked beside it, already
            // scoped to it, so this shows the panel rather than leaving the page.
            onClick={openAsk}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            title="Chat about this document"
          >
            <MessageSquare size={14} />
            Chat
          </button>
          <div className="relative">
            <button
              onClick={() => setConfirmDelete((open) => !open)}
              className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30 transition-colors"
              title="Delete this document"
            >
              <Trash2 size={14} />
              Delete
            </button>
            {confirmDelete && (
              <div className="absolute right-0 top-full z-50 mt-2 w-72 rounded-md border border-destructive/30 bg-popover px-3 py-2.5 shadow-lg">
                <p className="mb-2 text-xs text-foreground">
                  Delete <span className="font-semibold">{doc.title}</span>?
                </p>
                <p className="mb-2 text-xs text-muted-foreground">
                  This also deletes the uploaded file itself, along with its
                  chunks, vectors, highlights and notes. It cannot be undone.
                </p>
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="rounded border border-border px-2.5 py-1 text-xs hover:bg-accent"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      setConfirmDelete(false)
                      deleteDocumentMutation.mutate()
                    }}
                    disabled={deleteDocumentMutation.isPending}
                    className="rounded bg-destructive px-2.5 py-1 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                  >
                    {deleteDocumentMutation.isPending ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
            )}
          </div>
          {(docNotes?.length ?? 0) > 0 && (
            <button
              // The notes on this document are in the panel beside it, not on
              // another page.
              onClick={openNotes}
              className="flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-0.5 text-xs font-medium text-foreground/80 hover:bg-muted transition-colors"
              title="Notes on this document"
            >
              <StickyNote size={12} />
              {docNotes?.length ?? 0} note{(docNotes?.length ?? 0) === 1 ? "" : "s"}
            </button>
          )}
          {(docNotes?.length ?? 0) >= 3 && (
            <button
              onClick={() => {
                setChatPreload({
                  text: "compare my notes with this book",
                  documentId,
                  autoSubmit: true,
                  threadKey: docThreadKey(documentId),
                })
                openAsk()
              }}
              className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            >
              <GitCompareArrows size={14} />
              Compare my notes
            </button>
          )}
        </div>
      </div>

      {/* Two-panel layout; capturing a note docks into the panel, over nothing */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* Left panel — 60%; relative for SelectionActionBar absolute positioning */}
        <div ref={readerContainerRef} className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Document header — hidden in PDF/Book view to maximise canvas area.
              The ingestion diagnostics grid (chunk/vector/entity counts) is a
              processing-health readout, not reading chrome: it stays on Sections,
              where it sits next to the structure it describes, and is hidden on
              Read so opening a document to read it doesn't put a stats dashboard
              above the text. */}
          {leftTab !== "pdfview" && leftTab !== "bookview" && (
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
                {leftTab === "sections" && (
                  <div className="mt-3">
                    <IngestionHealthPanel documentId={documentId} stage={doc.stage} />
                  </div>
                )}
              </div>

              {/* Resume banner — shown once per session when a saved position exists */}
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
            {/* Search — the only affordance for it was Cmd+F, which is
                undiscoverable and unreachable on a touch device. PDF View has
                its own search, so the button follows the tabs that use this one. */}
            {(leftTab === "sections" || leftTab === "read") && (
              <button
                onClick={() => (searchOpen ? closeReaderSearch() : openReaderSearch())}
                title="Search in document (⌘F)"
                aria-label="Search in document"
                aria-pressed={searchOpen}
                className={cn(
                  "flex items-center justify-center px-2 py-2 text-xs transition-colors",
                  searchOpen
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Search size={14} />
              </button>
            )}
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

          {/* In-document search — shared by Sections and Read, which both key
              off data-section-id, so it stays put across a tab switch instead
              of living inside one tab's content. */}
          {searchOpen && (leftTab === "sections" || leftTab === "read") && (
            <div className="px-6 pt-3">
              <InDocSearchBar
                documentId={documentId}
                initialQuery={pendingSearchQuery}
                onConsumeInitialQuery={() => setPendingSearchQuery("")}
                onQueryChange={setSearchTerm}
                onResults={(results) => {
                  setSearchResults(orderHitsByDocument(results, sectionOrder))
                  setSearchHitIndex(0)
                }}
                onClose={() => {
                  closeReaderSearch()
                  setPendingSearchQuery("")
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
            </div>
          )}

          {/* PDF View — lazy-mounted, hidden when not active to preserve page state */}
          {doc.format === "pdf" && pdfViewVisited && (() => {
            let targetPdfPage = initialPage
            if (!targetPdfPage && savedPdfPage != null) targetPdfPage = savedPdfPage
            if (!targetPdfPage && initialSectionId) {
              const sec = doc.sections.find((s) => s.id === initialSectionId)
              if (sec && sec.page_start > 0) targetPdfPage = sec.page_start
            }
            return (
              <div className={cn("flex-1 overflow-hidden", leftTab !== "pdfview" && "hidden")}>
                <PDFViewer ref={pdfViewerRef} citationWords={initialCitationWords} documentId={documentId} sections={doc.sections} pageLabels={doc.page_labels ?? undefined} initialPage={targetPdfPage} annotations={docAnnotations ?? []} highlightsVisible={highlightsVisible} onPageChange={handlePageChange} />
              </div>
            )
          })()}

          {/* Book View — lazy-mounted for EPUB documents */}
          {bookViewVisited && (
            <div className={cn("flex-1 overflow-hidden", leftTab !== "bookview" && "hidden")}>
              <EPUBViewer documentId={documentId} />
            </div>
          )}

          {/* Read View — full document content as markdown, or transcript for YouTube.
              `data-reading-surface` marks this as the only pane whose sections count
              as reading: the contents list carries data-section-id too, and scrolling
              a table of contents is not reading the document. */}
          <div
            data-reading-surface=""
            className={cn("flex-1 overflow-hidden", leftTab !== "read" && "hidden")}
          >
            {isYouTube ? (
              <YouTubeTranscriptView doc={doc} initialSectionId={readTargetSectionId} initialChunkId={initialChunkId} />
            ) : (
              <ReadView
                documentId={documentId}
                initialSectionId={readTargetSectionId}
                annotations={docAnnotations ?? []}
                highlightsVisible={highlightsVisible}
                contentType={doc.content_type}
                structureType={doc.structure_type}
                extractionReport={doc.extraction_report}
                sourceUrl={doc.source_url}
                searchTerm={searchOpen ? searchTerm : ""}
                citationWords={initialCitationWords}
                citedSectionId={initialSectionId}
              />
            )}
          </div>

          {/* SelectionActionBar — fires on selections in both section list and PDF viewer */}
          <SelectionActionBar
            containerRef={readerContainerRef}
            resolveSourceRef={resolveSourceRef}
            onExplain={handleExplain}
            onAddToNote={selection.handleAddToNote}
            onCreateFlashcard={selection.handleCreateFlashcard}
            onAskInChat={selection.handleAskInChat}
            onHighlight={(text, sourceRef, color) => void selection.handleHighlight(text, sourceRef, color)}
            onClip={(text, sourceRef) => void selection.handleClip(text, sourceRef)}
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

        <PanelResizer
          onPointerDown={insights.onPointerDown}
          dragging={insights.dragging}
          label="Resize insights panel"
        />

        {insightsCollapsed && (
          <button
            type="button"
            onClick={toggleInsights}
            aria-label="Show insights"
            title="Show insights"
            className="flex w-8 shrink-0 items-start justify-center border-l border-border pt-4 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <PanelRightOpen size={16} />
          </button>
        )}
        {/* Hidden rather than unmounted: collapsing the panel is a layout
            change, and it may not cost a streaming answer or an unsaved note
            draft. */}
        <div
          className={`flex shrink-0 flex-col overflow-hidden ${insightsCollapsed ? "hidden" : ""}`}
          style={{ width: insights.width }}
        >
          <div className="flex items-center gap-1 border-b border-border px-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {PANEL_TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setInsightsTab(id)}
                aria-pressed={insightsTab === id}
                className={`shrink-0 rounded-md px-2 py-1 text-xs transition-colors ${
                  insightsTab === id
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
            </div>
            <button
              type="button"
              onClick={toggleInsights}
              aria-label="Hide insights"
              title="Hide insights"
              className="ml-1 shrink-0 text-muted-foreground hover:text-foreground"
            >
              <PanelRightClose size={16} />
            </button>
          </div>
          {/* Both stay mounted: a docked conversation that unmounted on every tab
              switch would drop a streaming answer. */}
          <div className={`min-h-0 flex-1 overflow-hidden ${insightsTab === "ask" ? "" : "hidden"}`}>
            <ChatConversation
              variant="docked"
              threadKey={docThreadKey(documentId)}
              pinnedDocumentId={documentId}
            />
          </div>
          <div className={`min-h-0 flex-1 overflow-hidden ${insightsTab === "note" ? "" : "hidden"}`}>
            {noteCaptureOpen ? (
              <NoteComposer
                variant="docked"
                open
                captureKey={noteCaptureKey}
                noteId={openNoteId}
                onClose={closeNoteCapture}
                onSaved={() => {
                  void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
                  void qc.invalidateQueries({ queryKey: ["reader-notes"] })
                  void qc.invalidateQueries({ queryKey: ["notes"] })
                  void qc.invalidateQueries({ queryKey: ["notes-groups"] })
                }}
                initialContent={noteCaptureContent}
                initialSourceDocIds={[documentId]}
                lockedCollectionId={autoCollection?.id ?? null}
                documentId={documentId}
                // Where the note came from, structured rather than only quoted
                // in its text: a selection's own section, or the section whose
                // note button was pressed. Without the first of these a note
                // taken from a passage stored no section at all, and nothing
                // could resolve it back.
                sectionId={selection.noteSourceRef?.sectionId ?? openNoteEditor}
                chunkId={selection.noteSourceRef?.chunkId}
              />
            ) : (
              <div className="flex h-full min-h-0 flex-col overflow-auto p-4">
                <button
                  type="button"
                  onClick={() => {
                    tabBefore.current = "note"
                    setDocNoteOpen(true)
                  }}
                  className="mb-3 flex w-fit items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
                >
                  <StickyNote size={13} />
                  New note
                </button>
                {notesLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <div key={i} className="h-12 animate-pulse rounded bg-muted" />
                    ))}
                  </div>
                ) : notesError ? (
                  <p className="text-xs text-destructive">Could not load notes for this document.</p>
                ) : (docNotes?.length ?? 0) === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No notes on this document yet. Select a passage and choose Note, or start one
                    above.
                  </p>
                ) : (
                  <ul data-testid="docked-notes-list" className="space-y-2">
                    {docNotes?.map((n) => (
                      <li key={n.id} className="rounded-md border border-border transition-colors hover:border-muted-foreground/30">
                        <button
                          type="button"
                          // A note opened from a document is edited beside it.
                          onClick={() => {
                            tabBefore.current = "note"
                            setOpenNoteId(n.id)
                          }}
                          className="w-full rounded-t-md px-3 py-2 text-left hover:bg-muted/50"
                        >
                          <p className="truncate text-xs text-foreground">
                            {n.title?.trim() || stripMarkdown(n.content).slice(0, 90) || "Untitled note"}
                          </p>
                        </button>
                        {n.section_id && (
                          <button
                            type="button"
                            onClick={() => goToSection(n.section_id!)}
                            className="w-full truncate rounded-b-md border-t border-border/60 px-3 py-1 text-left text-[10px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                          >
                            Go to {sectionMap.get(n.section_id)?.heading ?? "the passage"}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          {/* Practice: this document's flashcards, and the Feynman session that
              takes the face over while one is running. */}
          <div className={`min-h-0 flex-1 overflow-hidden ${insightsTab === "practice" ? "" : "hidden"}`}>
            {feynmanSection && FeynmanPanel ? (
              <Suspense fallback={null}>
                <FeynmanPanel
                  documentId={documentId}
                  sectionId={feynmanSection}
                  concept={doc.sections.find((s) => s.id === feynmanSection)?.heading ?? ""}
                  onClose={closeFeynman}
                />
              </Suspense>
            ) : (
              <DocumentFlashcardPanel
                documentId={documentId}
                // A selection scopes the generator; with none it is the document.
                sectionHeading={selection.flashcardOpen ? selection.flashcardHeading : undefined}
                context={selection.flashcardOpen ? selection.flashcardText : ""}
                onClearScope={selection.closeFlashcard}
              />
            )}
          </div>
          <div className={`min-h-0 flex-1 overflow-hidden ${insightsTab === "explain" ? "" : "hidden"}`}>
            {explainText ? (
              <ExplanationPanel
                // A new passage is a new explanation, not a reset of this one.
                key={`${explainMode}:${explainText}`}
                text={explainText}
                documentId={documentId}
                mode={explainMode}
                onClose={closeExplain}
              />
            ) : (
              <div className="p-4">
                <p className="text-xs text-muted-foreground">
                  Select a passage and choose Explain. The explanation streams here, beside the
                  text it is about.
                </p>
              </div>
            )}
          </div>
          <div className={`min-h-0 flex-1 overflow-auto p-6 ${insightsTab === "insights" ? "" : "hidden"}`}>
          {/* Video player for video documents */}
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
            form={doc.facets?.form}
          />
          </div>
        </div>

      </div>

      {/* Audio mini-player — sticky bottom bar, audio documents only */}
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

    </div>
  )
}
