import { describe, expect, it } from "vitest"

import { formatMetric } from "./formatMetric"

const metric = (value: number | null, unit: string) => ({
  value,
  unit,
  sample_size: 1,
  definition: "d",
  basis: "b",
})

describe("formatMetric", () => {
  it("attaches the unit the server named", () => {
    expect(formatMetric(metric(90.9, "percent"))).toBe("90.9%")
    expect(formatMetric(metric(25, "minutes"))).toBe("25m")
    expect(formatMetric(metric(2, "days"))).toBe("2")
    expect(formatMetric(metric(53, "count"))).toBe("53")
  })

  it("renders an uncomputed metric as an em dash, never a zero", () => {
    // A zero reads as a measurement. "Nothing recorded" and "measured nothing"
    // are the two things this page exists to keep apart.
    expect(formatMetric(metric(null, "minutes"))).toBe("—")
    expect(formatMetric(undefined)).toBe("—")
  })

  it("keeps a measured zero", () => {
    // 20 seconds rounds to 0 minutes and that is the truthful value; the basis
    // is what distinguishes it from absent.
    expect(formatMetric(metric(0, "minutes"))).toBe("0m")
  })
})
