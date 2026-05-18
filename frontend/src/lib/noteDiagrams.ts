export interface ExcalidrawNoteDiagramRef {
  svgPath: string
  scenePath: string
  start: number
  end: number
}

const EXCALIDRAW_MARKER_RE = /!\[Diagram\|large\]\((__LUMINARY_IMG__\/notes\/[^)]+\.svg)\)\s*\n?<!-- luminary:excalidraw=(__LUMINARY_IMG__\/notes\/[^>]+\.excalidraw\.json) -->/g

export function buildExcalidrawDiagramMarkdown(svgPath: string, scenePath: string): string {
  return `![Diagram|large](${svgPath})\n<!-- luminary:excalidraw=${scenePath} -->`
}

export function findLastExcalidrawDiagram(content: string): ExcalidrawNoteDiagramRef | null {
  return findExcalidrawDiagrams(content).at(-1) ?? null
}

export function findExcalidrawDiagrams(content: string): ExcalidrawNoteDiagramRef[] {
  return [...content.matchAll(EXCALIDRAW_MARKER_RE)].flatMap((match) => {
    if (match.index === undefined) return []
    return {
      svgPath: match[1],
      scenePath: match[2],
      start: match.index,
      end: match.index + match[0].length,
    }
  })
}

export function replaceExcalidrawDiagram(
  content: string,
  ref: ExcalidrawNoteDiagramRef,
  markdown: string,
): string {
  return content.substring(0, ref.start) + markdown + content.substring(ref.end)
}
