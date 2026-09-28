import { useEffect } from "react"
import { toast } from "sonner"
import {
  formatZoomPercentage,
  getCustomZoomHandler,
  getDefaultPanelForPath,
  getPanelDisplayName,
  usePanelZoomStore,
} from "@/store/panelZoomStore"

export type ZoomAction = "in" | "out" | "reset" | null

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false
  const nav = navigator as unknown as { userAgentData?: { platform?: string } }
  const platform = nav.userAgentData?.platform || navigator.platform || navigator.userAgent || ""
  return /Mac|iPhone|iPod|iPad/i.test(platform)
}

export function getZoomShortcutAction(e: KeyboardEvent, isMac: boolean): ZoomAction {
  // On Mac, support both Command (standard) and Control (external keyboards or muscle memory).
  // On Windows/Linux, support Control.
  const modifier = isMac
    ? (e.metaKey || e.ctrlKey) && !e.altKey
    : e.ctrlKey && !e.metaKey && !e.altKey

  if (!modifier) return null

  // Zoom In (+ or = or NumpadAdd or corresponding keyCodes)
  const isPlus =
    e.key === "+" ||
    e.key === "=" ||
    e.code === "Equal" ||
    e.code === "NumpadAdd" ||
    (e as unknown as { keyCode?: number }).keyCode === 187 ||
    (e as unknown as { which?: number }).which === 187 ||
    (e as unknown as { keyCode?: number }).keyCode === 61 ||
    (e as unknown as { which?: number }).which === 61 ||
    (e as unknown as { keyCode?: number }).keyCode === 107 ||
    (e as unknown as { which?: number }).which === 107

  if (isPlus) return "in"

  // Zoom Out (- or _ or NumpadSubtract or corresponding keyCodes)
  const isMinus =
    e.key === "-" ||
    e.key === "_" ||
    e.code === "Minus" ||
    e.code === "NumpadSubtract" ||
    (e as unknown as { keyCode?: number }).keyCode === 189 ||
    (e as unknown as { which?: number }).which === 189 ||
    (e as unknown as { keyCode?: number }).keyCode === 173 ||
    (e as unknown as { which?: number }).which === 173 ||
    (e as unknown as { keyCode?: number }).keyCode === 109 ||
    (e as unknown as { which?: number }).which === 109

  if (isMinus) return "out"

  // Zoom Reset (0 or Numpad0 or corresponding keyCodes)
  const isZero =
    e.key === "0" ||
    e.code === "Digit0" ||
    e.code === "Numpad0" ||
    (e as unknown as { keyCode?: number }).keyCode === 48 ||
    (e as unknown as { which?: number }).which === 48 ||
    (e as unknown as { keyCode?: number }).keyCode === 96 ||
    (e as unknown as { which?: number }).which === 96

  if (isZero) return "reset"

  return null
}

export function resolveTargetPanel(
  target: EventTarget | null,
  activePanelId: string | null,
  defaultPanelId?: string
): string | null {
  // 1. Check if the event target itself or an ancestor has data-zoom-panel
  if (target && typeof (target as { closest?: unknown }).closest === "function") {
    const el = target as unknown as { closest: (selector: string) => { getAttribute: (attr: string) => string | null } | null }
    const panelEl = el.closest("[data-zoom-panel]")
    if (panelEl) {
      const id = panelEl.getAttribute("data-zoom-panel")
      if (id) return id
    }
    // Explicitly ignored container (and not inside an inner zoom panel)
    if (el.closest("[data-zoom-ignore]")) {
      return null
    }
  }

  // 2. Check if mouse pointer is currently hovering over a zoom panel
  if (typeof document !== "undefined") {
    try {
      const hovered = document.querySelector("[data-zoom-panel]:hover")
      if (hovered) {
        const id = hovered.getAttribute("data-zoom-panel")
        if (id) return id
      }
    } catch {
      // Ignore pseudo-class query errors in headless/test environments
    }
  }

  // 3. Smart path and active view context
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/notes")) {
    if (typeof document !== "undefined") {
      const previewVisible = document.querySelector("[data-zoom-panel='note-preview']:not(.hidden)")
      const editorVisible = document.querySelector("[data-zoom-panel='note-editor']:not(.hidden)")
      if (previewVisible && !editorVisible) {
        return "note-preview"
      }
    }
  }

  if (activePanelId) return activePanelId
  if (defaultPanelId) return defaultPanelId
  if (typeof window !== "undefined") {
    return getDefaultPanelForPath(window.location.pathname)
  }
  return "reader"
}

interface UsePanelZoomShortcutOptions {
  /** Default panel to zoom if no panel is actively focused or clicked */
  defaultPanelId?: string
  /** Whether shortcut handling is enabled. Defaults to true */
  enabled?: boolean
  /** Custom zoom handler for special surfaces like PDF canvas */
  onCustomZoom?: (action: "in" | "out" | "reset", panelId: string) => boolean | void
}

export function usePanelZoomShortcut({
  defaultPanelId,
  enabled = true,
  onCustomZoom,
}: UsePanelZoomShortcutOptions = {}) {
  const setActivePanelId = usePanelZoomStore((s) => s.setActivePanelId)
  const zoomIn = usePanelZoomStore((s) => s.zoomIn)
  const zoomOut = usePanelZoomStore((s) => s.zoomOut)
  const resetZoom = usePanelZoomStore((s) => s.resetZoom)

  useEffect(() => {
    if (!enabled) return

    const isMac = isMacPlatform()

    // Track active panel on pointer over, click, or focus
    function onPointerOrFocus(e: Event) {
      const el = e.target as { closest?: (selector: string) => { getAttribute: (attr: string) => string | null } | null }
      if (!el || typeof el.closest !== "function") return
      const panelEl = el.closest("[data-zoom-panel]")
      if (panelEl) {
        const id = panelEl.getAttribute("data-zoom-panel")
        if (id && id !== usePanelZoomStore.getState().activePanelId) {
          setActivePanelId(id)
        }
      } else if (el.closest("[data-zoom-ignore]")) {
        setActivePanelId(null)
      }
    }

    function onKeyDown(e: KeyboardEvent) {
      const action = getZoomShortcutAction(e, isMac)
      if (!action) return

      // Always prevent default to stop whole-window zoom
      e.preventDefault()
      e.stopPropagation()

      const targetPanel = resolveTargetPanel(e.target, usePanelZoomStore.getState().activePanelId, defaultPanelId)
      if (!targetPanel) {
        return
      }

      // Allow caller option to intercept
      if (onCustomZoom && onCustomZoom(action, targetPanel) === true) {
        return
      }

      // Check globally registered handler for this panel
      const registeredHandler = getCustomZoomHandler(targetPanel)
      if (registeredHandler && registeredHandler(action) === true) {
        return
      }

      let result: { panelId: string; zoom: number }
      if (action === "in") {
        result = zoomIn(targetPanel)
      } else if (action === "out") {
        result = zoomOut(targetPanel)
      } else {
        result = resetZoom(targetPanel)
      }

      toast(`${getPanelDisplayName(result.panelId)}: ${formatZoomPercentage(result.zoom)}`, {
        id: `panel-zoom-${result.panelId}`,
        duration: 1200,
      })
    }

    window.addEventListener("pointerdown", onPointerOrFocus, { capture: true })
    window.addEventListener("pointerover", onPointerOrFocus, { capture: true, passive: true })
    window.addEventListener("focusin", onPointerOrFocus, { capture: true })
    window.addEventListener("keydown", onKeyDown, { capture: true })

    return () => {
      window.removeEventListener("pointerdown", onPointerOrFocus, { capture: true })
      window.removeEventListener("pointerover", onPointerOrFocus, { capture: true })
      window.removeEventListener("focusin", onPointerOrFocus, { capture: true })
      window.removeEventListener("keydown", onKeyDown, { capture: true })
    }
  }, [enabled, defaultPanelId, onCustomZoom, setActivePanelId, zoomIn, zoomOut, resetZoom])
}
