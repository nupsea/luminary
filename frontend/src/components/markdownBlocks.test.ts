import { describe, expect, it } from "vitest"
import { buildExcalidrawDiagramMarkdown } from "@/lib/noteDiagrams"
import { splitMarkdownIntoBlocks } from "./markdownBlocks"

describe("splitMarkdownIntoBlocks", () => {
  it("returns empty array for empty content", () => {
    expect(splitMarkdownIntoBlocks("")).toEqual([])
  })

  it("splits paragraphs separated by blank lines into chunks with stable line offsets", () => {
    const md = `First paragraph.

Second paragraph with an image:
![Test](https://example.com/test.png)

Third paragraph.`

    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks.length).toBe(3)
    expect(blocks[0].source).toBe("First paragraph.")
    expect(blocks[0].lineOffset).toBe(0)
    expect(blocks[1].source).toContain("Second paragraph")
    expect(blocks[1].lineOffset).toBe(2)
    expect(blocks[2].source).toBe("Third paragraph.")
    expect(blocks[2].lineOffset).toBe(5)
  })

  it("keeps code fences intact even if they contain blank lines", () => {
    const md = `# Heading

\`\`\`ts
const a = 1

const b = 2
\`\`\`

After code block.`

    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks.length).toBe(3)
    expect(blocks[0].source).toBe("# Heading")
    expect(blocks[1].source).toContain("const b = 2")
    expect(blocks[2].source).toBe("After code block.")
  })

  it("isolates diagrams with their stable scenePath key", () => {
    const diagSnippet = buildExcalidrawDiagramMarkdown(
      "__LUMINARY_IMG__/notes/diag1.svg",
      "__LUMINARY_IMG__/notes/diag1.excalidraw.json",
    )
    const md = `Before diagram.

${diagSnippet}

After diagram.`

    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks.some((b) => b.isDiagram)).toBe(true)
    const diagBlock = blocks.find((b) => b.isDiagram)
    expect(diagBlock?.key).toContain("diag1.excalidraw.json")
  })
})
