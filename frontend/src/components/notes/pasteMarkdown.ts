import type { Element, ElementContent, Nodes as HastNodes, Root as HastRoot } from "hast"
import type { ListItem, Nodes as MdastNodes, Root as MdastRoot, Table } from "mdast"
import { fromDom } from "hast-util-from-dom"
import { defaultHandlers, toMdast, type Handle } from "hast-util-to-mdast"
import { gfmToMarkdown } from "mdast-util-gfm"
import { mathToMarkdown } from "mdast-util-math"
import { toMarkdown } from "mdast-util-to-markdown"
import { classes, isCopySource, texAnnotation } from "@/lib/copySource"

export interface PastedMarkdown {
  markdown: string
  /** False for a single line, which can land mid-line. */
  block: boolean
}

// A paste with none of these keeps its plain text, which is exact for code
// copied out of an editor as styled divs and spans.
const FORMATTING_TAGS = new Set([
  "a", "b", "strong", "i", "em", "code", "pre", "kbd", "del", "s", "strike",
  "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "hr", "img",
])

function element(tagName: string, children: ElementContent[], properties: Element["properties"] = {}): Element {
  return { type: "element", tagName, properties, children }
}

// Stands in for an element whose markdown source is known; emitted verbatim. The
// exact source rides in a property because the converter collapses whitespace in
// text; the text child only keeps the spaces around an inline span.
function sourceElement(markdown: string): Element {
  return element("span", [{ type: "text", value: markdown }], { luminarySource: markdown, luminaryRewritten: true })
}

function findElement(node: Element, test: (el: Element) => boolean): Element | null {
  for (const child of node.children) {
    if (child.type !== "element") continue
    if (test(child)) return child
    const found = findElement(child, test)
    if (found) return found
  }
  return null
}

function mathSource(tex: string | null | undefined, display: boolean): Element | null {
  const value = tex?.trim()
  if (!value) return null
  const markdown = display ? `$$\n${value}\n$$` : `$${value}$`
  return isCopySource(markdown) ? sourceElement(markdown) : null
}

function textOf(node: ElementContent): string {
  if (node.type === "text") return node.value
  return node.type === "element" ? node.children.map(textOf).join("") : ""
}

// A formula's TeX: KaTeX's annotation, MathML's alttext, or Wikipedia's fallback
// image alt (Chrome drops the hidden MathML from a copy).
function formula(node: Element): Element | null {
  const names = classes(node)
  if (names.includes("katex-display") || names.includes("katex")) {
    const math = mathSource(texAnnotation(node), names.includes("katex-display"))
    if (math) return math
    // No TeX survived the copy: keep the rendered glyphs once, not MathML and glyphs both.
    const html = findElement(node, (el) => classes(el).includes("katex-html"))
    const text = (html ? textOf(html) : "").replace(/[\s\u200b]+/g, " ").trim()
    return text ? element("span", [{ type: "text", value: text }], { luminaryRewritten: true }) : null
  }
  if (node.tagName === "math") {
    return mathSource(texAnnotation(node) ?? String(node.properties.alttext ?? ""), node.properties.display === "block")
  }
  if (names.includes("mwe-math-element")) {
    const fallback = findElement(node, (el) => el.tagName === "img")
    const alt = String(fallback?.properties.alt ?? "").replace(/^\{\\displaystyle\s*([\s\S]*)\}$/, "$1")
    const display = fallback ? classes(fallback).includes("mwe-math-fallback-image-display") : false
    return mathSource(texAnnotation(node) ?? alt, display)
  }
  return null
}

function isGoogleDocsWrapper(node: Element): boolean {
  return node.tagName === "b" && String(node.properties.id ?? "").startsWith("docs-internal-guid")
}

// Google Docs carries bold and italic as inline styles on spans. Markdown
// emphasis cannot open or close on a space, so edge spaces stay outside it.
function googleDocsSpan(node: Element): ElementContent[] {
  const style = String(node.properties.style ?? "")
  const italic = /font-style:\s*italic/.test(style)
  const bold = /font-weight:\s*(?:bold|[6-9]00)/.test(style)
  if (!italic && !bold) return [node]
  const [, lead, core, trail] = /^(\s*)([\s\S]*?)(\s*)$/.exec(textOf(node))!
  let out: Element = element("span", [{ type: "text", value: core }])
  if (italic) out = element("em", [out])
  if (bold) out = element("strong", [out])
  const space = (value: string): ElementContent[] => (value ? [{ type: "text", value }] : [])
  return [...space(lead), out, ...space(trail)]
}

/** Rewrites clipboard markup the converter would misread into markup it reads. */
function prepare(node: HastRoot | Element, inGoogleDoc = false): void {
  node.children = node.children.flatMap((child): ElementContent[] => {
    if (child.type !== "element") return [child as ElementContent]
    const source = child.properties.dataLuminaryMd
    if (isCopySource(source)) return [sourceElement(source)]
    const math = formula(child)
    if (math) return [math]

    const googleDoc = inGoogleDoc || isGoogleDocsWrapper(child)
    prepare(child, googleDoc)
    if (isGoogleDocsWrapper(child)) return child.children
    if (googleDoc && child.tagName === "span") return googleDocsSpan(child)

    // GitHub names a code block's language on the wrapper, not on <code>.
    const lang = classes(child).find((n) => n.startsWith("highlight-source-"))?.slice("highlight-source-".length)
    const pre = lang ? findElement(child, (el) => el.tagName === "pre") : null
    if (pre && !findElement(pre, (el) => el.tagName === "code")) {
      pre.children = [element("code", pre.children, { className: [`language-${lang}`] })]
    }
    return [child]
  })
}

function hasFormatting(node: HastNodes): boolean {
  if (node.type === "element" && (FORMATTING_TAGS.has(node.tagName) || node.properties.luminaryRewritten)) return true
  return "children" in node && (node.children as HastNodes[]).some(hasFormatting)
}

// hName tells the converter whether the source flows inline or stands as its own block.
const span: Handle = (state, node) => {
  if (!("luminarySource" in node.properties)) return defaultHandlers.span(state, node)
  const value = String(node.properties.luminarySource)
  return { type: "html", value, data: { hName: value.includes("\n") ? "div" : "span" } }
}

// A data: image is uploaded by the image paste path; anything else but a web URL cannot resolve later.
const img: Handle = (state, node) =>
  /^https?:\/\//i.test(String(node.properties.src ?? "")) ? defaultHandlers.img(state, node) : undefined

// Without <th> the converter emits an empty header row; spreadsheets and most
// web tables have none, and their first row is the header a reader expects.
const headerFromFirstRow: Handle = (state, node) => {
  const result = defaultHandlers.table(state, node) as Table
  const [head, ...rest] = result.children
  if (rest.length && head.children.every((cell) => cell.children.length === 0)) result.children = rest
  return result
}

// Google Docs and Word wrap every list item in a <p>, which would make each list loose.
const tightItem: Handle = (state, node) => {
  const item = defaultHandlers.li(state, node) as ListItem
  if (item.children.length === 1 && item.children[0].type === "paragraph") item.spread = false
  return item
}

function serialise(tree: MdastNodes): string {
  return toMarkdown(tree, {
    extensions: [gfmToMarkdown(), mathToMarkdown()],
    bullet: "-",
    fences: true,
    rule: "-",
  }).trim()
}

export function hastToMarkdown(tree: HastRoot): PastedMarkdown | null {
  prepare(tree)
  if (!hasFormatting(tree)) return null
  const handlers = { span, img, table: headerFromFirstRow, li: tightItem }
  const markdown = serialise(toMdast(tree, { handlers }) as MdastRoot)
  return markdown ? { markdown, block: markdown.includes("\n") } : null
}

function htmlToMarkdown(html: string): PastedMarkdown | null {
  // DOMParser documents are inert: no scripts run and no images load.
  const body = new DOMParser().parseFromString(html, "text/html").body
  return hastToMarkdown({ type: "root", children: [fromDom(body) as Element] })
}

/** Tab-separated rows (a spreadsheet copied as plain text) as a GFM table. */
export function tsvToMarkdown(text: string): PastedMarkdown | null {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "").split("\n")
  // A leading tab is indentation, and rows of differing width are not a grid.
  if (lines.length < 2 || lines.some((l) => l.startsWith("\t"))) return null
  const rows = lines.map((l) => l.split("\t"))
  const width = rows[0].length
  if (width < 2 || rows.some((r) => r.length !== width)) return null
  const table: Table = {
    type: "table",
    children: rows.map((cells) => ({
      type: "tableRow",
      children: cells.map((cell) => ({ type: "tableCell", children: [{ type: "text", value: cell.trim() }] })),
    })),
  }
  return { markdown: serialise({ type: "root", children: [table] }), block: true }
}

export function clipboardToMarkdown(data: DataTransfer | null): PastedMarkdown | null {
  if (!data) return null
  const html = data.getData("text/html")
  return (html ? htmlToMarkdown(html) : null) ?? tsvToMarkdown(data.getData("text/plain"))
}
