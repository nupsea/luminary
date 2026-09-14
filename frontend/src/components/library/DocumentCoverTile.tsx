import { useState, useMemo } from "react"
import { API_BASE } from "@/lib/config"
import { isYouTubeDoc, getYouTubeThumbnail, CONTENT_TYPE_ICONS } from "./utils"
import type { DocumentListItem } from "./types"
import { cn } from "@/lib/utils"
import { Sparkles, Quote } from "lucide-react"

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

  // Curated color themes mapped by content type and facet domain
  const theme = useMemo(() => {
    switch (doc.content_type) {
      case "tech_book":
      case "code":
        return {
          from: "from-cyan-950/90",
          via: "via-slate-900/90",
          to: "to-indigo-950/90",
          accent: "text-cyan-400",
          border: "border-cyan-500/20",
          glow: "rgba(6, 182, 212, 0.15)",
        }
      case "video":
        return {
          from: "from-rose-950/90",
          via: "via-slate-900/90",
          to: "to-red-950/90",
          accent: "text-rose-400",
          border: "border-rose-500/20",
          glow: "rgba(244, 63, 94, 0.15)",
        }
      case "book":
      case "epub":
        return {
          from: "from-amber-950/90",
          via: "via-neutral-900/90",
          to: "to-stone-900/90",
          accent: "text-amber-400",
          border: "border-amber-500/20",
          glow: "rgba(245, 158, 11, 0.15)",
        }
      case "paper":
      case "tech_article":
        return {
          from: "from-emerald-950/90",
          via: "via-slate-900/90",
          to: "to-teal-950/90",
          accent: "text-emerald-400",
          border: "border-emerald-500/20",
          glow: "rgba(16, 185, 129, 0.15)",
        }
      default:
        return {
          from: "from-violet-950/90",
          via: "via-slate-900/90",
          to: "to-slate-950/90",
          accent: "text-violet-400",
          border: "border-violet-500/20",
          glow: "rgba(168, 85, 247, 0.15)",
        }
    }
  }, [doc.content_type])

  // SVG grid pattern variation based on hash
  const patternSeed = hash % 3

  return (
    <div
      className={cn(
        "relative h-full w-full overflow-hidden p-3.5 flex flex-col justify-between select-none bg-gradient-to-br transition-all duration-300",
        theme.from,
        theme.via,
        theme.to,
      )}
      style={{
        boxShadow: `inset 0 0 20px ${theme.glow}`,
      }}
    >
      {/* Background SVG ambient pattern */}
      <svg
        className="absolute inset-0 h-full w-full opacity-15 pointer-events-none"
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

      {/* Large watermark icon in background corner */}
      <Icon
        className={cn(
          "absolute -bottom-4 -right-4 h-24 w-24 opacity-10 pointer-events-none transition-transform duration-500 group-hover:scale-110 group-hover:rotate-6",
          theme.accent,
        )}
      />

      {/* Top Header / Domain Accent */}
      <div className="relative z-10 flex items-center gap-1.5">
        <span className={cn("text-[10px] font-semibold uppercase tracking-wider", theme.accent)}>
          {doc.facets?.domain || doc.content_type.replace("_", " ")}
        </span>
        {doc.facets?.form && (
          <>
            <span className="text-muted-foreground/50 text-[10px]">·</span>
            <span className="text-[10px] text-muted-foreground capitalize">
              {doc.facets.form}
            </span>
          </>
        )}
      </div>

      {/* Center content: Quote / Summary Resonance or Title glyph */}
      <div className="relative z-10 my-auto">
        {doc.summary_one_sentence ? (
          <div className="flex items-start gap-1.5">
            <Quote size={11} className={cn("shrink-0 mt-0.5 opacity-60", theme.accent)} />
            <p className="line-clamp-2 text-xs font-normal leading-snug text-foreground/90 tracking-tight">
              {doc.summary_one_sentence}
            </p>
          </div>
        ) : (
          <p className="line-clamp-2 text-xs font-medium text-foreground/75 italic">
            {doc.title}
          </p>
        )}
      </div>

      {/* Bottom meta row */}
      <div className="relative z-10 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{doc.format.toUpperCase()}</span>
        {doc.page_count > 0 && <span>{doc.page_count}p</span>}
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
        "group/tile relative mt-2.5 aspect-[16/9] w-full overflow-hidden rounded-lg border border-border/60 bg-muted/40 shadow-sm transition-all duration-300 hover:border-border hover:shadow-md",
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

          <img
            src={candidateUrl}
            alt={doc.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              "h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-105 group-hover:brightness-[1.03]",
              imageLoaded ? "opacity-100" : "opacity-0",
            )}
          />

          {/* Frosted subtle glass bottom badge with format or duration */}
          <div className="absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[9px] font-medium backdrop-blur-sm shadow-sm opacity-90 transition-opacity group-hover:opacity-100">
            <span>{isYouTube ? "YouTube" : doc.format.toUpperCase()}</span>
          </div>
        </>
      ) : (
        <ProceduralCoverTile doc={doc} />
      )}
    </div>
  )
}
