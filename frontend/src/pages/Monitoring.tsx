// Monitoring page shell: hash-persisted tab nav over four panels.
// Each tab fetches its own data via useSection, so a failed endpoint
// degrades one section, never the page (invariant I-10).

import { useEffect, useState } from "react"

import { EvalsTab } from "./Monitoring/EvalsTab"
import { MasteryPanel } from "./Monitoring/MasteryPanel"
import { OverviewTab } from "./Monitoring/OverviewTab"
import { PanelErrorBoundary } from "./Monitoring/SharedUI"
import { TracesTab } from "./Monitoring/TracesTab"
import { fetchDocuments } from "./Monitoring/api"
import type { Document } from "./Monitoring/types"
import { useSection } from "./Monitoring/useSection"

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "traces", label: "Traces" },
  { id: "evals", label: "Evals" },
  { id: "mastery", label: "Mastery" },
] as const

type TabId = (typeof TABS)[number]["id"]

function MasteryTab() {
  const docs = useSection<Document[]>("Documents", fetchDocuments, [])
  return <MasteryPanel documents={docs.data} />
}

export default function Monitoring() {
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const hash = window.location.hash.replace("#", "") as TabId
    return TABS.some((t) => t.id === hash) ? hash : "overview"
  })

  useEffect(() => {
    window.history.replaceState(null, "", `#${activeTab}`)
  }, [activeTab])

  return (
    <div className="flex flex-col gap-8 px-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Monitoring</h1>
        <div className="flex gap-1 rounded-lg border border-border bg-secondary p-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "overview" && (
        <PanelErrorBoundary name="Overview">
          <OverviewTab />
        </PanelErrorBoundary>
      )}
      {activeTab === "traces" && (
        <PanelErrorBoundary name="Traces">
          <TracesTab />
        </PanelErrorBoundary>
      )}
      {activeTab === "evals" && (
        <PanelErrorBoundary name="Evals">
          <EvalsTab />
        </PanelErrorBoundary>
      )}
      {activeTab === "mastery" && (
        <PanelErrorBoundary name="Mastery">
          <MasteryTab />
        </PanelErrorBoundary>
      )}
    </div>
  )
}
