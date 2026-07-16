// Theme persistence. The pre-paint script in index.html applies the stored choice
// before React mounts (so there's no flash); this module is the runtime source of
// truth once the app is interactive. Stored value is "light" | "dark" | "system";
// "system" (the default) follows the OS preference.

export type Theme = "light" | "dark" | "system"

const STORAGE_KEY = "luminary-theme"

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

export function getTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === "light" || stored === "dark" || stored === "system") return stored
  return "system"
}

// The effective light/dark currently in force, resolving "system".
export function isDark(): boolean {
  const t = getTheme()
  return t === "dark" || (t === "system" && prefersDark())
}

function apply(dark: boolean): void {
  document.documentElement.classList.toggle("dark", dark)
  // Canvas-based surfaces (Sigma graph) can't use CSS dark: variants; they
  // listen for this event to recolor at runtime.
  window.dispatchEvent(new CustomEvent("luminary:theme", { detail: { dark } }))
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(STORAGE_KEY, theme)
  apply(theme === "dark" || (theme === "system" && prefersDark()))
}

// Flip between explicit light and dark (used by the nav-rail shortcut).
export function toggleTheme(): void {
  setTheme(isDark() ? "light" : "dark")
}
