import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, BookOpen, FileText, Layers, LayoutGrid, StickyNote, Zap } from "lucide-react"
import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { Skeleton } from "@/components/ui/skeleton"
import { CollectionStudyDashboard } from "@/components/study/CollectionStudyDashboard"
import { apiGet } from "@/lib/apiClient"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"
import { relativeDate } from "@/components/library/utils"
import type { components } from "@/types/api"

// Helper: build a low-alpha hex from a collection color so we can layer
// soft tints over both light and dark themes without needing color math.
function withAlpha(hex: string | undefined, alpha: number): string {
  if (!hex) return `rgba(99, 102, 241, ${alpha})` // primary fallback
  const clean = hex.replace("#", "")
  const r = parseInt(clean.slice(0, 2), 16)
  const g = parseInt(clean.slice(2, 4), 16)
  const b = parseInt(clean.slice(4, 6), 16)
  if ([r, g, b].some(Number.isNaN)) return `rgba(99, 102, 241, ${alpha})`
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// Two in-workspace tabs (switch in place) plus three navigate-through tabs
// that hop to the canonical surface filtered to this collection. The
// navigate-throughs were previously inline tab views; user feedback was
// that the stripped per-content views with an "Open in Notes →" button
// felt like dead intermediates, so the click *is* the open now.
type InlineTab = "overview" | "study"
type NavTarget = "documents" | "notes" | "flashcards"
type TabId = InlineTab | NavTarget

type CollectionOverview = components["schemas"]["CollectionOverviewResponse"]

interface CollectionSummary {
  id: string
  name: string
  color: string
}

const INLINE_TABS: { id: InlineTab; label: string; icon: typeof BookOpen }[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "study", label: "Study", icon: Zap },
]

const NAV_TABS: { id: NavTarget; label: string; icon: typeof BookOpen }[] = [
  { id: "documents", label: "Documents", icon: BookOpen },
  { id: "notes", label: "Notes", icon: StickyNote },
  { id: "flashcards", label: "Flashcards", icon: Layers },
]

export default function CollectionWorkspace() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const [tab, setTab] = useState<InlineTab>("overview")

  function navigateTo(target: NavTarget) {
    // All three destinations read activeCollectionId on mount; Library
    // does so via the Learning page's useEffect that seeds + clears.
    setActiveCollectionId(collectionId)
    if (target === "documents") navigate("/library")
    else if (target === "notes") navigate("/notes")
    else navigate("/study")
  }

  function handleTabClick(tabId: TabId) {
    if (tabId === "overview" || tabId === "study") setTab(tabId)
    else navigateTo(tabId)
  }

  const collectionId = id ?? ""

  const { data: meta, isLoading: metaLoading } = useQuery({
    queryKey: ["collection-meta", collectionId],
    queryFn: () => apiGet<CollectionSummary>(`/collections/${collectionId}`),
    enabled: Boolean(collectionId),
  })

  if (!collectionId) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Collection not specified.</div>
    )
  }

  function handleStartStudy() {
    setActiveCollectionId(collectionId)
    navigate("/study")
  }

  const accentColor = meta?.color
  const accentUnderline = accentColor ?? "rgb(99, 102, 241)"

  return (
    <div className="flex h-full flex-col">
      {/* Banner header. The collection's own color anchors the surface so
          the click from a hub project card feels like a thematic
          continuation, not a UI break. Two ambient orbs and a soft gradient
          give the banner depth without committing to a fixed image. */}
      <header
        className="relative overflow-hidden border-b border-border"
        style={{
          backgroundImage: accentColor
            ? `linear-gradient(135deg, ${withAlpha(accentColor, 0.18)} 0%, ${withAlpha(accentColor, 0.06)} 60%, transparent 100%)`
            : undefined,
        }}
      >
        <span
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full opacity-30 blur-3xl"
          style={{ backgroundColor: withAlpha(accentColor, 0.35) }}
        />
        <span
          aria-hidden
          className="pointer-events-none absolute -left-10 -bottom-20 h-40 w-40 rounded-full opacity-20 blur-3xl"
          style={{ backgroundColor: withAlpha(accentColor, 0.3) }}
        />
        <div className="relative z-10 flex flex-col gap-3 px-6 py-5 md:px-8">
          <button
            onClick={() => navigate(-1)}
            className="flex w-fit items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft size={12} />
            Back
          </button>
          <div className="flex items-center gap-3 min-w-0">
            {meta && (
              <span
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-2 ring-background"
                style={{ backgroundColor: meta.color }}
              >
                <LayoutGrid size={16} className="text-white drop-shadow-sm" />
              </span>
            )}
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                Collection
              </span>
              {metaLoading ? (
                <Skeleton className="h-7 w-48" />
              ) : (
                <h1 className="truncate text-2xl font-semibold leading-tight text-foreground">
                  {meta?.name ?? "Collection"}
                </h1>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Tab nav. Active in-place tabs adopt the collection color as the
          underline so the surface continues to feel themed. The nav-through
          tabs sit visually distinct with arrows + dashed-divider separator. */}
      <nav className="flex items-center gap-1 border-b border-border bg-card/30 px-6 md:px-8">
        {INLINE_TABS.map(({ id: tabId, label, icon: Icon }) => {
          const active = tab === tabId
          return (
            <button
              key={tabId}
              onClick={() => handleTabClick(tabId)}
              className={cn(
                "flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors",
                active
                  ? "font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              style={
                active
                  ? { borderColor: accentUnderline }
                  : undefined
              }
            >
              <Icon size={14} />
              {label}
            </button>
          )
        })}
        <span className="mx-1 h-4 w-px bg-border" aria-hidden />
        {NAV_TABS.map(({ id: tabId, label, icon: Icon }) => (
          <button
            key={tabId}
            onClick={() => handleTabClick(tabId)}
            className="flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            title={`Open ${label} filtered to this collection`}
          >
            <Icon size={14} />
            {label}
            <ArrowRight size={11} className="opacity-60" />
          </button>
        ))}
      </nav>

      <div
        className="flex-1 overflow-auto"
        style={
          accentColor
            ? {
                backgroundImage: `linear-gradient(to bottom, ${withAlpha(accentColor, 0.04)} 0%, transparent 280px)`,
              }
            : undefined
        }
      >
        {tab === "overview" && (
          <OverviewTab
            collectionId={collectionId}
            accentColor={accentColor}
            onContinueStudy={() => setTab("study")}
            onOpenDocument={(docId) => {
              setActiveDocument(docId)
              setActiveCollectionId(collectionId)
              navigate("/library")
            }}
            onOpenNotes={() => {
              setActiveCollectionId(collectionId)
              navigate("/notes")
            }}
          />
        )}
        {tab === "study" && (
          <CollectionStudyDashboard
            collectionId={collectionId}
            onBack={() => navigate(-1)}
            onStartStudy={handleStartStudy}
            onStartTeachback={handleStartStudy}
            onNavigateToCollection={(cid) => navigate(`/collections/${cid}`)}
          />
        )}
      </div>
    </div>
  )
}

function OverviewTab({
  collectionId,
  accentColor,
  onContinueStudy,
  onOpenDocument,
  onOpenNotes,
}: {
  collectionId: string
  accentColor: string | undefined
  onContinueStudy: () => void
  onOpenDocument: (id: string) => void
  onOpenNotes: () => void
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["collection-overview", collectionId],
    queryFn: () => apiGet<CollectionOverview>(`/collections/${collectionId}/overview`),
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6 md:px-8">
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
        <Skeleton className="h-20 w-full rounded-2xl" />
      </div>
    )
  }
  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 py-6 md:px-8">
        <p className="text-sm text-amber-700">Could not load this collection's overview.</p>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6 md:px-8">
      {/* Stat hero: three large stats with the Continue-studying CTA placed
          where the eye lands. Uses the collection color as a soft tint so
          the surface reads as themed without overwhelming the data. */}
      <StatHero
        data={data}
        accentColor={accentColor}
        onContinueStudy={onContinueStudy}
      />

      <section className="flex flex-col gap-3">
        <SectionLabel>Recently touched</SectionLabel>
        {data.recent_items.length === 0 ? (
          <EmptyRow>Nothing touched in this collection yet.</EmptyRow>
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-2xl border border-border bg-card overflow-hidden">
            {data.recent_items.map((item) => {
              const Icon = item.member_type === "document" ? FileText : StickyNote
              const onClick = () => {
                if (item.member_type === "document") onOpenDocument(item.member_id)
                else onOpenNotes()
              }
              return (
                <li key={`${item.member_type}:${item.member_id}`}>
                  <button
                    onClick={onClick}
                    className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/60"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted/60">
                      <Icon size={13} className="text-muted-foreground" />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm font-medium text-foreground">
                        {item.title}
                      </span>
                      {item.preview && (
                        <span className="truncate text-xs text-muted-foreground">
                          {item.preview}
                        </span>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {relativeDate(item.last_meaningful_at)}
                    </span>
                    <ArrowRight
                      size={13}
                      className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                    />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <SectionLabel>Tags in this collection</SectionLabel>
        {data.tags.length === 0 ? (
          <EmptyRow>No tags yet on members of this collection.</EmptyRow>
        ) : (
          <div className="flex flex-wrap gap-2 rounded-2xl border border-border/60 bg-card/40 p-4">
            {data.tags.map((t) => (
              <span
                key={t.id}
                className="flex items-center gap-1.5 rounded-full border border-border bg-background px-3 py-1 text-xs text-foreground/80"
                title={`Used by ${t.count} member${t.count === 1 ? "" : "s"}`}
              >
                <span className="text-muted-foreground/70">#</span>
                <span className="truncate max-w-[12rem]">{t.display_name}</span>
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {t.count}
                </span>
              </span>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function StatHero({
  data,
  accentColor,
  onContinueStudy,
}: {
  data: CollectionOverview
  accentColor: string | undefined
  onContinueStudy: () => void
}) {
  const tintBg = accentColor ? withAlpha(accentColor, 0.07) : undefined
  const tintBorder = accentColor ? withAlpha(accentColor, 0.2) : undefined
  return (
    <div
      className="relative overflow-hidden rounded-2xl border bg-card p-5 sm:p-6"
      style={{
        backgroundColor: tintBg,
        borderColor: tintBorder,
      }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full opacity-30 blur-3xl"
        style={{ backgroundColor: withAlpha(accentColor, 0.25) }}
      />
      <div className="relative z-10 flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-end gap-6">
          <BigStat label="documents" value={data.document_count} />
          <BigStat label="notes" value={data.note_count} />
          <BigStat label="flashcards" value={data.flashcard_count} />
        </div>
        {data.flashcard_count > 0 && (
          <button
            onClick={onContinueStudy}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-all hover:bg-primary/90 hover:shadow-md"
          >
            <Zap size={13} />
            Continue studying
            <ArrowRight size={13} />
          </button>
        )}
      </div>
    </div>
  )
}

function BigStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-2xl font-semibold leading-none text-foreground sm:text-3xl">
        {value}
      </span>
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
      {children}
    </h2>
  )
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-2xl border border-dashed border-border bg-card/60 px-4 py-3 text-sm text-muted-foreground">
      {children}
    </p>
  )
}

