// Report text and the prefilled email built from it.

const LOG_MARK = "Recent log:"
// Windows refuses a mailto: link much past 2,000 characters.
const MAX_MAILTO = 1900

export interface ProblemReport {
  environment: string
  problem: string
  detail: string
  log: string
  email: string
}

export function compose(r: ProblemReport): string {
  const lines = [`What happened: ${r.problem}`]
  if (r.detail) lines.push(`Details: ${r.detail}`)
  lines.push("", r.environment, "", LOG_MARK, r.log || "(no log available)")
  return lines.join("\n")
}

function split(text: string): { head: string; log: string[] } {
  const at = text.indexOf(LOG_MARK)
  if (at < 0) return { head: text.trim(), log: [] }
  return {
    head: text.slice(0, at).trim(),
    log: text.slice(at + LOG_MARK.length).trim().split("\n"),
  }
}

/** The URL `build` makes from as many of the newest log lines as fit in `max`. */
function fitLog(log: string[], max: number, build: (log: string, trimmed: boolean) => string) {
  for (let from = 0; from <= log.length; from++) {
    const url = build(log.slice(from).join("\n"), from > 0)
    if (url.length <= max) return url
  }
  return build("", log.length > 0)
}

const enc = encodeURIComponent

export function emailUrl(email: string, problem: string, text: string): string {
  const { head, log } = split(text)
  return fitLog(log, MAX_MAILTO, (lines, trimmed) => {
    const note = trimmed ? "\n\n[Older log lines were cut to fit; the full report is on your clipboard.]" : ""
    const body = `${head}\n\n${LOG_MARK}\n${lines}${note}`
    return `mailto:${email}?subject=${enc(`Luminary problem: ${problem}`)}&body=${enc(body)}`
  })
}
