/**
 * explanationDiff -- client-side sentence-level LCS diff for Feynman comparison
 *
 * Splits text by ". " boundaries, computes LCS, classifies each sentence as:
 *   shared      -- appears in both user and model explanations
 *   user_only   -- appears only in user explanation
 *   model_only  -- appears only in model explanation
 */

export type DiffKind = "shared" | "user_only" | "model_only"

export interface DiffSegment {
  text: string
  kind: DiffKind
}

/**
 * Split text into sentences by ". " or trailing ".".
 * Trims each sentence; filters blanks.
 */
export function splitSentences(text: string): string[] {
  return text
    .split(/\.\s+/)
    .map((s) => s.replace(/\.$/, "").trim())
    .filter((s) => s.length > 0)
}

/**
 * Compute LCS length table for two string arrays.
 * Returns the DP table.
 */
function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1].toLowerCase() === b[j - 1].toLowerCase()) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }
  return dp
}

/**
 * Compute a diff of two sentence arrays via LCS.
 * Returns DiffSegments ordered as: shared/model_only interleaved in model order,
 * followed by user_only sentences not already matched.
 *
 * The output order for display is:
 *   - All model sentences annotated (shared=green, model_only=red)
 *   - User-only sentences (blue) appended after
 */
export function computeExplanationDiff(
  userSentences: string[],
  modelSentences: string[],
): DiffSegment[] {
  if (userSentences.length === 0 && modelSentences.length === 0) return []

  const dp = lcsTable(userSentences, modelSentences)

  // Backtrack to find which (i,j) pairs are in the LCS
  const sharedUserIdx = new Set<number>()
  const sharedModelIdx = new Set<number>()
  let i = userSentences.length
  let j = modelSentences.length
  while (i > 0 && j > 0) {
    if (userSentences[i - 1].toLowerCase() === modelSentences[j - 1].toLowerCase()) {
      sharedUserIdx.add(i - 1)
      sharedModelIdx.add(j - 1)
      i--
      j--
    } else if (dp[i - 1][j] >= dp[i][j - 1]) {
      i--
    } else {
      j--
    }
  }

  const segments: DiffSegment[] = []

  // Emit model sentences in order (shared=green, model_only=red)
  for (let mi = 0; mi < modelSentences.length; mi++) {
    segments.push({
      text: modelSentences[mi],
      kind: sharedModelIdx.has(mi) ? "shared" : "model_only",
    })
  }

  // Append user-only sentences (blue)
  for (let ui = 0; ui < userSentences.length; ui++) {
    if (!sharedUserIdx.has(ui)) {
      segments.push({
        text: userSentences[ui],
        kind: "user_only",
      })
    }
  }

  return segments
}
