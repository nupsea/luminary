import type { components } from "@/types/api"

type Metric = components["schemas"]["Metric"]

/** The number as the user should read it, with its unit attached.
 *
 *  A metric that could not be computed carries a null value and says why in its
 *  basis. It renders as an em dash: a zero here would read as a measurement,
 *  which is the failure the whole provenance contract exists to prevent.
 */
export function formatMetric(metric: Metric | undefined): string {
  if (!metric || metric.value === null) return "\u2014"
  switch (metric.unit) {
    case "percent":
      return `${metric.value}%`
    case "minutes":
      return `${metric.value}m`
    default:
      return `${metric.value}`
  }
}
