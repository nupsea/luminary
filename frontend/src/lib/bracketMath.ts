/**
 * Models write TeX as `\( … \)` and `\[ … \]`. CommonMark reads those as
 * escaped brackets and remark-math knows only dollars, so the backslashes
 * vanish and the TeX shows as text. These become `$ … $` and `$$ … $$`.
 */

const FENCE_OPEN = /^\s*(`{3,}|~{3,})/
const FENCE_CLOSE = /^\s*(`{3,}|~{3,})\s*$/

/** Rewrites bracket-delimited math to dollars, leaving code untouched. */
export function bracketMathToDollars(markdown: string): string {
  if (!markdown.includes("\\(") && !markdown.includes("\\[")) return markdown
  const out: string[] = []
  let prose: string[] = []
  let fence: string | null = null
  const flush = () => {
    if (prose.length) out.push(convertProse(prose.join("\n")))
    prose = []
  }
  for (const line of markdown.split("\n")) {
    if (fence) {
      const close = FENCE_CLOSE.exec(line)?.[1]
      if (close && close[0] === fence[0] && close.length >= fence.length) fence = null
      out.push(line)
      continue
    }
    const open = FENCE_OPEN.exec(line)?.[1]
    if (open) {
      flush()
      fence = open
      out.push(line)
      continue
    }
    prose.push(line)
  }
  flush()
  return out.join("\n")
}

function runLength(text: string, at: number, ch: string): number {
  let n = 0
  while (text[at + n] === ch) n++
  return n
}

/** End of the code span opened by the backtick run at `at`, or of the run itself if unclosed. */
function codeSpanEnd(text: string, at: number): number {
  const n = runLength(text, at, "`")
  let i = at + n
  while (i < text.length) {
    if (text[i] !== "`") {
      i++
      continue
    }
    const m = runLength(text, i, "`")
    if (m === n) return i + m
    i += m
  }
  return at + n
}

function convertProse(text: string): string {
  let out = ""
  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === "`") {
      const end = codeSpanEnd(text, i)
      out += text.slice(i, end)
      i = end
      continue
    }
    if (ch !== "\\") {
      out += ch
      i++
      continue
    }
    const kind = text[i + 1]
    if (kind === "(" || kind === "[") {
      const close = text.indexOf(kind === "(" ? "\\)" : "\\]", i + 2)
      const inner = close < 0 ? "" : text.slice(i + 2, close)
      // A pair past a blank line is a stray delimiter, not math spanning paragraphs.
      if (close >= 0 && !/\n[ \t]*\n/.test(inner)) {
        const after = text.slice(close + 2)
        out += kind === "(" ? `$${inner}$` : displayMath(out, inner, after)
        i = close + 2
        continue
      }
    }
    // Also steps over `\\`, so an escaped backslash never opens math.
    out += text.slice(i, i + 2)
    i += 2
  }
  return out
}

/**
 * `$$` on lines of its own is display math; remark-math reads `$$ x $$` within
 * a line as inline, so a `\[ … \]` that owns its line is split onto three.
 */
function displayMath(before: string, inner: string, after: string): string {
  const indent = /(?:^|\n)([ \t]*)$/.exec(before)?.[1]
  if (indent === undefined || !/^[ \t]*(?:\n|$)/.test(after)) return `$$${inner}$$`
  return `$$\n${indent}${inner.trim()}\n${indent}$$`
}
