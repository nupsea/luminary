import { findExcalidrawDiagrams, type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { lineOffsetAt } from "@/lib/rehypeSourceLine"

export interface MarkdownBlockChunk {
  key: string
  source: string
  lineOffset: number
  isDiagram?: boolean
  diagramRef?: ExcalidrawNoteDiagramRef
}

export function splitMarkdownIntoBlocks(content: string): MarkdownBlockChunk[] {
  if (!content) return []

  const diagrams = findExcalidrawDiagrams(content)
  const lines = content.split("\n")
  const chunks: MarkdownBlockChunk[] = []

  let currentBlockLines: string[] = []
  let blockStartLine = 0
  let inFencedCode = false
  let inMathBlock = false
  let fenceMarker = ""

  // Helper to check if a line is within an excalidraw diagram
  const getDiagramAtLine = (lineIdx: number): { diagram: ExcalidrawNoteDiagramRef; startLine: number; endLine: number } | null => {
    let charOffset = 0
    for (let i = 0; i < lineIdx; i++) {
      charOffset += lines[i].length + 1
    }
    for (const d of diagrams) {
      if (charOffset >= d.start && charOffset < d.end) {
        return {
          diagram: d,
          startLine: lineOffsetAt(content, d.start),
          endLine: lineOffsetAt(content, d.end),
        }
      }
    }
    return null
  }

  for (let i = 0; i < lines.length; i++) {
    const diag = getDiagramAtLine(i)
    if (diag) {
      if (currentBlockLines.length > 0) {
        chunks.push({
          key: `b-${blockStartLine}`,
          source: currentBlockLines.join("\n"),
          lineOffset: blockStartLine,
        })
        currentBlockLines = []
      }
      chunks.push({
        key: `diag-${diag.diagram.scenePath}`,
        source: content.substring(diag.diagram.start, diag.diagram.end),
        lineOffset: diag.startLine,
        isDiagram: true,
        diagramRef: diag.diagram,
      })
      i = diag.endLine
      blockStartLine = i + 1
      continue
    }

    const line = lines[i]
    const trimmed = line.trim()

    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/)
    if (fenceMatch) {
      if (!inFencedCode) {
        inFencedCode = true
        fenceMarker = fenceMatch[1]
      } else if (trimmed.startsWith(fenceMarker)) {
        inFencedCode = false
        fenceMarker = ""
      }
    }

    if (trimmed === "$$" || trimmed.startsWith("$$")) {
      inMathBlock = !inMathBlock
    }

    if (!inFencedCode && !inMathBlock && trimmed === "") {
      if (currentBlockLines.length > 0) {
        chunks.push({
          key: `b-${blockStartLine}`,
          source: currentBlockLines.join("\n"),
          lineOffset: blockStartLine,
        })
        currentBlockLines = []
      }
      blockStartLine = i + 1
      continue
    }

    currentBlockLines.push(line)
  }

  if (currentBlockLines.length > 0) {
    chunks.push({
      key: `b-${blockStartLine}`,
      source: currentBlockLines.join("\n"),
      lineOffset: blockStartLine,
    })
  }

  return chunks
}
