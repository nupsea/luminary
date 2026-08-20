import {
  Book,
  BookOpen,
  Cpu,
  FileCode,
  FileText,
  MessageSquare,
  Mic,
  StickyNote,
  Video,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  chipIsActive,
  toggleChip as toggleChipTypes,
  visibleChips,
  type LibraryFacets,
  type TypeChip as TypeChipBase,
} from "./filterChips"
import type { ContentType } from "./types"

export type { LibraryFacets }

/** A chip and the content types it stands for.
 *
 *  One vocabulary, and it is the one the Add Content dialog offers: a filter
 *  naming something you cannot add is a dead end. Five of the ten chips this
 *  replaces could not match a document in any library -- `code` is not in the
 *  backend's ContentType union at all, `epub` is a *format* (an EPUB is stored
 *  with content_type `book`), `kindle_clippings` needs a filename check, and
 *  `notes` names the separate Notes entity, not a document.
 *
 *  `types` is a list because Technical is one choice at upload and two stored
 *  values after classification.
 */
interface TypeChip extends TypeChipBase {
  icon: LucideIcon
}

const TYPE_GROUPS: { label: string; items: TypeChip[] }[] = [
  {
    label: "Library",
    items: [
      { id: "book", label: "Books", icon: Book, types: ["book"] },
      { id: "technical", label: "Technical", icon: Cpu, types: ["tech_book", "tech_article"] },
      { id: "paper", label: "Papers", icon: FileText, types: ["paper"] },
    ],
  },
  {
    label: "Capture",
    items: [
      {
        id: "conversation",
        label: "Conversations",
        icon: MessageSquare,
        types: ["conversation"],
      },
      { id: "notes", label: "Notes", icon: StickyNote, types: ["notes"] },
    ],
  },
  {
    label: "Media",
    items: [
      { id: "audio", label: "Audio", icon: Mic, types: ["audio"] },
      { id: "video", label: "Video", icon: Video, types: ["video"] },
    ],
  },
]

// Formats worth naming. A format answers a different question from a type --
// "which file is this" rather than "what kind of thing" -- which is why E-Books
// belongs here and never worked as a content type.
const FORMAT_LABELS: Record<string, { label: string; icon: LucideIcon }> = {
  epub: { label: "E-Books", icon: BookOpen },
  pdf: { label: "PDF", icon: FileText },
  md: { label: "Markdown", icon: FileCode },
  txt: { label: "Text", icon: FileText },
  docx: { label: "Word", icon: FileText },
}

interface FilterBarProps {
  selected: Set<ContentType>
  onChange: (selected: Set<ContentType>) => void
  selectedFormats: Set<string>
  onFormatsChange: (selected: Set<string>) => void
  /** Counts over the whole library. Undefined while loading: chips stay hidden
   *  rather than flashing in and out as the numbers arrive. */
  facets?: LibraryFacets
}

function Chip({
  label,
  icon: Icon,
  count,
  active,
  onClick,
}: {
  label: string
  icon: LucideIcon
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium whitespace-nowrap transition-all duration-200",
        active
          ? "border-primary/30 bg-primary/10 text-primary shadow-sm"
          : "border-transparent bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Icon size={14} className={cn(active ? "text-primary" : "text-muted-foreground")} />
      {label}
      <span className={cn("tabular-nums", active ? "text-primary/70" : "text-muted-foreground/60")}>
        {count}
      </span>
    </button>
  )
}

export function FilterBar({
  selected,
  onChange,
  selectedFormats,
  onFormatsChange,
  facets,
}: FilterBarProps) {
  function toggleChip(chip: TypeChip) {
    onChange(toggleChipTypes(chip, selected))
  }

  function toggleFormat(format: string) {
    const next = new Set(selectedFormats)
    if (next.has(format)) next.delete(format)
    else next.add(format)
    onFormatsChange(next)
  }

  const groups = TYPE_GROUPS.map((group) => ({
    label: group.label,
    items: visibleChips(group.items, facets) as { chip: TypeChip; count: number }[],
  })).filter((group) => group.items.length > 0)

  const formats = Object.entries(facets?.formats ?? {})
    .filter(([id, count]) => count > 0 && id in FORMAT_LABELS)
    .sort((a, b) => b[1] - a[1])

  if (groups.length === 0 && formats.length === 0) return null

  return (
    <div className="flex w-full flex-col gap-6 py-2">
      <div className="no-scrollbar flex items-start gap-12 overflow-x-auto pb-2">
        {groups.map((group) => (
          <div key={group.label} className="group/nav flex flex-col gap-3">
            <span className="lum-eyebrow transition-colors group-hover/nav:text-primary/70">
              {group.label}
            </span>
            <div className="flex items-center gap-2">
              {group.items.map(({ chip, count }) => (
                <Chip
                  key={chip.id}
                  label={chip.label}
                  icon={chip.icon}
                  count={count}
                  active={chipIsActive(chip, selected)}
                  onClick={() => toggleChip(chip)}
                />
              ))}
            </div>
          </div>
        ))}

        {formats.length > 0 && (
          <div className="group/nav flex flex-col gap-3">
            <span className="lum-eyebrow transition-colors group-hover/nav:text-primary/70">
              Format
            </span>
            <div className="flex items-center gap-2">
              {formats.map(([id, count]) => (
                <Chip
                  key={id}
                  label={FORMAT_LABELS[id].label}
                  icon={FORMAT_LABELS[id].icon}
                  count={count}
                  active={selectedFormats.has(id)}
                  onClick={() => toggleFormat(id)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
