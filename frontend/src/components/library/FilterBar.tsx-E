import { 
  Book, 
  FileText, 
  MessageSquare, 
  StickyNote, 
  Code, 
  Mic, 
  BookOpen, 
  Bookmark, 
  Cpu, 
  Newspaper 
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { ContentType } from "./types"

const CATEGORY_GROUPS = [
  {
    label: "Main Library",
    items: [
      { id: "tech_book" as const, label: "Tech Books", icon: Cpu },
      { id: "book" as const, label: "Books", icon: Book },
      { id: "paper" as const, label: "Papers", icon: FileText },
      { id: "epub" as const, label: "E-Books", icon: BookOpen },
    ]
  },
  {
    label: "Capture",
    items: [
      { id: "notes" as const, label: "Notes", icon: StickyNote },
      { id: "kindle_clippings" as const, label: "Kindle", icon: Bookmark },
      { id: "conversation" as const, label: "Chat Logs", icon: MessageSquare },
    ]
  },
  {
    label: "Resources",
    items: [
      { id: "code" as const, label: "Code", icon: Code },
      { id: "tech_article" as const, label: "Articles", icon: Newspaper },
      { id: "audio" as const, label: "Audio", icon: Mic },
    ]
  }
]

interface FilterBarProps {
  selected: Set<ContentType>
  onChange: (selected: Set<ContentType>) => void
}

export function FilterBar({ selected, onChange }: FilterBarProps) {
  function toggle(type: ContentType) {
    const next = new Set(selected)
    if (next.has(type)) {
      next.delete(type)
    } else {
      next.add(type)
    }
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-6 w-full py-2">
      <div className="flex items-center gap-12 overflow-x-auto no-scrollbar pb-2">
        {CATEGORY_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-3 group/nav">
            <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60 transition-colors group-hover/nav:text-primary/70">
              {group.label}
            </span>
            <div className="flex items-center gap-2">
              {group.items.map((item) => {
                const Icon = item.icon
                const isActive = selected.has(item.id)
                return (
                  <button
                    key={item.id}
                    onClick={() => toggle(item.id)}
                    className={cn(
                      "flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 border whitespace-nowrap",
                      isActive
                        ? "bg-primary/10 border-primary/30 text-primary shadow-sm"
                        : "bg-muted/30 border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <Icon size={14} className={cn(isActive ? "text-primary" : "text-muted-foreground")} />
                    {item.label}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
