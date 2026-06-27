// Guided first-run shown inside the empty Hub: three steps from a cold install to
// a first calibrated review. Step 1 opens the upload dialog inline; once a doc is
// ready we auto-generate a small starter deck (when the LLM is reachable, else we
// guide the user to start Ollama / generate manually); step 3 launches the review.
//
// The component drives itself off its own polled /documents query rather than the
// Hub's overview, so it keeps working through ingestion even though the Hub leaves
// its empty state once content exists.

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, ArrowRight, BookPlus, CheckCircle2, Loader2 } from "lucide-react"
import { Link } from "react-router-dom"

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import { UploadDialog } from "@/components/library/UploadDialog"
import { apiGet } from "@/lib/apiClient"
import { isDocumentReady } from "@/lib/documentReadiness"
import { launchStudy } from "@/lib/studyLauncher"
import { generateFlashcards } from "@/pages/Study/api"
import { cn } from "@/lib/utils"

interface FirstRunDoc {
  id: string
  title: string
  stage: string
}

interface DocsPage {
  items: FirstRunDoc[]
  total: number
}

type GenState = "idle" | "generating" | "done" | "error"

export function FirstRunGuide() {
  const [uploadOpen, setUploadOpen] = useState(false)
  const [genState, setGenState] = useState<GenState>("idle")
  const [genCount, setGenCount] = useState(0)

  // Poll the newest document so the guide reacts to upload + ingestion finishing.
  // Stops polling once a ready doc exists (generation is handled by the effect).
  const { data: docsPage } = useQuery({
    queryKey: ["first-run-docs"],
    queryFn: () => apiGet<DocsPage>("/documents", { sort: "newest", page: 1, page_size: 1 }),
    refetchInterval: (query) => {
      const first = (query.state.data as DocsPage | undefined)?.items?.[0]
      if (!first || !isDocumentReady(first)) return 4000
      return false
    },
    staleTime: 0,
  })
  const firstDoc = docsPage?.items?.[0]
  const hasDoc = !!firstDoc
  const docReady = isDocumentReady(firstDoc)

  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => apiGet<{ processing_mode: string; mode: string }>("/settings/llm"),
    staleTime: 30_000,
  })
  const ollamaDown = llm?.mode === "private" && llm?.processing_mode === "unavailable"

  // Auto-generate a starter deck once a ready doc appears and the LLM is up.
  useEffect(() => {
    if (!firstDoc || !docReady || ollamaDown || genState !== "idle") return
    // Intentional: flip to the loading state as we kick off the one-shot generation
    // (guarded by `genState !== "idle"` above so it fires once).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGenState("generating")
    generateFlashcards({
      document_id: firstDoc.id,
      scope: "full",
      section_heading: null,
      count: 5,
      difficulty: "medium",
    })
      .then((cards) => {
        setGenCount(cards.length)
        setGenState(cards.length > 0 ? "done" : "error")
      })
      .catch(() => setGenState("error"))
  }, [firstDoc, docReady, ollamaDown, genState])

  const step1Done = hasDoc
  const step2Done = genState === "done"

  return (
    <>
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 rounded-2xl border border-border bg-card/60 px-6 py-10">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/15">
            <LuminaryGlyph size={28} className="text-primary" />
          </span>
          <h2 className="text-xl font-semibold text-foreground">Welcome to Luminary</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Three quick steps to your first review. Everything stays on your machine.
          </p>
        </div>

        <ol className="flex flex-col gap-3">
          {/* Step 1 -- add a document */}
          <StepRow
            n={1}
            title="Add a document"
            state={step1Done ? "done" : "active"}
            detail={
              step1Done ? (
                <span className="truncate">{firstDoc!.title}</span>
              ) : (
                "A PDF, EPUB, article URL, or pasted text."
              )
            }
            action={
              !step1Done && (
                <button
                  onClick={() => setUploadOpen(true)}
                  className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <BookPlus size={14} />
                  Add
                </button>
              )
            }
          />

          {/* Step 2 -- generate the first cards */}
          <StepRow
            n={2}
            title="Generate your first cards"
            state={step2Done ? "done" : step1Done ? "active" : "pending"}
            detail={
              !step1Done ? (
                "Add a document first."
              ) : !docReady ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" />
                  Processing your document…
                </span>
              ) : ollamaDown ? (
                <span className="flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
                  <AlertTriangle size={12} className="shrink-0" />
                  Start Ollama (<code className="font-mono font-semibold">ollama serve</code>) to
                  generate cards, or{" "}
                  <Link to="/study" className="underline underline-offset-2">
                    do it in Study
                  </Link>
                  .
                </span>
              ) : genState === "generating" ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" />
                  Generating 5 cards…
                </span>
              ) : genState === "done" ? (
                `${genCount} card${genCount === 1 ? "" : "s"} ready.`
              ) : genState === "error" ? (
                <span className="flex items-center gap-1.5">
                  Couldn't generate automatically —{" "}
                  <Link to="/study" className="underline underline-offset-2">
                    try it in Study
                  </Link>
                  .
                </span>
              ) : null
            }
          />

          {/* Step 3 -- first review */}
          <StepRow
            n={3}
            title="Do your first review"
            state={step2Done ? "active" : "pending"}
            detail="Predict, then rate — Luminary tracks how well-calibrated you are."
            action={
              step2Done && (
                <button
                  onClick={() =>
                    launchStudy({ type: "doc", ref: firstDoc!.id, label: firstDoc!.title })
                  }
                  className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  Start review
                  <ArrowRight size={14} />
                </button>
              )
            }
          />
        </ol>

        <div className="text-center">
          <Link
            to="/library"
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Prefer to explore on your own? Go to the Library
          </Link>
        </div>
      </div>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  )
}

function StepRow({
  n,
  title,
  state,
  detail,
  action,
}: {
  n: number
  title: string
  state: "pending" | "active" | "done"
  detail?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors",
        state === "active"
          ? "border-primary/30 bg-primary/[0.04]"
          : state === "done"
            ? "border-border bg-card/40"
            : "border-dashed border-border/60 bg-transparent",
      )}
    >
      <span
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
          state === "done"
            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : state === "active"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground",
        )}
      >
        {state === "done" ? <CheckCircle2 size={16} /> : n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn(
            "text-sm font-medium",
            state === "pending" ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {title}
        </span>
        {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
      </div>
      {action}
    </li>
  )
}
