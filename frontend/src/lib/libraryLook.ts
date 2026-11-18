// How a library looks in the app: its title, initials and colour, and the id a new one gets.

import type { components } from "@/types/api"

type LibraryItem = components["schemas"]["LibraryItem"]
export type LibraryColor = NonNullable<LibraryItem["color"]>

// Literal class names: Tailwind keeps only the classes it finds written out in the source.
export const LIBRARY_COLORS: Record<LibraryColor, { swatch: string; tile: string }> = {
  slate: { swatch: "bg-slate-500", tile: "bg-slate-500 text-white" },
  blue: { swatch: "bg-blue-500", tile: "bg-blue-500 text-white" },
  green: { swatch: "bg-green-600", tile: "bg-green-600 text-white" },
  amber: { swatch: "bg-amber-500", tile: "bg-amber-500 text-white" },
  rose: { swatch: "bg-rose-500", tile: "bg-rose-500 text-white" },
  violet: { swatch: "bg-violet-500", tile: "bg-violet-500 text-white" },
  teal: { swatch: "bg-teal-600", tile: "bg-teal-600 text-white" },
  orange: { swatch: "bg-orange-500", tile: "bg-orange-500 text-white" },
}
export const COLOR_IDS = Object.keys(LIBRARY_COLORS) as LibraryColor[]

/** What a library is called: its name, else its id as a word. */
export function libraryTitle(item: Pick<LibraryItem, "id" | "name">): string {
  if (item.name) return item.name
  return item.id.charAt(0).toUpperCase() + item.id.slice(1).replace(/[-_]+/g, " ")
}

/** One or two letters for a library's tile. */
export function libraryInitials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return "?"
  const letters = words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0]
  return words.length === 1 ? letters.charAt(0).toUpperCase() + letters.slice(1).toLowerCase() : letters.toUpperCase()
}

/** A colour for a library that has none set: stable for its id, so it never changes. */
export function libraryColor(item: Pick<LibraryItem, "id" | "color">): LibraryColor {
  if (item.color) return item.color
  let hash = 0
  for (const ch of item.id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return COLOR_IDS[hash % COLOR_IDS.length]
}

/** The id a library named *name* gets: lower-case, path-safe and not one already *taken*. */
export function libraryIdFor(name: string, taken: Iterable<string>): string {
  const used = new Set(taken)
  const base =
    name
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 56) || "library"
  if (!used.has(base)) return base
  for (let n = 2; ; n++) {
    if (!used.has(`${base}-${n}`)) return `${base}-${n}`
  }
}

/** "2 hours ago", for when an archive was written. */
export function ago(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? "" : "s"} ago`
}
