import { useCallback, useEffect, useState } from "react"

/**
 * Reading preferences, remembered across reloads.
 *
 * The reading profile (see readingProfile.ts) picks defaults from what the
 * document is; these override them. Optimal reading conditions are personal --
 * measure, size and typeface all trade against each other differently per
 * reader and per screen -- so the profile is a starting point, never a verdict.
 *
 * "auto" and null mean "whatever the profile chose", so a preference left alone
 * keeps tracking the profile instead of freezing today's default in storage.
 */

export type FamilyPreference = "auto" | "serif" | "sans"
export type TintPreference = "auto" | "paper"

export interface ReaderPreferences {
  family: FamilyPreference
  /** Multiplier on the reading column's base font size. */
  fontScale: number
  lineHeight: number
  /** Characters per line, or null to keep the profile's measure. */
  measureCh: number | null
  tint: TintPreference
}

export const READER_PREF_LIMITS = {
  fontScale: { min: 0.85, max: 1.5, step: 0.05 },
  lineHeight: { min: 1.3, max: 2.1, step: 0.1 },
  // Below 45 characters the eye refixates too often; WCAG caps Latin text at 80.
  measureCh: { min: 45, max: 80, step: 1 },
} as const

export const DEFAULT_READER_PREFERENCES: ReaderPreferences = {
  family: "auto",
  fontScale: 1,
  lineHeight: 1.7,
  measureCh: null,
  tint: "auto",
}

const STORAGE_KEY = "luminary-reader-prefs"

function clamp(value: number, { min, max }: { min: number; max: number }): number {
  return Math.min(max, Math.max(min, value))
}

function read(): ReaderPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_READER_PREFERENCES
    const parsed = JSON.parse(raw) as Partial<ReaderPreferences>
    return {
      family:
        parsed.family === "serif" || parsed.family === "sans" ? parsed.family : "auto",
      fontScale:
        typeof parsed.fontScale === "number"
          ? clamp(parsed.fontScale, READER_PREF_LIMITS.fontScale)
          : DEFAULT_READER_PREFERENCES.fontScale,
      lineHeight:
        typeof parsed.lineHeight === "number"
          ? clamp(parsed.lineHeight, READER_PREF_LIMITS.lineHeight)
          : DEFAULT_READER_PREFERENCES.lineHeight,
      measureCh:
        typeof parsed.measureCh === "number"
          ? clamp(parsed.measureCh, READER_PREF_LIMITS.measureCh)
          : null,
      tint: parsed.tint === "paper" ? "paper" : "auto",
    }
  } catch {
    return DEFAULT_READER_PREFERENCES
  }
}

function write(prefs: ReaderPreferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
  } catch {
    // Private-browsing quota failures must not break reading.
  }
}

export function useReaderPreferences() {
  const [prefs, setPrefs] = useState<ReaderPreferences>(read)

  useEffect(() => {
    write(prefs)
  }, [prefs])

  const update = useCallback(<K extends keyof ReaderPreferences>(
    key: K,
    value: ReaderPreferences[K],
  ) => {
    setPrefs((prev) => ({ ...prev, [key]: value }))
  }, [])

  const reset = useCallback(() => setPrefs(DEFAULT_READER_PREFERENCES), [])

  return { prefs, update, reset }
}
