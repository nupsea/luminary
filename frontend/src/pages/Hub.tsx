// Luminary home hub -- dashboard shape.
//
// One fetch against /home/overview drives everything. The quote takes the
// full-width gradient at the top; below it a two-column magazine layout splits
// "act now" (primary column: today's focus, recommendations, continue reading,
// decay debt) from ambient context (rail: stats, projects, fading, tags).

import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Clock,
  Compass,
  Crosshair,
  Dumbbell,
  FileText,
  GraduationCap,
  FolderPlus,
  Hourglass,
  Loader2,
  Pencil,
  Quote,
  RefreshCw,
  Sparkles,
  StickyNote,
  Tag,
  X,
  Zap,
} from "lucide-react"
import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import { FirstRunGuide } from "@/components/FirstRunGuide"
import { useStartupStatus } from "@/hooks/useSetup"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/apiClient"
import { launchStudy } from "@/lib/studyLauncher"
import { quoteOfTheDay } from "@/lib/quotes"
import { useAppStore } from "@/store"
import { cn } from "@/lib/utils"
import { humanizeTitle } from "@/lib/humanizeTitle"
import { readingTimeLabel } from "@/lib/readingTime"
import type { components } from "@/types/api"

type HomeOverview = components["schemas"]["HomeOverviewResponse"]
type ContinueReadingItem = components["schemas"]["ContinueReadingItem"]
type ContinueNoteItem = components["schemas"]["ContinueNoteItem"]
type ContinueStudyItem = components["schemas"]["ContinueStudyItem"]
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
type Recommendation = components["schemas"]["Recommendation"]

const fetchHomeOverview = (): Promise<HomeOverview> =>
  apiGet<HomeOverview>("/home/overview")

const markRecommendationActed = (id: string | null | undefined) => {
  if (!id) return
  void apiPost<void>(`/home/recommendations/${id}/acted`).catch(() => {})
}

export default function Hub() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["home-overview"],
    queryFn: fetchHomeOverview,
    staleTime: 30_000,
  })

  if (isLoading) return <HubLoading />
  if (isError || !data) return <HubError onRetry={() => void refetch()} />

  // recent_tags is deliberately not counted: the auto-tagger tags every
  // ingested document, so including it made this false forever and replaced the
  // first-run guide with a page of empty sections.
  const isEmpty =
    !data.today_action &&
    data.recent_items.length === 0 &&
    data.active_collections.length === 0 &&
    (data.continue_reading?.length ?? 0) === 0 &&
    (data.fading_items?.length ?? 0) === 0

  if (isEmpty) return <HubEmpty />

  const hasRecommendations = (data.recommendations?.length ?? 0) > 0
  // Promoted beside the hero, so the hub opens on a choice between flow and
  // recall rather than on recall alone.
  const resumeTarget = data.continue_reading?.[0] ?? null
  const remainingReads = (data.continue_reading ?? []).filter(
    (d) => d.document_id !== resumeTarget?.document_id,
  )
  // Counted after the promotion: a lane holding only the document already shown
  // above would render "nothing in progress" over a library in progress.
  const hasContinue =
    remainingReads.length > 0 ||
    (data.continue_notes?.length ?? 0) > 0 ||
    data.continue_study != null
  const hasFading = (data.fading_items?.length ?? 0) > 0

  return (
    <PageSurface>
      <HubHeader />

      <DailyQuote />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Primary column: things to act on now */}
        <div className="flex flex-col gap-6 lg:col-span-2">
          {data.today_action &&
            (resumeTarget ? (
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <ResumeFlowCard item={resumeTarget} />
                <TodayHero action={data.today_action} />
              </div>
            ) : (
              <TodayHero action={data.today_action} />
            ))}
          {hasRecommendations && <RecommendedNext items={data.recommendations ?? []} />}
          {hasContinue && (
            <ContinueReadingCard
              items={remainingReads}
              notes={data.continue_notes ?? []}
              study={data.continue_study ?? null}
            />
          )}
          <DecayDebtWidget />
        </div>

        {/* Rail: ambient context */}
        <aside className="flex flex-col gap-6">
          {data.weekly_stats && <WeekStatsCard stats={data.weekly_stats} />}

          <Section icon={Sparkles} title="Active projects">
            {data.active_collections.length === 0 ? (
              <OrganizeCallout />
            ) : (
              <div className="flex flex-col gap-3">
                {data.active_collections.slice(0, 5).map((c) => (
                  <ActiveCollectionCard key={c.id} collection={c} />
                ))}
              </div>
            )}
          </Section>

          {hasFading && <FadingCard items={data.fading_items ?? []} />}

          {data.recent_tags.length > 0 && (
            <Section icon={Tag} title="What you've been into">
              <TagCloud tags={data.recent_tags} />
            </Section>
          )}
        </aside>
      </div>
    </PageSurface>
  )
}

// Offset so the hub and the setup screen never show the same line on one day.
const HUB_QUOTE_OFFSET = 7

function DailyQuote() {
  const [quote] = useState(() => quoteOfTheDay(new Date(), HUB_QUOTE_OFFSET))

  // Set in the app's own typeface throughout. What makes it read as a quote is
  // the scale and the surface, not a second font family -- which would have to
  // survive macOS, Windows and Linux without a bundled file.
  return (
    <figure className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary via-primary to-primary/75 px-7 py-7 shadow-lg shadow-primary/20">
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/15 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -left-8 -bottom-12 h-36 w-36 rounded-full bg-white/10 blur-3xl" />

      <div className="relative z-10 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
            <Quote size={13} className="text-primary-foreground" />
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary-foreground/80">
            Thought for the day
          </span>
        </div>

        <blockquote className="max-w-3xl text-xl font-medium leading-snug tracking-[-0.015em] text-gray-200 sm:text-2xl">
          &ldquo;{quote.text}&rdquo;
        </blockquote>

        <figcaption className="text-xs text-primary-foreground/70">
          <span className="font-semibold text-primary-foreground/85">{quote.author}</span>
          <span> · {quote.source}</span>
        </figcaption>
      </div>
    </figure>
  )
}

// -- Layout primitives -------------------------------------------------------

function PageSurface({ children }: { children: React.ReactNode }) {
  // A single soft glow anchored to the top gives depth without a heavy wash;
  // low alphas read identically in light and dark.
  return (
    <div className="relative min-h-full overflow-hidden bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-primary/[0.07] via-primary/[0.02] to-transparent"
      />
      <div className="relative mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 md:px-6 lg:py-10">
        {children}
      </div>
    </div>
  )
}

function HubHeader() {
  const dateLabel = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  })
  return (
    <header className="flex items-center gap-4">
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/15">
        <LuminaryGlyph size={40} className="text-primary" />
      </span>
      <div className="flex flex-col">
        <h1 className="text-2xl font-semibold leading-tight text-foreground sm:text-3xl">
          {greetingHeadline()}
        </h1>
        <span className="text-sm text-muted-foreground">{dateLabel}</span>
      </div>
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

function greetingHeadline() {
  const h = new Date().getHours()
  if (h < 5) return "Still up?"
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}

// -- Today hero --------------------------------------------------------------

const _HERO_FALLBACK_REASON: Record<string, string> = {
  continue_reading: "Pick up while the context is still warm — cold restarts cost more.",
  resume_note: "A quick note while it's fresh tends to stick.",
  drill_concept: "A focused drill now beats relearning it later.",
  fix_misconception: "Correcting a wrong model pays more than new material.",
  confidence_check: "You felt sure and missed — worth a recalibration pass.",
}

const _HERO_ICON: Record<string, typeof BookOpen> = {
  continue_reading: BookOpen,
  resume_note: Pencil,
  drill_concept: Dumbbell,
  fix_misconception: AlertTriangle,
  confidence_check: Crosshair,
}

function TodayHero({ action }: { action: TodayAction }) {
  const navigate = useNavigate()

  if (action.kind === "review_cards") {
    return <ReviewFocusHero action={action} />
  }

  // the recommender's evidence line wins over generic copy (docs/recommender-spec.md)
  const reason =
    action.reasons?.[0]?.detail ?? _HERO_FALLBACK_REASON[action.kind] ?? ""
  const Icon = _HERO_ICON[action.kind] ?? BookOpen
  const onClick = () => {
    markRecommendationActed(action.recommendation_id)
    switch (action.kind) {
      case "continue_reading":
        if (action.target_id) {
          navigate(`/library?doc=${encodeURIComponent(action.target_id)}`, {
            state: { from: "/" },
          })
        } else {
          navigate("/library", { state: { from: "/" } })
        }
        break
      case "drill_concept":
      case "confidence_check":
        launchStudy({ type: "concept", ref: action.target_id ?? "", label: action.label })
        break
      case "fix_misconception":
        if (action.target_id) {
          launchStudy({ type: "concept", ref: action.target_id, label: action.label })
        } else if (action.document_id) {
          launchStudy({ type: "doc", ref: action.document_id, label: action.label })
        } else {
          launchStudy({ type: "daily", label: "Today's pick" })
        }
        break
      default:
        navigate("/notes", { state: { from: "/" } })
    }
  }
  return (
    <button
      onClick={onClick}
      className="group flex w-full cursor-pointer select-none flex-col gap-2 rounded-2xl border border-primary/15 bg-primary/[0.06] px-6 py-5 text-left transition-colors hover:bg-primary/[0.09]"
    >
      <div className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20">
          <Icon size={13} className="text-primary" />
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary">
          Today
        </span>
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-lg font-semibold text-foreground sm:text-xl">{action.label}</span>
        <ArrowRight size={20} className="shrink-0 text-primary transition-transform group-hover:translate-x-0.5" />
      </div>
      <p className="max-w-2xl text-sm text-muted-foreground">{reason}</p>
    </button>
  )
}


/** The other half of the choice the hub opens with.
 *
 *  The hero offers recall; this offers flow. Both were available and only one
 *  was prominent, so returning to a half-read document meant scrolling past the
 *  day's review to a list. Deliberately styled a step quieter than the hero:
 *  two equal-weight primary cards compete rather than offer.
 */
function ResumeFlowCard({ item }: { item: ContinueReadingItem }) {
  const navigate = useNavigate()
  const pct = Math.round(item.reading_progress_pct * 100)
  const timeLeft = readingTimeLabel(item.word_count, item.reading_progress_pct)

  return (
    <div className="group rounded-2xl border border-border/60 bg-card/50 px-6 py-5">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-foreground/5 ring-1 ring-border">
            <BookOpen size={13} className="text-foreground/70" />
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-foreground/60">
            Resume reading
          </span>
        </div>

        <div className="flex items-start gap-3">
          <ProgressRing pct={pct} />
          <div className="flex min-w-0 flex-col gap-0.5">
            <h2
              className="truncate text-lg font-bold tracking-tight text-foreground sm:text-xl"
              title={item.title}
            >
              {humanizeTitle(item.title)}
            </h2>
            <p className="text-sm text-muted-foreground">
              {pct}% read · {sinceLabel(item.last_meaningful_at)}
              {timeLeft && (
                <>
                  {" · "}
                  <span title="Estimated at 200 words a minute, from the share of sections still unread.">
                    {timeLeft}
                  </span>
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            onClick={() =>
              navigate(`/library?doc=${encodeURIComponent(item.document_id)}`, {
                state: { from: "/" },
              })
            }
            className="flex items-center gap-2 rounded-xl border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground shadow-sm transition-colors hover:bg-muted"
          >
            Dive back in
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
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
    <div className="group rounded-2xl border border-primary/15 bg-primary/[0.06] px-6 py-5">
      <div className="flex flex-col gap-3">
        {/* label row */}
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20">
            <Zap size={13} className="text-primary" />
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary">
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
                  <h2 className="text-lg font-bold tracking-tight text-foreground sm:text-xl">
                    {action.collection_name}
                  </h2>
                </div>
                <p className="text-sm text-muted-foreground">
                  {focusCount} card{focusCount !== 1 ? "s" : ""} due from this project
                </p>
              </>
            ) : (
              <>
                <h2 className="text-lg font-bold text-foreground sm:text-xl">
                  Your daily review
                </h2>
                <p className="text-sm text-muted-foreground">
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
              markRecommendationActed(action.recommendation_id)
              setActiveDocument(null)
              setActiveCollectionId(action.collection_id ?? null)
              // route the daily call through the Study Launcher (docs/study-launcher.md)
              launchStudy(
                action.collection_id
                  ? {
                      type: "collection",
                      ref: action.collection_id,
                      label: action.collection_name ?? "this collection",
                    }
                  : { type: "daily", label: "Today's pick" },
              )
            }}
            className="flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
          >
            Start {sessionSize}-card session
            <ArrowRight size={14} />
          </button>
          <span className="text-xs text-muted-foreground">
            ~{estimatedMin} min
          </span>
        </div>

        {action.reasons?.[0]?.detail && (
          <p className="text-xs text-muted-foreground">{action.reasons[0].detail}</p>
        )}

        {/* overflow footnote */}
        {overflow > 0 && (
          <button
            onClick={() => {
              setActiveDocument(null)
              setActiveCollectionId(null)
              navigate("/study", { state: { from: "/" } })
            }}
            className="self-start text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            +{overflow} more cards across your library
          </button>
        )}
      </div>
    </div>
  )
}

// -- Recommended next stack ---------------------------------------------------

const _REC_ICON: Record<Recommendation["kind"], typeof Zap> = {
  overdue_reviews: Zap,
  weak_concept: Dumbbell,
  open_misconception: AlertTriangle,
  calibration_blind_spot: Crosshair,
  stalled_reading: BookOpen,
}

function RecommendedNext({ items }: { items: Recommendation[] }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())

  const dismiss = (rec: Recommendation) => {
    // optimistic hide; restore on failure
    setHidden((prev) => new Set(prev).add(rec.id))
    void apiPost<void>(`/home/recommendations/${rec.id}/dismiss`)
      .then(() => queryClient.invalidateQueries({ queryKey: ["home-overview"] }))
      .catch(() => {
        setHidden((prev) => {
          const next = new Set(prev)
          next.delete(rec.id)
          return next
        })
      })
  }

  const open = (rec: Recommendation) => {
    markRecommendationActed(rec.id)
    switch (rec.kind) {
      case "overdue_reviews":
        launchStudy({ type: "daily", label: "Today's pick" })
        break
      case "weak_concept":
      case "calibration_blind_spot":
        launchStudy({ type: "concept", ref: rec.concept_slug ?? rec.target_ref, label: rec.label })
        break
      case "open_misconception":
        if (rec.concept_slug) {
          launchStudy({ type: "concept", ref: rec.concept_slug, label: rec.label })
        } else if (rec.document_id) {
          launchStudy({ type: "doc", ref: rec.document_id, label: rec.label })
        } else {
          launchStudy({ type: "daily", label: "Today's pick" })
        }
        break
      case "stalled_reading":
        navigate(`/library?doc=${encodeURIComponent(rec.document_id ?? rec.target_ref)}`, {
          state: { from: "/" },
        })
        break
    }
  }

  const visible = items.filter((r) => !hidden.has(r.id)).slice(0, 3)
  if (visible.length === 0) return null

  return (
    <Section
      icon={Compass}
      title="Recommended next"
      subtitle="Backed by your own review record"
    >
      <div className="flex flex-col gap-2.5">
        {visible.map((rec) => {
          const Icon = _REC_ICON[rec.kind]
          return (
            <div
              key={rec.id}
              className="group relative flex items-center gap-3.5 overflow-hidden rounded-2xl border border-border/60 bg-card px-4 py-3.5 transition-all hover:border-primary/30 hover:shadow-sm"
            >
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 w-1 bg-primary/40 opacity-0 transition-opacity group-hover:opacity-100"
              />
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15">
                <Icon size={15} />
              </span>
              <button
                onClick={() => open(rec)}
                className="flex min-w-0 flex-1 cursor-pointer flex-col text-left"
              >
                <span className="truncate text-sm font-medium text-foreground">{rec.label}</span>
                {rec.reasons[0]?.detail && (
                  <span className="truncate text-xs text-muted-foreground">
                    {rec.reasons[0].detail}
                  </span>
                )}
              </button>
              <ArrowRight
                size={14}
                className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-60"
              />
              <button
                onClick={() => dismiss(rec)}
                aria-label="Dismiss recommendation"
                title="Dismiss"
                className="shrink-0 rounded-full p-1.5 text-muted-foreground/50 opacity-0 transition-all hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
              >
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </Section>
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

// A labelled group inside the continue lane. Issue #51 sketches three of them --
// notes, docs and study -- under one heading rather than three separate cards.
function LaneGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="px-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  )
}

function ContinueNoteRows({ items }: { items: ContinueNoteItem[] }) {
  const navigate = useNavigate()
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) => (
        <li key={item.note_id}>
          <button
            onClick={() => navigate("/notes", { state: { from: "/" } })}
            className="group/row flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-background"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
              <StickyNote size={12} className="text-muted-foreground" />
            </span>
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-sm text-foreground/90" title={item.title}>
                {humanizeTitle(item.title)}
              </span>
              <span className="text-xs text-muted-foreground">
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
  )
}

function ContinueStudyRow({ item }: { item: ContinueStudyItem }) {
  const navigate = useNavigate()
  // Routed to the Study page rather than deep-linked into the session: Study
  // owns resume (it takes a resumeSessionId) but reads neither search params nor
  // route state, so a deep link would silently start a fresh session instead.
  return (
    <button
      onClick={() => navigate("/study", { state: { from: "/" } })}
      className="group/row flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-background"
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
        <GraduationCap size={12} className="text-muted-foreground" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm text-foreground/90">
          {item.cards_remaining} card{item.cards_remaining === 1 ? "" : "s"} left in your{" "}
          {item.mode} session
        </span>
        <span className="text-xs text-muted-foreground">{sinceLabel(item.started_at)}</span>
      </div>
      <ArrowRight
        size={13}
        className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100"
      />
    </button>
  )
}

function ContinueReadingCard({
  items,
  notes = [],
  study = null,
}: {
  items: ContinueReadingItem[]
  notes?: ContinueNoteItem[]
  study?: ContinueStudyItem | null
}) {
  const navigate = useNavigate()
  const isEmpty = items.length === 0 && notes.length === 0 && study === null
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
      {isEmpty ? (
        <p className="py-3 text-sm text-muted-foreground">
          Nothing in progress — open a doc and you'll see it here.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {notes.length > 0 && (
            <LaneGroup label="Notes">
              <ContinueNoteRows items={notes} />
            </LaneGroup>
          )}
          {study && (
            <LaneGroup label="Study">
              <ContinueStudyRow item={study} />
            </LaneGroup>
          )}
          {items.length > 0 && (
          <LaneGroup label="Docs">
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
                    {humanizeTitle(item.title)}
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
          </LaneGroup>
          )}
        </div>
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
                    <span className="truncate text-sm text-foreground/90" title={item.title}>
                      {humanizeTitle(item.title)}
                    </span>
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
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 rounded-2xl border border-border/60 bg-card/40 px-4 py-4 backdrop-blur-sm">
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
  // The collection's own color anchors the card so the click through to
  // /collections/:id feels like a thematic continuation, not a surface break.
  return (
    <Link
      to={`/collections/${collection.id}`}
      state={{ from: "/" }}
      className="group relative flex items-center gap-3 overflow-hidden rounded-2xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md"
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
      <span
        className="relative z-10 mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: collection.color }}
      />
      <h3 className="relative z-10 line-clamp-1 flex-1 text-sm font-semibold text-foreground">
        {collection.name}
      </h3>
      <div className="relative z-10 flex items-center gap-1.5 text-[11px] text-muted-foreground">
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

// The four slices the week splits into, with the colour each is drawn in.
const _ACTIVITY_SLICES: { key: string; label: string; colour: string }[] = [
  { key: "note", label: "Notes", colour: "hsl(160 60% 45%)" },
  { key: "document", label: "Docs", colour: "hsl(217 75% 58%)" },
  { key: "review", label: "Review", colour: "hsl(38 85% 55%)" },
  { key: "study", label: "Study", colour: "hsl(265 60% 60%)" },
]

function durationLabel(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} hr` : `${hours} hr, ${rest}min`
}

/**
 * Where the week's foreground time went.
 *
 * Drawn only from `seconds_by_activity`, which is one basis across all four
 * slices. `minutes_studied` beside it is study-session wall clock and is a
 * different measurement of a different thing; mixing them would make the
 * wedges add up to something that is not the total.
 */
function ActivitySplit({ byActivity }: { byActivity: Record<string, number> }) {
  const slices = _ACTIVITY_SLICES.map((s) => ({ ...s, seconds: byActivity[s.key] ?? 0 }))
  const total = slices.reduce((sum, s) => sum + s.seconds, 0)

  if (total === 0) {
    return (
      <div className="flex flex-col gap-1 border-t border-border/60 pt-3">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Time in Luminary
        </span>
        <span className="text-[11px] text-muted-foreground">
          Nothing recorded yet — this fills in as you read, write and review.
        </span>
      </div>
    )
  }

  // One ring, each wedge a dash on the circumference. An SVG arc needs no
  // charting dependency for four numbers. Offsets are accumulated up front
  // rather than during the map, so nothing is reassigned mid-render.
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const wedges = slices.reduce<{ slice: (typeof slices)[number]; dash: number; offset: number }[]>(
    (acc, slice) => {
      const dash = (slice.seconds / total) * circumference
      const offset = acc.length === 0 ? 0 : acc[acc.length - 1].offset + acc[acc.length - 1].dash
      acc.push({ slice, dash, offset })
      return acc
    },
    [],
  )

  return (
    <div className="flex flex-col gap-2 border-t border-border/60 pt-3">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Time in Luminary
      </span>
      <div className="flex items-center gap-4">
      <svg width="72" height="72" viewBox="0 0 72 72" className="shrink-0" role="img"
           aria-label={`Time this week: ${slices
             .filter((s) => s.seconds > 0)
             .map((s) => `${s.label} ${durationLabel(s.seconds)}`)
             .join(", ")}`}>
        <g transform="rotate(-90 36 36)">
          {wedges.map(({ slice, dash, offset }) => (
            <circle
              key={slice.key}
              cx="36"
              cy="36"
              r={radius}
              fill="none"
              stroke={slice.colour}
              strokeWidth="10"
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
            />
          ))}
        </g>
      </svg>
      <ul className="flex min-w-0 flex-1 flex-col gap-1">
        {slices.map((slice) => (
          <li key={slice.key} className="flex items-center gap-2 text-[11px]">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: slice.colour }}
            />
            <span className="flex-1 truncate text-muted-foreground">{slice.label}</span>
            <span className="tabular-nums text-foreground/90">
              {durationLabel(slice.seconds)}
            </span>
          </li>
        ))}
      </ul>
      </div>
    </div>
  )
}

function WeekStatsCard({ stats }: { stats: WeeklyStats }) {
  const byActivity = stats.seconds_by_activity ?? {}
  const total = Object.values(byActivity).reduce((sum, s) => sum + (s ?? 0), 0)
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border/60 bg-card/50 p-5 backdrop-blur-sm">
      <div className="flex items-center gap-2">
        <Clock size={13} className="text-muted-foreground" />
        <h2 className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          This week
        </h2>
        {total > 0 && (
          <span
            className="ml-auto text-[11px] tabular-nums text-muted-foreground"
            // Named for what it is. This is time with a surface open and
            // visible, sampled by heartbeat -- not a claim about attention.
            title="Time in Luminary: a surface open and visible. Sampled, not a measure of attention."
          >
            {durationLabel(total)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <BigStat value={`${stats.minutes_studied}m`} label="studied" accent="primary" />
        <BigStat value={stats.cards_reviewed} label="cards" accent="amber" />
        <BigStat value={stats.notes_written} label="notes" accent="emerald" />
        <BigStat value={stats.docs_touched} label="docs" accent="blue" />
      </div>
      <ActivitySplit byActivity={byActivity} />
    </div>
  )
}

function BigStat({
  value,
  label,
  accent,
}: {
  value: number | string
  label: string
  accent: "primary" | "amber" | "emerald" | "blue"
}) {
  const dot = {
    primary: "bg-primary",
    amber: "bg-amber-500",
    emerald: "bg-emerald-500",
    blue: "bg-blue-500",
  }[accent]
  return (
    <div className="flex flex-col gap-0.5 rounded-xl bg-muted/40 px-3 py-2.5">
      <div className="flex items-center gap-1.5">
        <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />
        <span className="text-xl font-semibold text-foreground">{value}</span>
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
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
        Organize
        <ArrowRight size={12} />
      </span>
    </Link>
  )
}

function HubLoading() {
  return (
    <PageSurface>
      <div className="flex items-center gap-4">
        <Skeleton className="h-14 w-14 rounded-2xl" />
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-4 w-32" />
        </div>
      </div>
      <Skeleton className="h-32 w-full rounded-3xl" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Skeleton className="h-40 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
        <div className="flex flex-col gap-6">
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-32 rounded-2xl" />
        </div>
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
  // A backend that is still starting looks identical to a failed request from
  // here, and on a cold install it is by far the likelier of the two. Ask what
  // startup actually says before calling it an error.
  const { data: startup } = useStartupStatus()
  const starting = startup !== undefined && !startup.usable

  if (starting) {
    return (
      <PageSurface>
        <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
          <Loader2 size={15} className="animate-spin" />
          Luminary is still starting up.
        </div>
      </PageSurface>
    )
  }

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
      <FirstRunGuide />
    </PageSurface>
  )
}
