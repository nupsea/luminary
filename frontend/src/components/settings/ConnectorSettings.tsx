import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, ExternalLink, Plug, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { ConnectorConnectModal } from "@/components/library/ConnectorConnectModal"
import {
  CONNECTORS_KEY,
  type Connector,
  connectorStatus,
  disconnectConnector,
  listConnectors,
} from "@/lib/connectorsApi"

/** One card per installed connector, each drawn from what the connector described. */
export function ConnectorSettings() {
  const { data, isLoading, isError } = useQuery({ queryKey: CONNECTORS_KEY, queryFn: listConnectors })
  const [connecting, setConnecting] = useState<Connector | null>(null)
  const queryClient = useQueryClient()

  if (isLoading) return <div className="h-16 animate-pulse rounded-lg bg-muted" />
  if (isError) return <p className="text-xs text-red-500">Could not list the installed connectors.</p>
  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No connectors installed. A connector brings in links from one source, such as YouTube; install
        one from its folder with <code className="font-mono">python -m app.scripts.install_connector</code>.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {data.map((c) => (
        <ConnectorCard key={c.name} connector={c} onConnect={() => setConnecting(c)} />
      ))}
      <ConnectorConnectModal
        connector={connecting}
        onClose={() => setConnecting(null)}
        onSuccess={() => void queryClient.invalidateQueries({ queryKey: CONNECTORS_KEY })}
      />
    </div>
  )
}

function ConnectorCard({ connector, onConnect }: { connector: Connector; onConnect: () => void }) {
  const queryClient = useQueryClient()
  const [disconnecting, setDisconnecting] = useState(false)
  const signsIn = connector.credentials.length > 0
  // The check is a request to the source, so it runs only for a stored sign-in.
  const { data: status, isLoading, isError } = useQuery({
    queryKey: [...CONNECTORS_KEY, connector.name, "status"],
    queryFn: () => connectorStatus(connector.name),
    enabled: signsIn && connector.connected,
  })

  async function handleDisconnect() {
    setDisconnecting(true)
    try {
      await disconnectConnector(connector.name)
      await queryClient.invalidateQueries({ queryKey: CONNECTORS_KEY })
      toast.success(`${connector.label} disconnected`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Could not disconnect ${connector.label}`)
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-border bg-card/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
            <Plug className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-medium text-foreground">{connector.label}</h4>
            <p className="truncate text-xs text-muted-foreground">
              {connector.version} · {connector.licence} ·{" "}
              <a href={connector.terms.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:underline">
                source terms <ExternalLink className="h-2.5 w-2.5" />
              </a>
            </p>
          </div>
        </div>
        {signsIn && (
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={onConnect}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              {connector.connected ? "Update sign-in" : "Connect"}
            </button>
            {connector.connected && (
              <button
                onClick={() => void handleDisconnect()}
                disabled={disconnecting}
                aria-label={`Disconnect ${connector.label}`}
                title={`Disconnect ${connector.label}`}
                className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-red-400 hover:bg-red-500/20 disabled:opacity-50"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        )}
      </div>
      <ConnectorStatusLine
        connector={connector}
        signsIn={signsIn}
        checking={isLoading}
        failed={isError}
        status={status}
      />
    </div>
  )
}

function ConnectorStatusLine({
  connector,
  signsIn,
  checking,
  failed,
  status,
}: {
  connector: Connector
  signsIn: boolean
  checking: boolean
  failed: boolean
  status: Awaited<ReturnType<typeof connectorStatus>> | undefined
}) {
  if (!signsIn) return <p className="text-xs text-muted-foreground">Ready. Paste one of its links in Add document.</p>
  if (!connector.connected) return <p className="text-xs text-muted-foreground">Not connected.</p>
  if (checking) return <p className="text-xs text-muted-foreground">Checking the sign-in...</p>
  if (failed) return <p className="text-xs text-amber-500">Could not check the sign-in with {connector.label}.</p>
  if (status && !status.valid) {
    return <p className="text-xs text-amber-500">Sign-in not accepted: {status.error ?? "connect again"}</p>
  }
  return (
    <p className="flex items-center gap-1.5 text-xs text-emerald-500">
      <CheckCircle2 className="h-3.5 w-3.5" />
      Connected{status?.account ? ` as ${status.account}` : ""}
    </p>
  )
}
