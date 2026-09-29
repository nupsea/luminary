import type { EditorState, TransactionSpec } from "@codemirror/state"
import { isImageOnlyParagraph } from "./liveMarkdownRules"

// Mirrors the old insertAtTextareaCursor semantics: the block lands in its own
// paragraph with blank lines around it (mermaid/excalidraw insertions).
export function insertBlockSpec(state: EditorState, markdown: string): TransactionSpec {
  const { from, to } = state.selection.main
  const before = state.sliceDoc(0, from)
  const after = state.sliceDoc(to)
  let prefix = ""
  if (from > 0) {
    if (before.endsWith("\n\n")) prefix = ""
    else if (before.endsWith("\n")) prefix = "\n"
    else prefix = "\n\n"
  }
  let suffix = ""
  if (after.startsWith("\n\n")) suffix = ""
  else if (after.startsWith("\n")) suffix = "\n"
  else suffix = "\n\n"
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

/**
 * Smart Backspace: prevents destructive concatenation of prose onto atomic blocks
 * (images, diagrams, math, tables, code blocks) and handles atomic deletion.
 */
export function smartBackspaceSpec(state: EditorState): TransactionSpec | null {
  const { from, to, empty } = state.selection.main

  // 1. Non-empty selection covering an atomic block line (like an image/diagram)
  if (!empty) {
    const lineFrom = state.doc.lineAt(from)
    const lineTo = state.doc.lineAt(to)
    if (
      lineFrom.number === lineTo.number &&
      from <= lineFrom.from &&
      to >= lineTo.to &&
      isImageOnlyParagraph(lineFrom.text)
    ) {
      let deleteFrom = lineFrom.from
      let deleteTo = lineTo.to
      if (lineTo.number < state.doc.lines) {
        deleteTo = state.doc.line(lineTo.number + 1).from
      } else if (lineFrom.number > 1) {
        deleteFrom = state.doc.line(lineFrom.number - 1).to
      }
      return {
        changes: { from: deleteFrom, to: deleteTo, insert: "" },
        selection: { anchor: deleteFrom },
        scrollIntoView: true,
      }
    }
    return null
  }

  const currentLine = state.doc.lineAt(from)

  // 2. Cursor at line.to of an image-only paragraph:
  // Instead of deleting the closing ')' and corrupting markdown, select the block.
  if (from === currentLine.to && isImageOnlyParagraph(currentLine.text)) {
    return {
      selection: { anchor: currentLine.from, head: currentLine.to },
      scrollIntoView: true,
    }
  }

  // 3. Cursor at line.from (column 0)
  if (from === currentLine.from && currentLine.number > 1) {
    const prevLine = state.doc.line(currentLine.number - 1)
    const prevText = prevLine.text.trim()

    // If current line is blank, remove this blank line cleanly
    if (currentLine.text.trim() === "") {
      return {
        changes: { from: prevLine.to, to: currentLine.to, insert: "" },
        selection: { anchor: prevLine.to },
        scrollIntoView: true,
      }
    }

    const isBlockAbove =
      /^!\[.*\]\(.*\)/.test(prevText) ||
      /^<!--\s*luminary:excalidraw=.*-->$/.test(prevText) ||
      prevText.startsWith("$$") ||
      prevText.startsWith("```") ||
      prevText.startsWith("~~~") ||
      prevText.includes("|")

    if (isBlockAbove) {
      const block = findEnclosingBlock(state, prevLine.from)
      const selFrom = block ? block.from : prevLine.from
      const selTo = block ? block.to : prevLine.to
      return {
        selection: { anchor: selFrom, head: selTo },
        scrollIntoView: true,
      }
    }
  }

  return null
}

/**
 * Smart Delete: prevents destructive concatenation when cursor is at the end of a line above an atomic block,
 * or cleanly deletes a selected atomic image block.
 */
export function smartDeleteSpec(state: EditorState): TransactionSpec | null {
  const { from, to, empty } = state.selection.main

  if (!empty) {
    const lineFrom = state.doc.lineAt(from)
    const lineTo = state.doc.lineAt(to)
    if (
      lineFrom.number === lineTo.number &&
      from <= lineFrom.from &&
      to >= lineTo.to &&
      isImageOnlyParagraph(lineFrom.text)
    ) {
      let deleteFrom = lineFrom.from
      let deleteTo = lineTo.to
      if (lineTo.number < state.doc.lines) {
        deleteTo = state.doc.line(lineTo.number + 1).from
      } else if (lineFrom.number > 1) {
        deleteFrom = state.doc.line(lineFrom.number - 1).to
      }
      return {
        changes: { from: deleteFrom, to: deleteTo, insert: "" },
        selection: { anchor: deleteFrom },
        scrollIntoView: true,
      }
    }
    return null
  }

  const currentLine = state.doc.lineAt(from)
  if (from === currentLine.to && currentLine.number < state.doc.lines) {
    const nextLine = state.doc.line(currentLine.number + 1)
    const nextText = nextLine.text.trim()

    if (currentLine.text.trim() === "") {
      return {
        changes: { from: currentLine.from, to: nextLine.from, insert: "" },
        selection: { anchor: currentLine.from },
        scrollIntoView: true,
      }
    }

    const isBlockBelow =
      /^!\[.*\]\(.*\)/.test(nextText) ||
      /^<!--\s*luminary:excalidraw=.*-->$/.test(nextText) ||
      nextText.startsWith("$$") ||
      nextText.startsWith("```") ||
      nextText.startsWith("~~~") ||
      nextText.includes("|")

    if (isBlockBelow) {
      const block = findEnclosingBlock(state, nextLine.from)
      const selFrom = block ? block.from : nextLine.from
      const selTo = block ? block.to : nextLine.to
      return {
        selection: { anchor: selFrom, head: selTo },
        scrollIntoView: true,
      }
    }
  }

  return null
}

const INDENT_SPACES = "  "

/**
 * Smart Tab handler for Markdown:
 * - Inside a table: delegates to tableNextCellSpec
 * - On a list item: indents the list item by 2 spaces
 * - Multiline selection: indents all selected lines by 2 spaces
 * - Mid-text or line start: indents or inserts 2 spaces
 */
export function indentMarkdownSpec(state: EditorState): TransactionSpec | null {
  const tableSpec = tableNextCellSpec(state)
  if (tableSpec) return tableSpec

  const { from, to, empty } = state.selection.main
  const startLine = state.doc.lineAt(from)
  const endLine = state.doc.lineAt(to)

  if (startLine.number !== endLine.number) {
    const changes: { from: number; to: number; insert: string }[] = []
    let addedChars = 0
    for (let ln = startLine.number; ln <= endLine.number; ln++) {
      const line = state.doc.line(ln)
      changes.push({ from: line.from, to: line.from, insert: INDENT_SPACES })
      addedChars += INDENT_SPACES.length
    }
    return {
      changes,
      selection: {
        anchor: from + INDENT_SPACES.length,
        head: to + addedChars,
      },
      scrollIntoView: true,
    }
  }

  const line = startLine
  const listMatch = line.text.match(/^(\s*)([-*+]\s+\[[ xX]\]|[-*+]|\d+[.)])(\s+)/)
  if (listMatch) {
    return {
      changes: { from: line.from, to: line.from, insert: INDENT_SPACES },
      selection: { anchor: from + INDENT_SPACES.length },
      scrollIntoView: true,
    }
  }

  if (!empty) {
    return {
      changes: { from: line.from, to: line.from, insert: INDENT_SPACES },
      selection: { anchor: from + INDENT_SPACES.length, head: to + INDENT_SPACES.length },
      scrollIntoView: true,
    }
  }

  const nonSpace = line.text.search(/\S/)
  if (nonSpace === -1 || from <= line.from + nonSpace) {
    return {
      changes: { from: line.from, to: line.from, insert: INDENT_SPACES },
      selection: { anchor: from + INDENT_SPACES.length },
      scrollIntoView: true,
    }
  }

  return {
    changes: { from, to: from, insert: INDENT_SPACES },
    selection: { anchor: from + INDENT_SPACES.length },
    scrollIntoView: true,
  }
}

/**
 * Smart Shift-Tab handler for Markdown:
 * - Inside a table: delegates to tablePrevCellSpec
 * - On a list item or line: dedents by removing up to 2 leading spaces or 1 tab
 * - Multiline selection: dedents all selected lines
 */
export function dedentMarkdownSpec(state: EditorState): TransactionSpec | null {
  const tableSpec = tablePrevCellSpec(state)
  if (tableSpec) return tableSpec

  const { from, to } = state.selection.main
  const startLine = state.doc.lineAt(from)
  const endLine = state.doc.lineAt(to)

  if (startLine.number !== endLine.number) {
    const changes: { from: number; to: number; insert: string }[] = []
    let totalRemoved = 0
    let firstLineRemoved = 0
    for (let ln = startLine.number; ln <= endLine.number; ln++) {
      const line = state.doc.line(ln)
      const leadingMatch = line.text.match(/^ {1,2}|\t/)
      if (leadingMatch) {
        const removeCount = leadingMatch[0].length
        changes.push({ from: line.from, to: line.from + removeCount, insert: "" })
        totalRemoved += removeCount
        if (ln === startLine.number) firstLineRemoved = removeCount
      }
    }
    if (changes.length === 0) return null
    return {
      changes,
      selection: {
        anchor: Math.max(startLine.from, from - firstLineRemoved),
        head: Math.max(startLine.from, to - totalRemoved),
      },
      scrollIntoView: true,
    }
  }

  const line = startLine
  const leadingMatch = line.text.match(/^ {1,2}|\t/)
  if (!leadingMatch) return null

  const removeCount = leadingMatch[0].length
  const newAnchor = Math.max(line.from, from - removeCount)
  const newHead = Math.max(line.from, to - removeCount)
  return {
    changes: { from: line.from, to: line.from + removeCount, insert: "" },
    selection: { anchor: newAnchor, head: newHead },
    scrollIntoView: true,
  }
}

/**
 * Smart Enter for Markdown lists and blockquotes:
 * - Continues bullet lists (- ), numbered lists (1. -> 2. ), and task lists (- [ ] )
 * - Pressing Enter on an empty list item dedents or clears the marker, cleanly exiting the list
 * - Continues or exits blockquotes (> )
 */
export function smartEnterSpec(state: EditorState): TransactionSpec | null {
  const { from, empty } = state.selection.main
  if (!empty) return null

  const line = state.doc.lineAt(from)
  const lineText = line.text

  // 1. Task list item (e.g. `- [ ] `, `* [x] `)
  const taskMatch = lineText.match(/^(\s*)([-*+])\s+\[[ xX]\](\s*)(.*)$/)
  if (taskMatch) {
    const indent = taskMatch[1]
    const bullet = taskMatch[2]
    const content = taskMatch[4]

    if (!content.trim()) {
      if (indent.length >= 2) {
        const newIndent = indent.slice(2)
        const newText = `${newIndent}${bullet} [ ] `
        return {
          changes: { from: line.from, to: line.to, insert: newText },
          selection: { anchor: line.from + newText.length },
          scrollIntoView: true,
        }
      }
      return {
        changes: { from: line.from, to: line.to, insert: "" },
        selection: { anchor: line.from },
        scrollIntoView: true,
      }
    }

    const insertText = `\n${indent}${bullet} [ ] `
    return {
      changes: { from, to: from, insert: insertText },
      selection: { anchor: from + insertText.length },
      scrollIntoView: true,
    }
  }

  // 2. Ordered list item (e.g. `1. `, `1) `)
  const orderedMatch = lineText.match(/^(\s*)(\d+)([.)])(\s*)(.*)$/)
  if (orderedMatch) {
    const indent = orderedMatch[1]
    const num = parseInt(orderedMatch[2], 10)
    const delimiter = orderedMatch[3]
    const content = orderedMatch[5]

    if (!content.trim()) {
      if (indent.length >= 2) {
        const newIndent = indent.slice(2)
        const newText = `${newIndent}${num}${delimiter} `
        return {
          changes: { from: line.from, to: line.to, insert: newText },
          selection: { anchor: line.from + newText.length },
          scrollIntoView: true,
        }
      }
      return {
        changes: { from: line.from, to: line.to, insert: "" },
        selection: { anchor: line.from },
        scrollIntoView: true,
      }
    }

    const insertText = `\n${indent}${num + 1}${delimiter} `
    return {
      changes: { from, to: from, insert: insertText },
      selection: { anchor: from + insertText.length },
      scrollIntoView: true,
    }
  }

  // 3. Bullet list item (e.g. `- `, `* `, `+ `)
  const bulletMatch = lineText.match(/^(\s*)([-*+])(\s+)(.*)$/)
  if (bulletMatch) {
    const indent = bulletMatch[1]
    const bullet = bulletMatch[2]
    const content = bulletMatch[4]

    if (!content.trim()) {
      if (indent.length >= 2) {
        const newIndent = indent.slice(2)
        const newText = `${newIndent}${bullet} `
        return {
          changes: { from: line.from, to: line.to, insert: newText },
          selection: { anchor: line.from + newText.length },
          scrollIntoView: true,
        }
      }
      return {
        changes: { from: line.from, to: line.to, insert: "" },
        selection: { anchor: line.from },
        scrollIntoView: true,
      }
    }

    const insertText = `\n${indent}${bullet} `
    return {
      changes: { from, to: from, insert: insertText },
      selection: { anchor: from + insertText.length },
      scrollIntoView: true,
    }
  }

  // 4. Blockquote item (e.g. `> `)
  const quoteMatch = lineText.match(/^(\s*>\s*)(.*)$/)
  if (quoteMatch) {
    const prefix = quoteMatch[1]
    const content = quoteMatch[2]
    if (!content.trim()) {
      return {
        changes: { from: line.from, to: line.to, insert: "" },
        selection: { anchor: line.from },
        scrollIntoView: true,
      }
    }
    const insertText = `\n${prefix}`
    return {
      changes: { from, to: from, insert: insertText },
      selection: { anchor: from + insertText.length },
      scrollIntoView: true,
    }
  }

  return null
}

/**
 * Toggle link markdown around selection: [text](url).
 */
export function toggleLinkSpec(state: EditorState): TransactionSpec {
  const { from, to, empty } = state.selection.main
  const selected = state.sliceDoc(from, to)

  const linkMatch = selected.match(/^\[(.*)\]\((.*)\)$/)
  if (linkMatch) {
    const innerText = linkMatch[1] || linkMatch[2]
    return {
      changes: { from, to, insert: innerText },
      selection: { anchor: from, head: from + innerText.length },
      scrollIntoView: true,
    }
  }

  if (empty) {
    const insert = "[](url)"
    return {
      changes: { from, to: from, insert },
      selection: { anchor: from + 1 },
      scrollIntoView: true,
    }
  }

  if (/^https?:\/\//.test(selected.trim())) {
    const insert = `[Link](${selected.trim()})`
    return {
      changes: { from, to, insert },
      selection: { anchor: from + 1, head: from + 5 },
      scrollIntoView: true,
    }
  }

  const insert = `[${selected}](url)`
  const urlStart = from + selected.length + 3
  return {
    changes: { from, to, insert },
    selection: { anchor: urlStart, head: urlStart + 3 },
    scrollIntoView: true,
  }
}
