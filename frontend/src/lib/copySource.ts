import type { Element, ElementContent, Root } from "hast"

/**
 * The markdown a rendered element came from. A diagram, formula, note link or
 * note image renders to something with no markdown left in it, and Chrome drops
 * KaTeX's TeX annotation from a copy; this attribute survives the copy, so a
 * paste into a note restores the source.
 */
const COPY_SOURCE_ATTR = "data-luminary-md"

// Only these shapes are restored, so a web page cannot smuggle arbitrary text
// into a note through a hidden attribute.
const COPY_SOURCE_SHAPES = [
  /^\$[^$\n]+\$$/,
  /^\$\$\n[^$]+\n\$\$$/,
  /^```mermaid\n[\s\S]*\n```$/,
  /^\[\[[a-f0-9-]+\|[^\]\n]+\]\]$/,
  /^!\[[^\]\n]*\]\((?:__LUMINARY_IMG__\/|https?:\/\/)[^)\s]+\)(?:\s*\n?<!-- luminary:excalidraw=__LUMINARY_IMG__\/notes\/[^>\s]+\.excalidraw\.json -->)?$/,
]

export function copySource(markdown: string): Record<string, string> {
  return { [COPY_SOURCE_ATTR]: markdown }
}

export function isCopySource(value: unknown): value is string {
  return typeof value === "string" && COPY_SOURCE_SHAPES.some((shape) => shape.test(value))
}

export function classes(node: Element): string[] {
  const value = node.properties.className
  return Array.isArray(value) ? value.map(String) : []
}

/** The TeX source KaTeX keeps in its MathML annotation, if any. */
export function texAnnotation(node: ElementContent): string | null {
  if (node.type !== "element") return null
  if (node.tagName === "annotation" && node.properties.encoding === "application/x-tex") {
    return node.children.map((c) => (c.type === "text" ? c.value : "")).join("").trim()
  }
  for (const child of node.children) {
    const tex = texAnnotation(child)
    if (tex !== null) return tex
  }
  return null
}

/** Rehype plugin, after rehype-katex: stamps each formula with its dollar source. */
export function rehypeMathCopySource() {
  const visit = (node: Root | Element) => {
    for (const child of node.children) {
      if (child.type !== "element") continue
      const names = classes(child)
      const display = names.includes("katex-display")
      if (display || names.includes("katex")) {
        const tex = texAnnotation(child)
        if (tex) {
          child.properties.dataLuminaryMd = display ? `$$\n${tex}\n$$` : `$${tex}$`
          continue
        }
      }
      visit(child)
    }
  }
  return visit
}
