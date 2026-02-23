import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BookOpen, MessageSquare, Network, BarChart2, Activity } from "lucide-react"
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom"
import { cn } from "./lib/utils"
import Chat from "./pages/Chat"
import Learning from "./pages/Learning"
import Monitoring from "./pages/Monitoring"
import Study from "./pages/Study"
import Viz from "./pages/Viz"

const queryClient = new QueryClient()

const NAV_ITEMS = [
  { to: "/", icon: BookOpen, label: "Learning" },
  { to: "/chat", icon: MessageSquare, label: "Chat" },
  { to: "/viz", icon: Network, label: "Viz" },
  { to: "/study", icon: BarChart2, label: "Study" },
  { to: "/monitoring", icon: Activity, label: "Monitoring" },
] as const

function Sidebar() {
  return (
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
    </nav>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="flex h-screen w-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-auto">
            <Routes>
              <Route path="/" element={<Learning />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/viz" element={<Viz />} />
              <Route path="/study" element={<Study />} />
              <Route path="/monitoring" element={<Monitoring />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
