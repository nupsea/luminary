import { describe, expect, it, afterEach } from "vitest"
import {
  isArrowKey,
  arrowDelta,
  isMacPlatform,
  getModifierLabel,
  getModifierSymbol,
} from "./keyboard"

describe("keyboard utilities", () => {
  const originalNavigator = globalThis.navigator

  afterEach(() => {
    Object.defineProperty(globalThis, "navigator", {
      value: originalNavigator,
      configurable: true,
      writable: true,
    })
  })

  it("checks arrow keys and deltas", () => {
    expect(isArrowKey("ArrowLeft")).toBe(true)
    expect(isArrowKey("ArrowUp")).toBe(true)
    expect(isArrowKey("ArrowRight")).toBe(true)
    expect(isArrowKey("ArrowDown")).toBe(true)
    expect(isArrowKey("Enter")).toBe(false)

    expect(arrowDelta("ArrowLeft")).toBe(-1)
    expect(arrowDelta("ArrowUp")).toBe(-1)
    expect(arrowDelta("ArrowRight")).toBe(1)
    expect(arrowDelta("ArrowDown")).toBe(1)
  })

  it("detects macOS platform", () => {
    Object.defineProperty(globalThis, "navigator", {
      value: {
        platform: "MacIntel",
        userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      },
      configurable: true,
      writable: true,
    })

    expect(isMacPlatform()).toBe(true)
    expect(getModifierLabel()).toBe("Cmd")
    expect(getModifierSymbol()).toBe("⌘")
  })

  it("detects Windows platform", () => {
    Object.defineProperty(globalThis, "navigator", {
      value: {
        platform: "Win32",
        userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      },
      configurable: true,
      writable: true,
    })

    expect(isMacPlatform()).toBe(false)
    expect(getModifierLabel()).toBe("Ctrl")
    expect(getModifierSymbol()).toBe("Ctrl")
  })

  it("detects Linux platform", () => {
    Object.defineProperty(globalThis, "navigator", {
      value: {
        platform: "Linux x86_64",
        userAgent: "Mozilla/5.0 (X11; Linux x86_64)",
      },
      configurable: true,
      writable: true,
    })

    expect(isMacPlatform()).toBe(false)
    expect(getModifierLabel()).toBe("Ctrl")
    expect(getModifierSymbol()).toBe("Ctrl")
  })
})
