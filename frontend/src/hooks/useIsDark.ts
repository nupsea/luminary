// Reactive effective-theme hook for canvas renderers that can't use CSS
// dark: variants. Tracks the "luminary:theme" event fired by lib/theme.

import { useEffect, useState } from "react"

import { isDark } from "@/lib/theme"

export function useIsDark(): boolean {
  const [dark, setDark] = useState(isDark)
  useEffect(() => {
    const onTheme = (e: Event) => setDark((e as CustomEvent<{ dark: boolean }>).detail.dark)
    window.addEventListener("luminary:theme", onTheme)
    return () => window.removeEventListener("luminary:theme", onTheme)
  }, [])
  return dark
}
