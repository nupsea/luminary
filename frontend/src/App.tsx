import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BookOpen, MessageSquare, Network, BarChart2, Activity, StickyNote } from "lucide-react"
import { lazy, Suspense, useEffect, useState } from "react"
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom"
import { Toaster } from "sonner"
import { cn } from "./lib/utils"
import { logger } from "./lib/logger"
import { LLMModeBadge, SettingsDrawer } from "./components/SettingsDrawer"
import { SearchDialog } from "./components/SearchDialog"
import { Skeleton } from "./components/ui/skeleton"
import Chat from "./pages/Chat"
import Learning from "./pages/Learning"
import Notes from "./pages/Notes"
import Study from "./pages/Study"

const Viz = lazy(() => import("./pages/Viz"))
const Monitoring = lazy(() => import("./pages/Monitoring"))

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      logger.error("[Query]", String(query.queryKey), error instanceof Error ? error.message : String(error))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

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

const NAV_ITEMS = [
  { to: "/", icon: BookOpen, label: "Learning" },
  { to: "/chat", icon: MessageSquare, label: "Chat" },
  { to: "/viz", icon: Network, label: "Viz" },
  { to: "/study", icon: BarChart2, label: "Study" },
  { to: "/notes", icon: StickyNote, label: "Notes" },
  { to: "/monitoring", icon: Activity, label: "Monitoring" },
] as const

function Sidebar() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <>
      <nav className="flex h-full w-16 flex-col items-center gap-2 bg-sidebar py-4">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex h-10 w-10 items-center justify-center rounded-md text-sidebar-foreground transition-colors hover:bg-accent",
                isActive && "bg-accent",
              )
            }
            title={label}
          >
            <Icon size={20} />
          </NavLink>
        ))}
        <div className="mt-auto">
          <LLMModeBadge onClick={() => setSettingsOpen(true)} />
        </div>
      </nav>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}

function AppShell() {
  const [searchOpen, setSearchOpen] = useState(false)

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
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Learning />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/viz" element={<Suspense fallback={<PageSkeleton />}><Viz /></Suspense>} />
          <Route path="/study" element={<Study />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/monitoring" element={<Suspense fallback={<PageSkeleton />}><Monitoring /></Suspense>} />
        </Routes>
      </main>
      <SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  )
}

export default App
