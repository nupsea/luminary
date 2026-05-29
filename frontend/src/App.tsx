import {
  QueryCache,
  QueryClient,
  QueryClientProvider,
  useIsFetching,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import type { QueryKey } from "@tanstack/react-query"
import { Activity, AlertTriangle, BookOpen, Info, MessageSquare, Network, BarChart2, StickyNote, TrendingUp, Wrench, X, Sun, Moon, ClipboardCheck } from "lucide-react"
import { LuminaryGlyph } from "./components/icons/LuminaryGlyph"
import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { Toaster, toast } from "sonner"
import { cn } from "./lib/utils"
import { getHomeRedirectTarget } from "./lib/homeRedirect"
import { useAppStore } from "./store"
import { useSurfaceStore } from "./store/surface"
import { SURFACE_TIER, navTabs, routedSurfaces, visibleSurfaces, findLabsSurfaceByRoute } from "./lib/surfaceManifest"
import type { Surface } from "./lib/surfaceManifest"
import { logger } from "./lib/logger"
import { LLMModeBadge, SettingsDrawer } from "./components/SettingsDrawer"
import { StreakXPWidget } from "./components/StreakXPWidget"
import { SearchDialog } from "./components/SearchDialog"
import { FocusTimerPill } from "./components/FocusTimerPill"
import { Skeleton } from "./components/ui/skeleton"
import { useReviewNotification } from "./hooks/useReviewNotification"
import { IngestionTrackerProvider } from "./hooks/IngestionTrackerProvider"
import { IngestionProgressPills } from "./components/IngestionProgressPills"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./components/ui/dialog"
// All pages are lazy-loaded to reduce the initial bundle and improve tab-switch
// performance. Keyed by their manifest `frontend.component` path so the router
// and nav rail can be generated from surface-manifest.json.
const Chat = lazy(() => import("@/pages/Chat"))
const Learning = lazy(() => import("@/pages/Learning"))
const Notes = lazy(() => import("@/pages/Notes"))
const Study = lazy(() => import("@/pages/Study"))
const Viz = lazy(() => import("@/pages/Viz"))
const Quality = lazy(() => import("@/pages/Quality"))
const Progress = lazy(() => import("@/pages/Progress"))
const Admin = lazy(() => import("@/pages/Admin"))
const Monitoring = lazy(() => import("@/pages/Monitoring"))
const CollectionWorkspace = lazy(() => import("@/pages/CollectionWorkspace"))
const Hub = lazy(() => import("@/pages/Hub"))

type LazyPage = React.LazyExoticComponent<React.ComponentType<unknown>>

const COMPONENT_REGISTRY: Record<string, LazyPage> = {
  "pages/Hub": Hub,
  "pages/Learning": Learning,
  "pages/Notes": Notes,
  "pages/Study": Study,
  "pages/Chat": Chat,
  "pages/Viz": Viz,
  "pages/Progress": Progress,
  "pages/CollectionWorkspace": CollectionWorkspace,
  "pages/Quality": Quality,
  "pages/Admin": Admin,
  "pages/Monitoring": Monitoring,
}

type IconComponent = React.ComponentType<{ size?: number; className?: string }>

const ICONS: Record<string, IconComponent> = {
  luminary_hub: LuminaryGlyph,
  library: BookOpen,
  notes: StickyNote,
  study: BarChart2,
  ask: MessageSquare,
  map: Network,
  progress: TrendingUp,
  quality_dashboard: ClipboardCheck,
  admin: Wrench,
  monitoring: Activity,
}

import { apiGet } from "@/lib/apiClient"

const prefetchDocuments = (): Promise<unknown> =>
  apiGet("/documents", { sort: "newest", page: 1, page_size: 20 })

const prefetchLLMSettings = (): Promise<unknown> => apiGet("/settings/llm")

const prefetchDueCards = (): Promise<unknown> => apiGet("/study/due")

const prefetchProgressData = (): Promise<unknown> => apiGet("/study/due-count")

const prefetchHomeOverview = (): Promise<unknown> => apiGet("/home/overview")

interface PrefetchDef {
  key: QueryKey
  fn: () => Promise<unknown>
}

const PREFETCH: Record<string, PrefetchDef> = {
  luminary_hub: { key: ["home-overview"], fn: prefetchHomeOverview },
  library: { key: ["documents", undefined, null, "newest", 1, 20], fn: prefetchDocuments },
  study: { key: ["study-due"], fn: prefetchDueCards },
  ask: { key: ["llm-settings"], fn: prefetchLLMSettings },
  progress: { key: ["study-due"], fn: prefetchProgressData },
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      logger.error("[Query]", String(query.queryKey), error instanceof Error ? error.message : String(error))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 2,
      retryDelay: 1000,
    },
  },
})

// Global top-of-page loading bar

function GlobalLoadingBar() {
  const isFetching = useIsFetching({
    predicate: (query) => {
      // Exclude slow background queries from showing the loading bar
      const key = query.queryKey[0] as string
      if (key === "chat-suggestions" || key === "chat-suggestions-cached") return false
      if (key === "chat-explorations") return false
      return true
    },
  })

  useEffect(() => {
    logger.debug("[Loading bar]", { fetchingCount: isFetching })
  }, [isFetching])

  if (isFetching === 0) return null

  return (
    <div className="fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden bg-primary/20">
      <div
        className="h-full bg-primary"
        style={{ animation: "loading-bar 1.2s ease-in-out infinite" }}
      />
    </div>
  )
}

// Page skeleton (Suspense fallback for lazy routes)

function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-6">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    </div>
  )
}

// Whole-shell fallback while the surface manifest state loads, so the nav rail
// never flashes a set of tabs it then has to remove.
function BootSkeleton() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <div className="flex h-full w-[4.5rem] flex-col items-center gap-2 border-r border-border/50 bg-sidebar py-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-12 rounded-xl" />
        ))}
      </div>
      <div className="flex-1">
        <PageSkeleton />
      </div>
    </div>
  )
}

// Sidebar with hover-prefetch. Tabs are manifest-driven; `mainTabs` are the
// learner-facing rail and `devTabs` are demoted to small icons at the bottom.
function Sidebar({ mainTabs, devTabs }: { mainTabs: Surface[]; devTabs: Surface[] }) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const qc = useQueryClient()

  async function handleHoverPrefetch(prefetchKey: QueryKey, prefetchFn: () => Promise<unknown>) {
    const existing = qc.getQueryData(prefetchKey)
    if (existing !== undefined) {
      logger.debug("[Prefetch] hit", { key: String(prefetchKey[0]) })
      return
    }
    logger.info("[Prefetch] fetching", { key: String(prefetchKey[0]) })
    try {
      await qc.prefetchQuery({
        queryKey: prefetchKey,
        queryFn: prefetchFn,
        staleTime: 60_000,
      })
    } catch (e: unknown) {
      logger.warn("[Prefetch] failed", { key: String(prefetchKey[0]), error: String(e) })
    }
  }

  return (
    <>
      <nav className="flex h-full w-[4.5rem] flex-col items-center gap-1 bg-gradient-to-b from-sidebar via-sidebar to-primary/5 py-4 border-r border-border/50">
        {mainTabs.map((s) => {
          const to = s.frontend!.route!
          const Icon = ICONS[s.id] ?? BookOpen
          const label = s.labels.en
          const prefetch = PREFETCH[s.id]
          return (
            <NavLink
              key={s.id}
              to={to}
              end={to === "/" || to === "/library"}
              className={({ isActive }) =>
                cn(
                  "relative flex h-14 w-14 flex-col items-center justify-center gap-0.5 rounded-xl text-sidebar-foreground/60 transition-all duration-200 hover:bg-accent hover:text-sidebar-foreground group",
                  isActive && "bg-accent text-sidebar-foreground",
                )
              }
              title={label}
              onMouseEnter={() => {
                if (prefetch) void handleHoverPrefetch(prefetch.key, prefetch.fn)
              }}
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 h-7 w-1 rounded-r-full bg-primary transition-all" />
                  )}
                  <Icon size={18} className={cn("transition-colors", isActive && "text-primary")} />
                  <span className={cn("text-[9px] font-medium leading-none", isActive ? "text-foreground" : "text-sidebar-foreground/50 group-hover:text-sidebar-foreground/80")}>
                    {label}
                  </span>
                </>
              )}
            </NavLink>
          )
        })}
        {/* Streak & XP widget */}
        <div className="mt-auto mb-2">
          <StreakXPWidget />
        </div>
        <div className="flex flex-col items-center gap-2">
          {/* Dev-tier surfaces are demoted from the learner rail to small icons.
              They are only present here on a `dev` bundle — lower tiers shed them
              from the manifest entirely, so prod ships no link or route. */}
          {devTabs.map((s) => {
            const Icon = ICONS[s.id] ?? Wrench
            return (
              <NavLink
                key={s.id}
                to={s.frontend!.route!}
                title={`${s.labels.en} (dev)`}
                className={({ isActive }) =>
                  cn(
                    "flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/40 transition-colors hover:bg-accent hover:text-sidebar-foreground",
                    isActive && "bg-accent text-sidebar-foreground",
                  )
                }
              >
                <Icon size={14} />
              </NavLink>
            )
          })}
          <LLMModeBadge onClick={() => setSettingsOpen(true)} />
          {/* Dark mode toggle */}
          <button
            onClick={() => {
              document.documentElement.classList.toggle("dark")
            }}
            className="flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/40 transition-colors hover:bg-accent hover:text-sidebar-foreground"
            title="Toggle dark mode"
          >
            <Sun size={14} className="dark:hidden" />
            <Moon size={14} className="hidden dark:block" />
          </button>
          <AboutButton />
        </div>
      </nav>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}

// About dialog — version + surface tier info for the end user.

const TIER_META: Record<string, { label: string; color: string; description: string }> = {
  dev: {
    label: "dev",
    color: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
    description: "All surfaces enabled, including quality tools and admin panels.",
  },
  labs: {
    label: "labs",
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    description: "Experimental features toggled per-surface via the Labs panel.",
  },
  public: {
    label: "public",
    color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    description: "Stable, minimal install — only learner-facing surfaces.",
  },
}

function AboutButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/40 transition-colors hover:bg-accent hover:text-sidebar-foreground"
        title="About Luminary"
      >
        <Info size={14} />
      </button>
      <AboutDialog open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data } = useQuery<{ version: string; status: string }>({
    queryKey: ["health"],
    queryFn: () => apiGet("/health"),
    enabled: open,
    staleTime: 60_000,
  })
  const tier = SURFACE_TIER
  const meta = TIER_META[tier] ?? TIER_META.public
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <LuminaryGlyph size={18} className="text-primary" />
            Luminary
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 pt-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Version</span>
            <span className="font-medium">{data?.version ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Build tier</span>
            <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-medium", meta.color)}>
              {meta.label}
            </span>
          </div>
          <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            {meta.description}
          </p>
          <p className="text-xs text-muted-foreground">
            Local-first knowledge and learning assistant. Your documents, notes, and review history
            stay on your machine.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// The Luminary home hub (2E.7). Legacy deep-link query params (?doc,
// ?section_id, ?chunk_id, ?page, ?tag) hitting / forward to /library so
// existing bookmarks keep working; otherwise the hub renders.
function HomeRoute() {
  const { search } = useLocation()
  const target = getHomeRedirectTarget(search)
  if (target) return <Navigate to={target} replace />
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Hub />
    </Suspense>
  )
}

// Self-healing 404. A stale bookmark into a gated labs surface gets a toast and
// a redirect home rather than a dead route; truly unknown URLs just redirect.
function NotFoundRedirect() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const labsEnabled = useSurfaceStore((s) => s.labsEnabled)

  useEffect(() => {
    const labs = findLabsSurfaceByRoute(pathname)
    if (labs && SURFACE_TIER !== "dev" && !labsEnabled.has(labs.id)) {
      toast.info(`${labs.labels.en} is a Labs feature — enable it in Settings → Labs to use it.`)
    }
    navigate("/", { replace: true })
  }, [pathname, navigate, labsEnabled])

  return <PageSkeleton />
}

// App shell with startup prefetch

function AppShell() {
  const [searchOpen, setSearchOpen] = useState(false)
  const [ollamaWarningDismissed, setOllamaWarningDismissed] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const chatPanelOpen = useAppStore(s => s.chatPanelOpen)
  const setChatPanelOpen = useAppStore(s => s.setChatPanelOpen)
  const setActiveTag = useAppStore((s) => s.setActiveTag)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setNotePreload = useAppStore((s) => s.setNotePreload)

  const surfaceLoaded = useSurfaceStore((s) => s.loaded)
  const labsEnabled = useSurfaceStore((s) => s.labsEnabled)

  const mainTabs = useMemo(() => navTabs(labsEnabled).filter((s) => s.tier !== "dev"), [labsEnabled])
  const devTabs = useMemo(() => navTabs(labsEnabled).filter((s) => s.tier === "dev"), [labsEnabled])
  const routes = useMemo(() => routedSurfaces(labsEnabled), [labsEnabled])
  const pomodoroVisible = useMemo(() => visibleSurfaces(labsEnabled).some((s) => s.id === "pomodoro"), [labsEnabled])

  // Boot: load surface tier + labs toggles before rendering the rail/routes.
  useEffect(() => {
    void useSurfaceStore.getState().fetch()
  }, [])

  // Surface a global warning when Ollama is unreachable in private mode
  const { data: llmData } = useQuery<{
    processing_mode: string
    mode: string
  }>({
    queryKey: ["llm-settings"],
    queryFn: prefetchLLMSettings as () => Promise<{ processing_mode: string; mode: string }>,
    staleTime: 30_000,
  })
  const ollamaUnavailable = llmData?.mode === "private" && llmData?.processing_mode === "unavailable"
  // Reset dismissed state when Ollama comes back online
  useEffect(() => {
    if (!ollamaUnavailable) setOllamaWarningDismissed(false)
  }, [ollamaUnavailable])

  // review reminder notifications
  useReviewNotification()

  // cross-tab navigation from tag graph node click or tag chip click
  useEffect(() => {
    function onLuminaryNavigate(e: Event) {
      const detail = (e as CustomEvent<{
        tab: string
        tagFilter?: string
        filter?: { tag?: string }
        documentId?: string
        prefilledContent?: string
        collectionId?: string
      }>).detail
      const fromState = { state: { from: window.location.pathname } }
      if (detail.tab === "notes") {
        // prefilled note from gap analysis "Take a note" action
        if (detail.prefilledContent) {
          setNotePreload({ content: detail.prefilledContent, collectionId: detail.collectionId })
        }
        // Support both legacy shape (detail.tagFilter) and new shape (detail.filter.tag)
        const tagPath = detail.filter?.tag ?? detail.tagFilter ?? null
        setActiveTag(tagPath)
        navigate("/notes", fromState)
      } else if (detail.tab === "learning") {
        // source document subtitle click from NoteReaderSheet
        const target = detail.documentId ? `/library?doc=${detail.documentId}` : "/library"
        navigate(target, fromState)
      } else if (detail.tab === "chat") {
        // document action menu -> Chat about this
        // Store updates (chatSelectedDocId, chatScope) happen at dispatch site
        navigate("/chat", fromState)
      } else if (detail.tab === "study") {
        // cards due pill or document action menu
        if (detail.documentId) setActiveDocument(detail.documentId)
        navigate("/study", fromState)
      } else if (detail.tab === "viz") {
        // document action menu -> View in graph
        if (detail.documentId) setActiveDocument(detail.documentId)
        navigate("/viz")
      } else if (detail.tab === "progress") {
        // avg mastery pill click from LibraryStatsBar
        navigate("/progress")
      }
    }
    window.addEventListener("luminary:navigate", onLuminaryNavigate)
    return () => window.removeEventListener("luminary:navigate", onLuminaryNavigate)
  }, [navigate, setActiveTag, setActiveDocument, setNotePreload])

  // Startup prefetch: documents list + LLM settings
  useEffect(() => {
    const docsKey: QueryKey = ["documents", undefined, null, "newest", 1, 20]
    const llmKey: QueryKey = ["llm-settings"]

    if (qc.getQueryData(docsKey) !== undefined) {
      logger.debug("[Prefetch] hit", { key: "documents" })
    } else {
      logger.info("[Prefetch] fetching", { key: "documents" })
      void qc.prefetchQuery({
        queryKey: docsKey,
        queryFn: prefetchDocuments,
        staleTime: 60_000,
      }).catch((e: unknown) => {
        logger.warn("[Prefetch] failed", { key: "documents", error: String(e) })
      })
    }

    if (qc.getQueryData(llmKey) !== undefined) {
      logger.debug("[Prefetch] hit", { key: "llm-settings" })
    } else {
      logger.info("[Prefetch] fetching", { key: "llm-settings" })
      void qc.prefetchQuery({
        queryKey: llmKey,
        queryFn: prefetchLLMSettings,
        staleTime: 60_000,
      }).catch((e: unknown) => {
        logger.warn("[Prefetch] failed", { key: "llm-settings", error: String(e) })
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    function isTypingTarget(t: EventTarget | null): boolean {
      if (!(t instanceof HTMLElement)) return false
      if (t.isContentEditable) return true
      const tag = t.tagName
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
    }

    function onKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key === "k") {
        e.preventDefault()
        setSearchOpen((prev) => !prev)
        return
      }
      // 2C.1: ⌘+1..6 jumps to nav tabs. Skip when typing in an input so
      // a numeric keystroke inside a search field doesn't navigate.
      if (mod && !e.shiftKey && /^[1-6]$/.test(e.key) && !isTypingTarget(e.target)) {
        const idx = parseInt(e.key, 10) - 1
        const item = mainTabs[idx]
        if (item?.frontend?.route) {
          e.preventDefault()
          navigate(item.frontend.route)
        }
        return
      }
      // 2C.2: ⌘+Shift+N opens the global capture-note flow with the
      // currently-active doc preloaded as the source. ⌘+N is reserved
      // by browsers for "new window," so we add Shift.
      if (mod && e.shiftKey && e.key.toLowerCase() === "n") {
        e.preventDefault()
        const { activeDocumentId, setNotesDocumentId, setNotePreload } = useAppStore.getState()
        setNotesDocumentId(activeDocumentId)
        setNotePreload({ content: "" })
        navigate("/notes")
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [navigate, mainTabs])

  if (!surfaceLoaded) return <BootSkeleton />

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <Sidebar mainTabs={mainTabs} devTabs={devTabs} />
      <main className="flex-1 h-full overflow-auto relative animate-[fadeIn_0.2s_ease-out]">
        {ollamaUnavailable && !ollamaWarningDismissed && (
          <div className="mx-4 mt-2 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
            <AlertTriangle size={14} className="shrink-0" />
            <span className="flex-1">
              Ollama is not running. LLM features (chat, teach-back, flashcard generation) are unavailable. Start it with: <code className="font-mono font-semibold">ollama serve</code>
            </span>
            <button onClick={() => setOllamaWarningDismissed(true)} className="shrink-0 hover:text-amber-900 dark:hover:text-amber-100" aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}
        {/* global focus timer pill -- labs surface, only when pomodoro is visible */}
        {pomodoroVisible && (
          <div className="flex items-center justify-end gap-2 px-4 pt-3">
            <FocusTimerPill />
          </div>
        )}
        <Routes>
          {routes.map((s) => {
            const route = s.frontend!.route!
            if (route === "/") return <Route key={s.id} path="/" element={<HomeRoute />} />
            const Comp = COMPONENT_REGISTRY[s.frontend!.component ?? ""]
            if (!Comp) {
              logger.warn("[Routes] no component registered", { id: s.id, component: s.frontend?.component })
              return null
            }
            return (
              <Route
                key={s.id}
                path={route}
                element={<Suspense fallback={<PageSkeleton />}><Comp /></Suspense>}
              />
            )
          })}
          {SURFACE_TIER === "dev" && <Route path="/evals" element={<Navigate to="/quality" replace />} />}
          <Route path="*" element={<NotFoundRedirect />} />
        </Routes>
      </main>

      {/* Global Sliding Chat Panel Overlay */}
      <div
        className={cn(
           "fixed top-0 right-0 h-full transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] border-l border-border bg-background shadow-2xl z-50 transform flex flex-col",
           chatPanelOpen ? "w-[450px] translate-x-0 opacity-100" : "w-0 translate-x-[200px] opacity-0 pointer-events-none"
        )}
      >
        {chatPanelOpen && (
           <>
             <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-muted/30">
               <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <MessageSquare size={16} className="text-primary"/> Luminary AI
               </h2>
               <button onClick={() => setChatPanelOpen(false)} className="rounded-md p-1.5 hover:bg-accent text-muted-foreground hover:text-foreground transition-colors">
                  <X size={15}/>
               </button>
             </div>
             <div className="flex-1 overflow-hidden relative">
               <Suspense fallback={<PageSkeleton />}><Chat /></Suspense>
             </div>
           </>
        )}
      </div>

      <SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <IngestionTrackerProvider>
        <GlobalLoadingBar />
        <BrowserRouter>
          <AppShell />
        </BrowserRouter>
        <IngestionProgressPills />
        <Toaster position="bottom-right" richColors />
      </IngestionTrackerProvider>
    </QueryClientProvider>
  )
}

export default App
