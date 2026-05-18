export function parseAudioStartTime(heading: string): number | null {
  const m = heading.match(/\((\d+(?:\.\d+)?)s-/)
  if (!m) return null
  return parseFloat(m[1])
}

export function formatMmSs(seconds: number): string {
  const s = Math.floor(seconds)
  const mm = Math.floor(s / 60).toString().padStart(2, "0")
  const ss = (s % 60).toString().padStart(2, "0")
  return `${mm}:${ss}`
}
