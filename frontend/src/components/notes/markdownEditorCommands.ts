import type { EditorState, TransactionSpec } from "@codemirror/state"

// Mirrors the old insertAtTextareaCursor semantics: the block lands in its own
// paragraph with blank lines around it (mermaid/excalidraw insertions).
export function insertBlockSpec(state: EditorState, markdown: string): TransactionSpec {
  const { from, to } = state.selection.main
  const before = state.sliceDoc(0, from)
  const after = state.sliceDoc(to)
  const prefix = from > 0 && !before.endsWith("\n") ? "\n\n" : ""
  const suffix = after.startsWith("\n") ? "" : "\n\n"
  const insertion = `${prefix}${markdown}${suffix}`
  return {
    changes: { from, to, insert: insertion },
    selection: { anchor: from + insertion.length },
    scrollIntoView: true,
  }
}

export function insertInlineSpec(state: EditorState, text: string): TransactionSpec {
  const { from, to } = state.selection.main
  return {
    changes: { from, to, insert: text },
    selection: { anchor: from + text.length },
    scrollIntoView: true,
  }
}

// Sync an external value into the view as a minimal edit. A full 0..len
// replace would remap the caret to the document start; diffing to the changed
// span lets CodeMirror carry the selection through, so a programmatic edit
// (image-size pipe, diagram swap, append) does not eject the cursor.
export function syncDocSpec(state: EditorState, value: string): TransactionSpec | null {
  const current = state.doc.toString()
  if (value === current) return null
  let start = 0
  const minLen = Math.min(current.length, value.length)
  while (start < minLen && current.charCodeAt(start) === value.charCodeAt(start)) start++
  let endCur = current.length
  let endVal = value.length
  while (
    endCur > start &&
    endVal > start &&
    current.charCodeAt(endCur - 1) === value.charCodeAt(endVal - 1)
  ) {
    endCur--
    endVal--
  }
  // Seeding an empty view with async-loaded content: land the caret at the
  // end so the first keystroke appends instead of prepending at offset 0.
  if (current.length === 0) {
    return { changes: { from: 0, insert: value }, selection: { anchor: value.length } }
  }
  return { changes: { from: start, to: endCur, insert: value.slice(start, endVal) } }
}

export function replaceSelectionSpec(
  state: EditorState,
  fn: (selected: string) => string,
): TransactionSpec {
  const { from, to } = state.selection.main
  const next = fn(state.sliceDoc(from, to))
  return {
    changes: { from, to, insert: next },
    selection: { anchor: from + next.length },
    scrollIntoView: true,
  }
}

// Rewrite the |size pipe of the image whose URL matches the rendered src.
// Mirrored images render as <apiBase>/images/local/... but are authored as
// __LUMINARY_IMG__/..., so both spellings are tried.
export function setImageSizeInMarkdown(
  content: string,
  src: string,
  size: string,
  apiBase?: string,
): string {
  const candidates = [src]
  if (apiBase && src.startsWith(`${apiBase}/images/local/`)) {
    candidates.push(src.replace(`${apiBase}/images/local/`, "__LUMINARY_IMG__/"))
  }
  for (const url of candidates) {
    const closeIdx = content.indexOf(`](${url})`)
    if (closeIdx === -1) continue
    const openIdx = content.lastIndexOf("![", closeIdx)
    if (openIdx === -1) continue
    const alt = content.slice(openIdx + 2, closeIdx)
    const base = alt.split("|")[0].trim() || "Image"
    const end = closeIdx + 2 + url.length + 1
    return `${content.slice(0, openIdx)}![${base}|${size}](${url})${content.slice(end)}`
  }
  return content
}

// Toggle **strong** / *emphasis* markers around the selection. An empty
// selection gets an open pair with the cursor inside.
export function toggleInlineMarkSpec(state: EditorState, marker: string): TransactionSpec {
  const { from, to } = state.selection.main
  const selected = state.sliceDoc(from, to)
  const mlen = marker.length

  if (selected.startsWith(marker) && selected.endsWith(marker) && selected.length >= mlen * 2) {
    const inner = selected.slice(mlen, selected.length - mlen)
    return {
      changes: { from, to, insert: inner },
      selection: { anchor: from, head: from + inner.length },
    }
  }

  const beforeMark = state.sliceDoc(Math.max(0, from - mlen), from)
  const afterMark = state.sliceDoc(to, Math.min(state.doc.length, to + mlen))
  if (beforeMark === marker && afterMark === marker) {
    return {
      changes: { from: from - mlen, to: to + mlen, insert: selected },
      selection: { anchor: from - mlen, head: from - mlen + selected.length },
    }
  }

  return {
    changes: { from, to, insert: `${marker}${selected}${marker}` },
    selection: selected
      ? { anchor: from + mlen, head: from + mlen + selected.length }
      : { anchor: from + mlen },
  }
}

export interface EnclosingBlock {
  from: number
  to: number
  startLine: number
  endLine: number
  type: "math" | "table" | "code" | "diagram" | "heading"
}

/**
 * Identify whether `pos` sits within a structured markdown block (display math, table, code, diagram, or heading).
 */
export function findEnclosingBlock(state: EditorState, pos: number): EnclosingBlock | null {
  if (pos < 0 || pos > state.doc.length) return null
  const currentLine = state.doc.lineAt(pos)
  const totalLines = state.doc.lines

  // 1. Check Math block: $$ ... $$
  let mathOpenLine: number | null = null
  for (let ln = currentLine.number; ln >= 1; ln--) {
    const text = state.doc.line(ln).text.trim()
    if (text === "$$") {
      let isCloseOfPrevious = false
      let countAbove = 0
      for (let up = ln - 1; up >= 1; up--) {
        if (state.doc.line(up).text.trim() === "$$") countAbove++
      }
      if (countAbove % 2 === 1 && ln === currentLine.number) {
        isCloseOfPrevious = true
      }
      if (isCloseOfPrevious) {
        for (let up = ln - 1; up >= 1; up--) {
          if (state.doc.line(up).text.trim() === "$$") {
            const openL = state.doc.line(up)
            const closeL = state.doc.line(ln)
            return {
              from: openL.from,
              to: closeL.to,
              startLine: openL.number,
              endLine: closeL.number,
              type: "math",
            }
          }
        }
      }
      mathOpenLine = ln
      break
    }
  }

  if (mathOpenLine !== null) {
    let mathCloseLine: number | null = null
    for (let ln = mathOpenLine + 1; ln <= totalLines; ln++) {
      if (state.doc.line(ln).text.trim() === "$$") {
        mathCloseLine = ln
        break
      }
    }
    if (mathCloseLine !== null && currentLine.number <= mathCloseLine) {
      const openL = state.doc.line(mathOpenLine)
      const closeL = state.doc.line(mathCloseLine)
      return {
        from: openL.from,
        to: closeL.to,
        startLine: openL.number,
        endLine: closeL.number,
        type: "math",
      }
    }
  }

  // 2. Check Fenced Code Block: ``` or ~~~
  let codeOpenLine: number | null = null
  let codeFenceChar = ""
  for (let ln = currentLine.number; ln >= 1; ln--) {
    const text = state.doc.line(ln).text.trim()
    const match = text.match(/^(`{3,}|~{3,})/)
    if (match) {
      let countAbove = 0
      for (let up = ln - 1; up >= 1; up--) {
        const upText = state.doc.line(up).text.trim()
        if (upText.startsWith(match[1])) countAbove++
      }
      if (countAbove % 2 === 1 && ln === currentLine.number) {
        // Closing fence on current line
        for (let up = ln - 1; up >= 1; up--) {
          const upText = state.doc.line(up).text.trim()
          if (upText.startsWith(match[1])) {
            const openL = state.doc.line(up)
            const closeL = state.doc.line(ln)
            return {
              from: openL.from,
              to: closeL.to,
              startLine: openL.number,
              endLine: closeL.number,
              type: "code",
            }
          }
        }
      }
      codeOpenLine = ln
      codeFenceChar = match[1]
      break
    }
  }
  if (codeOpenLine !== null) {
    let codeCloseLine: number | null = null
    const fencePrefix = codeFenceChar[0].repeat(codeFenceChar.length)
    for (let ln = codeOpenLine + 1; ln <= totalLines; ln++) {
      const text = state.doc.line(ln).text.trim()
      if (text.startsWith(fencePrefix)) {
        codeCloseLine = ln
        break
      }
    }
    if (codeCloseLine !== null && currentLine.number <= codeCloseLine) {
      const openL = state.doc.line(codeOpenLine)
      const closeL = state.doc.line(codeCloseLine)
      return {
        from: openL.from,
        to: closeL.to,
        startLine: openL.number,
        endLine: closeL.number,
        type: "code",
      }
    }
  }

  // 3. Check Table: consecutive lines containing | and having a header separator
  if (currentLine.text.includes("|")) {
    let tableStart = currentLine.number
    while (
      tableStart > 1 &&
      state.doc.line(tableStart - 1).text.includes("|") &&
      state.doc.line(tableStart - 1).text.trim().length > 0
    ) {
      tableStart--
    }
    let tableEnd = currentLine.number
    while (
      tableEnd < totalLines &&
      state.doc.line(tableEnd + 1).text.includes("|") &&
      state.doc.line(tableEnd + 1).text.trim().length > 0
    ) {
      tableEnd++
    }
    if (tableEnd > tableStart) {
      let hasSep = false
      for (let ln = tableStart; ln <= tableEnd; ln++) {
        if (/\|[\s:-]+-+\s*\|/.test(state.doc.line(ln).text)) {
          hasSep = true
          break
        }
      }
      if (hasSep) {
        const startL = state.doc.line(tableStart)
        const endL = state.doc.line(tableEnd)
        return {
          from: startL.from,
          to: endL.to,
          startLine: startL.number,
          endLine: endL.number,
          type: "table",
        }
      }
    }
  }

  // 4. Check Diagram / Image block: ![...] + optional <!-- luminary:excalidraw=... -->
  const trimmed = currentLine.text.trim()
  const isImageLine = /^!\[.*\]\(.*\)/.test(trimmed)
  const isExcalidrawComment = /^<!--\s*luminary:excalidraw=.*-->$/.test(trimmed)
  if (isImageLine || isExcalidrawComment) {
    let diagStart = currentLine.number
    let diagEnd = currentLine.number
    if (
      isExcalidrawComment &&
      diagStart > 1 &&
      /^!\[.*\]\(.*\)/.test(state.doc.line(diagStart - 1).text.trim())
    ) {
      diagStart = diagStart - 1
    } else if (
      isImageLine &&
      diagEnd < totalLines &&
      /^<!--\s*luminary:excalidraw=.*-->$/.test(state.doc.line(diagEnd + 1).text.trim())
    ) {
      diagEnd = diagEnd + 1
    }
    const startL = state.doc.line(diagStart)
    const endL = state.doc.line(diagEnd)
    return {
      from: startL.from,
      to: endL.to,
      startLine: startL.number,
      endLine: endL.number,
      type: "diagram",
    }
  }

  // 5. Check Heading block
  if (/^#{1,6}\s+\S/.test(trimmed)) {
    return {
      from: currentLine.from,
      to: currentLine.to,
      startLine: currentLine.number,
      endLine: currentLine.number,
      type: "heading",
    }
  }

  return null
}

/**
 * Move the current block (or current line) up (-1) or down (1).
 * When cursor is inside a math block, table, code, diagram, or heading, moves the entire block as a unit,
 * seamlessly swapping past adjacent blocks or paragraphs while normalizing spacing.
 */
export function moveBlockOrLineSpec(state: EditorState, dir: -1 | 1): TransactionSpec | null {
  const { from, to } = state.selection.main
  const block = findEnclosingBlock(state, from)

  if (block) {
    const startLine = block.startLine
    const endLine = block.endLine
    const blockText = state.sliceDoc(block.from, block.to).trim()

    if (dir === -1) {
      // Move UP
      if (startLine <= 1) return null
      let targetLineNum = startLine - 1
      while (targetLineNum > 1 && state.doc.line(targetLineNum).text.trim() === "") {
        targetLineNum--
      }
      if (state.doc.line(targetLineNum).text.trim() === "") return null

      const aboveBlock = findEnclosingBlock(state, state.doc.line(targetLineNum).from)
      const targetStartLine = aboveBlock ? aboveBlock.startLine : targetLineNum
      const targetFrom = state.doc.line(targetStartLine).from
      const aboveText = state.sliceDoc(targetFrom, state.doc.line(startLine - 1).to).trim()

      const newText = `${blockText}\n\n${aboveText}`
      const replaceTo = block.to
      const relOffset = Math.min(from - block.from, blockText.length)
      return {
        changes: { from: targetFrom, to: replaceTo, insert: newText },
        selection: { anchor: targetFrom + relOffset },
        scrollIntoView: true,
      }
    } else {
      // Move DOWN
      if (endLine >= state.doc.lines) return null
      let targetLineNum = endLine + 1
      while (targetLineNum < state.doc.lines && state.doc.line(targetLineNum).text.trim() === "") {
        targetLineNum++
      }
      if (state.doc.line(targetLineNum).text.trim() === "") return null

      const belowBlock = findEnclosingBlock(state, state.doc.line(targetLineNum).from)
      const targetEndLine = belowBlock ? belowBlock.endLine : targetLineNum
      const targetTo = state.doc.line(targetEndLine).to
      const belowText = state.sliceDoc(state.doc.line(endLine + 1).from, targetTo).trim()

      const newText = `${belowText}\n\n${blockText}`
      const targetFrom = block.from
      const newBlockStart = targetFrom + belowText.length + 2 // length + \n\n
      const relOffset = Math.min(from - block.from, blockText.length)
      return {
        changes: { from: targetFrom, to: targetTo, insert: newText },
        selection: { anchor: newBlockStart + relOffset },
        scrollIntoView: true,
      }
    }
  }

  // Normal line motion — block aware so lines do not slice into the middle of structured blocks
  const lineFrom = state.doc.lineAt(from)
  const lineTo = state.doc.lineAt(to)
  if (dir === -1) {
    if (lineFrom.number <= 1) return null
    const targetNum = lineFrom.number - 1
    const aboveBlock = findEnclosingBlock(state, state.doc.line(targetNum).from)
    const targetStartLine = aboveBlock ? aboveBlock.startLine : targetNum
    const prevFrom = state.doc.line(targetStartLine).from
    const movingText = state.sliceDoc(lineFrom.from, lineTo.to)
    const aboveText = state.sliceDoc(prevFrom, lineFrom.from - 1)
    return {
      changes: [
        { from: prevFrom, to: lineTo.to, insert: `${movingText}\n${aboveText}` },
      ],
      selection: { anchor: prevFrom + (from - lineFrom.from) },
      scrollIntoView: true,
    }
  } else {
    if (lineTo.number >= state.doc.lines) return null
    const targetNum = lineTo.number + 1
    const belowBlock = findEnclosingBlock(state, state.doc.line(targetNum).from)
    const targetEndLine = belowBlock ? belowBlock.endLine : targetNum
    const nextTo = state.doc.line(targetEndLine).to
    const movingText = state.sliceDoc(lineFrom.from, lineTo.to)
    const belowText = state.sliceDoc(lineTo.to + 1, nextTo)
    return {
      changes: [
        { from: lineFrom.from, to: nextTo, insert: `${belowText}\n${movingText}` },
      ],
      selection: { anchor: lineFrom.from + belowText.length + 1 + (from - lineFrom.from) },
      scrollIntoView: true,
    }
  }
}

/**
 * Navigate to next cell in a markdown table on Tab.
 * If at end of row, moves to next row.
 * If at end of last row, automatically appends a new row with matching column count!
 */
export function tableNextCellSpec(state: EditorState): TransactionSpec | null {
  const { from } = state.selection.main
  const line = state.doc.lineAt(from)
  if (!line.text.includes("|")) return null

  const parts = line.text.split("|")
  if (parts.length < 3) return null

  const colIndex = from - line.from
  let cumLen = 0
  let currentPipeIndex = 0
  for (let i = 0; i < parts.length; i++) {
    cumLen += parts[i].length + (i > 0 ? 1 : 0)
    if (colIndex <= cumLen) {
      currentPipeIndex = i
      break
    }
  }

  // Next cell in same row
  if (currentPipeIndex < parts.length - 2) {
    const nextPipeIdx = currentPipeIndex + 1
    const cellStart = parts.slice(0, nextPipeIdx).join("|").length + 1
    const cellText = parts[nextPipeIdx]
    const contentOffset = cellText.startsWith(" ") ? 1 : 0
    return {
      selection: { anchor: line.from + cellStart + contentOffset },
      scrollIntoView: true,
    }
  }

  // Last cell in row -> move to next row
  const nextLineNum = line.number + 1
  if (nextLineNum <= state.doc.lines) {
    const nextLine = state.doc.line(nextLineNum)
    if (nextLine.text.includes("|")) {
      if (/\|[\s:-]+-+\s*\|/.test(nextLine.text)) {
        if (nextLineNum + 1 <= state.doc.lines) {
          const rowAfter = state.doc.line(nextLineNum + 1)
          if (rowAfter.text.includes("|")) {
            const firstCellOffset = rowAfter.text.indexOf("|") + 1
            const spaceOffset = rowAfter.text.slice(firstCellOffset).startsWith(" ") ? 1 : 0
            return {
              selection: { anchor: rowAfter.from + firstCellOffset + spaceOffset },
              scrollIntoView: true,
            }
          }
        }
      } else {
        const firstCellOffset = nextLine.text.indexOf("|") + 1
        const spaceOffset = nextLine.text.slice(firstCellOffset).startsWith(" ") ? 1 : 0
        return {
          selection: { anchor: nextLine.from + firstCellOffset + spaceOffset },
          scrollIntoView: true,
        }
      }
    }
  }

  // At the very end of table -> append a new row
  const colCount = Math.max(1, parts.length - 2)
  const newRow = "\n| " + Array(colCount).fill(" ").join(" | ") + " |"
  const insertPos = line.to
  return {
    changes: { from: insertPos, to: insertPos, insert: newRow },
    selection: { anchor: insertPos + 3 },
    scrollIntoView: true,
  }
}

/**
 * Navigate to previous cell in a markdown table on Shift-Tab.
 */
export function tablePrevCellSpec(state: EditorState): TransactionSpec | null {
  const { from } = state.selection.main
  const line = state.doc.lineAt(from)
  if (!line.text.includes("|")) return null

  const parts = line.text.split("|")
  if (parts.length < 3) return null

  const colIndex = from - line.from
  let cumLen = 0
  let currentPipeIndex = 0
  for (let i = 0; i < parts.length; i++) {
    cumLen += parts[i].length + (i > 0 ? 1 : 0)
    if (colIndex <= cumLen) {
      currentPipeIndex = i
      break
    }
  }

  if (currentPipeIndex > 1) {
    const prevPipeIdx = currentPipeIndex - 1
    const cellStart = parts.slice(0, prevPipeIdx).join("|").length + 1
    const cellText = parts[prevPipeIdx]
    const contentOffset = cellText.startsWith(" ") ? 1 : 0
    return {
      selection: { anchor: line.from + cellStart + contentOffset },
      scrollIntoView: true,
    }
  }

  // First cell in row -> move to last cell of previous row
  const prevLineNum = line.number - 1
  if (prevLineNum >= 1) {
    let targetPrevNum = prevLineNum
    let targetPrevLine = state.doc.line(targetPrevNum)
    if (targetPrevLine.text.includes("|") && /\|[\s:-]+-+\s*\|/.test(targetPrevLine.text)) {
      if (targetPrevNum - 1 >= 1) {
        targetPrevNum--
        targetPrevLine = state.doc.line(targetPrevNum)
      }
    }
    if (targetPrevLine.text.includes("|")) {
      const prevParts = targetPrevLine.text.split("|")
      if (prevParts.length >= 3) {
        const lastCellIdx = prevParts.length - 2
        const cellStart = prevParts.slice(0, lastCellIdx).join("|").length + 1
        const cellText = prevParts[lastCellIdx]
        const contentOffset = cellText.startsWith(" ") ? 1 : 0
        return {
          selection: { anchor: targetPrevLine.from + cellStart + contentOffset },
          scrollIntoView: true,
        }
      }
    }
  }

  return null
}

/**
 * Insert a clean line/paragraph break below the current block (Mod-Enter).
 * Allows instantly escaping any block without breaking delimiters.
 */
export function insertBlockBreakSpec(state: EditorState): TransactionSpec | null {
  const { from } = state.selection.main
  const block = findEnclosingBlock(state, from)
  if (block) {
    const insertPos = block.to
    return {
      changes: { from: insertPos, to: insertPos, insert: "\n\n" },
      selection: { anchor: insertPos + 2 },
      scrollIntoView: true,
    }
  }
  const line = state.doc.lineAt(from)
  return {
    changes: { from: line.to, to: line.to, insert: "\n" },
    selection: { anchor: line.to + 1 },
    scrollIntoView: true,
  }
}
