import { useEffect } from "react"

// The keys a focused scroller scrolls by itself.
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "])

/**
 * Calls `onInput` when the reader scrolls `ref`'s element themselves: wheel, touch, its
 * scrollbar or a scrolling key. A scroll with none of these is a jump the app made, to a
 * citation, a search hit or a contents entry, and is not where the reader is reading.
 */
export function useReaderInput(
  ref: React.RefObject<HTMLElement | null>,
  enabled: boolean,
  onInput: () => void,
): void {
  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return
    // A pointerdown on the scroller itself, not on its content, is its scrollbar.
    const onPointerDown = (e: PointerEvent) => { if (e.target === el) onInput() }
    const onKeyDown = (e: KeyboardEvent) => { if (SCROLL_KEYS.has(e.key)) onInput() }
    el.addEventListener("wheel", onInput, { passive: true })
    el.addEventListener("touchmove", onInput, { passive: true })
    el.addEventListener("pointerdown", onPointerDown)
    el.addEventListener("keydown", onKeyDown)
    return () => {
      el.removeEventListener("wheel", onInput)
      el.removeEventListener("touchmove", onInput)
      el.removeEventListener("pointerdown", onPointerDown)
      el.removeEventListener("keydown", onKeyDown)
    }
  }, [ref, enabled, onInput])
}
