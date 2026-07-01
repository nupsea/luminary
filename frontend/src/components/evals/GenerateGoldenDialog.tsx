import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { AlertTriangle, Sparkles } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/config"

interface Models {
  local: string[]
  frontier: string[]
}

async function fetchModels(): Promise<Models> {
  const res = await fetch(`${API_BASE}/evals/models`)
  if (!res.ok) throw new Error("Failed to fetch models")
  return res.json() as Promise<Models>
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultName: string
  defaultSourceFile: string
  onStarted: (label: string) => void
}

export function GenerateGoldenDialog({
  open,
  onOpenChange,
  defaultName,
  defaultSourceFile,
  onStarted,
}: Props) {
  const modelsQuery = useQuery({ queryKey: ["eval-models"], queryFn: fetchModels, enabled: open })
  const models = modelsQuery.data ?? { local: [], frontier: [] }
  const allModels = [...models.frontier, ...models.local]

  const [name, setName] = useState(defaultName)
  const [sourceFile, setSourceFile] = useState(defaultSourceFile)
  const [generator, setGenerator] = useState("openai/gpt-5.4")
  const [verify1, setVerify1] = useState("openai/gpt-5.1")
  const [verify2, setVerify2] = useState("ollama/qwen2.5:14b-instruct")
  const [target, setTarget] = useState(50)

  const mut = useMutation({
    mutationFn: async () => {
      const verify_models = [verify1, verify2].filter((m, i, a) => m && a.indexOf(m) === i)
      const res = await fetch(`${API_BASE}/evals/golden/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          source_file: sourceFile,
          generator_model: generator,
          verify_models,
          target,
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string }
        throw new Error(body.detail ?? "Failed to start generation")
      }
      return res.json()
    },
    onSuccess: () => {
      onOpenChange(false)
      onStarted(`generating ${name} · ${generator.split("/").pop()}`)
      toast.success(`Generating golden "${name}" — this can take a few minutes`)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Generation failed"),
  })

  const localVerifyDown =
    /^ollama\//.test(verify2) && models.local.length === 0 && !modelsQuery.isLoading
  const Select = ({
    value,
    onChange,
    includeNone,
  }: {
    value: string
    onChange: (v: string) => void
    includeNone?: boolean
  }) => (
    <select
      className="h-9 rounded-md border bg-background px-2 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {includeNone && <option value="">None</option>}
      {allModels.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
      {value && !allModels.includes(value) && <option value={value}>{value}</option>}
    </select>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Generate / replace golden</DialogTitle>
          <DialogDescription>
            One-time generation with cross-model verification. Reusing a name replaces it.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <label className="grid gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Dataset name</span>
            <input
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Source file (repo-relative)</span>
            <input
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={sourceFile}
              onChange={(e) => setSourceFile(e.target.value)}
              placeholder="DATA/books/…"
            />
          </label>
          <label className="grid gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Generator model</span>
            <Select value={generator} onChange={setGenerator} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1 text-xs">
              <span className="font-medium text-muted-foreground">Verifier 1</span>
              <Select value={verify1} onChange={setVerify1} includeNone />
            </label>
            <label className="grid gap-1 text-xs">
              <span className="font-medium text-muted-foreground">Verifier 2</span>
              <Select value={verify2} onChange={setVerify2} includeNone />
            </label>
          </div>
          <label className="grid gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Target questions: {target}</span>
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
            />
          </label>
          {localVerifyDown && (
            <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              No local models detected (Ollama down). A local verifier will reject everything —
              start Ollama or pick a frontier verifier.
            </div>
          )}
        </div>

        <DialogFooter>
          <button
            type="button"
            disabled={mut.isPending || !name || !sourceFile}
            onClick={() => mut.mutate()}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            Generate
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
