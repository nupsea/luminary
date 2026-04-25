// ---------------------------------------------------------------------------
// focusUtils -- pure helpers for the global focus timer pill (S209).
// Surface inference and time formatting live here so they are easy to unit test.
// ---------------------------------------------------------------------------

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
  // Strip trailing slash and query but keep the first segment for matching.
  const path = pathname.split("?")[0]?.replace(/\/$/, "") ?? ""

  if (path === "" || path === "/") return "read"
  if (path.startsWith("/study")) return "recall"
  if (path.startsWith("/notes")) return "write"
  if (path.startsWith("/chat")) return "explore"
  // Learning page is the root; explicit alias if anyone routes there.
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
