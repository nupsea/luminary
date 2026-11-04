import { useState } from "react"
import { Check, ExternalLink, KeyRound, Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { type Connector, connectConnector, fieldValues } from "@/lib/connectorsApi"

interface ConnectorConnectModalProps {
  connector: Connector | null
  onClose: () => void
  onSuccess?: () => void
}

/** One sign-in form for every connector, drawn from the fields its `describe` declares. */
export function ConnectorConnectModal({ connector, onClose, onSuccess }: ConnectorConnectModalProps) {
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!connector) return null
  const fields = connector.credentials

  function close() {
    setForm({})
    setError(null)
    onClose()
  }

  async function handleSave() {
    if (!connector) return
    const { values, missing } = fieldValues(fields, form)
    if (missing.length > 0) {
      setError(`Fill in ${missing.join(", ")}`)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const status = await connectConnector(connector.name, values)
      toast.success(status.account ? `Connected to ${connector.label} as ${status.account}` : `${connector.label} connected`)
      setForm({})
      onClose()
      onSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not connect ${connector.label}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-xs" onClick={close} />
      <div
        role="dialog"
        aria-label={`Connect ${connector.label}`}
        className="relative z-10 w-full max-w-lg rounded-xl border border-border bg-background p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between border-b border-border pb-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-muted">
              <KeyRound className="h-4 w-4 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-medium text-foreground">Connect {connector.label}</h3>
              <p className="text-xs text-muted-foreground">Stored on this machine, readable only by you</p>
            </div>
          </div>
          <button onClick={close} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3.5">
          {fields.map((field) => (
            <div key={field.name}>
              <label htmlFor={`cred-${field.name}`} className="mb-1.5 block text-xs font-medium text-foreground">
                {field.label}
                {!(field.required ?? true) && <span className="ml-1 font-normal text-muted-foreground">(optional)</span>}
              </label>
              {field.multiline ? (
                <textarea
                  id={`cred-${field.name}`}
                  rows={4}
                  value={form[field.name] ?? ""}
                  onChange={(e) => {
                    setForm({ ...form, [field.name]: e.target.value })
                    setError(null)
                  }}
                  spellCheck={false}
                  autoComplete="off"
                  className="w-full resize-none rounded-lg border border-border bg-muted/40 px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                />
              ) : (
                <input
                  id={`cred-${field.name}`}
                  type={field.secret ? "password" : "text"}
                  value={form[field.name] ?? ""}
                  onChange={(e) => {
                    setForm({ ...form, [field.name]: e.target.value })
                    setError(null)
                  }}
                  autoComplete="off"
                  className="w-full rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                />
              )}
              {field.help && <p className="mt-1 text-xs text-muted-foreground">{field.help}</p>}
            </div>
          ))}
          {error && <p className="text-xs text-red-500">{error}</p>}
          <a
            href={connector.terms.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
          >
            {connector.label}'s terms <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2.5 border-t border-border pt-4">
          <button
            type="button"
            onClick={close}
            disabled={saving}
            className="rounded-lg px-3.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            {saving ? "Checking..." : "Check and connect"}
          </button>
        </div>
      </div>
    </div>
  )
}
