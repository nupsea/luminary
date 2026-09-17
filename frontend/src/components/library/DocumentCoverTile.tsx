import { useState, useMemo } from "react"
import { API_BASE } from "@/lib/config"
import { isYouTubeDoc, getYouTubeThumbnail, CONTENT_TYPE_ICONS } from "./utils"
import type { DocumentListItem } from "./types"
import { cn } from "@/lib/utils"
import { Sparkles } from "lucide-react"

interface DocumentCoverTileProps {
  doc: DocumentListItem
  className?: string
}

function hashString(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

/**
 * Procedural generative resonance banner when no raster cover or diagram exists.
 * Employs curated gradients, subtle technical SVG meshes, watermarked icons,
 * and high-contrast typographic excerpts from summary_one_sentence.
 */
function ProceduralCoverTile({ doc }: { doc: DocumentListItem }) {
  const Icon = CONTENT_TYPE_ICONS[doc.content_type] || Sparkles
  const hash = useMemo(() => hashString(doc.id + doc.title), [doc.id, doc.title])

  // Curated color themes mapped by content type, styled for both light and dark modes
  const theme = useMemo(() => {
    switch (doc.content_type) {
      case "tech_book":
      case "code":
        return {
          gradient:
            "from-sky-50 via-cyan-50/50 to-indigo-50/60 dark:from-cyan-950/95 dark:via-slate-900/95 dark:to-indigo-950/95",
          accent: "text-sky-700 dark:text-cyan-400",
          border: "border-sky-200/80 dark:border-cyan-500/20",
          iconColor: "text-sky-600/20 dark:text-cyan-400/10",
        }
      case "video":
        return {
          gradient:
            "from-rose-50 via-pink-50/50 to-red-50/60 dark:from-rose-950/95 dark:via-slate-900/95 dark:to-red-950/95",
          accent: "text-rose-700 dark:text-rose-400",
          border: "border-rose-200/80 dark:border-rose-500/20",
          iconColor: "text-rose-600/20 dark:text-rose-400/10",
        }
      case "book":
      case "epub":
        return {
          gradient:
            "from-amber-50 via-orange-50/40 to-stone-100/70 dark:from-amber-950/95 dark:via-neutral-900/95 dark:to-stone-900/95",
          accent: "text-amber-800 dark:text-amber-400",
          border: "border-amber-200/80 dark:border-amber-500/20",
          iconColor: "text-amber-700/20 dark:text-amber-400/10",
        }
      case "paper":
      case "tech_article":
        return {
          gradient:
            "from-emerald-50 via-teal-50/40 to-slate-100/70 dark:from-emerald-950/95 dark:via-slate-900/95 dark:to-teal-950/95",
          accent: "text-emerald-800 dark:text-emerald-400",
          border: "border-emerald-200/80 dark:border-emerald-500/20",
          iconColor: "text-emerald-700/20 dark:text-emerald-400/10",
        }
      default:
        return {
          gradient:
            "from-violet-50 via-purple-50/40 to-slate-100/70 dark:from-violet-950/95 dark:via-slate-900/95 dark:to-slate-950/95",
          accent: "text-violet-800 dark:text-violet-400",
          border: "border-violet-200/80 dark:border-violet-500/20",
          iconColor: "text-violet-700/20 dark:text-violet-400/10",
        }
    }
  }, [doc.content_type])

  // SVG grid pattern variation based on hash
  const patternSeed = hash % 3

  // Description from summary_one_sentence
  const description = doc.summary_one_sentence || ""

  return (
    <div
      className={cn(
        "relative h-full w-full overflow-hidden p-3 flex flex-col justify-between select-none bg-gradient-to-br transition-all duration-300",
        theme.gradient,
      )}
    >
      {/* Background SVG ambient pattern */}
      <svg
        className="absolute inset-0 h-full w-full opacity-25 dark:opacity-15 pointer-events-none"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
      >
        <defs>
          <pattern
            id={`grid-${doc.id}`}
            width={patternSeed === 0 ? "16" : patternSeed === 1 ? "24" : "12"}
            height={patternSeed === 0 ? "16" : patternSeed === 1 ? "24" : "12"}
            patternUnits="userSpaceOnUse"
          >
            {patternSeed === 0 ? (
              <circle cx="2" cy="2" r="1" fill="currentColor" className={theme.accent} />
            ) : patternSeed === 1 ? (
              <path d="M 24 0 L 0 0 0 24" fill="none" stroke="currentColor" strokeWidth="0.5" className={theme.accent} />
            ) : (
              <path d="M 0 6 L 12 6 M 6 0 L 6 12" stroke="currentColor" strokeWidth="0.5" className={theme.accent} />
            )}
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#grid-${doc.id})`} />
      </svg>

      {/* Watermark icon in background corner */}
      <Icon
        className={cn(
          "absolute -bottom-3 -right-3 h-20 w-20 pointer-events-none transition-transform duration-500 group-hover/tile:scale-110 group-hover/tile:rotate-6",
          theme.iconColor,
        )}
      />

      {/* Top Header: Content type badge + Format pill */}
      <div className="relative z-10 flex items-center justify-between gap-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <Icon size={12} className={cn("shrink-0", theme.accent)} />
          <span className={cn("truncate text-[10px] font-bold uppercase tracking-wider", theme.accent)}>
            {doc.facets?.domain || doc.content_type.replace("_", " ")}
          </span>
          {doc.facets?.form && (
            <>
              <span className="text-slate-400 dark:text-muted-foreground/40 text-[10px]">·</span>
              <span className="truncate text-[10px] text-slate-600 dark:text-muted-foreground/80 capitalize">
                {doc.facets.form}
              </span>
            </>
          )}
        </div>
        <span className="shrink-0 rounded bg-white/80 dark:bg-background/60 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 dark:text-muted-foreground backdrop-blur-xs border border-slate-200/80 dark:border-border/40 shadow-2xs">
          {doc.format.toUpperCase()}
        </span>
      </div>

      {/* Center content: Prominent Title + Brief Description */}
      <div className="relative z-10 my-auto py-1">
        <h3 className="line-clamp-2 text-sm font-bold leading-snug tracking-tight text-slate-900 dark:text-slate-100 group-hover/tile:text-slate-950 dark:group-hover/tile:text-white transition-colors">
          {doc.title}
        </h3>
        {description && (
          <p className="line-clamp-2 mt-1 text-[11px] font-normal leading-relaxed text-slate-600 dark:text-slate-300">
            {description}
          </p>
        )}
      </div>

      {/* Bottom meta row */}
      <div className="relative z-10 flex items-center justify-between text-[10px] text-slate-500 dark:text-muted-foreground/80 font-medium">
        <span>
          {doc.page_count > 0
            ? `${doc.page_count} pages`
            : doc.word_count > 0
              ? `${doc.word_count.toLocaleString()} words`
              : doc.format.toUpperCase()}
        </span>
        {doc.audio_duration_seconds != null && (
          <span>{Math.round(doc.audio_duration_seconds / 60)}m</span>
        )}
      </div>
    </div>
  )
}

export function DocumentCoverTile({ doc, className }: DocumentCoverTileProps) {
  const [imageError, setImageError] = useState(false)
  const [imageLoaded, setImageLoaded] = useState(false)

  const isYouTube = isYouTubeDoc(doc)
  const candidateUrl = useMemo(() => {
    if (isYouTube) {
      const yt = getYouTubeThumbnail(doc.source_url)
      if (yt) return yt
    }
    return `${API_BASE}/documents/${doc.id}/cover`
  }, [isYouTube, doc.source_url, doc.id])

  return (
    <div
      className={cn(
        "group/tile relative mt-2.5 aspect-[16/9] w-full overflow-hidden rounded-lg border border-slate-200/80 dark:border-border/60 bg-slate-50/50 dark:bg-muted/40 shadow-xs dark:shadow-sm transition-all duration-300 hover:border-slate-300 dark:hover:border-border hover:shadow-md",
        className,
      )}
      title={doc.summary_one_sentence || doc.title}
    >
      {!imageError && candidateUrl ? (
        <>
          {/* Skeleton pulse while loading image */}
          {!imageLoaded && (
            <div className="absolute inset-0 animate-pulse bg-muted/70" />
          )}

          {/* Ambient blurred backdrop for portrait book covers */}
          <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
            <img
              src={candidateUrl}
              alt=""
              className="h-full w-full object-cover blur-xl scale-125 opacity-35 dark:opacity-25"
            />
          </div>

          <img
            src={candidateUrl}
            alt={doc.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              "relative z-10 h-full w-full object-contain p-1 drop-shadow-sm transition-transform duration-500 ease-out group-hover:scale-105 group-hover:brightness-[1.03]",
              imageLoaded ? "opacity-100" : "opacity-0",
            )}
          />

          {/* Frosted subtle glass bottom badge with format or duration */}
          <div className="absolute bottom-1.5 right-1.5 z-20 flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[9px] font-medium backdrop-blur-sm shadow-sm opacity-90 transition-opacity group-hover:opacity-100">
            <span>{isYouTube ? "YouTube" : doc.format.toUpperCase()}</span>
          </div>
        </>
      ) : (
        <ProceduralCoverTile doc={doc} />
      )}
    </div>
  )
}
