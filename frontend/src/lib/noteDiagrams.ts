export const DIAGRAM_LABEL = "Diagram"
export const ANNOTATED_IMAGE_LABEL = "Annotated image"

export type ImageSize = "small" | "medium" | "large"

export interface ExcalidrawNoteDiagramRef {
  svgPath: string
  scenePath: string
  label: string
  /** null when the markdown names no size and the renderer's default applies. */
  size: ImageSize | null
  start: number
  end: number
}

/** A plain note image about to be annotated; saving replaces it with a diagram. */
interface NoteImageRef {
  imagePath: string
  size: ImageSize | null
  start: number
  end: number
}

export type AnnotationTarget = ExcalidrawNoteDiagramRef | NoteImageRef

const EXCALIDRAW_MARKER_RE = /!\[([^\]|\n]+)(?:\|(small|medium|large))?\]\((__LUMINARY_IMG__\/notes\/[^)]+\.svg)\)\s*\n?<!-- luminary:excalidraw=(__LUMINARY_IMG__\/notes\/[^>]+\.excalidraw\.json) -->/g

export function parseImageAlt(alt?: string): { alt: string; size?: ImageSize } {
  if (!alt) return { alt: "" }
  const parts = alt.split("|")
  if (parts.length < 2) return { alt }
  const potentialSize = parts.at(-1)?.trim().toLowerCase()
  if (potentialSize === "small" || potentialSize === "medium" || potentialSize === "large") {
    return { alt: parts.slice(0, -1).join("|").trim(), size: potentialSize }
  }
  return { alt }
}

export function buildExcalidrawDiagramMarkdown(
  svgPath: string,
  scenePath: string,
  label: string = DIAGRAM_LABEL,
  size: ImageSize | null = "large",
): string {
  return `![${label}${size ? `|${size}` : ""}](${svgPath})\n<!-- luminary:excalidraw=${scenePath} -->`
}

/** A diagram renders as a captioned figure; an annotated image renders as the image it replaced. */
export function isAnnotatedImage(diagram: ExcalidrawNoteDiagramRef): boolean {
  return diagram.label !== DIAGRAM_LABEL
}

export function findExcalidrawDiagrams(content: string): ExcalidrawNoteDiagramRef[] {
  return [...content.matchAll(EXCALIDRAW_MARKER_RE)].flatMap((match) => {
    if (match.index === undefined) return []
    return {
      label: match[1],
      size: (match[2] as ImageSize | undefined) ?? null,
      svgPath: match[3],
      scenePath: match[4],
      start: match.index,
      end: match.index + match[0].length,
    }
  })
}

export function replaceExcalidrawDiagram(
  content: string,
  ref: { start: number; end: number },
  markdown: string,
): string {
  return content.substring(0, ref.start) + markdown + content.substring(ref.end)
}

/**
 * The note image whose URL matches a rendered src. Mirrored images render as
 * <apiBase>/images/local/... but are authored as __LUMINARY_IMG__/..., so both
 * spellings are tried.
 */
export function findMarkdownImage(
  content: string,
  src: string,
  apiBase?: string,
): { url: string; alt: string; start: number; end: number } | null {
  const candidates = [src]
  if (apiBase && src.startsWith(`${apiBase}/images/local/`)) {
    candidates.push(src.replace(`${apiBase}/images/local/`, "__LUMINARY_IMG__/"))
  }
  for (const url of candidates) {
    const closeIdx = content.indexOf(`](${url})`)
    if (closeIdx === -1) continue
    const openIdx = content.lastIndexOf("![", closeIdx)
    if (openIdx === -1) continue
    return {
      url,
      alt: content.slice(openIdx + 2, closeIdx),
      start: openIdx,
      end: closeIdx + 2 + url.length + 1,
    }
  }
  return null
}

/**
 * What the annotation editor opens for a rendered note image: its saved scene when it was
 * annotated before, else the image. Only a note asset qualifies: an outside URL would taint the canvas.
 */
export function annotationTarget(content: string, src: string, apiBase?: string): AnnotationTarget | null {
  const image = findMarkdownImage(content, src, apiBase)
  if (!image?.url.startsWith("__LUMINARY_IMG__/")) return null
  const saved = findExcalidrawDiagrams(content).find((diagram) => diagram.start === image.start)
  if (saved) return saved
  return { imagePath: image.url, size: parseImageAlt(image.alt).size ?? null, start: image.start, end: image.end }
}

/** The diagram or annotated image a block consists of, or null when it holds anything else. */
export function soleBlockDiagram(source: string): ExcalidrawNoteDiagramRef | null {
  const block = source.trim()
  const [diagram] = findExcalidrawDiagrams(block)
  return diagram?.start === 0 && diagram.end === block.length ? diagram : null
}

/** The src of the one image or drawing a block consists of, or null when it holds anything else. */
export function soleBlockImageSrc(source: string): string | null {
  return soleBlockDiagram(source)?.svgPath ?? source.trim().match(/^!\[[^\]\n]*\]\(([^)\s]+)\)$/)?.[1] ?? null
}

/** Fits an image onto the canvas at most `maxWidth` wide; the file keeps its full resolution. */
export function fitAnnotationImage(
  width: number,
  height: number,
  maxWidth = 1200,
): { width: number; height: number } {
  if (width <= maxWidth) return { width, height }
  return { width: maxWidth, height: Math.round((height * maxWidth) / width) }
}
