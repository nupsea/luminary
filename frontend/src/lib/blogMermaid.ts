// blogMermaid — render the ```mermaid blocks in a note to standalone SVG so they
// can be published as images (the Astro site has no mermaid integration).
// Block order/keys mirror the backend transform (mermaid-1, mermaid-2, ...).

const MERMAID_RE = /^[ \t]*```mermaid[ \t]*\r?\n([\s\S]*?)^[ \t]*```[ \t]*$/gm

export function extractMermaidBlocks(content: string): string[] {
  const out: string[] = []
  let m: RegExpExecArray | null
  MERMAID_RE.lastIndex = 0
  while ((m = MERMAID_RE.exec(content)) !== null) out.push(m[1].trim())
  return out
}

export async function renderMermaidSvgs(content: string): Promise<Record<string, string>> {
  const blocks = extractMermaidBlocks(content)
  if (blocks.length === 0) return {}
  const mermaid = (await import("mermaid")).default
  mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" })
  const result: Record<string, string> = {}
  for (let i = 0; i < blocks.length; i++) {
    try {
      const { svg } = await mermaid.render(`blog-mermaid-${i}-${Date.now()}`, blocks[i])
      result[`mermaid-${i + 1}`] = svg
    } catch {
      // A broken diagram is skipped; publish reports the missing SVG so the
      // user can fix the note rather than shipping a blank image.
    }
  }
  return result
}

export function svgToDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
