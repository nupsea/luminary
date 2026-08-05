// The last thing between a render error and a white screen.
//
// Pages are lazy() behind Suspense, so a render throw or a chunk that fails to
// load unmounts the whole tree with nothing shown and nothing logged. That is
// indistinguishable from the app being broken, and it hides the actual error.

import { Component, type ErrorInfo, type ReactNode } from "react"
import { RefreshCw } from "lucide-react"

import { logger } from "@/lib/logger"

interface State {
  error: string | null
}

export class RouteErrorBoundary extends Component<{ children: ReactNode }, State> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error.message : String(error) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    logger.error("[Route] render error", {
      error: String(error),
      componentStack: info.componentStack ?? "",
    })
  }

  render() {
    if (this.state.error === null) return this.props.children

    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="flex max-w-md flex-col gap-3 rounded-lg border border-border bg-card px-6 py-5">
          <p className="text-sm font-medium text-foreground">This page didn't load</p>
          <p className="break-all font-mono text-xs text-muted-foreground">
            {this.state.error}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => this.setState({ error: null })}
              className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <RefreshCw size={13} />
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="self-start rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              Reload Luminary
            </button>
          </div>
        </div>
      </div>
    )
  }
}
