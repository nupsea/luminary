// Pure helpers (formatters + colour mappers) consumed by the Monitoring
// page sub-components. No React, no fetches.

export function formatDuration(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)} min`
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(2)} s`
  return `${ms.toFixed(1)} ms`
}

export function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}k`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function masteryColor(mastery: number | null): string {
  if (mastery === null) return "bg-gray-100 dark:bg-gray-800"
  if (mastery < 0.3) return "bg-blue-200 dark:bg-blue-900"
  if (mastery < 0.6) return "bg-blue-400 dark:bg-blue-700"
  if (mastery < 0.8) return "bg-green-400 dark:bg-green-700"
  return "bg-green-600 dark:bg-green-500"
}
