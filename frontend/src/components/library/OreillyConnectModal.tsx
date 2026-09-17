import { useState } from "react"
import { BookOpen, Check, ExternalLink, Key, Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { saveOreillyCookies } from "@/lib/oreillyApi"

interface OreillyConnectModalProps {
  open: boolean
  onClose: () => void
  onSuccess?: () => void
}

export function OreillyConnectModal({ open, onClose, onSuccess }: OreillyConnectModalProps) {
  const [cookieInput, setCookieInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  async function handleSave() {
    if (!cookieInput.trim()) {
      setError("Please paste your O'Reilly cookies")
      return
    }

    setLoading(true)
    setError(null)
    try {
      const res = await saveOreillyCookies(cookieInput.trim())
      toast.success(
        res.user ? `Connected to O'Reilly as ${res.user}` : "O'Reilly subscription connected!",
      )
      setCookieInput("")
      onClose()
      onSuccess?.()
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to authenticate cookies"
      setError(msg)
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-xs" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg rounded-xl border border-zinc-800 bg-zinc-950 p-6 shadow-2xl text-zinc-100 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between pb-4 border-b border-zinc-800/80">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-500/10 text-red-400 border border-red-500/20">
              <BookOpen className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-medium text-zinc-100">Connect O'Reilly Subscription</h3>
              <p className="text-xs text-zinc-400">One-time setup to ingest technical books into Luminary</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3.5 text-xs text-zinc-300">
          <div className="rounded-lg bg-zinc-900/80 border border-zinc-800 p-3 space-y-2">
            <p className="font-medium text-zinc-200 flex items-center gap-1.5">
              <Key className="h-3.5 w-3.5 text-amber-400" />
              How to export your session cookies:
            </p>
            <ol className="list-decimal list-inside space-y-1.5 text-zinc-400 pl-1">
              <li>
                Log in to{" "}
                <a
                  href="https://learning.oreilly.com"
                  target="_blank"
                  rel="noreferrer"
                  className="text-red-400 hover:underline inline-flex items-center gap-0.5"
                >
                  learning.oreilly.com <ExternalLink className="h-2.5 w-2.5" />
                </a>{" "}
                in your browser.
              </li>
              <li>
                Export cookies as JSON using a browser extension (like <em>Cookie-Editor</em>) or copy the{" "}
                <code className="bg-zinc-800 px-1 py-0.5 rounded text-zinc-200">Cookie:</code> header from DevTools Network.
              </li>
              <li>Paste the JSON or cookie string below.</li>
            </ol>
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-1.5">
              O'Reilly Cookies (JSON or Header String)
            </label>
            <textarea
              rows={4}
              value={cookieInput}
              onChange={(e) => {
                setCookieInput(e.target.value)
                setError(null)
              }}
              placeholder='[{"name": "_abck", "value": "..."}, {"name": "sessionid", "value": "..."}]'
              className="w-full rounded-lg border border-zinc-800 bg-zinc-900/90 px-3 py-2 text-xs font-mono text-zinc-200 placeholder:text-zinc-600 focus:border-red-500/60 focus:outline-none focus:ring-1 focus:ring-red-500/60 transition-all resize-none"
            />
            {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2.5 pt-4 border-t border-zinc-800/80">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-lg px-3.5 py-1.5 text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading || !cookieInput.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm shadow-red-950"
          >
            {loading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Verifying Session...
              </>
            ) : (
              <>
                <Check className="h-3.5 w-3.5" />
                Verify & Connect
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
