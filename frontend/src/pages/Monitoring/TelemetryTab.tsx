// Telemetry tab: what is collected, where it goes, and how to stop it.
//
// This lives on Monitoring rather than in the Settings drawer because it is a
// disclosure surface, not a preference: the point is to show the reader the
// exact record that would leave the machine. Monitoring is `mode: full` in
// surface-manifest.json, so this is never mounted on a public build.
//
// The captured fields are rendered from `platform_metadata` returned by the
// backend -- the same dict `send_signal` transmits -- rather than from a list
// written here. A hand-maintained list drifts from the payload, and a privacy
// disclosure that has drifted is worse than none.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ShieldCheck, X } from "lucide-react"
import { toast } from "sonner"

import { apiGet, apiPatch } from "@/lib/apiClient"

import { EmptyState, SectionErrorCard, SectionSkeleton, StatCard, StatusPill } from "./SharedUI"

interface TelemetryOverview {
  enabled: boolean
  client_id: string
  app_id: string
  telemetrydeck_configured: boolean
  distribution: string
  platform_metadata: Record<string, unknown>
  local_stats: {
    installs_total?: number
    runs_total?: number
    by_distribution?: Record<string, number>
    last_event_at?: string | null
    recent_events?: { signal_type?: string; at?: string }[]
  }
  github_dmg_downloads?: number | null
}

// Named because they are the reason the toggle exists. Each is a category a
// reader might reasonably fear is being collected; none of it is.
const NEVER_COLLECTED = [
  "Document or note content",
  "Questions, answers or prompts",
  "File names and paths",
  "Your username or home directory",
  "IP address or location",
  "Anything about which models you run locally",
]

export function TelemetryTab() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ["telemetry-overview"],
    queryFn: () => apiGet<TelemetryOverview>("/monitoring/telemetry"),
  })

  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      apiPatch<{ enabled: boolean }>("/settings/telemetry", { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["telemetry-overview"] })
      toast.success("Telemetry preference saved")
    },
    onError: () => toast.error("Could not save the telemetry preference"),
  })

  if (isLoading) return <SectionSkeleton rows={4} />
  if (isError || !data) return <SectionErrorCard name="Telemetry" />

  const fields = Object.entries(data.platform_metadata ?? {})
  const stats = data.local_stats ?? {}
  const recent = stats.recent_events ?? []
  // Nothing leaves the machine unless a TelemetryDeck app ID is configured;
  // without one the same records are kept locally and shown below.
  const leavesMachine = data.enabled && data.telemetrydeck_configured

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill
          state={data.enabled ? "online" : "disabled"}
          label={data.enabled ? "Telemetry on" : "Telemetry off"}
          detail={data.distribution}
        />
        <StatusPill
          state={leavesMachine ? "online" : "disabled"}
          label={leavesMachine ? "Sending to TelemetryDeck" : "Stored on this machine only"}
          detail={data.telemetrydeck_configured ? data.app_id : "no endpoint configured"}
        />
        <button
          onClick={() => toggle.mutate(!data.enabled)}
          disabled={toggle.isPending}
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-50"
        >
          {data.enabled ? "Turn off" : "Turn on"}
        </button>
      </div>

      <section className="rounded-lg border border-border p-4">
        <h3 className="mb-1 text-sm font-semibold text-foreground">
          Exactly what is recorded
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Read from the payload itself, so this cannot drift from what is sent.
        </p>
        {fields.length === 0 ? (
          <EmptyState message="No payload reported." />
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {fields.map(([key, value]) => (
                <tr key={key} className="border-b border-border/50 last:border-0">
                  <td className="py-1.5 pr-4 font-mono text-xs text-muted-foreground">{key}</td>
                  <td className="py-1.5 font-mono text-xs text-foreground">{String(value)}</td>
                </tr>
              ))}
              <tr>
                <td className="py-1.5 pr-4 font-mono text-xs text-muted-foreground">
                  anonymous id
                </td>
                <td className="py-1.5 font-mono text-xs text-foreground">{data.client_id}</td>
              </tr>
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          The id is a random UUID generated on this machine. It is not derived from
          your hardware, MAC address or any account, and it identifies an install
          rather than a person. Deleting it starts a new one.
        </p>
      </section>

      <section className="rounded-lg border border-border p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
          <ShieldCheck size={14} /> Never collected
        </h3>
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {NEVER_COLLECTED.map((item) => (
            <li key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
              <X size={12} className="shrink-0 text-muted-foreground" />
              {item}
            </li>
          ))}
        </ul>
        <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
          <Check size={12} className="mt-0.5 shrink-0" />
          Private mode sends nothing at all, whatever this page says: telemetry is
          refused whenever the LLM mode is private. Setting DO_NOT_TRACK=1 does the
          same on every platform, including the installers.
        </p>
      </section>

      <section className="rounded-lg border border-border p-4">
        <h3 className="mb-3 text-sm font-semibold text-foreground">Recorded on this machine</h3>
        <div className="mb-4 flex flex-wrap gap-3">
          <StatCard value={stats.installs_total ?? 0} label="Installs" />
          <StatCard value={stats.runs_total ?? 0} label="Runs" />
          {data.github_dmg_downloads != null && (
            <StatCard value={data.github_dmg_downloads} label="DMG downloads" />
          )}
        </div>
        {recent.length === 0 ? (
          <EmptyState message="No events recorded yet." />
        ) : (
          <ul className="flex flex-col gap-1">
            {recent.slice(0, 8).map((event, i) => (
              <li key={i} className="flex justify-between text-xs">
                <span className="font-mono text-foreground">{event.signal_type ?? "?"}</span>
                <span className="text-muted-foreground">{event.at ?? ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
