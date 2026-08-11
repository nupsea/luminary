/**
 * Highlight swatch classes shared by HighlightsPanel and DocumentReader. Kept
 * in its own module so the panel file exports only components (fast refresh).
 */

export const COLOR_CLASSES: Record<string, string> = {
  yellow: "bg-yellow-200 dark:bg-yellow-900/50",
  green: "bg-green-200 dark:bg-green-900/50",
  blue: "bg-blue-200 dark:bg-blue-900/50",
  pink: "bg-pink-200 dark:bg-pink-900/50",
}
