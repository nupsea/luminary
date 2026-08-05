import { describe, expect, it } from "vitest"
import type { Root } from "hast"
import { SOURCE_LINE_ATTR, lineOffsetAt, rehypeSourceLine } from "./rehypeSourceLine"

function element(tagName: string, line: number | null) {
  return {
    type: "element" as const,
    tagName,
    properties: {},
    children: [],
    ...(line == null ? {} : { position: { start: { line, column: 1, offset: 0 }, end: { line, column: 1, offset: 0 } } }),
  }
}

function stamp(tree: Root, offset = 0) {
  rehypeSourceLine(offset)(tree)
  return tree.children.map((n) =>
    n.type === "element" ? n.properties?.[SOURCE_LINE_ATTR] : undefined,
  )
}

describe("rehypeSourceLine", () => {
  it("stamps top-level blocks with their source line", () => {
    const tree: Root = {
      type: "root",
      children: [element("h1", 1), element("p", 3), element("ul", 5)],
    }
    expect(stamp(tree)).toEqual(["1", "3", "5"])
  })

  it("skips nodes whose position was lost", () => {
    const tree: Root = {
      type: "root",
      children: [element("h1", 1), element("div", null), element("p", 9)],
    }
    expect(stamp(tree)).toEqual(["1", undefined, "9"])
  })

  it("applies the chunk offset so split notes keep one line axis", () => {
    const tree: Root = { type: "root", children: [element("p", 1), element("p", 4)] }
    expect(stamp(tree, 20)).toEqual(["21", "24"])
  })

  it("leaves existing properties intact", () => {
    const tree: Root = { type: "root", children: [element("p", 2)] }
    if (tree.children[0].type === "element") {
      tree.children[0].properties = { className: ["keep"] }
    }
    rehypeSourceLine()(tree)
    const node = tree.children[0]
    expect(node.type === "element" && node.properties).toEqual({
      className: ["keep"],
      [SOURCE_LINE_ATTR]: "2",
    })
  })
})

describe("lineOffsetAt", () => {
  const source = "one\ntwo\nthree\nfour"

  it("counts the lines before a character index", () => {
    expect(lineOffsetAt(source, 0)).toBe(0)
    expect(lineOffsetAt(source, 4)).toBe(1)
    expect(lineOffsetAt(source, 8)).toBe(2)
  })

  it("clamps past the end of the source", () => {
    expect(lineOffsetAt(source, 9999)).toBe(3)
  })

  it("makes a chunk's stamped lines continue the parent document", () => {
    // The chunk after a diagram starts at index 8, i.e. document line 3. Its own
    // first block reports line 1, so the offset must lift it back to 3.
    expect(lineOffsetAt(source, 8) + 1).toBe(3)
  })
})
