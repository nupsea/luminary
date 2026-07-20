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
  mermaid.initialize({
    startOnLoad: false,
    theme: "default",
    securityLevel: "loose",
    // Keeps a malformed diagram from appending mermaid's error graphic to the
    // live page while we are only rendering SVGs for export.
    suppressErrorRendering: true,
  })
  const result: Record<string, string> = {}
  for (let i = 0; i < blocks.length; i++) {
    const renderId = `blog-mermaid-${i}-${Date.now()}`
    try {
      const { svg } = await mermaid.render(renderId, blocks[i])
      result[`mermaid-${i + 1}`] = svg
    } catch {
      // A broken diagram is skipped; publish reports the missing SVG so the
      // user can fix the note rather than shipping a blank image.
      document.getElementById(`d${renderId}`)?.remove()
    }
  }
  return result
}

export function svgToDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
