import { Loader2 } from "lucide-react"
import { type Connector, type ConnectorPreview, type Picks, togglePick } from "@/lib/connectorsApi"

interface ConnectorLinkPanelProps {
  connector: Connector
  preview: ConnectorPreview | null
  picks: Picks
  previewing: boolean
  previewError: string | null
  inputs: Record<string, string>
  onInputs: (inputs: Record<string, string>) => void
  onConnect: () => void
  onPreview: () => void
  onPicks: (picks: Picks) => void
}

/** What the upload dialog shows under a link an installed connector claims: whether it is
 *  signed in, and the choices its preview offers before the fetch. */
export function ConnectorLinkPanel({
  connector,
  preview,
  picks,
  previewing,
  previewError,
  inputs,
  onInputs,
  onConnect,
  onPreview,
  onPicks,
}: ConnectorLinkPanelProps) {
  const needsSignIn = connector.credentials.length > 0 && !connector.connected
  return (
    <div className="mt-2 space-y-2">
      {needsSignIn ? (
        <div className="flex items-center justify-between rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs text-foreground">
          <span>{connector.label} link: sign in first</span>
          <button type="button" onClick={onConnect} className="ml-2 font-medium text-primary hover:underline">
            Connect
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1.5 text-xs text-foreground">
          <span>{connector.label} link</span>
          {connector.preview && !preview && (
            <button
              type="button"
              onClick={onPreview}
              disabled={previewing}
              className="ml-2 inline-flex items-center gap-1 font-medium text-primary hover:underline disabled:opacity-50"
            >
              {previewing && <Loader2 className="h-3 w-3 animate-spin" />}
              {previewing ? "Reading..." : "Choose what to import"}
            </button>
          )}
        </div>
      )}
      {connector.inputs.map((field) => (
        <div key={field.name} className="text-xs">
          <label htmlFor={`input-${field.name}`} className="mb-1 block font-medium text-foreground">
            {field.label}
            {!(field.required ?? true) && <span className="ml-1 font-normal text-muted-foreground">(optional)</span>}
          </label>
          <input
            id={`input-${field.name}`}
            type={field.secret ? "password" : "text"}
            value={inputs[field.name] ?? ""}
            onChange={(e) => onInputs({ ...inputs, [field.name]: e.target.value })}
            className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
          {field.help && <p className="mt-0.5 text-muted-foreground">{field.help}</p>}
        </div>
      ))}
      {previewError && <p className="text-xs text-red-500">{previewError}</p>}
      {preview && <PreviewChoices preview={preview} picks={picks} onPicks={onPicks} />}
    </div>
  )
}

function PreviewChoices({
  preview,
  picks,
  onPicks,
}: {
  preview: ConnectorPreview
  picks: Picks
  onPicks: (picks: Picks) => void
}) {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/40 px-2.5 py-2 text-xs">
      <div>
        <p className="font-medium text-foreground">{preview.title}</p>
        {preview.detail && <p className="text-muted-foreground">{preview.detail}</p>}
      </div>
      {preview.choices.map((choice) => (
        <fieldset key={choice.field} className="space-y-1">
          <legend className="font-medium text-foreground">{choice.label}</legend>
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {choice.options.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-start gap-2 select-none">
                <input
                  type={choice.multiple ? "checkbox" : "radio"}
                  name={choice.field}
                  checked={(picks[choice.field] ?? []).includes(option.value)}
                  onChange={() => onPicks(togglePick(picks, choice, option.value))}
                  className="mt-0.5 h-3.5 w-3.5"
                />
                <span className="text-foreground">
                  {option.label}
                  {option.detail && <span className="ml-1 text-muted-foreground">{option.detail}</span>}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  )
}
