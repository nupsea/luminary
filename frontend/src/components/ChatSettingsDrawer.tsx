import { Globe } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"

interface WebSearchSettings {
  provider: string
  enabled: boolean
}

interface ChatSettingsDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  model: string
  onModelChange: (model: string) => void
  modelOptions: string[]
  llmLoading: boolean
  webEnabled: boolean
  onWebToggle: () => void
  webSearchSettings: WebSearchSettings | undefined
  scope: "single" | "all"
  onScopeChange: (scope: "single" | "all") => void
}

export function ChatSettingsDrawer({
  open,
  onOpenChange,
  model,
  onModelChange,
  modelOptions,
  llmLoading,
  webEnabled,
  onWebToggle,
  webSearchSettings,
  scope,
  onScopeChange,
}: ChatSettingsDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-80">
        <SheetHeader>
          <SheetTitle>Chat Settings</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Scope */}
          <div className="space-y-2">
            <p className="text-sm font-medium">Scope</p>
            <div className="flex items-center rounded-md border border-border">
              <button
                onClick={() => onScopeChange("single")}
                className={`flex-1 rounded-l-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  scope === "single"
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50"
                }`}
              >
                This document
              </button>
              <button
                onClick={() => onScopeChange("all")}
                className={`flex-1 rounded-r-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  scope === "all"
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50"
                }`}
              >
                All my content
              </button>
            </div>
          </div>

          {/* LLM Model */}
          <div className="space-y-2">
            <p className="text-sm font-medium">LLM Model</p>
            {llmLoading ? (
              <Skeleton className="h-8 w-full" />
            ) : modelOptions.length > 0 ? (
              <select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-xs text-muted-foreground">
                Cloud routing active -- no model selection needed
              </p>
            )}
          </div>

          {/* Web Search */}
          <div className="space-y-2">
            <p className="text-sm font-medium">Web Search</p>
            <div
              title={
                webSearchSettings?.enabled
                  ? "Toggle web augmentation (adds current web results to low-confidence answers)"
                  : "Configure a web search provider in Settings to enable web search"
              }
            >
              <button
                disabled={!webSearchSettings?.enabled}
                onClick={onWebToggle}
                className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors ${
                  webEnabled
                    ? "border-blue-300 bg-blue-50 text-blue-700"
                    : "border-border text-muted-foreground hover:bg-accent"
                } disabled:cursor-not-allowed disabled:opacity-50`}
              >
                <Globe size={12} />
                {webEnabled ? "Web search on" : "Web search off"}
              </button>
            </div>
            {!webSearchSettings?.enabled && (
              <p className="text-xs text-muted-foreground">
                Configure a web search provider in Settings to enable.
              </p>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
