import { useIngestionTracker } from "@/hooks/ingestionTrackerCore"

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing document",
  transcribing: "Transcribing audio",
  classifying: "Classifying content",
  chunking: "Chunking text",
  embedding: "Generating embeddings",
  indexing: "Building keyword index",
  entity_extract: "Extracting entities",
  enriching: "Enriching content",
  complete: "Complete",
}

function ProgressRing({ value, size = 32 }: { value: number; size?: number }) {
  const r = (size - 5) / 2
  const c = 2 * Math.PI * r
  const clamped = Math.max(0, Math.min(100, value))
  const offset = c - (clamped / 100) * c
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="3.5"
      />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeWidth="3.5"
        strokeDasharray={c} strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 400ms ease" }}
      />
      {/* Percentage text inside ring */}
      <text
        x={size / 2} y={size / 2}
        textAnchor="middle" dominantBaseline="central"
        fill="currentColor" fontSize={size * 0.28} fontWeight="600"
      >
        {Math.round(clamped)}
      </text>
    </svg>
  )
}

function truncate(s: string, n = 48): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

function elapsed(startedAt: number): string {
  const secs = Math.round((Date.now() - startedAt) / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  const rem = secs % 60
  return `${mins}m ${rem}s`
}

export function IngestionProgressPills() {
  const { jobs } = useIngestionTracker()
  const active = Object.values(jobs).filter((j) => j.status === "processing")
  if (active.length === 0) return null

  return (
    <div className="pointer-events-none fixed bottom-5 left-5 z-40 flex flex-col gap-3">
      {active.map((job) => (
        <div
          key={job.docId}
          className="pointer-events-auto flex items-center gap-3 rounded-xl border border-border bg-background/95 px-4 py-3 shadow-lg backdrop-blur-md text-primary"
          style={{ minWidth: 320, maxWidth: 420 }}
        >
          <ProgressRing value={job.progressPct} size={38} />
          <div className="flex flex-1 flex-col gap-0.5 min-w-0">
            <span className="text-sm font-semibold text-foreground truncate">
              {truncate(job.filename)}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {STAGE_LABELS[job.stage] ?? job.stage}
              </span>
              <span className="text-[10px] text-muted-foreground/60">
                {elapsed(job.startedAt)}
              </span>
            </div>
            {/* Mini progress bar */}
            <div className="mt-1 h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
                style={{ width: `${job.progressPct}%` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
