// The engine question, for a library that already existed when it shipped.
//
// `FirstRunGuide` asks it once, on an empty library. Everyone who upgraded kept
// the `private` default without being asked, met the local arm's complete-answer
// time with no explanation for it, and had no route to the other arm except a
// radio in Settings they had to already know to look for. This is the same
// question, in the one place an existing library's owner lands: it changes
// nothing until it is answered, and it does not come back once it has been.
//
// It renders `EngineChoice` rather than restating it. Two copies of a question
// about what leaves the machine is two wordings to keep true (I-16).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Cloud } from "lucide-react"
import { useState } from "react"

import { EngineChoice } from "@/components/setup/EngineChoice"
import { useHostVerdict } from "@/hooks/useHostVerdict"
import { apiGet, apiPatch } from "@/lib/apiClient"
import { engineOfferCopy, shouldOfferEngineChoice } from "@/lib/engineOffer"

interface LLMOfferState {
  mode: string
  mode_chosen: boolean
  offer_dismissed: boolean
}

export function EngineOffer() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => apiGet<LLMOfferState>("/settings/llm"),
    staleTime: 30_000,
  })

  const host = useHostVerdict()

  const dismiss = useMutation({
    mutationFn: () => apiPatch("/settings/llm", { offer_dismissed: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["llm-settings"] }),
  })

  const offer = shouldOfferEngineChoice(
    data && {
      mode: data.mode,
      modeChosen: data.mode_chosen,
      offerDismissed: data.offer_dismissed,
    },
  )
  if (!offer) return null
  const copy = engineOfferCopy(host?.supported)

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex items-start gap-2.5">
        <Cloud size={15} className="mt-0.5 shrink-0 text-blue-500" />
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold text-foreground">{copy.title}</h2>
          {/* What each mode sends is stated once, on its card in EngineChoice.
              A summary here promised "the question and the passages -- and
              nothing else", which Cloud mode does not keep. */}
          <p className="max-w-2xl text-xs text-muted-foreground">{copy.body}</p>
        </div>
      </div>

      {open ? (
        <div className="rounded-lg border border-border bg-background/40 p-3">
          <EngineChoice onChosen={() => setOpen(false)} />
        </div>
      ) : (
        <div className="flex items-center gap-3 pl-6">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Choose where answers come from
          </button>
          <button
            type="button"
            onClick={() => dismiss.mutate()}
            disabled={dismiss.isPending}
            className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-60"
          >
            Not now
          </button>
        </div>
      )}
    </section>
  )
}
