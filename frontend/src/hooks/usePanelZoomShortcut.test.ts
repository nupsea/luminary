import { describe, it, expect } from "vitest"
import {
  getZoomShortcutAction,
  resolveTargetPanel,
} from "./usePanelZoomShortcut"

describe("usePanelZoomShortcut", () => {
  describe("getZoomShortcutAction", () => {
    it("recognizes Zoom In on Mac using metaKey", () => {
      const e1 = { metaKey: true, ctrlKey: false, altKey: false, key: "=", code: "Equal" } as KeyboardEvent
      const e2 = { metaKey: true, ctrlKey: false, altKey: false, key: "+", code: "Equal" } as KeyboardEvent
      const e3 = { metaKey: true, ctrlKey: false, altKey: false, key: "Add", code: "NumpadAdd" } as KeyboardEvent

      expect(getZoomShortcutAction(e1, true)).toBe("in")
      expect(getZoomShortcutAction(e2, true)).toBe("in")
      expect(getZoomShortcutAction(e3, true)).toBe("in")
    })

    it("recognizes Zoom Out on Mac using metaKey", () => {
      const e1 = { metaKey: true, ctrlKey: false, altKey: false, key: "-", code: "Minus" } as KeyboardEvent
      const e2 = { metaKey: true, ctrlKey: false, altKey: false, key: "_", code: "Minus" } as KeyboardEvent
      const e3 = { metaKey: true, ctrlKey: false, altKey: false, key: "Subtract", code: "NumpadSubtract" } as KeyboardEvent

      expect(getZoomShortcutAction(e1, true)).toBe("out")
      expect(getZoomShortcutAction(e2, true)).toBe("out")
      expect(getZoomShortcutAction(e3, true)).toBe("out")
    })

    it("recognizes Zoom Reset on Mac using metaKey + 0", () => {
      const e1 = { metaKey: true, ctrlKey: false, altKey: false, key: "0", code: "Digit0" } as KeyboardEvent
      const e2 = { metaKey: true, ctrlKey: false, altKey: false, key: "0", code: "Numpad0" } as KeyboardEvent

      expect(getZoomShortcutAction(e1, true)).toBe("reset")
      expect(getZoomShortcutAction(e2, true)).toBe("reset")
    })

    it("requires ctrlKey instead of metaKey on Windows/Linux", () => {
      const macEvent = { metaKey: true, ctrlKey: false, altKey: false, key: "=", code: "Equal" } as KeyboardEvent
      const winEvent = { metaKey: false, ctrlKey: true, altKey: false, key: "=", code: "Equal" } as KeyboardEvent

      expect(getZoomShortcutAction(macEvent, false)).toBeNull()
      expect(getZoomShortcutAction(winEvent, false)).toBe("in")
    })

    it("ignores unrelated keys or chords with Alt", () => {
      const altEvent = { metaKey: true, ctrlKey: false, altKey: true, key: "=", code: "Equal" } as KeyboardEvent
      const otherKey = { metaKey: true, ctrlKey: false, altKey: false, key: "k", code: "KeyK" } as KeyboardEvent

      expect(getZoomShortcutAction(altEvent, true)).toBeNull()
      expect(getZoomShortcutAction(otherKey, true)).toBeNull()
    })
  })

  describe("resolveTargetPanel", () => {
    it("extracts data-zoom-panel from event target if present", () => {
      const div = {
        closest: (sel: string) => (sel === "[data-zoom-panel]" ? { getAttribute: () => "note-editor" } : null),
      }
      expect(resolveTargetPanel(div as unknown as HTMLElement, null)).toBe("note-editor")
    })

    it("falls back to activePanelId when target is not inside a panel", () => {
      expect(resolveTargetPanel(null, "note-preview")).toBe("note-preview")
    })

    it("falls back to defaultPanelId when activePanelId is null", () => {
      expect(resolveTargetPanel(null, null, "docked-panel")).toBe("docked-panel")
    })

    it("falls back to 'reader' if nothing else is specified", () => {
      expect(resolveTargetPanel(null, null)).toBe("reader")
    })
  })
})
