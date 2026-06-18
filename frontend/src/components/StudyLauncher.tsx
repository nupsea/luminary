// StudyLauncher -- one sheet every study entry point opens (docs/study-launcher.md).
// Reads launcherStore; mounted once in App.tsx. Opened via the luminary:launch-study
// event. Honest preview + tier-aware teach-back; Start records a Study Event and
// routes to Study.

import { useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useLauncherStore, type StudyMode } from "@/store/launcherStore"
import { LAUNCH_STUDY_EVENT, type StudyScope } from "@/lib/studyLauncher"

const MODES: { id: StudyMode; label: string }[] = [
  { id: "quick_quiz", label: "Quick quiz" },
  { id: "full_session", label: "Full session" },
  { id: "drill", label: "Drill" },
]
const LENGTHS = [5, 15, 25]

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "rounded-full border px-3 py-1 text-sm transition-colors " +
        (active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-accent")
      }
    >
      {children}
    </button>
  )
}

export function StudyLauncher() {
  const {
    open, scope, mode, lengthMin, loading, starting, error, preview, teachbackAvailable,
    openWith, close, setMode, setLength, start,
  } = useLauncherStore()

  // open via the cross-surface event bus (I-11)
  useEffect(() => {
    function onLaunch(e: Event) {
      const detail = (e as CustomEvent<{ scope: StudyScope }>).detail
      if (detail?.scope) openWith(detail.scope)
    }
    window.addEventListener(LAUNCH_STUDY_EVENT, onLaunch)
    return () => window.removeEventListener(LAUNCH_STUDY_EVENT, onLaunch)
  }, [openWith])

  async function onStart() {
    const res = await start()
    if (res) {
      window.dispatchEvent(new CustomEvent("luminary:navigate", { detail: { tab: "study" } }))
    }
  }

  const scopeLabel = scope?.label ?? scope?.ref ?? (scope?.type === "daily" ? "Today's pick" : scope?.type)

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Study</DialogTitle>
          <DialogDescription>
            Scope · <span className="text-foreground">{scopeLabel}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Mode</div>
            <div className="flex flex-wrap gap-2">
              {MODES.map((m) => (
                <Pill key={m.id} active={mode === m.id} onClick={() => setMode(m.id)}>
                  {m.label}
                </Pill>
              ))}
            </div>
            {teachbackAvailable && (
              <div className="text-xs text-muted-foreground">Teach-back available at the end.</div>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Length</div>
            <div className="flex gap-2">
              {LENGTHS.map((n) => (
                <Pill key={n} active={lengthMin === n} onClick={() => setLength(n)}>
                  {n} min
                </Pill>
              ))}
            </div>
          </div>

          <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
            {loading ? (
              <Skeleton className="h-4 w-3/4" />
            ) : error ? (
              <span className="text-amber-600 dark:text-amber-400">{error}</span>
            ) : preview ? (
              <PreviewLine />
            ) : (
              <span className="text-muted-foreground">Pick something to study.</span>
            )}
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={onStart}
            disabled={starting}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {starting ? "Starting…" : "Start →"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PreviewLine() {
  const preview = useLauncherStore((s) => s.preview)
  if (!preview) return null
  const { due_count, generated_count, unmapped_count, topic_mix, thin_scope_warning } = preview
  const total = due_count + generated_count
  return (
    <div className="space-y-1">
      <div>
        {total === 0 ? (
          <span className="text-muted-foreground">No due cards in this scope yet.</span>
        ) : (
          <>
            <span className="text-foreground">{due_count} due</span>
            {generated_count > 0 && <> + {generated_count} generated</>}
            {topic_mix.length > 0 && (
              <span className="text-muted-foreground"> · {topic_mix.slice(0, 3).join(", ")}</span>
            )}
          </>
        )}
      </div>
      {unmapped_count > 0 && (
        <div className="text-xs text-muted-foreground">{unmapped_count} not yet mapped to a concept</div>
      )}
      {thin_scope_warning && (
        <div className="text-xs text-amber-600 dark:text-amber-400">{thin_scope_warning}</div>
      )}
    </div>
  )
}
