import { describe, expect, it } from "vitest"
import {
  ANNOTATED_IMAGE_LABEL,
  annotationTarget,
  buildExcalidrawDiagramMarkdown,
  findExcalidrawDiagrams,
  fitAnnotationImage,
  replaceExcalidrawDiagram,
  soleBlockImageSrc,
} from "./noteDiagrams"

const API = "http://localhost:7820"
const SVG = "__LUMINARY_IMG__/notes/a.svg"
const SCENE = "__LUMINARY_IMG__/notes/a.excalidraw.json"

describe("findExcalidrawDiagrams", () => {
  it("reads a diagram written before labels existed as a Diagram", () => {
    const content = `intro\n\n![Diagram|large](${SVG})\n<!-- luminary:excalidraw=${SCENE} -->\n`
    const [diagram] = findExcalidrawDiagrams(content)
    expect(diagram).toMatchObject({ label: "Diagram", size: "large", svgPath: SVG, scenePath: SCENE })
    expect(content.slice(diagram.start, diagram.end)).toBe(
      `![Diagram|large](${SVG})\n<!-- luminary:excalidraw=${SCENE} -->`,
    )
  })

  it("round-trips an annotated image's label and size", () => {
    const markdown = buildExcalidrawDiagramMarkdown(SVG, SCENE, ANNOTATED_IMAGE_LABEL, "medium")
    expect(markdown.startsWith(`![${ANNOTATED_IMAGE_LABEL}|medium](`)).toBe(true)
    expect(findExcalidrawDiagrams(markdown)).toEqual([
      { label: ANNOTATED_IMAGE_LABEL, size: "medium", svgPath: SVG, scenePath: SCENE, start: 0, end: markdown.length },
    ])
  })

  it("keeps an image that named no size sizeless", () => {
    const markdown = buildExcalidrawDiagramMarkdown(SVG, SCENE, ANNOTATED_IMAGE_LABEL, null)
    expect(markdown.startsWith(`![${ANNOTATED_IMAGE_LABEL}](`)).toBe(true)
    expect(findExcalidrawDiagrams(markdown)[0].size).toBeNull()
  })

  it("ignores a plain image with no scene beside it", () => {
    expect(findExcalidrawDiagrams(`![Pasted Image|large](${SVG})`)).toEqual([])
  })
})

describe("annotationTarget", () => {
  const content = "before\n\n![Pasted Image|medium](__LUMINARY_IMG__/notes/shot.png)\n\nafter"

  it("finds a note image by its rendered URL, with its size, and replaces it with the annotation", () => {
    const ref = annotationTarget(content, `${API}/images/local/notes/shot.png`, API)
    expect(ref).toEqual({
      imagePath: "__LUMINARY_IMG__/notes/shot.png",
      size: "medium",
      start: content.indexOf("!["),
      end: content.indexOf("\n\nafter"),
    })
    const annotated = buildExcalidrawDiagramMarkdown(SVG, SCENE, ANNOTATED_IMAGE_LABEL, ref!.size)
    const next = replaceExcalidrawDiagram(content, ref!, annotated)
    expect(next).toBe(`before\n\n${annotated}\n\nafter`)
    expect(findExcalidrawDiagrams(next)).toEqual([expect.objectContaining({ size: "medium" })])
  })

  it("reopens an annotated image's saved scene rather than annotating the flattened SVG", () => {
    const annotated = `before\n\n${buildExcalidrawDiagramMarkdown(SVG, SCENE, ANNOTATED_IMAGE_LABEL, "small")}\n\nafter`
    expect(annotationTarget(annotated, `${API}/images/local/notes/a.svg`, API)).toMatchObject({
      scenePath: SCENE,
      size: "small",
      end: annotated.indexOf("\n\nafter"),
    })
  })

  it("refuses an image that is not a local asset", () => {
    const external = "![Chart](https://example.com/chart.png)"
    expect(annotationTarget(external, "https://example.com/chart.png", API)).toBeNull()
  })

  it("returns null when the image is not in the note", () => {
    expect(annotationTarget(content, `${API}/images/local/notes/other.png`, API)).toBeNull()
  })
})

describe("soleBlockImageSrc", () => {
  it("names the image of an image-only block and the SVG of a drawing block", () => {
    expect(soleBlockImageSrc("![Shot|small](__LUMINARY_IMG__/notes/s.png)\n")).toBe("__LUMINARY_IMG__/notes/s.png")
    expect(soleBlockImageSrc(buildExcalidrawDiagramMarkdown(SVG, SCENE, ANNOTATED_IMAGE_LABEL))).toBe(SVG)
  })

  it("is null for a block holding text beside the image", () => {
    expect(soleBlockImageSrc("See ![Shot](__LUMINARY_IMG__/notes/s.png)")).toBeNull()
  })
})

describe("fitAnnotationImage", () => {
  it("keeps an image that already fits", () => {
    expect(fitAnnotationImage(800, 600)).toEqual({ width: 800, height: 600 })
  })

  it("scales a retina screenshot down to the canvas width, keeping its aspect", () => {
    expect(fitAnnotationImage(2880, 1800)).toEqual({ width: 1200, height: 750 })
  })
})
