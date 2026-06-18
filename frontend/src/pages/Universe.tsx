// Universe -- the Knowledge Universe lens (docs/universe.md). Concept stars lit by
// warmth (mastery x recency); click a star to study it. Baseline sky is always
// meaningful; edges appear only when the concept linker has produced relations.

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { launchStudy } from "@/lib/studyLauncher"

interface Star {
  id: string
  label: string
  kind: string
  status: string
  mastery: number
  warmth: number
}
interface Edge {
  source: string
  target: string
}
interface UniverseData {
  stars: Star[]
  edges: Edge[]
}

const VW = 1000
const VH = 620

// deterministic position from the concept id -> stable sky
function starPos(id: string): { x: number; y: number } {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  const x = (h % 997) / 997
  const y = (Math.floor(h / 997) % 991) / 991
  return { x: (0.05 + x * 0.9) * VW, y: (0.08 + y * 0.84) * VH }
}

function starColor(warmth: number): string {
  const cold = [100, 116, 139] // slate-500
  const warm = [251, 191, 36] // amber-400
  const c = cold.map((v, i) => Math.round(v + (warm[i] - v) * warmth))
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

export default function Universe() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: ["universe"],
    queryFn: () => apiGet<UniverseData>("/concepts/universe"),
  })

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    data?.stars.forEach((s) => map.set(s.id, starPos(s.id)))
    return map
  }, [data])

  // attention rail: coldest-but-weakest (lowest warmth, then lowest mastery)
  const attention = useMemo(
    () =>
      [...(data?.stars ?? [])]
        .sort((a, b) => a.warmth - b.warmth || a.mastery - b.mastery)
        .slice(0, 3),
    [data],
  )

  const selected = data?.stars.find((s) => s.id === selectedId) ?? null

  if (isLoading) {
    return (
      <div className="p-6">
        <Skeleton className="h-[620px] w-full rounded-xl" />
      </div>
    )
  }
  if (isError) {
    return <div className="p-6 text-sm text-red-500">Couldn't load the Universe.</div>
  }
  if (!data || data.stars.length === 0) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center gap-2 p-6 text-center">
        <Sparkles className="text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Your Universe is empty.</p>
        <p className="text-xs text-muted-foreground">
          Add a document so Lumen can extract concepts (or run the concept backfill).
        </p>
      </div>
    )
  }

  return (
    <div className="relative p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h1 className="text-lg font-semibold text-foreground">Knowledge Universe</h1>
        <span className="text-xs text-muted-foreground">
          {data.stars.length} concepts · warmth = mastery × recency
        </span>
      </div>

      <div className="relative overflow-hidden rounded-xl border border-border bg-gradient-to-b from-slate-950 to-slate-900">
        <svg viewBox={`0 0 ${VW} ${VH}`} className="h-[620px] w-full" preserveAspectRatio="xMidYMid meet">
          {data.edges.map((e, i) => {
            const a = positions.get(e.source)
            const b = positions.get(e.target)
            if (!a || !b) return null
            return (
              <line
                key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke="rgb(148,163,184)" strokeOpacity={0.15} strokeWidth={1}
              />
            )
          })}
          {data.stars.map((s) => {
            const p = positions.get(s.id)!
            const r = 4 + (s.mastery / 100) * 8
            const color = starColor(s.warmth)
            const isSel = s.id === selectedId
            return (
              <g key={s.id} className="cursor-pointer" onClick={() => setSelectedId(s.id)}>
                <circle cx={p.x} cy={p.y} r={r + 6} fill={color} opacity={0.12} />
                <circle
                  cx={p.x} cy={p.y} r={r} fill={color}
                  opacity={0.35 + s.warmth * 0.55}
                  stroke={isSel ? "white" : "none"} strokeWidth={isSel ? 2 : 0}
                />
              </g>
            )
          })}
        </svg>

        {/* attention rail */}
        <div className="absolute left-3 top-3 w-56 rounded-lg border border-white/10 bg-black/40 p-3 backdrop-blur">
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Needs attention
          </div>
          <div className="flex flex-col gap-1">
            {attention.map((s) => (
              <button
                key={s.id}
                onClick={() => setSelectedId(s.id)}
                className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-xs text-slate-200 hover:bg-white/10"
              >
                <span className="truncate">{s.label}</span>
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: starColor(s.warmth) }}
                />
              </button>
            ))}
          </div>
        </div>

        {/* star panel */}
        {selected && (
          <div className="absolute right-3 top-3 w-64 rounded-lg border border-white/10 bg-black/60 p-4 backdrop-blur">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-sm font-semibold text-white">{selected.label}</h2>
              <button onClick={() => setSelectedId(null)} className="text-slate-400 hover:text-white">
                ×
              </button>
            </div>
            <div className="mt-2 space-y-1 text-xs text-slate-300">
              <div>Mastery · {Math.round(selected.mastery)}%</div>
              <div>Warmth · {Math.round(selected.warmth * 100)}%</div>
              {selected.status !== "confirmed" && <div>Status · {selected.status}</div>}
            </div>
            <button
              onClick={() => launchStudy({ type: "concept", ref: selected.id, label: selected.label })}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400"
            >
              <Sparkles size={14} /> Study this
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
