// The token layer in index.css is the only place colour is decided, so its legibility is
// checked here, in both themes: text pairs against WCAG 2.x 4.5:1, UI marks against 3:1,
// and the right/wrong pair against the three common forms of colour blindness.
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

type Rgb = [number, number, number]

const css = readFileSync(resolve(__dirname, "../index.css"), "utf8")

function block(selector: string): Record<string, Rgb> {
  const start = css.indexOf(`${selector} {`)
  const body = css.slice(start, css.indexOf("\n  }", start))
  const out: Record<string, Rgb> = {}
  for (const m of body.matchAll(/--lum-([\w-]+):\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%;/g)) {
    out[m[1]] = hslToRgb(Number(m[2]), Number(m[3]) / 100, Number(m[4]) / 100)
  }
  return out
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  const k = (n: number) => (n + h / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))
  return [f(0), f(8), f(4)]
}

const linear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const luminance = ([r, g, b]: Rgb) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// Machado, Oliveira & Fernandes (2009), full severity, applied in linear RGB.
const CVD = {
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritanopia: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
} as const

function lab(rgbLinear: number[]): Rgb {
  const [r, g, b] = rgbLinear.map((v) => Math.min(1, Math.max(0, v)))
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  const x = f((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047)
  const y = f(0.2126 * r + 0.7152 * g + 0.0722 * b)
  const z = f((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)]
}

function separation(a: Rgb, b: Rgb, kind: keyof typeof CVD): number {
  const sim = (c: Rgb) => {
    const v = c.map(linear)
    return CVD[kind].map((row) => row[0] * v[0] + row[1] * v[1] + row[2] * v[2])
  }
  const [p, q] = [lab(sim(a)), lab(sim(b))]
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
}

const hex = (h: string): Rgb => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as Rgb

// CIE76 distance after simulation. A material-style green #4CAF50 against red #F44336 falls
// to 17.5 under deuteranopia and reads as one colour; the right/wrong teal and terracotta
// keep at least 30.4 under all three. 25 sits between them.
const MIN_CVD_SEPARATION = 25

const SURFACES = ["canvas", "raised", "sunken", "rail", "hover"]
const TEXT_PAIRS: [string, string][] = [
  ...SURFACES.flatMap((s) => [["ink-1", s], ["ink-2", s]] as [string, string][]),
  ["action-fg", "action"],
  ["danger-fg", "danger"],
  ["positive-fg", "positive-soft"],
  ["negative-fg", "negative-soft"],
  ["caution-fg", "caution-soft"],
  ["info-fg", "info-soft"],
  ["answer-partial-fg", "answer-partial-soft"],
  ["brand", "canvas"],
]
const MARK_NAMES = [
  "focus", "positive", "negative", "caution", "info", "answer-partial",
  "mode-recall", "mode-quiz", "mode-explain",
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => `chart-${n}`),
]

describe.each([
  ["light", block(":root")],
  ["dark", block(".dark")],
])("%s tokens", (_theme, t) => {
  it("parses the token block", () => {
    expect(Object.keys(t).length).toBeGreaterThan(40)
  })

  it.each(TEXT_PAIRS)("%s on %s reaches 4.5:1", (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each(MARK_NAMES)("%s stands out from the canvas at 3:1", (name) => {
    expect(contrast(t[name], t.canvas)).toBeGreaterThanOrEqual(3)
  })

  it.each(Object.keys(CVD) as (keyof typeof CVD)[])("right and wrong stay apart under %s", (kind) => {
    expect(separation(t.positive, t.negative, kind)).toBeGreaterThanOrEqual(MIN_CVD_SEPARATION)
    expect(separation(t["positive-fg"], t["negative-fg"], kind)).toBeGreaterThanOrEqual(MIN_CVD_SEPARATION)
  })
})

describe("the colour-blind threshold", () => {
  it("rejects a red and green that deuteranopes cannot tell apart", () => {
    expect(separation(hex("#4CAF50"), hex("#F44336"), "deuteranopia")).toBeLessThan(MIN_CVD_SEPARATION)
  })
})
