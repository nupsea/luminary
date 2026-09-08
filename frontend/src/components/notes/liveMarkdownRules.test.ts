import { describe, expect, it } from "vitest"

import {
  clickedSourceLine,
  hidesBlock,
  hidesMark,
  isImageOnlyParagraph,
  lineIsBeingEdited,
  mathBlockRanges,
  rendersAsBlock,
} from "./liveMarkdownRules"

describe("hidesMark", () => {
  it("hides the markers that sit beside their text", () => {
    expect(hidesMark("HeaderMark")).toBe(true)
    expect(hidesMark("QuoteMark")).toBe(true)
    expect(hidesMark("EmphasisMark")).toBe(true)
    expect(hidesMark("StrikethroughMark")).toBe(true)
  })

  it("hides inline backticks but never a fence", () => {
    expect(hidesMark("CodeMark", "InlineCode")).toBe(true)
    expect(hidesMark("CodeMark", "FencedCode")).toBe(false)
  })

  it("hides a link's brackets and target, leaving its text", () => {
    expect(hidesMark("LinkMark", "Link")).toBe(true)
    expect(hidesMark("URL", "Link")).toBe(true)
  })

  it("leaves an image's markup alone: nothing renders it mid-paragraph", () => {
    expect(hidesMark("LinkMark", "Image")).toBe(false)
    expect(hidesMark("URL", "Image")).toBe(false)
  })

  it("leaves structure the reader needs alone", () => {
    expect(hidesMark("ListMark")).toBe(false)
    expect(hidesMark("Paragraph")).toBe(false)
  })
})

describe("lineIsBeingEdited", () => {
  const line = { from: 10, to: 20 }

  it("counts a cursor anywhere on the line, including both ends", () => {
    for (const at of [10, 15, 20]) {
      expect(lineIsBeingEdited([{ from: at, to: at }], line.from, line.to)).toBe(true)
    }
  })

  it("does not count a cursor on another line", () => {
    expect(lineIsBeingEdited([{ from: 9, to: 9 }], line.from, line.to)).toBe(false)
    expect(lineIsBeingEdited([{ from: 21, to: 21 }], line.from, line.to)).toBe(false)
  })

  it("counts a selection that crosses the line", () => {
    expect(lineIsBeingEdited([{ from: 0, to: 40 }], line.from, line.to)).toBe(true)
  })

  it("is false with no selection at all", () => {
    expect(lineIsBeingEdited([], line.from, line.to)).toBe(false)
  })
})

describe("rendersAsBlock", () => {
  it("names the blocks the renderer draws", () => {
    expect(rendersAsBlock("Table")).toBe(true)
    // Code is styled in place: a rendered block cannot be typed into where it
    // was clicked, and the caret landed in front of the fence.
    expect(rendersAsBlock("FencedCode")).toBe(false)
    expect(rendersAsBlock("Paragraph")).toBe(false)
    expect(rendersAsBlock("HTMLBlock")).toBe(false)
  })
})

describe("isImageOnlyParagraph", () => {
  it("is true for a paragraph holding one image and nothing else", () => {
    expect(isImageOnlyParagraph("![Diagram|large](__LUMINARY_IMG__/notes/a.svg)")).toBe(true)
    expect(isImageOnlyParagraph("  ![](x.png)  ")).toBe(true)
  })

  it("is false when the image shares the paragraph with prose", () => {
    expect(isImageOnlyParagraph("see ![](x.png)")).toBe(false)
    expect(isImageOnlyParagraph("![](x.png) and more")).toBe(false)
    expect(isImageOnlyParagraph("a plain paragraph")).toBe(false)
  })
})

describe("mathBlockRanges", () => {
  it("finds a closed display block, opening line through closing line", () => {
    const text = "before\n$$\nx = y + z\n$$\nafter"
    expect(mathBlockRanges(text)).toEqual([{ from: 7, to: 22 }])
    expect(text.slice(7, 22)).toBe("$$\nx = y + z\n$$")
  })

  it("ignores an unclosed block", () => {
    expect(mathBlockRanges("$$\nx = 1\n")).toEqual([])
  })

  it("finds more than one", () => {
    expect(mathBlockRanges("$$\na\n$$\n$$\nb\n$$")).toHaveLength(2)
  })

  it("finds none where there is no math", () => {
    expect(mathBlockRanges("just prose\nwith $inline$ dollars")).toEqual([])
  })
})

describe("hidesBlock", () => {
  it("hides an HTML comment however the grammar spelled it", () => {
    expect(hidesBlock("HTMLBlock")).toBe(true)
    expect(hidesBlock("CommentBlock")).toBe(true)
    expect(hidesBlock("Comment")).toBe(true)
  })

  it("hides nothing else", () => {
    expect(hidesBlock("Paragraph")).toBe(false)
    expect(hidesBlock("Table")).toBe(false)
  })
})

describe("clickedSourceLine", () => {
  // | C1 | C2 |      <- row 0, source line 0
  // | -- | -- |      <-        source line 1
  // | 23 | 34 |      <- row 1, source line 2
  const tableLines = 3

  it("maps a header click to the header line", () => {
    expect(clickedSourceLine(0, tableLines)).toBe(0)
  })

  it("maps a body row past the delimiter line", () => {
    expect(clickedSourceLine(1, tableLines)).toBe(2)
  })

  it("never runs past the block", () => {
    expect(clickedSourceLine(9, tableLines)).toBe(2)
  })

  it("answers with the last line when the click was not on a row", () => {
    expect(clickedSourceLine(null, 3)).toBe(2)
    expect(clickedSourceLine(null, 1)).toBe(0)
  })
})
