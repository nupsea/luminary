import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, CheckCircle2, Key, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { clearOreillyCookies, fetchOreillyStatus } from "@/lib/oreillyApi"
import { OreillyConnectModal } from "@/components/library/OreillyConnectModal"

export function OreillySettings() {
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)

  const { data: status, isLoading } = useQuery({
    queryKey: ["oreilly-status"],
    queryFn: fetchOreillyStatus,
  })

  async function handleDisconnect() {
    setDisconnecting(true)
    try {
      await clearOreillyCookies()
      await queryClient.invalidateQueries({ queryKey: ["oreilly-status"] })
      toast.success("O'Reilly subscription disconnected")
    } catch {
      toast.error("Failed to disconnect O'Reilly")
    } finally {
      setDisconnecting(false)
    }
  }

  const isConnected = status?.configured && status?.valid

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-red-500/10 text-red-500 border border-red-500/20">
            <BookOpen className="h-4 w-4" />
          </div>
          <div>
            <h4 className="text-sm font-medium text-foreground">O'Reilly Learning</h4>
            <p className="text-xs text-muted-foreground">
              Ingest technical books directly into your local library using your subscription
            </p>
          </div>
        </div>

        {isConnected ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent transition-colors"
            >
              <Key className="h-3 w-3 text-muted-foreground" />
              Update Cookies
            </button>
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              className="inline-flex items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
              title="Disconnect O'Reilly"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Connect
          </button>
        )}
      </div>

      {!isLoading && (
        <div className="pt-1">
          {isConnected ? (
            <div className="flex items-center gap-1.5 text-xs text-emerald-500">
              <CheckCircle2 className="h-3.5 w-3.5" />
              <span>Connected as {status.user ?? "Active Subscriber"}</span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Not connected. Connect your browser cookies once to auto-detect and ingest any O'Reilly book URL.
            </p>
          )}
        </div>
      )}

      <OreillyConnectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={() => void queryClient.invalidateQueries({ queryKey: ["oreilly-status"] })}
      />
    </div>
  )
}
