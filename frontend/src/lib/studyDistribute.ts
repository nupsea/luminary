// Pure helpers for splitting a collection-wide generation total across its
// sources. No imports, no side effects -- unit-tested in studyDistribute.test.ts.

// Split a target TOTAL across N sources as evenly as possible (remainder spread
// one-per-source from the front). Sum of the result always equals `total`.
export function distributeCount(total: number, buckets: number): number[] {
  if (buckets <= 0) return []
  const base = Math.floor(Math.max(0, total) / buckets)
  let remainder = Math.max(0, total) - base * buckets
  return Array.from({ length: buckets }, () => {
    if (remainder > 0) {
      remainder -= 1
      return base + 1
    }
    return base
  })
}

// Distribute a proportional remainder by the largest-remainder method.
function largestRemainder(total: number, weights: number[]): number[] {
  const n = weights.length
  const sum = weights.reduce((a, b) => a + b, 0)
  if (n === 0 || total <= 0 || sum <= 0) return new Array(n).fill(0)
  const ideal = weights.map((w) => (w / sum) * total)
  const result = ideal.map((x) => Math.floor(x))
  let remaining = total - result.reduce((a, b) => a + b, 0)
  const byFrac = ideal
    .map((x, i) => ({ i, frac: x - Math.floor(x) }))
    .sort((a, b) => b.frac - a.frac)
  for (let k = 0; k < byFrac.length && remaining > 0; k++) {
    result[byFrac[k].i] += 1
    remaining -= 1
  }
  return result
}

// Split a target TOTAL across sources by content size, but fairly: a big book
// gets most of the questions while a small note still keeps a real share. We
// dampen the raw sizes with a square root (so a 200x-larger book isn't 200x the
// questions) and guarantee every source with content at least one card when the
// total allows. Sum always equals `total`.
export function distributeByWeight(total: number, weights: number[]): number[] {
  const n = weights.length
  if (n === 0 || total <= 0) return new Array(n).fill(0)
  const eff = weights.map((w) => Math.sqrt(Math.max(0, w)))
  const contentIdx = eff.flatMap((e, i) => (e > 0 ? [i] : []))
  if (contentIdx.length === 0) return distributeCount(total, n)

  const result = new Array<number>(n).fill(0)
  let remaining = total
  // Floor of 1 per content source when affordable; below that, pure proportional.
  if (total >= contentIdx.length) {
    for (const i of contentIdx) {
      result[i] = 1
      remaining -= 1
    }
  }
  const extra = largestRemainder(remaining, eff)
  for (let i = 0; i < n; i++) result[i] += extra[i]
  return result
}
