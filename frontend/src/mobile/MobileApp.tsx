import { useState } from "react"

import { connect, parseServer } from "./server"

type State =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "connected"; version: string }
  | { kind: "failed"; message: string }

/**
 * The mobile shell (#448, #449): which Luminary server this phone reads from. Pairing, the
 * document cache and reading arrive with the mobile client (#454).
 */
export function MobileApp() {
  const [address, setAddress] = useState("")
  const [state, setState] = useState<State>({ kind: "idle" })

  async function check() {
    const server = parseServer(address)
    if ("error" in server) {
      setState({ kind: "failed", message: server.error })
      return
    }
    setState({ kind: "checking" })
    try {
      const health = await connect(server)
      setState({ kind: "connected", version: health.version })
    } catch (err) {
      setState({ kind: "failed", message: err instanceof Error ? err.message : String(err) })
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">Luminary</h1>
      <label className="flex flex-col gap-1 text-sm">
        Your Luminary server
        <input
          className="rounded-md border border-border bg-background px-3 py-2"
          inputMode="url"
          autoCapitalize="none"
          placeholder="https://luminary.your-tailnet.ts.net"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
        />
      </label>
      <button
        className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        disabled={!address.trim() || state.kind === "checking"}
        onClick={() => void check()}
      >
        Check
      </button>
      {state.kind === "connected" && <p className="text-sm">Luminary {state.version} answers.</p>}
      {state.kind === "failed" && <p className="text-sm text-destructive">{state.message}</p>}
    </main>
  )
}
