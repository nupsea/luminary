// Luminary home hub -- one reading column.
//
// One fetch against /home/overview drives everything. The page is read top to
// bottom once a day, so it is shaped like something read rather than a
// dashboard: a 780px measure, one card for the decision the page exists for
// ("where you left off": carry on, or sharpen), then rows, then the ambient
// shape of the week two-up at the foot.

import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  FileText,
  GraduationCap,
  Loader2,
  RefreshCw,
  StickyNote,
} from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

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
import { buildBars } from "./Hub/activityBars"
import { HubRow, HubSection, MiniRow, SectionLabel } from "./Hub/HubPrimitives"
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

  const resume = data.continue_reading?.[0] ?? null
  const remainingReads = (data.continue_reading ?? []).filter(
    (d) => d.document_id !== resume?.document_id,
  )
  const hasContinue =
    remainingReads.length > 0 ||
    (data.continue_notes?.length ?? 0) > 0 ||
    data.continue_study != null

  return (
    <PageSurface>
      <HubHeader />

      <WhereYouLeftOff resume={resume} action={data.today_action ?? null} />

      {(data.recommendations?.length ?? 0) > 0 && (
        <NextSection items={data.recommendations ?? []} />
      )}

      {hasContinue && (
        <ContinueSection
          docs={remainingReads}
          notes={data.continue_notes ?? []}
          study={data.continue_study ?? null}
        />
      )}

      <DecayDebtWidget />

      {/* Ambient context, two up. Everything above is something to do; this is
          the shape of the week behind it. */}
      <section className="grid grid-cols-1 gap-x-10 gap-y-8 sm:grid-cols-2">
        {data.weekly_stats && <ThisWeek stats={data.weekly_stats} />}
        <ActiveProjects collections={data.active_collections} />
        {(data.fading_items?.length ?? 0) > 0 && (
          <FadingBlock items={data.fading_items ?? []} />
        )}
        {data.recent_tags.length > 0 && <TopicsBlock tags={data.recent_tags} />}
      </section>
    </PageSurface>
  )
}

// Offset so the hub and the setup screen never show the same line on one day.
const HUB_QUOTE_OFFSET = 7

/** One reading column, centred, with air between sections.
 *
 *  The two-column dashboard it replaces put eight competing surfaces on one
 *  screen. A hub is read top to bottom once a day, so it is shaped like
 *  something read: a single measure, a generous rhythm, and one card.
 */
function PageSurface({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-full overflow-hidden bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-primary/[0.06] via-primary/[0.02] to-transparent"
      />
      <div className="relative mx-auto flex w-full max-w-[780px] flex-col gap-14 px-6 pb-28 pt-12 sm:pt-16">
        {children}
      </div>
    </div>
  )
}

function HubHeader() {
  const dateLabel = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  })
  const [quote] = useState(() => quoteOfTheDay(new Date(), HUB_QUOTE_OFFSET))

  return (
    <header className="flex flex-col gap-5">
      <div className="flex items-center gap-3.5">
        <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-xl bg-accent">
          <LuminaryGlyph size={20} className="text-foreground/75" />
        </span>
        <div className="flex flex-col gap-0.5">
          <h1 className="text-[30px] font-semibold leading-none tracking-[-0.02em] text-foreground">
            {greetingHeadline()}
          </h1>
          <span className="text-[13px] text-muted-foreground">{dateLabel}</span>
        </div>
      </div>
      {/* The quote is ambient: a rule, a serif line, an attribution. It used to
          be a full-width gradient block that pushed every action below the fold. */}
      <figure
        className="flex max-w-[620px] flex-col gap-2 border-l-2 border-border pl-[18px]"
        title={`${quote.text} — ${quote.author}, ${quote.source}`}
      >
        <blockquote className="font-serif text-[17px] leading-[1.55] text-foreground/[0.82]">
          &ldquo;{quote.text}&rdquo;
        </blockquote>
        <figcaption className="text-xs text-muted-foreground">{quote.author}</figcaption>
      </figure>
    </header>
  )
}

function greetingHeadline() {
  const h = new Date().getHours()
  if (h < 5) return "Still up?"
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}

const _SESSION_SIZE = 15

/**
 * The one card on the page: the document you were in, and the review waiting.
 *
 * Reading and recall were two separate heroes competing for the same glance.
 * They are one card now because they are one decision -- carry on, or sharpen
 * -- and the divider is what keeps them legible as two answers to it.
 */
function WhereYouLeftOff({
  resume,
  action,
}: {
  resume: ContinueReadingItem | null
  action: TodayAction | null
}) {
  const navigate = useNavigate()
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)

  const pct = resume ? Math.round(resume.reading_progress_pct * 100) : 0
  const timeLeft = resume ? readingTimeLabel(resume.word_count, resume.reading_progress_pct) : null

  const total = action?.count ?? 0
  const scoped = action?.scoped_count ?? 0
  const focusCount = scoped > 0 ? scoped : total
  const sessionSize = Math.min(_SESSION_SIZE, focusCount)
  const estimatedMin = Math.max(1, Math.round(sessionSize * 0.9))
  const overflow = total - focusCount

  const startSession = () => {
    markRecommendationActed(action?.recommendation_id)
    setActiveDocument(null)
    setActiveCollectionId(action?.collection_id ?? null)
    launchStudy(
      action?.collection_id
        ? {
            type: "collection",
            ref: action.collection_id,
            label: action.collection_name ?? "this collection",
          }
        : { type: "daily", label: "Today's pick" },
    )
  }

  return (
    <HubSection label="Where you left off" accent gap="gap-5">
      <div className="flex flex-col gap-6 rounded-3xl border border-border bg-card px-7 py-6 transition-colors hover:border-primary/35">
        {resume ? (
          <>
            <div className="flex items-start gap-4">
              <ProgressRing pct={pct} size={46} label={`${pct}%`} />
              <div className="flex min-w-0 flex-col gap-1.5">
                <h2
                  className="truncate text-[22px] font-semibold leading-tight tracking-[-0.015em] text-foreground"
                  title={resume.title}
                >
                  {humanizeTitle(resume.title)}
                </h2>
                <span className="text-[13px] text-muted-foreground">
                  {sinceLabel(resume.last_meaningful_at)}
                  {timeLeft && (
                    <span title="Estimated at 200 words a minute, from the share of sections still unread.">
                      {" · "}
                      {timeLeft}
                    </span>
                  )}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3.5">
              <button
                onClick={() =>
                  navigate(`/library?doc=${encodeURIComponent(resume.document_id)}`, {
                    state: { from: "/" },
                  })
                }
                className="flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 active:translate-y-px"
              >
                Dive back in
                <ArrowRight size={15} />
              </button>
              <span className="text-[13px] text-muted-foreground">
                or take a note while it&rsquo;s fresh
              </span>
            </div>
          </>
        ) : (
          <p className="text-[15px] text-muted-foreground">
            Nothing open. Add something to the library, or start a review below.
          </p>
        )}

        {action && total > 0 && (
          <>
            <div className="h-px bg-border" />
            <div className="flex flex-wrap items-center justify-between gap-3.5">
              <div className="flex min-w-0 items-center gap-2.5">
                {action.collection_color && (
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: action.collection_color }}
                    aria-hidden
                  />
                )}
                <span className="truncate text-sm font-medium text-foreground">
                  {action.collection_name ?? "Your daily review"}
                </span>
                <span className="shrink-0 text-[13px] text-muted-foreground">
                  · {focusCount} card{focusCount === 1 ? "" : "s"} due
                </span>
              </div>
              <button
                onClick={startSession}
                className="flex shrink-0 items-center gap-2 rounded-xl border border-border bg-transparent px-4 py-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-muted-foreground/40 hover:bg-accent active:translate-y-px"
              >
                Start {sessionSize}-card session
                <span className="font-normal text-muted-foreground">~{estimatedMin} min</span>
              </button>
            </div>
            {overflow > 0 && (
              <span className="text-xs text-muted-foreground/80">
                {total} cards due across your library
              </span>
            )}
          </>
        )}
      </div>
    </HubSection>
  )
}

const _REC_BADGE: Record<Recommendation["kind"], string> = {
  overdue_reviews: "!",
  weak_concept: "!",
  open_misconception: "!",
  calibration_blind_spot: "?",
  stalled_reading: "↩",
}

function NextSection({ items }: { items: Recommendation[] }) {
  const navigate = useNavigate()
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)

  const open = (rec: Recommendation) => {
    markRecommendationActed(rec.id)
    if (rec.target_type === "document" && rec.target_ref) {
      setActiveDocument(rec.target_ref)
      navigate(`/library?doc=${encodeURIComponent(rec.target_ref)}`, { state: { from: "/" } })
      return
    }
    if (rec.target_ref) {
      launchStudy({ type: "concept", ref: rec.target_ref, label: rec.label })
      return
    }
    navigate("/study", { state: { from: "/" } })
  }

  return (
    <HubSection label="Next" note="From your review record">
      <div className="flex flex-col gap-2">
        {items.map((rec) => (
          <HubRow
            key={rec.id}
            bordered
            badge={_REC_BADGE[rec.kind] ?? "•"}
            title={rec.label}
            meta={rec.reasons?.[0]?.detail ?? undefined}
            onClick={() => open(rec)}
          />
        ))}
      </div>
    </HubSection>
  )
}

function ContinueSection({
  docs,
  notes,
  study,
}: {
  docs: ContinueReadingItem[]
  notes: ContinueNoteItem[]
  study: ContinueStudyItem | null
}) {
  const navigate = useNavigate()
  const setNotesDocumentId = useAppStore((s) => s.setNotesDocumentId)

  return (
    <HubSection label="Continue">
      <div className="flex flex-col">
        {notes.map((n) => (
          <HubRow
            key={n.note_id}
            icon={StickyNote}
            title={n.title || "(untitled)"}
            meta={sinceLabel(n.last_meaningful_at)}
            trailing={<KindTag>Note</KindTag>}
            onClick={() => {
              setNotesDocumentId(null)
              navigate("/notes", { state: { from: "/", noteId: n.note_id } })
            }}
          />
        ))}
        {study && (
          <HubRow
            icon={GraduationCap}
            title={`${study.cards_remaining} card${study.cards_remaining === 1 ? "" : "s"} left in your session`}
            meta={sinceLabel(study.started_at)}
            trailing={<KindTag>Study</KindTag>}
            onClick={() => navigate("/study", { state: { from: "/" } })}
          />
        )}
        {docs.map((d) => (
          <HubRow
            key={d.document_id}
            icon={FileText}
            title={humanizeTitle(d.title)}
            meta={`${Math.round(d.reading_progress_pct * 100)}% · ${sinceLabel(d.last_meaningful_at)}`}
            trailing={<KindTag>Doc</KindTag>}
            onClick={() =>
              navigate(`/library?doc=${encodeURIComponent(d.document_id)}`, {
                state: { from: "/" },
              })
            }
          />
        ))}
      </div>
    </HubSection>
  )
}

function KindTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="shrink-0 text-[11px] uppercase tracking-[0.08em] text-muted-foreground/75">
      {children}
    </span>
  )
}

function ThisWeek({ stats }: { stats: WeeklyStats }) {
  const { bars, total } = buildBars(stats.seconds_by_activity ?? {})

  return (
    <div className="flex flex-col gap-3.5">
      <SectionLabel>This week</SectionLabel>
      <div className="flex flex-col gap-2.5">
        {bars.map((bar) => (
          <div key={bar.key} className="flex items-center gap-3">
            <span className="w-16 shrink-0 text-[13px] text-muted-foreground">{bar.label}</span>
            <span className="h-1 flex-1 overflow-hidden rounded-sm bg-muted">
              <span
                className="block h-full rounded-sm bg-primary/75"
                style={{ width: `${bar.pct}%` }}
              />
            </span>
            <span className="w-14 shrink-0 text-right text-xs tabular-nums text-foreground/80">
              {bar.seconds > 0 ? durationLabel(bar.seconds) : "—"}
            </span>
          </div>
        ))}
      </div>
      <span className="text-xs text-muted-foreground/80">
        {total > 0 ? `${durationLabel(total)} total` : "No time recorded yet"} ·{" "}
        {stats.notes_written} note{stats.notes_written === 1 ? "" : "s"} · {stats.docs_touched} docs
        touched
      </span>
    </div>
  )
}

function ActiveProjects({ collections }: { collections: ActiveCollection[] }) {
  const navigate = useNavigate()
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)

  return (
    <div className="flex flex-col gap-3.5">
      <SectionLabel>Active projects</SectionLabel>
      {collections.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Group documents into a project to track them together.
        </p>
      ) : (
        <div className="flex flex-col gap-0.5">
          {collections.slice(0, 5).map((c) => (
            <MiniRow
              key={c.id}
              label={c.name}
              dot={c.color}
              value={`${c.document_count}d · ${c.note_count}n · ${c.flashcard_count}c`}
              onClick={() => {
                setActiveCollectionId(c.id)
                navigate("/library", { state: { from: "/" } })
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function FadingBlock({ items }: { items: FadingItem[] }) {
  const navigate = useNavigate()
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)

  return (
    <div className="flex flex-col gap-3.5">
      <SectionLabel>Fading</SectionLabel>
      <div className="flex flex-col gap-0.5">
        {items.map((item) => (
          <MiniRow
            key={`${item.member_type}-${item.member_id}`}
            label={humanizeTitle(item.title)}
            value={`${item.days_since}d`}
            onClick={() => {
              if (item.member_type === "note") {
                navigate("/notes", { state: { from: "/", noteId: item.member_id } })
              } else {
                setActiveDocument(item.member_id)
                navigate(`/library?doc=${encodeURIComponent(item.member_id)}`, {
                  state: { from: "/" },
                })
              }
            }}
          />
        ))}
      </div>
    </div>
  )
}

function TopicsBlock({ tags }: { tags: RecentTag[] }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col gap-3.5">
      <SectionLabel>Topics</SectionLabel>
      <div className="flex flex-wrap gap-1.5">
        {tags.slice(0, 8).map((tag) => (
          <button
            key={tag.id}
            onClick={() =>
              navigate(`/library?tag=${encodeURIComponent(tag.id)}`, { state: { from: "/" } })
            }
            className="flex items-baseline gap-1.5 rounded-full bg-muted/60 px-3 py-1 text-[13px] text-foreground/80 transition-colors hover:bg-primary/10 hover:text-primary"
          >
            {tag.display_name}
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {tag.document_count + tag.note_count}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function ProgressRing({ pct, size = 32, label }: { pct: number; size?: number; label?: string }) {
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
      {label && (
        <text
          x={size / 2}
          y={size / 2 + 4}
          textAnchor="middle"
          className="fill-foreground text-[11px] font-semibold"
        >
          {label}
        </text>
      )}
    </svg>
  )
}

function durationLabel(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest}`
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

function HubLoading() {
  return (
    <PageSurface>
      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-3.5">
          <Skeleton className="h-[34px] w-[34px] rounded-xl" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-7 w-44" />
            <Skeleton className="h-3.5 w-32" />
          </div>
        </div>
        <Skeleton className="h-14 w-full max-w-[620px]" />
      </div>
      <Skeleton className="h-52 w-full rounded-3xl" />
      <div className="flex flex-col gap-2">
        <Skeleton className="h-16 rounded-2xl" />
        <Skeleton className="h-16 rounded-2xl" />
      </div>
      <div className="grid grid-cols-1 gap-x-10 gap-y-8 sm:grid-cols-2">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
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
    <HubSection
      label="Worth revisiting"
      note={`${data.total_at_risk} card${data.total_at_risk !== 1 ? "s" : ""} near the forgetting threshold`}
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
    </HubSection>
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
