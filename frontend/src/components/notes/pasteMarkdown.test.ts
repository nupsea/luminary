import { describe, expect, it } from "vitest"
import React from "react"
import ReactDOMServer from "react-dom/server"
import type { Element, Root } from "hast"
import { fromHtml } from "hast-util-from-html"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { hastToMarkdown, tsvToMarkdown } from "./pasteMarkdown"

// The same shape htmlToMarkdown builds from DOMParser: a root holding <body>.
function paste(html: string) {
  const doc = fromHtml(html)
  const htmlEl = doc.children.find((c): c is Element => c.type === "element" && c.tagName === "html")!
  const body = htmlEl.children.find((c): c is Element => c.type === "element" && c.tagName === "body")!
  return hastToMarkdown({ type: "root", children: [body] } satisfies Root)
}

describe("hastToMarkdown", () => {
  it("keeps a web page table as a GFM table", () => {
    const html =
      `<meta charset="utf-8"><table><thead><tr><th>Table</th><th>Grain (one row is…)</th><th>Key columns</th></tr></thead>` +
      `<tbody><tr><td>vehicle_positions</td><td>one vehicle in one poll</td><td>vehicle_id, trip_id</td></tr>` +
      `<tr><td>routes</td><td>one route</td><td>route_id | route_type</td></tr></tbody></table>`
    expect(paste(html)).toEqual({
      markdown: [
        "| Table             | Grain (one row is…)     | Key columns            |",
        "| ----------------- | ----------------------- | ---------------------- |",
        "| vehicle_positions | one vehicle in one poll | vehicle_id, trip_id    |",
        "| routes            | one route               | route_id \\| route_type |",
      ].join("\n"),
      block: true,
    })
  })

  it("uses the first row as the header when a table has no <th>", () => {
    const html = `<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>`
    expect(paste(html)?.markdown).toBe("| a | b |\n| - | - |\n| 1 | 2 |")
  })

  it("keeps headings, lists, emphasis, links and code blocks", () => {
    const html =
      `<h2>Setup</h2><p>Run <code>make dev</code> and read <a href="https://example.org/docs">the docs</a>, <strong>first</strong>.</p>` +
      `<ul><li>one<ul><li>nested</li></ul></li><li>two</li></ul><ol><li>step</li></ol>` +
      `<pre><code class="language-sql">SELECT *\nFROM t;</code></pre><blockquote><p>quoted</p></blockquote>`
    expect(paste(html)?.markdown).toBe(
      [
        "## Setup",
        "",
        "Run `make dev` and read [the docs](https://example.org/docs), **first**.",
        "",
        "- one",
        "  - nested",
        "- two",
        "",
        "1. step",
        "",
        "```sql",
        "SELECT *",
        "FROM t;",
        "```",
        "",
        "> quoted",
      ].join("\n"),
    )
  })

  it("pastes a single formatted paragraph inline", () => {
    expect(paste(`<span>see <b>this</b> point</span>`)).toEqual({ markdown: "see **this** point", block: false })
  })

  it("leaves markup without formatting to the plain-text paste", () => {
    // VS Code copies code as styled divs and spans; its plain text is exact, a conversion is not.
    const html = `<div style="color: #d4d4d4;"><div><span style="color: #569cd6;">def</span><span> add(a, b):</span></div><div><span>    return a + b</span></div></div>`
    expect(paste(html)).toBeNull()
  })

  it("does not bold a whole Google Docs selection", () => {
    const html = `<b style="font-weight:normal;" id="docs-internal-guid-1234"><p><span>Plain line</span></p><ul><li><span>item</span></li></ul></b>`
    expect(paste(html)?.markdown).toBe("Plain line\n\n- item")
  })

  it("keeps a bold run that is not the Google Docs wrapper", () => {
    expect(paste(`<p><b>bold</b> text</p>`)?.markdown).toBe("**bold** text")
  })

  it("turns rendered KaTeX back into its TeX source", () => {
    const katex = (tex: string) =>
      `<span class="katex"><span class="katex-mathml"><math><semantics><mrow><mi>x</mi></mrow>` +
      `<annotation encoding="application/x-tex">${tex}</annotation></semantics></math></span>` +
      `<span class="katex-html" aria-hidden="true"><span class="mord mathnormal">x</span></span></span>`
    expect(paste(`<p>Energy ${katex("E = mc^2")} holds.</p>`)?.markdown).toBe("Energy $E = mc^2$ holds.")
    expect(paste(`<span class="katex-display">${katex("\\sum_i x_i")}</span>`)?.markdown).toBe("$$\n\\sum_i x_i\n$$")
  })

  it("keeps web images and drops ones that cannot resolve later", () => {
    const html = `<p><img src="https://example.org/a.png" alt="chart"><img src="blob:https://x/1" alt="gone"></p>`
    expect(paste(html)?.markdown).toBe("![chart](https://example.org/a.png)")
    expect(paste(`<p><img src="file:///tmp/a.png" alt="gone"></p>`)).toBeNull()
  })
})

describe("copying what Luminary rendered", () => {
  // Every format the notes renderer draws, in the source form a paste must restore.
  const note = [
    "# Heading one",
    "",
    "## Heading two",
    "",
    "Plain paragraph with **bold**, *italic*, ~~strike~~, `inline code` and a [link](https://example.org).",
    "",
    "- bullet one",
    "- bullet two",
    "  - nested bullet",
    "",
    "1. first",
    "2. second",
    "",
    "- [ ] open task",
    "- [x] done task",
    "",
    "> A quote",
    "",
    "---",
    "",
    "| Name | Value |",
    "| ---- | ----- |",
    "| a    | 1     |",
    "",
    "Inline math $E = mc^2$ here.",
    "",
    "$$",
    "\\int_0^1 x^2 \\, dx",
    "$$",
    "",
    "```js",
    "function add(a, b) {",
    "  return a + b",
    "}",
    "```",
    "",
    "```mermaid",
    "graph TD",
    "  A --> B",
    "```",
    "",
    "![Chart|small](__LUMINARY_IMG__/notes/chart.png)",
    "",
    "![Diagram](__LUMINARY_IMG__/notes/drawing.svg)",
    "<!-- luminary:excalidraw=__LUMINARY_IMG__/notes/drawing.excalidraw.json -->",
    "",
    "Link to [[00000000-0000-0000-0000-000000000001|Other note]].",
  ].join("\n")

  // Chrome drops KaTeX's TeX annotation from a copy; the round trip must not need it.
  const withoutAnnotations = (html: string) => html.replace(/<annotation\b[\s\S]*?<\/annotation>/g, "")

  it("pastes back the markdown it was rendered from", () => {
    const html = ReactDOMServer.renderToStaticMarkup(React.createElement(MarkdownRenderer, { reading: true, children: note }))
    expect(html).toContain("<annotation")
    expect(paste(withoutAnnotations(html))?.markdown).toBe(note)
  })

  it("keeps an inline formula or note link on its line", () => {
    const html =
      `<span>Energy </span><span class="katex" data-luminary-md="$E = mc^2$">E=mc2</span><span> and </span>` +
      `<span data-luminary-md="[[00000000-0000-0000-0000-000000000001|Other]]">Other</span>`
    expect(paste(html)).toEqual({
      markdown: "Energy $E = mc^2$ and [[00000000-0000-0000-0000-000000000001|Other]]",
      block: false,
    })
  })

  it("ignores a copy-source attribute that is not one of Luminary's shapes", () => {
    const html = `<p>Shown <b>text</b><span data-luminary-md="# hidden heading">!</span></p>`
    expect(paste(html)?.markdown).toBe("Shown **text**!")
  })
})

describe("web sources", () => {
  it("keeps GitHub task lists and its code block language", () => {
    const html =
      `<ul class="contains-task-list"><li class="task-list-item"><input type="checkbox" disabled> open</li>` +
      `<li class="task-list-item"><input type="checkbox" checked disabled> done</li></ul>` +
      `<div class="highlight highlight-source-rust"><pre><span class="pl-k">fn</span> f() {\n    <span class="pl-k">return</span>;\n}</pre></div>`
    expect(paste(html)?.markdown).toBe("- [ ] open\n- [x] done\n\n```rust\nfn f() {\n    return;\n}\n```")
  })

  it("reads a Wikipedia formula from its fallback image when Chrome drops the MathML", () => {
    const html =
      `<p>Mass–energy: <span class="mwe-math-element"><img class="mwe-math-fallback-image-inline" ` +
      `src="https://wikimedia.org/api/rest_v1/media/math/render/svg/abc" alt="{\\displaystyle E=mc^{2}}"></span> holds.</p>`
    expect(paste(html)?.markdown).toBe("Mass–energy: $E=mc^{2}$ holds.")
  })

  it("keeps a formula's glyphs once when no TeX survives the copy", () => {
    const html =
      `<p>Inline <span class="katex"><span class="katex-mathml"><math><semantics><mrow><mi>E</mi><mo>=</mo><mi>m</mi></mrow></semantics></math></span>` +
      `<span class="katex-html" aria-hidden="true"><span class="mord">E</span><span class="mrel">=</span><span class="mord">m</span></span></span> here.</p>`
    expect(paste(html)?.markdown).toBe("Inline E=m here.")
  })

  it("keeps Google Docs bold and italic runs and tight lists", () => {
    const html =
      `<b style="font-weight:normal;" id="docs-internal-guid-1"><p><span style="font-weight:700;">Bold run</span>` +
      `<span style="font-weight:400;"> then plain</span><span style="font-style:italic;"> italic</span></p>` +
      `<ul><li><p><span>one</span></p></li><li><p><span>two</span></p></li></ul></b>`
    expect(paste(html)?.markdown).toBe("**Bold run** then plain *italic*\n\n- one\n- two")
  })
})

describe("tsvToMarkdown", () => {
  it("turns spreadsheet rows into a table", () => {
    expect(tsvToMarkdown("Table\tGrain\nstops\tone stop\r\nroutes\tone route\n")).toEqual({
      markdown: "| Table  | Grain     |\n| ------ | --------- |\n| stops  | one stop  |\n| routes | one route |",
      block: true,
    })
  })

  it("escapes markdown in cells, since spreadsheet text is literal", () => {
    expect(tsvToMarkdown("a|b\t*c*\n1\t2")?.markdown).toBe("| a\\|b | \\*c\\* |\n| ---- | ----- |\n| 1    | 2     |")
  })

  it.each([
    ["one line", "a\tb"],
    ["ragged rows", "a\tb\nc\td\te"],
    ["indented code", "\tfoo()\n\tbar()"],
    ["no tabs", "plain\ntext"],
  ])("leaves %s alone", (_, text) => {
    expect(tsvToMarkdown(text)).toBeNull()
  })
})
