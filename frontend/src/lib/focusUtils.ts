// focusUtils — pure helpers for the global focus timer pill (surface inference, time formatting)

export type Surface = "read" | "recall" | "write" | "explore" | "none"

export const VALID_SURFACES: ReadonlyArray<Surface> = [
  "read",
  "recall",
  "write",
  "explore",
  "none",
]

// Map the active route pathname to a surface label that POST /pomodoro/start
// expects. Routes outside the four learning surfaces map to "none".
export function inferSurfaceFromPath(pathname: string): Surface {
  const path = pathname.split("?")[0]?.replace(/\/$/, "") ?? ""

  if (path.startsWith("/library")) return "read"
  if (path.startsWith("/study")) return "recall"
  if (path.startsWith("/notes")) return "write"
  if (path.startsWith("/chat")) return "explore"
  // Pre-2E.0 alias: / still renders Library until the hub UI lands (2E.7).
  if (path === "" || path === "/") return "read"
  // Pre-2E.0 alias: /learning was an early codename for Library.
  if (path.startsWith("/learning")) return "read"
  return "none"
}

// Format a number of seconds as MM:SS, never negative.
export function formatMmSs(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const m = Math.floor(safe / 60)
  const s = safe % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

// Validate a minute input -- 1..120 inclusive, integer.
export function isValidMinutes(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= 120
}
