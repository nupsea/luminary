/** True when the event target is an editable control, so global shortcuts must not fire. */
export function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  if (t.isContentEditable) return true
  const tag = t.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
}

/** True when a focused button should own this Enter/Space keypress (native activation). */
export function isButtonActivation(e: KeyboardEvent): boolean {
  return (
    (e.key === "Enter" || e.key === " ") &&
    e.target instanceof HTMLElement &&
    e.target.tagName === "BUTTON"
  )
}

/** Rove focus across the visible [data-kbnav] buttons, cycling at the ends. */
export function moveKbnavFocus(delta: number) {
  const buttons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("[data-kbnav]"),
  ).filter((b) => !b.disabled)
  if (buttons.length === 0) return
  const idx = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const next =
    idx === -1
      ? delta > 0 ? 0 : buttons.length - 1
      : (idx + delta + buttons.length) % buttons.length
  buttons[next]?.focus()
}

export function isArrowKey(key: string): boolean {
  return key === "ArrowLeft" || key === "ArrowUp" || key === "ArrowRight" || key === "ArrowDown"
}

export function arrowDelta(key: string): number {
  return key === "ArrowLeft" || key === "ArrowUp" ? -1 : 1
}

/**
 * Returns true if running on macOS or iOS (browser or Tauri desktop app).
 * Checks User-Agent Client Hints, navigator.platform, and navigator.userAgent.
 */
export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false
  const nav = navigator as unknown as { userAgentData?: { platform?: string } }
  const platform = nav.userAgentData?.platform || navigator.platform || navigator.userAgent || ""
  return /Mac|iPhone|iPod|iPad/i.test(platform)
}

/**
 * Returns primary modifier label: "Cmd" on macOS, "Ctrl" on Windows/Linux.
 */
export function getModifierLabel(): "Cmd" | "Ctrl" {
  return isMacPlatform() ? "Cmd" : "Ctrl"
}

/**
 * Returns primary modifier symbol: "⌘" on macOS, "Ctrl" on Windows/Linux.
 */
export function getModifierSymbol(): "⌘" | "Ctrl" {
  return isMacPlatform() ? "⌘" : "Ctrl"
}
