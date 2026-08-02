// setupApi — /setup/* : startup progress, installable components, capabilities

import { apiDelete, apiGet, apiPost } from "@/lib/apiClient"
import { API_BASE } from "@/lib/config"

export type PhaseState =
  | "pending"
  | "downloading"
  | "loading"
  | "ready"
  | "failed"
  | "skipped"

export interface StartupPhase {
  key: string
  label: string
  required: boolean
  state: PhaseState
  detail: string
  completed_bytes: number
  total_bytes: number
  percent: number | null
}

export interface StartupStatus {
  status: "starting" | "provisioning" | "ready" | "degraded"
  /** Everything required is in place. */
  ready: boolean
  /** The library opens and browsing works; model-backed features may not. */
  usable: boolean
  /** Whether the user should be held on the setup screen. Optional downloads never block. */
  blocking: boolean
  failed: string[]
  elapsed_seconds: number
  phases: StartupPhase[]
  version: string
}

export interface Component {
  id: string
  label: string
  description: string
  kind: "ollama_model" | "python_extra" | "tool"
  ref: string
  size_bytes: number
  licence: string
  default: boolean
  enables: string[]
  installed: boolean
}

export interface Capability {
  available: boolean
  /** Component ids that would enable it. */
  requires: string[]
}

export type CapabilityKey =
  | "audio_ingest"
  | "video_ingest"
  | "youtube_ingest"
  | "web_ingest"
  | "vision"
  | "chat"

export type Capabilities = Record<CapabilityKey, Capability>

export function fetchStartupStatus(): Promise<StartupStatus> {
  return apiGet<StartupStatus>("/setup/status")
}

export async function fetchComponents(): Promise<Component[]> {
  const data = await apiGet<{ components: Component[] }>("/setup/components")
  return data.components
}

export function fetchCapabilities(): Promise<Capabilities> {
  return apiGet<Capabilities>("/setup/capabilities")
}

/** Re-run whatever failed at startup. Without it a transient network problem
 *  leaves the install degraded until the app is restarted. */
export function retrySetup(): Promise<{ retried: string[] }> {
  return apiPost<{ retried: string[] }>("/setup/retry")
}

export function uninstallComponent(id: string): Promise<{ removed: string }> {
  return apiDelete<{ removed: string }>(`/setup/components/${id}`)
}

export interface InstallProgress {
  state: PhaseState
  detail?: string
  completed_bytes?: number
  total_bytes?: number
}

/**
 * Install a component, calling `onProgress` as it streams.
 *
 * Server-sent events rather than apiClient: this reports byte counts over
 * minutes, and a download of several gigabytes has to show movement.
 */
export async function installComponent(
  id: string,
  onProgress: (event: InstallProgress) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/setup/components/${id}/install`, {
    method: "POST",
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`install failed (${resp.status})`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith("data:")) continue
      try {
        onProgress(JSON.parse(line.slice(5).trim()) as InstallProgress)
      } catch {
        // A malformed frame must not abort a multi-gigabyte download.
      }
    }
  }
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 MB"
  const gb = bytes / 1024 ** 3
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`
}
