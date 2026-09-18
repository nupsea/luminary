/**
 * BlogRefineDialog — full-mode step before publish: run the note through an
 * LLM grammar/structure pass (the author's own instruction, editable), review
 * the result side by side with the original, then approve into
 * BlogPublishDialog. The underlying note is never modified here.
 */

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, Maximize2, Minimize2, Sparkles, UploadCloud } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ModelSelector } from "@/components/ModelSelector"
import { ApiError, apiGet } from "@/lib/apiClient"
import { DEFAULT_REFINE_PROMPT, refineNote, KIND_SINGULAR, type BlogKind } from "@/lib/blogApi"
import { fetchLLMSettings } from "@/lib/llmSettings"
import {
  buildModelOptions,
  cloudOverrideAllowed,
  effectiveDefaultModel,
  shouldClearPrivateModeOverride,
} from "@/lib/chatSettingsUtils"

interface BlogRefineDialogProps {
  open: boolean
  onClose: () => void
  noteId: string
  noteContent: string
  kind?: BlogKind
  onApprove: (refinedContent: string) => void
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.body) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      /* non-JSON body */
    }
    return `HTTP ${err.status}`
  }
  return err instanceof Error ? err.message : fallback
}

export function BlogRefineDialog({
  open,
  onClose,
  noteId,
  noteContent,
  kind = "blog",
  onApprove,
}: BlogRefineDialogProps) {
  const kindLabel = KIND_SINGULAR[kind]
  const [instruction, setInstruction] = useState(DEFAULT_REFINE_PROMPT)
  const [refined, setRefined] = useState<string | null>(null)
  const [refining, setRefining] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  // Same selector as Chat/Study/Practice: "Auto" follows Settings, a concrete
  // id overrides only this refine call.
  const [refineModel, setRefineModel] = useState("")
  const { data: llmSettings } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
  const cloudAllowed = cloudOverrideAllowed(llmSettings?.mode)
  const provider = llmSettings?.provider
  const { data: cloudModels } = useQuery({
    queryKey: ["blog-refine-cloud-models", provider],
    queryFn: () =>
      apiGet<{ id: string }[]>("/settings/llm/models", { provider: provider as string }),
    enabled: Boolean(provider) && cloudAllowed,
    staleTime: 300_000,
  })
  const cloudModelChoices = cloudAllowed
    ? (cloudModels ?? []).map((m) => `${provider}/${m.id}`)
    : []
  const activeModel = shouldClearPrivateModeOverride(llmSettings?.mode, refineModel)
    ? ""
    : refineModel

  useEffect(() => {
    if (!open) return
    setInstruction(DEFAULT_REFINE_PROMPT)
    setRefined(null)
    setError(null)
  }, [open, noteId])

  async function handleRefine() {
    setRefining(true)
    setError(null)
    try {
      const { refined_content } = await refineNote(noteId, instruction, activeModel || undefined)
      setRefined(refined_content)
    } catch (err) {
      setError(errorMessage(err, "Refine failed"))
    } finally {
      setRefining(false)
    }
  }

  function handleApprove() {
    if (!refined) return
    onApprove(refined)
  }

  function handleClose() {
    setRefined(null)
    setError(null)
    setExpanded(false)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent
        className={
          expanded
            ? "flex h-[97vh] max-h-[97vh] w-[97vw] max-w-none flex-col overflow-hidden p-0"
            : "flex h-[88vh] max-h-[88vh] w-[92vw] max-w-[1300px] flex-col overflow-hidden p-0"
        }
      >
        <DialogHeader className="flex-row items-start justify-between gap-4 p-6 pb-2 space-y-0">
          <div className="space-y-1.5">
            <DialogTitle className="text-xl">
              Refine before publishing as {kindLabel.toLowerCase()}
            </DialogTitle>
            <DialogDescription>
              Runs your note through an editable instruction, then you review the result before it
              goes to the publish preview. Your saved note is not changed.
            </DialogDescription>
          </div>
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "Restore" : "Expand"}
            className="mt-1 shrink-0 rounded-md border border-input bg-background p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </DialogHeader>

        <div className="flex flex-1 flex-col gap-3 overflow-hidden px-6 py-3">
          <div className="flex items-start justify-between gap-3">
            <label className="flex flex-1 flex-col gap-1.5">
              <span className="text-xs font-semibold text-foreground">Refine instruction</span>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={4}
                className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              />
            </label>
            <ModelSelector
              value={refineModel}
              onChange={setRefineModel}
              localModels={buildModelOptions(llmSettings)}
              cloudModels={cloudModelChoices}
              effectiveDefault={effectiveDefaultModel(llmSettings)}
              title="Model used to refine this note. 'Auto' follows your Settings."
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {error}
            </div>
          )}

          <div className="flex flex-1 gap-3 overflow-hidden">
            <div className="flex flex-1 flex-col gap-1.5 overflow-hidden">
              <span className="text-xs font-semibold text-muted-foreground">Original note</span>
              <pre className="flex-1 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 text-sm text-foreground">
                {noteContent}
              </pre>
            </div>
            <div className="flex flex-1 flex-col gap-1.5 overflow-hidden">
              <span className="text-xs font-semibold text-muted-foreground">
                Refined -- edit freely before approving
              </span>
              {refining ? (
                <div className="flex flex-1 items-center justify-center rounded-md border border-border bg-muted/30 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Refining…
                </div>
              ) : (
                <textarea
                  value={refined ?? ""}
                  onChange={(e) => setRefined(e.target.value)}
                  placeholder="Run Refine to see the result here."
                  className="flex-1 resize-none rounded-md border border-border bg-white p-3 text-sm text-slate-900"
                />
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="flex items-center justify-end gap-2 border-t border-border bg-muted/10 p-4">
          <button
            onClick={handleClose}
            className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={() => void handleRefine()}
            disabled={refining || !instruction.trim()}
            className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
          >
            {refining ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {refined ? "Refine again" : "Run refine"}
          </button>
          <button
            onClick={handleApprove}
            disabled={!refined || !refined.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <UploadCloud className="h-4 w-4" />
            Approve &amp; continue
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
