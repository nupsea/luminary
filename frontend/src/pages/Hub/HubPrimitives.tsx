import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * The hub's section label: 10px, uppercase, widely tracked.
 *
 * One label style for every section is what lets the page be scanned in a
 * single pass. `accent` marks the one section the page is actually for; the
 * rest recede.
 */
export function SectionLabel({
  children,
  accent = false,
  note,
}: {
  children: React.ReactNode
  accent?: boolean
  note?: string
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-2.5">
      <span
        className={cn(
          "text-[10px] font-bold uppercase leading-none tracking-[0.15em]",
          accent ? "text-primary" : "text-muted-foreground/70",
        )}
      >
        {children}
      </span>
      {note && <span className="text-xs text-muted-foreground/80">{note}</span>}
    </div>
  )
}

/** A section: its label, then its content, at the page's own rhythm. */
export function HubSection({
  label,
  note,
  accent = false,
  gap = "gap-3.5",
  children,
}: {
  label: string
  note?: string
  accent?: boolean
  gap?: string
  children: React.ReactNode
}) {
  return (
    <section className={cn("flex flex-col", gap)}>
      <SectionLabel accent={accent} note={note}>
        {label}
      </SectionLabel>
      {children}
    </section>
  )
}

/**
 * A flat row: an icon, a title over a meta line, and an optional trailing note.
 *
 * Rows rather than cards below the fold. A page of bordered boxes reads as a
 * dashboard competing for attention; the one card on this page is the thing it
 * wants you to do.
 */
export function HubRow({
  icon: Icon,
  badge,
  title,
  meta,
  trailing,
  onClick,
  bordered = false,
}: {
  icon?: LucideIcon
  badge?: string
  title: string
  meta?: string
  trailing?: React.ReactNode
  onClick: () => void
  bordered?: boolean
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        "group flex w-full items-center gap-3.5 text-left transition-colors",
        bordered
          ? "rounded-2xl border border-border bg-card px-4 py-4 hover:border-muted-foreground/35 hover:bg-accent/50"
          : "-mx-3.5 rounded-xl px-3.5 py-3 hover:bg-accent/55",
      )}
    >
      {(Icon || badge) && (
        <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[10px] bg-muted text-[11px] font-semibold text-muted-foreground">
          {badge ?? (Icon ? <Icon size={14} strokeWidth={1.5} /> : null)}
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-medium text-foreground">{title}</span>
        {meta && <span className="truncate text-xs text-muted-foreground">{meta}</span>}
      </span>
      {trailing}
    </button>
  )
}

/** A compact list row for the two-column footer blocks. */
export function MiniRow({
  label,
  value,
  dot,
  onClick,
}: {
  label: string
  value: string
  dot?: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className="-mx-2.5 flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left transition-colors hover:bg-accent/55"
    >
      {dot && (
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dot }}
          aria-hidden
        />
      )}
      <span className="min-w-0 flex-1 truncate text-[13px] text-foreground/85">{label}</span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{value}</span>
    </button>
  )
}
