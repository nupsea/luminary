import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Download, ExternalLink, Loader2, Plug, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { ConnectorConnectModal } from "@/components/library/ConnectorConnectModal"
import {
  CATALOGUE_KEY,
  CONNECTORS_KEY,
  type CatalogueItem,
  type Connector,
  connectorStatus,
  disconnectConnector,
  installFromCatalogue,
  listCatalogue,
  listConnectors,
  offeredFromCatalogue,
  uninstallConnector,
} from "@/lib/connectorsApi"
import { formatBytes } from "@/lib/setupApi"

/** The installed connectors, one card each drawn from what the connector described, then the
 *  catalogue's, each showing its licence and its source's terms before an install. */
export function ConnectorSettings() {
  const { data, isLoading, isError } = useQuery({ queryKey: CONNECTORS_KEY, queryFn: listConnectors })
  const [connecting, setConnecting] = useState<Connector | null>(null)
  const queryClient = useQueryClient()

  if (isLoading) return <div className="h-16 animate-pulse rounded-lg bg-muted" />
  if (isError) return <p className="text-xs text-red-500">Could not list the installed connectors.</p>
  return (
    <div className="space-y-3">
      {(data ?? []).length === 0 && (
        <p className="text-xs text-muted-foreground">
          No connectors installed. A connector brings in links from one source, such as YouTube.
        </p>
      )}
      {(data ?? []).map((c) => (
        <ConnectorCard key={c.name} connector={c} onConnect={() => setConnecting(c)} />
      ))}
      <CatalogueSection />
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

  async function handleUninstall() {
    try {
      await uninstallConnector(connector.name)
      await queryClient.invalidateQueries({ queryKey: CONNECTORS_KEY })
      toast.success(`${connector.label} uninstalled. Its documents stay in your library.`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Could not uninstall ${connector.label}`)
    }
  }

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
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => void handleUninstall()}
            className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent"
          >
            Uninstall
          </button>
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

function CatalogueSection() {
  const { data, isLoading, isError } = useQuery({ queryKey: CATALOGUE_KEY, queryFn: listCatalogue })
  if (isLoading) return <div className="h-12 animate-pulse rounded-lg bg-muted" />
  if (isError) return <p className="text-xs text-red-500">Could not read the connector catalogue.</p>
  const offered = offeredFromCatalogue(data ?? [])
  if (offered.length === 0) return null
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Available</h4>
      {offered.map((item) => (
        <CatalogueCard key={item.name} item={item} />
      ))}
    </div>
  )
}

function CatalogueCard({ item }: { item: CatalogueItem }) {
  const queryClient = useQueryClient()
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleInstall() {
    setError(null)
    setProgress("Starting...")
    try {
      await installFromCatalogue(item.name, (event) => setProgress(event.detail ?? "Installing..."))
      await queryClient.invalidateQueries({ queryKey: CONNECTORS_KEY })
      toast.success(`${item.label} installed`)
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not install ${item.label}`)
    } finally {
      setProgress(null)
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-dashed border-border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-foreground">
            {item.label} <span className="font-normal text-muted-foreground">{item.version}</span>
          </h4>
          <p className="text-xs text-muted-foreground">{item.summary}</p>
          <p className="text-xs text-muted-foreground">
            {item.licence} · {formatBytes(item.size_bytes)} ·{" "}
            <a href={item.repository} target="_blank" rel="noreferrer" className="hover:underline">
              source code
            </a>
            {item.installed_version && ` · installed ${item.installed_version}`}
          </p>
        </div>
        <button
          onClick={() => void handleInstall()}
          disabled={progress !== null}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {progress !== null ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
          {item.installed_version ? "Update" : "Install"}
        </button>
      </div>
      <div className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
        <p className="mb-1 font-medium text-foreground">The source's terms</p>
        <p>{item.terms.statement}</p>
        <a href={item.terms.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 hover:underline">
          Read them in full <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {progress && <p className="text-xs text-muted-foreground">{progress}</p>}
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  )
}
