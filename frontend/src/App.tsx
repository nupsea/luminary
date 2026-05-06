import {
  QueryCache,
  QueryClient,
  QueryClientProvider,
  useIsFetching,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import type { QueryKey } from "@tanstack/react-query"
import { AlertTriangle, BookOpen, MessageSquare, Network, BarChart2, TrendingUp, StickyNote, Wrench, X, Sun, Moon, ClipboardCheck } from "lucide-react"
import { lazy, Suspense, useEffect, useState } from "react"
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom"
import { Toaster } from "sonner"
import { cn } from "./lib/utils"
import { useAppStore } from "./store"
import { logger } from "./lib/logger"
import { LLMModeBadge, SettingsDrawer } from "./components/SettingsDrawer"
import { StreakXPWidget } from "./components/StreakXPWidget"
import { SearchDialog } from "./components/SearchDialog"
import { FocusTimerPill } from "./components/FocusTimerPill"
import { Skeleton } from "./components/ui/skeleton"
import { useReviewNotification } from "./hooks/useReviewNotification"
// All core pages are lazy-loaded to reduce the initial bundle and improve tab-switch
// performance. Viz and Monitoring were already lazy -- Chat, Learning, Notes, Study added in S84.
// S177: Monitoring -> Progress (learner view); Admin page added at /admin (dev view).
const Chat = lazy(() => import("./pages/Chat"))
const Learning = lazy(() => import("./pages/Learning"))
const Notes = lazy(() => import("./pages/Notes"))
const Study = lazy(() => import("./pages/Study"))
const Viz = lazy(() => import("./pages/Viz"))
const Quality = lazy(() => import("./pages/Quality"))
const Progress = lazy(() => import("./pages/Progress"))
const Admin = lazy(() => import("./pages/Admin"))

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Prefetch helpers
// ---------------------------------------------------------------------------

async function prefetchDocuments(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=20`)
  if (!res.ok) throw new Error("prefetch failed")
  return res.json()
}

async function prefetchLLMSettings(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("prefetch failed")
  return res.json()
}

async function prefetchDueCards(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/study/due`)
  if (!res.ok) throw new Error("prefetch failed")
  return res.json()
}

async function prefetchProgressData(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/study/due-count`)
  if (!res.ok) throw new Error("prefetch failed")
  return res.json()
}

// ---------------------------------------------------------------------------
// QueryClient
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Nav items with per-tab prefetch config
// ---------------------------------------------------------------------------

interface NavItemDef {
  to: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string
  prefetchKey?: QueryKey
  prefetchFn?: () => Promise<unknown>
}

const NAV_ITEMS: NavItemDef[] = [
  {
    to: "/",
    icon: BookOpen,
    label: "Learning",
    prefetchKey: ["documents", undefined, null, "newest", 1, 20],
    prefetchFn: prefetchDocuments,
  },
  {
    to: "/chat",
    icon: MessageSquare,
    label: "Chat",
    prefetchKey: ["llm-settings"],
    prefetchFn: prefetchLLMSettings,
  },
  { to: "/viz", icon: Network, label: "Viz" },
  {
    to: "/study",
    icon: BarChart2,
    label: "Study",
    prefetchKey: ["study-due"],
    prefetchFn: prefetchDueCards,
  },
  { to: "/notes", icon: StickyNote, label: "Notes" },
  { to: "/quality", icon: ClipboardCheck, label: "Quality" },
  {
    to: "/progress",
    icon: TrendingUp,
    label: "Progress",
    prefetchKey: ["study-due"],
    prefetchFn: prefetchProgressData,
  },
]

// ---------------------------------------------------------------------------
// Global top-of-page loading bar
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Page skeleton (Suspense fallback for lazy routes)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Sidebar with hover-prefetch
// ---------------------------------------------------------------------------

function Sidebar() {
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
        {NAV_ITEMS.map(({ to, icon: Icon, label, prefetchKey, prefetchFn }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "relative flex h-14 w-14 flex-col items-center justify-center gap-0.5 rounded-xl text-sidebar-foreground/60 transition-all duration-200 hover:bg-accent hover:text-sidebar-foreground group",
                isActive && "bg-accent text-sidebar-foreground",
              )
            }
            title={label}
            onMouseEnter={() => {
              if (prefetchKey && prefetchFn) {
                void handleHoverPrefetch(prefetchKey, prefetchFn)
              }
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
        ))}
        {/* Streak & XP widget */}
        <div className="mt-auto mb-2">
          <StreakXPWidget />
        </div>
        <div className="flex flex-col items-center gap-2">
          {/* Dev Tools link -- hidden from nav, accessible via this small icon at the bottom */}
          <NavLink
            to="/admin"
            title="Dev Tools"
            className={({ isActive }) =>
              cn(
                "flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/40 transition-colors hover:bg-accent hover:text-sidebar-foreground",
                isActive && "bg-accent text-sidebar-foreground",
              )
            }
          >
            <Wrench size={14} />
          </NavLink>
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
        </div>
      </nav>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}

// ---------------------------------------------------------------------------
// App shell with startup prefetch
// ---------------------------------------------------------------------------

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

  // S118: review reminder notifications
  useReviewNotification()

  // S167/S176: cross-tab navigation from tag graph node click or tag chip click
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
      if (detail.tab === "notes") {
        // S197: prefilled note from gap analysis "Take a note" action
        if (detail.prefilledContent) {
          setNotePreload({ content: detail.prefilledContent, collectionId: detail.collectionId })
        }
        // Support both legacy shape (detail.tagFilter) and new shape (detail.filter.tag)
        const tagPath = detail.filter?.tag ?? detail.tagFilter ?? null
        setActiveTag(tagPath)
        navigate("/notes")
      } else if (detail.tab === "learning") {
        // S176: source document subtitle click from NoteReaderSheet
        const target = detail.documentId ? `/?doc=${detail.documentId}` : "/"
        navigate(target)
      } else if (detail.tab === "chat") {
        // S191: document action menu -> Chat about this
        // Store updates (chatSelectedDocId, chatScope) happen at dispatch site
        navigate("/chat")
      } else if (detail.tab === "study") {
        // S183/S191: cards due pill or document action menu
        if (detail.documentId) setActiveDocument(detail.documentId)
        navigate("/study")
      } else if (detail.tab === "viz") {
        // S191: document action menu -> View in graph
        if (detail.documentId) setActiveDocument(detail.documentId)
        navigate("/viz")
      } else if (detail.tab === "progress") {
        // S183: avg mastery pill click from LibraryStatsBar
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
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setSearchOpen((prev) => !prev)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <Sidebar />
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
        {/* S209: global focus timer pill -- visible on every tab */}
        <div className="flex items-center justify-end gap-2 px-4 pt-3">
          <FocusTimerPill />
        </div>
        <Routes>
          <Route path="/" element={<Suspense fallback={<PageSkeleton />}><Learning /></Suspense>} />
          <Route path="/chat" element={<Suspense fallback={<PageSkeleton />}><Chat /></Suspense>} />
          <Route path="/viz" element={<Suspense fallback={<PageSkeleton />}><Viz /></Suspense>} />
          <Route path="/study" element={<Suspense fallback={<PageSkeleton />}><Study /></Suspense>} />
          <Route path="/notes" element={<Suspense fallback={<PageSkeleton />}><Notes /></Suspense>} />
          <Route path="/quality" element={<Suspense fallback={<PageSkeleton />}><Quality /></Suspense>} />
          <Route path="/evals" element={<Navigate to="/quality" replace />} />
          <Route path="/progress" element={<Suspense fallback={<PageSkeleton />}><Progress /></Suspense>} />
          <Route path="/admin" element={<Suspense fallback={<PageSkeleton />}><Admin /></Suspense>} />
          <Route path="/monitoring" element={<Suspense fallback={<PageSkeleton />}><Progress /></Suspense>} />
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

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <GlobalLoadingBar />
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  )
}

export default App
