/**
 * The selection guard pdf.js's TextLayerBuilder adds around a bare TextLayer, ported because
 * pdf_viewer.mjs needs a global `pdfjsLib` before it loads. Without it, a drag over the gaps
 * between spans lands on the layer itself and the selection snaps to the page's end.
 * Source: pdfjs-dist web/text_layer_builder.js (#bindMouse, #enableGlobalSelectionListener).
 */

const layers = new Map<HTMLDivElement, HTMLDivElement>()
let listeners: AbortController | null = null

function reset(end: HTMLDivElement, layer: HTMLDivElement) {
  layer.append(end)
  end.style.width = ""
  end.style.height = ""
  layer.classList.remove("selecting")
}

function enableGlobalListener() {
  if (listeners) return
  listeners = new AbortController()
  const { signal } = listeners
  let pointerDown = false
  let prevRange: Range | null = null

  document.addEventListener("pointerdown", () => { pointerDown = true }, { signal })
  document.addEventListener("pointerup", () => {
    pointerDown = false
    layers.forEach(reset)
  }, { signal })
  window.addEventListener("blur", () => {
    pointerDown = false
    layers.forEach(reset)
  }, { signal })
  document.addEventListener("keyup", () => {
    if (!pointerDown) layers.forEach(reset)
  }, { signal })

  document.addEventListener("selectionchange", () => {
    const selection = document.getSelection()
    if (!selection || selection.rangeCount === 0) {
      layers.forEach(reset)
      return
    }
    const active = new Set<HTMLDivElement>()
    for (let i = 0; i < selection.rangeCount; i++) {
      const range = selection.getRangeAt(i)
      for (const layer of layers.keys()) {
        if (!active.has(layer) && range.intersectsNode(layer)) active.add(layer)
      }
    }
    for (const [layer, end] of layers) {
      if (active.has(layer)) layer.classList.add("selecting")
      else reset(end, layer)
    }

    // Move the marker next to the moving end of the selection, so the gap the
    // pointer is over belongs to it rather than to the layer's last span.
    const range = selection.getRangeAt(0)
    const modifyStart = prevRange !== null && (
      range.compareBoundaryPoints(Range.END_TO_END, prevRange) === 0 ||
      range.compareBoundaryPoints(Range.START_TO_END, prevRange) === 0
    )
    let anchor: Node | null = modifyStart ? range.startContainer : range.endContainer
    if (anchor?.nodeType === Node.TEXT_NODE) anchor = anchor.parentNode
    const anchorEl = anchor as HTMLElement | null
    const layer = anchorEl?.parentElement?.closest<HTMLDivElement>(".textLayer")
    const end = layer ? layers.get(layer) : undefined
    if (layer && end && anchorEl?.parentElement) {
      end.style.width = layer.style.width
      end.style.height = layer.style.height
      anchorEl.parentElement.insertBefore(end, modifyStart ? anchorEl : anchorEl.nextSibling)
    }
    prevRange = range.cloneRange()
  }, { signal })
}

/** Call once the layer's spans are rendered; the returned function unbinds it. */
export function bindTextLayerSelection(layer: HTMLDivElement): () => void {
  const end = document.createElement("div")
  end.className = "endOfContent"
  layer.append(end)
  const onMouseDown = () => layer.classList.add("selecting")
  layer.addEventListener("mousedown", onMouseDown)
  layers.set(layer, end)
  enableGlobalListener()

  return () => {
    layer.removeEventListener("mousedown", onMouseDown)
    layer.classList.remove("selecting")
    end.remove()
    layers.delete(layer)
    if (layers.size === 0) {
      listeners?.abort()
      listeners = null
    }
  }
}
