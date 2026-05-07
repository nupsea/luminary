import { useIngestionTracker } from "@/hooks/ingestionTrackerCore"

const STAGE_LABELS: Record<string, string> = {
  parsing: "parsing",
  transcribing: "transcribing",
  classifying: "classifying",
  chunking: "chunking",
  embedding: "embedding",
  indexing: "indexing",
  entity_extract: "extracting entities",
  complete: "complete",
}

function ProgressPie({ value }: { value: number }) {
  // Donut-style pie. r=8, circumference ≈ 50.27
  const r = 8
  const c = 2 * Math.PI * r
  const clamped = Math.max(0, Math.min(100, value))
  const offset = c - (clamped / 100) * c
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" className="shrink-0">
      <circle cx="11" cy="11" r={r} fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <circle
        cx="11"
        cy="11"
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 11 11)"
        style={{ transition: "stroke-dashoffset 300ms ease" }}
      />
    </svg>
  )
}

function truncate(s: string, n = 32): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

export function IngestionProgressPills() {
  const { jobs } = useIngestionTracker()
  const active = Object.values(jobs).filter((j) => j.status === "processing")
  if (active.length === 0) return null

  return (
    <div className="pointer-events-none fixed bottom-4 left-4 z-40 flex flex-col gap-2">
      {active.map((job) => (
        <div
          key={job.docId}
          className="pointer-events-auto flex items-center gap-2 rounded-full border border-border bg-background/95 px-3 py-1.5 shadow-md backdrop-blur text-primary"
          title={`${job.filename} — ${STAGE_LABELS[job.stage] ?? job.stage}`}
        >
          <ProgressPie value={job.progressPct} />
          <div className="flex flex-col leading-tight text-foreground">
            <span className="text-xs font-medium">{truncate(job.filename)}</span>
            <span className="text-[10px] text-muted-foreground">
              {STAGE_LABELS[job.stage] ?? job.stage} · {job.progressPct}%
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
