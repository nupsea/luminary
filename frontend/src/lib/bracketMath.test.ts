import { describe, expect, it } from "vitest"

import { bracketMathToDollars } from "./bracketMath"

describe("bracketMathToDollars", () => {
  it("turns inline brackets into dollars, inside parentheses too", () => {
    expect(bracketMathToDollars("- **Mean (\\(\\mu\\))**: centre")).toBe("- **Mean ($\\mu$)**: centre")
    expect(bracketMathToDollars("for \\( x \\):")).toBe("for $ x $:")
  })

  it("keeps a display block that owns its lines on lines of its own, at its indent", () => {
    const md = "- PDF for \\( x \\):\n  \\[\n  f(x) = \\frac{1}{\\sqrt{2\\pi}\\sigma}\n  \\]\n\nNext"
    expect(bracketMathToDollars(md)).toBe(
      "- PDF for $ x $:\n  $$\n  f(x) = \\frac{1}{\\sqrt{2\\pi}\\sigma}\n  $$\n\nNext",
    )
    expect(bracketMathToDollars("\\[ x^2 \\]")).toBe("$$\nx^2\n$$")
  })

  it("keeps a display block that shares its line inline", () => {
    expect(bracketMathToDollars("so \\[x^2\\] holds")).toBe("so $$x^2$$ holds")
  })

  it("leaves code, escaped backslashes and other escapes alone", () => {
    const fenced = "```latex\n\\( x \\)\n```"
    expect(bracketMathToDollars(fenced)).toBe(fenced)
    expect(bracketMathToDollars("run `\\( x \\)` then \\( y \\)")).toBe("run `\\( x \\)` then $ y $")
    expect(bracketMathToDollars("a \\\\( b \\\\)")).toBe("a \\\\( b \\\\)")
    expect(bracketMathToDollars("\\*not bold\\* \\( x \\)")).toBe("\\*not bold\\* $ x $")
  })

  it("leaves a delimiter unpaired while it streams, or paired only across a blank line", () => {
    expect(bracketMathToDollars("so \\[\n  f(x) =")).toBe("so \\[\n  f(x) =")
    expect(bracketMathToDollars("a \\( b\n\nc \\) d")).toBe("a \\( b\n\nc \\) d")
  })
})
