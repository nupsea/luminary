// Provider -> key -> model, in the order a user needs them. The model list is
// readable before a key exists; a key is checked with the provider before it is
// kept, so a mistyped one is named here rather than as an empty model list.

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, KeyRound, Loader2 } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { apiPatch } from "@/lib/apiClient"
import {
  cloudModelsQuery,
  invalidateKeyedQueries,
  type KeyCheck,
  saveProviderKey,
} from "@/lib/cloudKeys"
import {
  type CloudProvider,
  formatModelOption,
  hasKeyFor,
  keyField,
  type KeyFlags,
  modelForProvider,
} from "@/lib/cloudModels"
import { PROVIDER_SETUP, providerSetup } from "@/lib/engineOffer"
import { cn } from "@/lib/utils"

interface Props {
  llm: (KeyFlags & { keyring_available?: boolean; provider: string; model: string }) | undefined
  provider: CloudProvider
  onProviderChange: (p: CloudProvider) => void
  model: string
  onModelChange: (m: string) => void
  apiKey: string
  onApiKeyChange: (k: string) => void
  enabled: boolean
}

const INPUT =
  "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"

export function CloudProviderSettings({
  llm,
  provider,
  onProviderChange,
  model,
  onModelChange,
  apiKey,
  onApiKeyChange,
  enabled,
}: Props) {
  const queryClient = useQueryClient()
  const setup = providerSetup(provider)
  const label = setup?.label ?? provider
  const hasKey = hasKeyFor(provider, llm)

  const [replacing, setReplacing] = useState(false)
  const [checking, setChecking] = useState(false)
  const [lastCheck, setLastCheck] = useState<KeyCheck | null>(null)
  const [useCustomModel, setUseCustomModel] = useState(false)
  // The provider most recently clicked, so a slow list for an earlier click is ignored.
  const latestPick = useRef<CloudProvider>(provider)

  const {
    data: models = [],
    isLoading,
    isError,
  } = useQuery({ ...cloudModelsQuery(provider, hasKey), enabled })

  async function chooseProvider(p: CloudProvider) {
    if (p === provider) return
    latestPick.current = p
    onProviderChange(p)
    onApiKeyChange("")
    setReplacing(false)
    setLastCheck(null)
    setUseCustomModel(false)
    if (p === llm?.provider) {
      onModelChange(llm.model)
      return
    }
    onModelChange("")
    try {
      const list = await queryClient.fetchQuery(cloudModelsQuery(p, hasKeyFor(p, llm)))
      if (latestPick.current === p) onModelChange(modelForProvider(list, ""))
    } catch {
      // The model field shows the load error; the user can type an ID.
    }
  }

  async function checkAndSaveKey() {
    const key = apiKey.trim()
    if (!key) return
    setChecking(true)
    try {
      const result = await saveProviderKey(provider, key)
      setLastCheck(result)
      if (result.saved) {
        onApiKeyChange("")
        setReplacing(false)
        invalidateKeyedQueries(queryClient)
      }
    } catch {
      setLastCheck({ status: "unchecked", saved: false, message: "Could not save the key. Is the app's backend running?" })
    } finally {
      setChecking(false)
    }
  }

  async function removeKey() {
    try {
      await apiPatch("/settings/llm", { [keyField(provider)]: "" })
      setLastCheck(null)
      invalidateKeyedQueries(queryClient)
      toast.success(`${label} key removed`)
    } catch {
      toast.error("Could not remove the key")
    }
  }

  const savedModelMissing =
    !useCustomModel &&
    model !== "" &&
    models.length > 0 &&
    !models.some((m) => m.id === model)
  const showKeyInput = !hasKey || replacing

  return (
    <div className="space-y-4 rounded-lg border border-border p-3">
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Provider</p>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Cloud provider">
          {PROVIDER_SETUP.map((p) => {
            const active = p.id === provider
            const keyed = hasKeyFor(p.id, llm)
            return (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => void chooseProvider(p.id)}
                className={cn(
                  "flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors",
                  active ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground",
                )}
              >
                <span className="text-sm font-medium text-foreground">{p.label}</span>
                <span
                  className={cn(
                    "text-[11px]",
                    keyed ? "text-green-700 dark:text-green-400" : "text-muted-foreground",
                  )}
                >
                  {keyed ? "Key saved" : "No key"}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-muted text-[10px]">1</span>
          {label} API key
        </p>
        {showKeyInput ? (
          <>
            <div className="flex gap-2">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => onApiKeyChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void checkAndSaveKey()
                }}
                placeholder={`Paste your ${label} key`}
                autoComplete="off"
                className={INPUT}
              />
              <button
                type="button"
                onClick={() => void checkAndSaveKey()}
                disabled={!apiKey.trim() || checking}
                className="flex flex-shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {checking ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                {checking ? "Checking..." : "Save key"}
              </button>
              {replacing && (
                <button
                  type="button"
                  onClick={() => {
                    setReplacing(false)
                    onApiKeyChange("")
                  }}
                  className="flex-shrink-0 text-xs text-muted-foreground hover:text-foreground"
                >
                  Cancel
                </button>
              )}
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              No key yet? Create one at{" "}
              <a
                href={setup?.consoleUrl ?? "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-foreground"
              >
                {setup?.consoleLabel}
              </a>
              . The key is checked with {label} before it is saved.
            </p>
          </>
        ) : (
          <div className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2">
            <span className="flex items-center gap-1.5 text-sm text-foreground">
              <CheckCircle2 size={14} className="text-green-600" />
              Key saved
            </span>
            <span className="flex gap-3 text-xs">
              <button type="button" onClick={() => setReplacing(true)} className="text-muted-foreground hover:text-foreground">
                Replace
              </button>
              <button type="button" onClick={() => void removeKey()} className="text-muted-foreground hover:text-destructive">
                Remove
              </button>
            </span>
          </div>
        )}
        {lastCheck && (
          <p
            role="status"
            className={cn(
              "mt-1.5 text-xs",
              lastCheck.status === "verified" && "text-green-700 dark:text-green-400",
              lastCheck.status === "rejected" && "text-destructive",
              lastCheck.status === "unchecked" && "text-amber-700 dark:text-amber-400",
            )}
          >
            {lastCheck.message}
          </p>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          {llm?.keyring_available === false
            ? "This install has no OS keychain, so the key is saved in your library database."
            : "Stored in your OS keychain, never in the library."}
        </p>
      </div>

      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-muted text-[10px]">2</span>
          Model
          {isLoading && <Loader2 size={12} className="animate-spin" />}
        </p>
        {isLoading ? (
          <div className="h-8 animate-pulse rounded-md bg-muted" />
        ) : useCustomModel || models.length === 0 ? (
          <input
            type="text"
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            placeholder={`A ${label} model ID`}
            className={INPUT}
          />
        ) : (
          <select
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            className={INPUT}
            aria-label={`${label} model`}
          >
            {model === "" && (
              <option value="" disabled>
                Choose a model
              </option>
            )}
            {savedModelMissing && <option value={model}>{model} (not in {label}'s list)</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {formatModelOption(m)}
              </option>
            ))}
          </select>
        )}
        {isError && (
          <p className="mt-1 text-xs text-destructive">Could not load {label}'s models. Enter a model ID instead.</p>
        )}
        {savedModelMissing && (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
            {model} is not in {label}'s current list, so it may have been retired. Pick another to be safe.
          </p>
        )}
        {!isLoading && !hasKey && models.length > 0 && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            {label}'s current models. Once your key is saved, this lists exactly what it can use.
          </p>
        )}
        {models.length > 0 && (
          <button
            type="button"
            onClick={() => setUseCustomModel(!useCustomModel)}
            className="mt-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {useCustomModel ? "Pick from the list" : "Enter a model ID instead"}
          </button>
        )}
      </div>
    </div>
  )
}
