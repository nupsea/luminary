/**
 * Predict-panel helpers shared with SectionListItem. Kept in its own module so
 * PredictPanel.tsx exports only components (fast refresh).
 */

/** Section preview contains a fenced code block (newline-delimited ``` fence). */
export function hasCodeFence(preview: string): boolean {
  return /^```\w*/m.test(preview) && preview.includes("\n")
}
