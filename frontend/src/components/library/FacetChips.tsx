import { cn } from "@/lib/utils"
import type { DocumentFacets } from "./types"

/** What each facet answers, for the title attribute. */
const FACET_HELP: Record<string, string> = {
  form: "Shape: how the document reads",
  domain: "Subject: whether the content is technical",
  register: "Whether it tells a story or explains a subject",
  card_genre: "Which flashcard strategy this document gets",
}

/** A null facet is not a value — nothing has classified it.
 *
 *  Showing "general" for an unclassified document would present a default as a
 *  decision, which is the thing the reader is looking at this strip to check.
 */
function Facet({ label, value }: { label: string; value: string | null }) {
  const unclassified = !value
  return (
    <span
      className="inline-flex items-baseline gap-1"
      title={`${FACET_HELP[label] ?? label}${unclassified ? " — not yet classified" : ""}`}
    >
      <span className="text-muted-foreground/60">{label}</span>
      <span
        className={cn(
          "font-medium",
          unclassified ? "italic text-muted-foreground/50" : "text-foreground/80",
        )}
      >
        {value ?? "unclassified"}
      </span>
    </span>
  )
}

/** The three facets the pipeline records, plus the card strategy they imply.
 *
 *  Rendered so a reader can check the classification rather than trust it: the
 *  card strategy is the visible consequence of `form` and `domain`, so a wrong
 *  facet shows up here as a wrong strategy before it shows up as a bad card.
 */
export function FacetChips({
  facets,
  className,
}: {
  facets?: DocumentFacets | null
  className?: string
}) {
  if (!facets?.form) return null
  return (
    <div
      className={cn(
        "flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[10px] leading-relaxed",
        className,
      )}
    >
      <Facet label="form" value={facets.form} />
      <Facet label="domain" value={facets.domain} />
      <Facet label="register" value={facets.register} />
      <span className="inline-flex items-baseline gap-1" title={FACET_HELP.card_genre}>
        <span className="text-muted-foreground/60">cards</span>
        <span
          className={cn(
            "font-medium",
            facets.card_genre ? "text-primary/80" : "italic text-muted-foreground/50",
          )}
        >
          {/* Blank rather than a strategy name: the facets did not determine
              one. A default shown here is what made The Odyssey non-fiction. */}
          {facets.card_genre ?? "unclassified"}
        </span>
      </span>
    </div>
  )
}
