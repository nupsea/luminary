import { useLocation, useNavigate } from "react-router-dom"

const BACK_LABELS: Record<string, string> = {
  "/study": "Back to Study",
  "/chat": "Back to Chat",
  "/notes": "Back to Notes",
  "/library": "Back to Library",
  "/": "Back to Home",
}

function resolveLabel(from: string): string {
  if (from.startsWith("/collections/")) return "Back to Collection"
  return BACK_LABELS[from] ?? "Back"
}

interface BackNavigation {
  /** The pathname we came from, or null if no state was set. */
  fromPath: string | null
  /** True when fromPath is set — use to conditionally render back button. */
  canGoBack: boolean
  /** Human-readable label for the back button. */
  backLabel: string
  /** Navigates one step back in the browser history. */
  goBack: () => void
}

/**
 * Reads location.state.from (set by contextual navigate calls) and returns
 * a consistent back-navigation affordance. Use canGoBack to gate rendering.
 */
export function useBackNavigation(): BackNavigation {
  const location = useLocation()
  const navigate = useNavigate()
  const fromPath = (location.state as { from?: string } | null)?.from ?? null
  return {
    fromPath,
    canGoBack: !!fromPath,
    backLabel: fromPath ? resolveLabel(fromPath) : "Back",
    goBack: () => navigate(-1),
  }
}
