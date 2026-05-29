// Luminary home hub -- coach shape (post-2E.7 redesign, polished pass).
//
// One fetch against /home/overview drives everything. Visual language:
// soft gradient page surface, a single filled hero, two lanes with
// distinct personalities (Continue = warm, Fading = muted), a backdropped
// tag cloud, color-anchored project cards, and a slim weekly-stats strip
// at the foot.

import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  BookOpen,
  Clock,
  FileText,
  FolderPlus,
  Hourglass,
  Pencil,
  RefreshCw,
  Sparkles,
  StickyNote,
  Tag,
  Zap,
} from "lucide-react"
import { Link, useNavigate } from "react-router-dom"

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { useAppStore } from "@/store"
import { cn } from "@/lib/utils"
import type { components } from "@/types/api"

type HomeOverview = components["schemas"]["HomeOverviewResponse"]
type ContinueReadingItem = components["schemas"]["ContinueReadingItem"]
type FadingItem = components["schemas"]["FadingItem"]
type ActiveCollection = components["schemas"]["ActiveCollection"] & {
  due_card_count?: number
}
type RecentTag = components["schemas"]["RecentTag"]
type TodayAction = components["schemas"]["TodayAction"] & {
  collection_id?: string | null
  collection_name?: string | null
  collection_color?: string | null
  scoped_count?: number | null
}
type WeeklyStats = components["schemas"]["WeeklyStats"]

const fetchHomeOverview = (): Promise<HomeOverview> =>
  apiGet<HomeOverview>("/home/overview")

export default function Hub() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["home-overview"],
    queryFn: fetchHomeOverview,
    staleTime: 30_000,
  })

  if (isLoading) return <HubLoading />
  if (isError || !data) return <HubError onRetry={() => void refetch()} />

  const isEmpty =
    !data.today_action &&
    data.recent_items.length === 0 &&
    data.active_collections.length === 0 &&
    data.recent_tags.length === 0 &&
    (data.continue_reading?.length ?? 0) === 0 &&
    (data.fading_items?.length ?? 0) === 0

  if (isEmpty) return <HubEmpty />

  return (
    <PageSurface>
      <HubHeader />

      {data.today_action && <TodayHero action={data.today_action} />}

      {((data.continue_reading?.length ?? 0) > 0 || (data.fading_items?.length ?? 0) > 0) && (
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            (data.fading_items?.length ?? 0) > 0 && "md:grid-cols-2",
          )}
        >
          <ContinueReadingCard items={data.continue_reading ?? []} />
          {(data.fading_items?.length ?? 0) > 0 && (
            <FadingCard items={data.fading_items ?? []} />
          )}
        </div>
      )}

      <DecayDebtWidget />

      {data.recent_tags.length > 0 && (
        <Section
          icon={Tag}
          title="What you've been into"
          subtitle="Threaded through your recent activity"
        >
          <TagCloud tags={data.recent_tags} />
        </Section>
      )}

      <Section
        icon={Sparkles}
        title="Your active projects"
        subtitle="Collections you've touched lately"
      >
        {data.active_collections.length === 0 ? (
          <OrganizeCallout />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.active_collections.slice(0, 4).map((c) => (
              <ActiveCollectionCard key={c.id} collection={c} />
            ))}
          </div>
        )}
      </Section>

      {data.weekly_stats && <WeeklyStatsStrip stats={data.weekly_stats} />}
    </PageSurface>
  )
}

// -- Layout primitives -------------------------------------------------------

function PageSurface({ children }: { children: React.ReactNode }) {
  // A soft top-to-bottom wash gives the page a sense of depth without
  // committing to a heavy gradient. Picked very low alphas so it reads
  // identically in light and dark modes.
  return (
    <div className="min-h-full bg-gradient-to-b from-primary/[0.04] via-background to-background">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-8 md:px-6">
        {children}
      </div>
    </div>
  )
}

function HubHeader() {
  const today = new Date()
  const dateLabel = today.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  })
  return (
    <header className="flex items-end justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/15">
          <LuminaryGlyph size={22} className="text-primary" />
        </span>
        <div className="flex flex-col">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {greeting()}
          </span>
          <h1 className="text-2xl font-semibold leading-tight text-foreground">
            Luminary
          </h1>
        </div>
      </div>
      <span className="hidden text-xs text-muted-foreground sm:inline">{dateLabel}</span>
    </header>
  )
}

function Section({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: typeof Sparkles
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Icon size={13} className="text-muted-foreground" />
        <h2 className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </h2>
        {subtitle && (
          <span className="text-xs text-muted-foreground/70">· {subtitle}</span>
        )}
      </div>
      {children}
    </section>
  )
}

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return "still up — be kind to yourself"
  if (h < 12) return "good morning"
  if (h < 17) return "afternoon"
  return "evening"
}

// -- Today hero --------------------------------------------------------------

function TodayHero({ action }: { action: TodayAction }) {
  const navigate = useNavigate()

  if (action.kind === "review_cards") {
    return <ReviewFocusHero action={action} />
  }

  const reason =
    action.kind === "continue_reading"
      ? "Pick up while the context is still warm — cold restarts cost more."
      : "A quick note while it's fresh tends to stick."
  const Icon = action.kind === "continue_reading" ? BookOpen : Pencil
  const onClick = () => {
    if (action.kind === "continue_reading" && action.target_id) {
      navigate(`/library?doc=${encodeURIComponent(action.target_id)}`, { state: { from: "/" } })
    } else {
      navigate("/notes", { state: { from: "/" } })
    }
  }
  return (
    <button
      onClick={onClick}
      className="group relative flex w-full cursor-pointer select-none flex-col gap-2 overflow-hidden rounded-2xl bg-gradient-to-br from-primary via-primary to-primary/75 px-6 py-5 text-left text-primary-foreground shadow-md shadow-primary/15 transition-all hover:shadow-lg hover:shadow-primary/20"
    >
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full bg-white/15 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -left-8 -bottom-12 h-32 w-32 rounded-full bg-white/10 blur-3xl" />
      <div className="relative z-10 flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
          <Icon size={14} />
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary-foreground/80">
          Today
        </span>
      </div>
      <div className="relative z-10 flex items-center justify-between gap-3 pt-0.5">
        <span className="truncate text-lg font-semibold sm:text-xl">{action.label}</span>
        <ArrowRight size={20} className="shrink-0 text-primary-foreground/85 transition-transform group-hover:translate-x-0.5" />
      </div>
      <p className="relative z-10 max-w-xl text-xs text-primary-foreground/75">{reason}</p>
    </button>
  )
}

const _SESSION_SIZE = 15

function ReviewFocusHero({ action }: { action: TodayAction }) {
  const navigate = useNavigate()
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const total = action.count ?? 0
  const scoped = action.scoped_count ?? 0
  const focusCount = scoped > 0 ? scoped : total
  const sessionSize = Math.min(_SESSION_SIZE, focusCount)
  const estimatedMin = Math.max(1, Math.round(sessionSize * 0.9))
  const overflow = total - focusCount

  return (
    <div className="group relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary via-primary to-primary/75 px-6 py-5 shadow-md shadow-primary/15">
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full bg-white/15 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -left-8 -bottom-12 h-32 w-32 rounded-full bg-white/10 blur-3xl" />

      <div className="relative z-10 flex flex-col gap-3">
        {/* label row */}
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
            <Zap size={14} />
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary-foreground/80">
            Today's focus
          </span>
        </div>

        {/* project name + due count */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            {action.collection_name ? (
              <>
                <div className="flex items-center gap-2">
                  {action.collection_color && (
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-white/30"
                      style={{ backgroundColor: action.collection_color }}
                    />
                  )}
                  <h2 className="text-xl font-bold tracking-tight text-primary-foreground sm:text-2xl">
                    {action.collection_name}
                  </h2>
                </div>
                <p className="text-sm text-primary-foreground/80">
                  {focusCount} card{focusCount !== 1 ? "s" : ""} due from this project
                </p>
              </>
            ) : (
              <>
                <h2 className="text-xl font-bold text-primary-foreground sm:text-2xl">
                  Your daily review
                </h2>
                <p className="text-sm text-primary-foreground/80">
                  {total} card{total !== 1 ? "s" : ""} ready to review
                </p>
              </>
            )}
          </div>
        </div>

        {/* CTA */}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            onClick={() => {
              setActiveDocument(null)
              setActiveCollectionId(action.collection_id ?? null)
              navigate("/study", { state: { from: "/" } })
            }}
            className="flex items-center gap-2 rounded-xl bg-white/20 px-4 py-2 text-sm font-semibold text-primary-foreground ring-1 ring-white/25 transition-all hover:bg-white/30"
          >
            Start {sessionSize}-card session
            <ArrowRight size={14} />
          </button>
          <span className="text-xs text-primary-foreground/70">
            ~{estimatedMin} min
          </span>
        </div>

        {/* overflow footnote */}
        {overflow > 0 && (
          <button
            onClick={() => {
              setActiveDocument(null)
              setActiveCollectionId(null)
              navigate("/study", { state: { from: "/" } })
            }}
            className="self-start text-xs text-primary-foreground/60 underline-offset-2 hover:text-primary-foreground/90 hover:underline"
          >
            +{overflow} more cards across your library
          </button>
        )}
      </div>
    </div>
  )
}

// -- Continue / Fading lanes -------------------------------------------------

function LaneShell({
  variant,
  icon: Icon,
  title,
  trailing,
  children,
}: {
  variant: "continue" | "fading"
  icon: typeof BookOpen
  title: string
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  const tone =
    variant === "continue"
      ? "border-primary/20 bg-primary/[0.03]"
      : "border-dashed border-muted-foreground/30 bg-muted/30"
  const iconTone =
    variant === "continue"
      ? "bg-primary/10 text-primary ring-primary/15"
      : "bg-muted-foreground/10 text-muted-foreground ring-muted-foreground/15"
  return (
    <div className={cn("flex flex-col gap-3 rounded-2xl border p-4 sm:p-5", tone)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex h-6 w-6 items-center justify-center rounded-full ring-1",
              iconTone,
            )}
          >
            <Icon size={12} />
          </span>
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-foreground/80">
            {title}
          </h2>
        </div>
        {trailing}
      </div>
      {children}
    </div>
  )
}

function ContinueReadingCard({ items }: { items: ContinueReadingItem[] }) {
  const navigate = useNavigate()
  return (
    <LaneShell
      variant="continue"
      icon={BookOpen}
      title="Pick up where you left off"
      trailing={
        items.length > 0 && (
          <Link to="/library" className="text-[11px] text-muted-foreground hover:text-foreground">
            All →
          </Link>
        )
      }
    >
      {items.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">
          Nothing in progress — open a doc and you'll see it here.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.document_id}>
              <button
                onClick={() =>
                  navigate(`/library?doc=${encodeURIComponent(item.document_id)}`, { state: { from: "/" } })
                }
                className="group/row flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-background"
              >
                <ProgressRing pct={item.reading_progress_pct * 100} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium text-foreground">
                    {item.title}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {Math.round(item.reading_progress_pct * 100)}% ·{" "}
                    {sinceLabel(item.last_meaningful_at)}
                  </span>
                </div>
                <ArrowRight
                  size={13}
                  className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100"
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </LaneShell>
  )
}

function FadingCard({ items }: { items: FadingItem[] }) {
  const navigate = useNavigate()
  return (
    <LaneShell variant="fading" icon={Hourglass} title="Worth a refresher?">
      {items.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">
          Nothing fading right now — you've been keeping up.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => {
            const Icon = item.member_type === "document" ? FileText : StickyNote
            const onClick = () => {
              if (item.member_type === "document") {
                navigate(`/library?doc=${encodeURIComponent(item.member_id)}`, { state: { from: "/" } })
              } else {
                navigate("/notes", { state: { from: "/" } })
              }
            }
            return (
              <li key={`${item.member_type}:${item.member_id}`}>
                <button
                  onClick={onClick}
                  className="group/row flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-background"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
                    <Icon size={12} className="text-muted-foreground" />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm text-foreground/90">{item.title}</span>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock size={9} />
                      {item.days_since} day{item.days_since === 1 ? "" : "s"} ago
                    </span>
                  </div>
                  <ArrowRight
                    size={13}
                    className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100"
                  />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </LaneShell>
  )
}

// -- Tag cloud ---------------------------------------------------------------

function TagCloud({ tags }: { tags: RecentTag[] }) {
  const maxTotal = Math.max(
    1,
    ...tags.map((t) => t.document_count + t.note_count),
  )
  const setActiveTag = useAppStore((s) => s.setActiveTag)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border/60 bg-card/40 px-5 py-4 backdrop-blur-sm">
      {tags.map((t) => {
        const total = t.document_count + t.note_count
        const weight = total / maxTotal
        const sizeClass =
          weight > 0.66
            ? "text-base font-medium"
            : weight > 0.33
              ? "text-sm"
              : "text-xs"
        return (
          <Link
            key={t.id}
            to={`/library?tag=${encodeURIComponent(t.id)}`}
            onClick={() => setActiveTag(t.id)}
            className={cn(
              "flex items-baseline gap-1.5 rounded-full px-3 py-1 text-foreground/80 transition-colors hover:bg-primary/10 hover:text-primary",
              sizeClass,
            )}
            title={`${t.document_count} documents · ${t.note_count} notes`}
          >
            <span className="text-muted-foreground/70">#</span>
            {t.display_name}
            <span className="text-[10px] text-muted-foreground">
              {t.document_count}/{t.note_count}
            </span>
          </Link>
        )
      })}
    </div>
  )
}

// -- Active collection card --------------------------------------------------

function ActiveCollectionCard({ collection }: { collection: ActiveCollection }) {
  // Use the collection's own color as the visual anchor so the click
  // through to /collections/:id feels like a thematic continuation, not a
  // surface break. A vertical color stripe + a faint tinted backdrop using
  // the same color keeps it consistent across both surfaces.
  return (
    <Link
      to={`/collections/${collection.id}`}
      className="group relative flex flex-col gap-3 overflow-hidden rounded-2xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md"
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1"
        style={{ backgroundColor: collection.color }}
      />
      <span
        aria-hidden
        className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full opacity-[0.07] blur-2xl transition-opacity group-hover:opacity-15"
        style={{ backgroundColor: collection.color }}
      />
      <div className="relative z-10 flex items-start gap-2">
        <span
          className="mt-1 h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: collection.color }}
        />
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {collection.name}
        </h3>
      </div>
      <div className="relative z-10 mt-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <StatPill label="d" value={collection.document_count} />
        <StatPill label="n" value={collection.note_count} />
        <StatPill label="c" value={collection.flashcard_count} />
      </div>
    </Link>
  )
}

function StatPill({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-baseline gap-0.5 rounded-md bg-muted/60 px-1.5 py-0.5">
      <span className="font-semibold text-foreground">{value}</span>
      <span className="text-muted-foreground/80">{label}</span>
    </span>
  )
}

// -- Weekly stats ------------------------------------------------------------

function WeeklyStatsStrip({ stats }: { stats: WeeklyStats }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-border/60 bg-card/40 px-5 py-3 text-sm backdrop-blur-sm">
      <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        <Clock size={11} />
        This week
      </span>
      <Stat label="studied" value={`${stats.minutes_studied}m`} accent="primary" />
      <Stat label="cards" value={stats.cards_reviewed} accent="amber" />
      <Stat label="notes" value={stats.notes_written} accent="emerald" />
      <Stat label="docs" value={stats.docs_touched} accent="blue" />
    </div>
  )
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string
  value: number | string
  accent: "primary" | "amber" | "emerald" | "blue"
}) {
  const dot = {
    primary: "bg-primary",
    amber: "bg-amber-500",
    emerald: "bg-emerald-500",
    blue: "bg-blue-500",
  }[accent]
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />
      <span className="text-base font-semibold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </span>
  )
}

// -- Helpers + auxiliary states ---------------------------------------------

function ProgressRing({ pct }: { pct: number }) {
  const size = 32
  const r = (size - 4) / 2
  const circ = 2 * Math.PI * r
  const dashOffset = circ - (Math.min(100, Math.max(0, pct)) / 100) * circ
  return (
    <svg width={size} height={size} className="shrink-0">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={2.5}
        className="stroke-muted"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="stroke-primary"
      />
    </svg>
  )
}

function sinceLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const days = Math.floor(ms / (1000 * 60 * 60 * 24))
  if (days === 0) return "today"
  if (days === 1) return "yesterday"
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  return `${weeks} week${weeks === 1 ? "" : "s"} ago`
}

function OrganizeCallout() {
  return (
    <Link
      to="/library"
      className="flex items-center gap-3 rounded-2xl border border-dashed border-border bg-card/60 px-4 py-3 text-sm text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
    >
      <FolderPlus size={16} className="shrink-0 text-primary" />
      <span className="flex-1">No active projects yet.</span>
      <span className="flex items-center gap-1 text-primary">
        Organize your library
        <ArrowRight size={12} />
      </span>
    </Link>
  )
}

function HubLoading() {
  return (
    <PageSurface>
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-xl" />
        <Skeleton className="h-7 w-40" />
      </div>
      <Skeleton className="h-28 w-full rounded-2xl" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-44 rounded-2xl" />
      </div>
      <Skeleton className="h-20 w-full rounded-2xl" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-2xl" />
        ))}
      </div>
    </PageSurface>
  )
}

interface DecayDebtItem {
  document_id: string
  document_title: string
  card_count: number
  avg_retention: number
  due_within_days: number
}

interface DecayDebtResponse {
  items: DecayDebtItem[]
  total_at_risk: number
}

function DecayDebtWidget() {
  const { data } = useQuery<DecayDebtResponse>({
    queryKey: ["study-decay-debt"],
    queryFn: () => apiGet<DecayDebtResponse>("/study/decay-debt", { limit: 3 }),
    staleTime: 60_000,
  })
  const navigate = useNavigate()
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)

  if (!data || data.items.length === 0) return null

  return (
    <Section
      icon={RefreshCw}
      title="Worth revisiting"
      subtitle={`${data.total_at_risk} card${data.total_at_risk !== 1 ? "s" : ""} approaching the forgetting threshold`}
    >
      <div className="flex flex-col gap-2">
        {data.items.map((item) => {
          const retPct = Math.round(item.avg_retention * 100)
          return (
            <button
              key={item.document_id}
              onClick={() => {
                setActiveCollectionId(null)
                setActiveDocument(item.document_id)
                navigate("/study", { state: { from: "/" } })
              }}
              className="flex items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3 text-left transition-colors hover:bg-accent/50"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <RefreshCw size={12} />
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                {item.document_title}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {item.card_count} card{item.card_count !== 1 ? "s" : ""}
              </span>
              <RetentionBar pct={retPct} />
            </button>
          )
        })}
        {data.total_at_risk > 3 && (
          <button
            onClick={() => navigate("/study", { state: { from: "/" } })}
            className="self-start pl-1 text-xs text-muted-foreground hover:text-foreground"
          >
            +{data.total_at_risk - 3} more in Study →
          </button>
        )}
      </div>
    </Section>
  )
}

function RetentionBar({ pct }: { pct: number }) {
  const barColor =
    pct === 0
      ? "bg-red-400 dark:bg-red-500"
      : pct < 50
        ? "bg-amber-400 dark:bg-amber-500"
        : "bg-emerald-400 dark:bg-emerald-500"
  return (
    <div className="flex shrink-0 flex-col items-end gap-0.5">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: pct === 0 ? "4%" : `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-muted-foreground">
        {pct === 0 ? "review now" : `${pct}% retained`}
      </span>
    </div>
  )
}

function HubError({ onRetry }: { onRetry: () => void }) {
  return (
    <PageSurface>
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
        Could not load your hub overview.
      </div>
      <button
        onClick={onRetry}
        className="self-start rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent"
      >
        Retry
      </button>
    </PageSurface>
  )
}

function HubEmpty() {
  return (
    <PageSurface>
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-4 rounded-2xl border border-border bg-card/60 px-6 py-12 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/15">
          <LuminaryGlyph size={28} className="text-primary" />
        </span>
        <h2 className="text-xl font-semibold text-foreground">Welcome to Luminary</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          Open a document or write a note to start. Your active projects,
          in-progress reads, and study cadence will surface here.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Link
            to="/library"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Go to Library
          </Link>
          <Link
            to="/notes"
            className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
          >
            Open Notes
          </Link>
        </div>
      </div>
    </PageSurface>
  )
}
