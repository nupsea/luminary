import { RotateCcw, Type, X } from "lucide-react"
import { useEffect, useRef } from "react"

import { cn } from "@/lib/utils"

import type { ReadingProfile } from "./readingProfile"
import {
  READER_PREF_LIMITS,
  type FamilyPreference,
  type ReaderPreferences,
  type TintPreference,
} from "./useReaderPreferences"

const PROFILE_LABEL: Record<ReadingProfile, string> = {
  prose: "Prose",
  article: "Article",
  paper: "Paper",
  technical: "Technical",
  dialogue: "Dialogue",
  script: "Script",
  reference: "Reference",
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      {children}
    </div>
  )
}

function Choice<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex rounded-md border border-border p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex-1 rounded px-2 py-1 text-xs transition-colors",
            value === opt.value
              ? "bg-primary/10 font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function Slider({
  value,
  min,
  max,
  step,
  display,
  onChange,
}: {
  value: number
  min: number
  max: number
  step: number
  display: string
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-primary"
      />
      <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {display}
      </span>
    </div>
  )
}

interface ReaderSettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  profile: ReadingProfile
  /** The measure in force, so "Auto" can show what it resolved to. */
  effectiveMeasureCh: number
  prefs: ReaderPreferences
  onUpdate: <K extends keyof ReaderPreferences>(key: K, value: ReaderPreferences[K]) => void
  onReset: () => void
}

export function ReaderSettings({
  open,
  onOpenChange,
  profile,
  effectiveMeasureCh,
  prefs,
  onUpdate,
  onReset,
}: ReaderSettingsProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      const target = e.target as Node
      if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) return
      onOpenChange(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("pointerdown", onPointerDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("pointerdown", onPointerDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [open, onOpenChange])

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => onOpenChange(!open)}
        aria-label="Reading settings"
        aria-expanded={open}
        title="Reading settings"
        className={cn(
          "flex items-center gap-1 rounded-md border border-border bg-background/80 px-2 py-1 text-xs backdrop-blur transition-colors",
          open ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        )}
      >
        <Type size={13} />
      </button>

      {open && (
        <div
          ref={panelRef}
          className="absolute right-0 top-full z-50 mt-1 w-72 space-y-4 rounded-lg border border-border bg-background p-3 shadow-xl"
        >
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-foreground">
              Reading
              <span className="ml-1.5 font-normal text-muted-foreground">
                {PROFILE_LABEL[profile]}
              </span>
            </p>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={onReset}
                title="Reset to this document's defaults"
                className="text-muted-foreground hover:text-foreground"
              >
                <RotateCcw size={13} />
              </button>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label="Close reading settings"
                className="text-muted-foreground hover:text-foreground"
              >
                <X size={13} />
              </button>
            </div>
          </div>

          <Row label="Typeface">
            <Choice<FamilyPreference>
              value={prefs.family}
              onChange={(v) => onUpdate("family", v)}
              options={[
                { value: "auto", label: "Auto" },
                { value: "serif", label: "Serif" },
                { value: "sans", label: "Sans" },
              ]}
            />
          </Row>

          <Row label="Text size">
            <Slider
              value={prefs.fontScale}
              {...READER_PREF_LIMITS.fontScale}
              display={`${Math.round(prefs.fontScale * 100)}%`}
              onChange={(v) => onUpdate("fontScale", v)}
            />
          </Row>

          <Row label="Line spacing">
            <Slider
              value={prefs.lineHeight}
              {...READER_PREF_LIMITS.lineHeight}
              display={prefs.lineHeight.toFixed(1)}
              onChange={(v) => onUpdate("lineHeight", v)}
            />
          </Row>

          <Row label="Line width">
            <Slider
              value={prefs.measureCh ?? effectiveMeasureCh}
              {...READER_PREF_LIMITS.measureCh}
              display={
                prefs.measureCh === null ? `${effectiveMeasureCh}` : `${prefs.measureCh}`
              }
              onChange={(v) => onUpdate("measureCh", v)}
            />
            <p className="text-[11px] text-muted-foreground">
              {prefs.measureCh === null ? (
                `Auto — ${effectiveMeasureCh} characters per line`
              ) : (
                <button
                  type="button"
                  onClick={() => onUpdate("measureCh", null)}
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  Back to auto
                </button>
              )}
            </p>
          </Row>

          <Row label="Background">
            <Choice<TintPreference>
              value={prefs.tint}
              onChange={(v) => onUpdate("tint", v)}
              options={[
                { value: "auto", label: "Default" },
                { value: "paper", label: "Paper" },
              ]}
            />
          </Row>
        </div>
      )}
    </div>
  )
}
