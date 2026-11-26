import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// Without this, tailwind-merge reads `text-ui` as a colour and drops it beside `text-ink-2`.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["eyebrow", "caption", "ui", "body", "title", "h3", "h2", "h1"] }],
      shadow: [{ shadow: ["overlay"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Strip markdown syntax from a string, returning readable plain text suitable
 * for single-line preview (e.g. table cells). Removes heading markers, bold,
 * italic emphasis markers, blockquote prefixes, and backtick fences.
 */
export function stripMarkdown(content: string): string {
  return content
    .replace(/^#{1,6}\s+/gm, "")      // heading markers: # ## ###
    .replace(/\*\*(.+?)\*\*/g, "$1")  // bold **text**
    .replace(/__(.+?)__/g, "$1")       // bold __text__
    .replace(/\*(.+?)\*/g, "$1")       // italic *text*
    .replace(/_(.+?)_/g, "$1")         // italic _text_
    .replace(/^>\s*/gm, "")            // blockquote >
    .replace(/`{1,3}[^`]*`{1,3}/g, "") // inline code and fenced code
    .replace(/\n+/g, " ")              // collapse newlines to space
    .trim()
}
