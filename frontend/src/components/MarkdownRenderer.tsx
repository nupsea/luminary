import {
  createContext,
  memo,
  type ComponentPropsWithoutRef,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
} from "react"
import type { Root, RootContent } from "hast"
import { FileText, Pencil } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import rehypeRaw from "rehype-raw"
import type { PluggableList } from "unified"
import "katex/dist/katex.min.css"
import { API_BASE } from "@/lib/config"
import { findExcalidrawDiagrams, type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { resolveLuminaryAssetUrl } from "@/lib/noteAssets"
import { SOURCE_LINE_ATTR, lineOffsetAt, rehypeSourceLine } from "@/lib/rehypeSourceLine"
import { cn } from "@/lib/utils"

export type ImageSize = "small" | "medium" | "large"

export interface MarkdownRendererProps {
  children: string
  className?: string
  /** When provided, note link IDs NOT in this set are rendered as broken (muted red). */
  validNoteIds?: Set<string>
  /** Cap width applied to rendered <img>. Defaults to "medium" so large pasted images don't blow up the page. */
  imageSize?: ImageSize
  /** Reading variant: roomier spacing for notes and long-form. Default is
   * the compact sans body used in chat answers so they match the UI chrome. */
  reading?: boolean
  onEditExcalidrawDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
  /** When set, [[id|text]] note links become navigable buttons. */
  onNoteLinkClick?: (noteId: string) => void
  /** When set, clicking an image opens a small size picker that writes the
   * |small/medium/large alt pipe back into the source markdown. */
  onSetImageSize?: (src: string, size: ImageSize) => void
  /** Stamp rendered blocks with their markdown line so a split editor can
   * scroll-sync against them. Off by default — only the editors need it. */
  trackSourceLines?: boolean
  /** Lines of the original document preceding `children`, when this body is one
   * chunk of a note split around diagrams. */
  sourceLineOffset?: number
  /** Parent document ID used to resolve relative image paths to document asset endpoints. */
  documentId?: string
  /** Notified when any image finishes loading in the DOM. */
  onImageLoad?: () => void
}

const IMAGE_SIZE_STYLE: Record<ImageSize, { maxWidth: string; maxHeight: string; objectFit: "contain" }> = {
  small: { maxWidth: "240px", maxHeight: "200px", objectFit: "contain" },
  medium: { maxWidth: "480px", maxHeight: "360px", objectFit: "contain" },
  large: { maxWidth: "800px", maxHeight: "600px", objectFit: "contain" },
}

const IMAGE_SIZE_CLASS: Record<ImageSize, string> = {
  small: "prose-img:max-w-[240px] prose-img:max-h-[200px] prose-img:object-contain",
  medium: "prose-img:max-w-[480px] prose-img:max-h-[360px] prose-img:object-contain",
  large: "prose-img:max-w-[800px] prose-img:max-h-[600px] prose-img:object-contain",
}

const NOTE_LINK_MARKER_RE = /(?:\[\[|\[)([a-f0-9-]+)\|([^\]]+)(?:\]\]|\])/g

function preprocessLinks(content: string): string {
  let text = content.replace(
    NOTE_LINK_MARKER_RE,
    (_m, id, text) => `\`[note:${id}|${text}]\``
  )
  // Resolve local mirrored images: __LUMINARY_IMG__/doc_id/filename -> API_BASE/images/local/doc_id/filename
  text = text.replace(/__LUMINARY_IMG__\//g, `${API_BASE}/images/local/`)
  return text
}

function parseImageAlt(alt?: string): { alt: string; size?: ImageSize } {
  if (!alt) return { alt: "" }

  const parts = alt.split("|")
  if (parts.length < 2) return { alt }

  const potentialSize = parts.at(-1)?.trim().toLowerCase()
  if (potentialSize === "small" || potentialSize === "medium" || potentialSize === "large") {
    return {
      alt: parts.slice(0, -1).join("|").trim(),
      size: potentialSize,
    }
  }

  return { alt }
}

function MermaidBlock({ chart }: { chart: string }) {
  const generatedId = useId()
  const [svg, setSvg] = useState("")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const renderId = `mermaid-${generatedId.replace(/:/g, "")}`
    async function renderMermaid() {
      try {
        setError(null)
        const mermaid = (await import("mermaid")).default
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          suppressErrorRendering: true,
          theme: document.documentElement.classList.contains("dark") ? "dark" : "default",
        })
        const { svg } = await mermaid.render(renderId, chart)
        if (!cancelled) setSvg(svg)
      } catch (err) {
        document.getElementById(`d${renderId}`)?.remove()
        if (!cancelled) {
          setSvg("")
          setError(err instanceof Error ? err.message : "Could not render Mermaid diagram")
        }
      }
    }
    void renderMermaid()
    return () => {
      cancelled = true
    }
  }, [chart, generatedId])

  if (error) {
    return (
      <pre className="not-prose overflow-auto rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
        <code>{error}</code>
      </pre>
    )
  }

  if (!svg) {
    return (
      <div className="not-prose rounded border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        Rendering diagram...
      </div>
    )
  }

  return (
    <div
      className="not-prose my-4 overflow-auto rounded border border-border bg-background p-3"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

const ExcalidrawDiagramPreview = memo(function ExcalidrawDiagramPreview({
  diagram,
  index,
  onEdit,
  sourceLine,
  onImageLoad,
}: {
  diagram: ExcalidrawNoteDiagramRef
  index: number
  onEdit?: (diagram: ExcalidrawNoteDiagramRef) => void
  sourceLine?: number
  onImageLoad?: () => void
}) {
  return (
    <figure
      {...(sourceLine != null ? { [SOURCE_LINE_ATTR]: String(sourceLine) } : {})}
      className="not-prose my-5 overflow-hidden rounded-lg border border-border bg-background shadow-sm"
    >
      <div className="flex items-center justify-between border-b border-border bg-muted/35 px-3 py-2">
        <figcaption className="text-xs font-medium text-muted-foreground">
          Diagram {index + 1}
        </figcaption>
        {onEdit && (
          <button
            type="button"
            onClick={() => onEdit(diagram)}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
            title={`Edit diagram ${index + 1}`}
          >
            <Pencil size={12} />
            Edit
          </button>
        )}
      </div>
      <div className="overflow-auto bg-white p-3 dark:bg-zinc-950">
        <img
          src={resolveLuminaryAssetUrl(diagram.svgPath)}
          alt={`Diagram ${index + 1}`}
          decoding="async"
          onLoad={onImageLoad}
          className="mx-auto block max-h-[600px] max-w-[800px] object-contain"
        />
      </div>
    </figure>
  )
})

/**
 * Strip inter-element whitespace text nodes from table structures before rehypeRaw.
 * Without this, rehypeRaw's HTML5 parser (parse5) foster-parents any whitespace text
 * nodes found inside <table>, <thead>, <tbody>, or <tr> to before the table element,
 * causing dozens of empty lines (900px+ of blank void) in white-space: pre-wrap containers.
 */
function rehypeCleanTableWhitespace() {
  return (tree: Root) => {
    function visit(node: RootContent | Root) {
      if (
        node.type === "element" &&
        (node.tagName === "table" ||
          node.tagName === "thead" ||
          node.tagName === "tbody" ||
          node.tagName === "tfoot" ||
          node.tagName === "tr")
      ) {
        node.children = node.children.filter(
          (c) => !(c.type === "text" && /^\s+$/.test(c.value)),
        )
      }
      if ("children" in node && Array.isArray(node.children)) {
        node.children.forEach(visit)
      }
    }
    visit(tree)
  }
}

function resolveImageUrl(src?: string, documentId?: string): string {
  if (!src) return ""
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:") ||
    src.startsWith("blob:")
  ) {
    return src
  }
  const clean = src.replace(/^\.?\//, "")
  if (documentId) {
    return `${API_BASE}/documents/${documentId}/asset/${clean}`
  }
  return src
}

interface MarkdownRendererContextValue {
  documentId?: string
  imageSize: ImageSize
  onSetImageSize?: (src: string, size: ImageSize) => void
  onOpenMenu: (menu: { src: string; x: number; y: number }) => void
  onImageLoad?: () => void
  validNoteIds?: Set<string>
  onNoteLinkClick?: (noteId: string) => void
}

const MarkdownRendererContext = createContext<MarkdownRendererContextValue | null>(null)

const MarkdownImage = memo(function MarkdownImage({
  src,
  alt,
}: {
  src?: string
  alt?: string
}) {
  const ctx = useContext(MarkdownRendererContext)
  const parsed = parseImageAlt(alt)
  const size = parsed.size ?? ctx?.imageSize ?? "medium"
  const resolvedSrc = resolveImageUrl(src, ctx?.documentId)
  const onSetImageSize = ctx?.onSetImageSize
  const onOpenMenu = ctx?.onOpenMenu
  const onImageLoad = ctx?.onImageLoad

  return (
    <img
      src={resolvedSrc}
      alt={parsed.alt}
      decoding="async"
      onLoad={onImageLoad}
      onClick={
        onSetImageSize && resolvedSrc && onOpenMenu
          ? (e) => onOpenMenu({ src: resolvedSrc, x: e.clientX, y: e.clientY })
          : undefined
      }
      title={onSetImageSize ? "Click to set display size" : undefined}
      className={cn(
        "rounded-lg shadow-md mx-auto my-4 block transition-opacity duration-150",
        onSetImageSize && "cursor-pointer",
        size === "small" && "max-w-[240px] max-h-[200px] object-contain",
        size === "medium" && "max-w-[480px] max-h-[360px] object-contain",
        size === "large" && "max-w-[800px] max-h-[600px] object-contain",
      )}
      style={IMAGE_SIZE_STYLE[size]}
    />
  )
})

const MarkdownPre = memo(function MarkdownPre({
  children: preChildren,
}: {
  children?: ReactNode
}) {
  const child = Array.isArray(preChildren) ? preChildren[0] : preChildren
  if (
    typeof child === "object" &&
    child !== null &&
    "props" in child &&
    typeof child.props === "object" &&
    child.props !== null
  ) {
    const props = child.props as { className?: string; children?: ReactNode }
    if (props.className?.includes("language-mermaid")) {
      return <MermaidBlock chart={String(props.children ?? "").trim()} />
    }
  }
  return <pre>{preChildren}</pre>
})

const MarkdownCode = memo(function MarkdownCode({
  children: codeChildren,
  ...props
}: ComponentPropsWithoutRef<"code">) {
  const ctx = useContext(MarkdownRendererContext)
  const text = String(codeChildren)
  const m = text.match(/^\[note:([a-f0-9-]+)\|(.+)\]$/)
  if (m) {
    const [, id, label] = m
    const isBroken = ctx?.validNoteIds !== undefined && !ctx.validNoteIds.has(id)
    if (isBroken) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-500 dark:bg-red-950 dark:text-red-400 line-through not-prose">
          <FileText size={11} className="shrink-0" />
          <span>{label}</span>
        </span>
      )
    }
    if (ctx?.onNoteLinkClick) {
      return (
        <button
          type="button"
          onClick={() => ctx.onNoteLinkClick!(id)}
          className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs bg-primary/10 text-primary hover:bg-primary/20 dark:bg-primary/20 dark:text-primary font-medium not-prose cursor-pointer transition-colors border border-primary/25 shadow-xs"
          title={`Open linked note: ${label}`}
        >
          <FileText size={11} className="shrink-0 opacity-80" />
          <span className="truncate max-w-[280px]">{label}</span>
        </button>
      )
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary font-medium not-prose border border-primary/20">
        <FileText size={11} className="shrink-0 opacity-80" />
        <span className="truncate max-w-[280px]">{label}</span>
      </span>
    )
  }
  return <code {...props}>{codeChildren}</code>
})

const STABLE_MARKDOWN_COMPONENTS = {
  pre: MarkdownPre,
  img: MarkdownImage,
  code: MarkdownCode,
}

function MarkdownBody({
  children,
  className,
  validNoteIds,
  imageSize = "medium",
  reading = false,
  onNoteLinkClick,
  onSetImageSize,
  trackSourceLines = false,
  sourceLineOffset = 0,
  documentId,
  onImageLoad,
}: MarkdownRendererProps) {
  // Only inline substitutions — line numbering must survive for scroll sync.
  const processed = preprocessLinks(children)
  const [sizeMenu, setSizeMenu] = useState<{ src: string; x: number; y: number } | null>(null)

  const rehypePlugins: PluggableList = useMemo(
    () =>
      trackSourceLines
        ? [rehypeCleanTableWhitespace, rehypeHighlight, rehypeKatex, rehypeRaw, [rehypeSourceLine, sourceLineOffset]]
        : [rehypeCleanTableWhitespace, rehypeHighlight, rehypeKatex, rehypeRaw],
    [trackSourceLines, sourceLineOffset],
  )

  const contextValue = useMemo<MarkdownRendererContextValue>(
    () => ({
      documentId,
      imageSize,
      validNoteIds,
      onNoteLinkClick,
      onSetImageSize,
      onImageLoad,
      onOpenMenu: setSizeMenu,
    }),
    [documentId, imageSize, validNoteIds, onNoteLinkClick, onSetImageSize, onImageLoad],
  )

  return (
    <MarkdownRendererContext.Provider value={contextValue}>
      <div
        className={cn(
          "prose prose-base dark:prose-invert max-w-none font-sans leading-relaxed text-foreground/90 [font-size:inherit]",
          "prose-headings:font-sans prose-headings:font-semibold prose-headings:tracking-tight",
          reading ? "" : "prose-p:my-3 prose-li:my-1 prose-ul:my-4 prose-ol:my-4",
          "prose-img:rounded-lg prose-img:shadow-md prose-img:mx-auto",
          "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
          IMAGE_SIZE_CLASS[imageSize],
          className,
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={rehypePlugins}
          components={STABLE_MARKDOWN_COMPONENTS}
        >
          {processed}
        </ReactMarkdown>
        {sizeMenu && onSetImageSize && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setSizeMenu(null)} />
            <div
              className="fixed z-50 flex gap-1 rounded-md border border-border bg-popover p-1 shadow-md not-prose"
              style={{ left: sizeMenu.x, top: sizeMenu.y }}
            >
              {(["small", "medium", "large"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    onSetImageSize(sizeMenu.src, s)
                    setSizeMenu(null)
                  }}
                  className="rounded px-2 py-0.5 text-xs capitalize text-foreground hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </MarkdownRendererContext.Provider>
  )
}

export function MarkdownRenderer({
  children,
  className,
  validNoteIds,
  imageSize = "medium",
  reading = false,
  onEditExcalidrawDiagram,
  onNoteLinkClick,
  onSetImageSize,
  trackSourceLines = false,
  documentId,
  onImageLoad,
}: MarkdownRendererProps) {
  const diagrams = useMemo(() => findExcalidrawDiagrams(children), [children])

  if (diagrams.length === 0) {
    return (
      <MarkdownBody
        className={className}
        validNoteIds={validNoteIds}
        imageSize={imageSize}
        reading={reading}
        onNoteLinkClick={onNoteLinkClick}
        onSetImageSize={onSetImageSize}
        trackSourceLines={trackSourceLines}
        documentId={documentId}
        onImageLoad={onImageLoad}
      >
        {children}
      </MarkdownBody>
    )
  }

  const lastEnd = diagrams.at(-1)?.end ?? 0

  return (
    <div className={cn("max-w-none space-y-4", className)}>
      {diagrams.map((diagram, index) => {
        const previousEnd = index === 0 ? 0 : diagrams[index - 1].end
        const before = children.substring(previousEnd, diagram.start)
        const lineOffset = lineOffsetAt(children, previousEnd)
        return (
          <div key={diagram.scenePath || `diagram-${index}`}>
            {before.trim() && (
              <MarkdownBody
                validNoteIds={validNoteIds}
                imageSize={imageSize}
                reading={reading}
                onNoteLinkClick={onNoteLinkClick}
                onSetImageSize={onSetImageSize}
                trackSourceLines={trackSourceLines}
                sourceLineOffset={lineOffset}
                documentId={documentId}
                onImageLoad={onImageLoad}
              >
                {before}
              </MarkdownBody>
            )}
            <ExcalidrawDiagramPreview
              diagram={diagram}
              index={index}
              onEdit={onEditExcalidrawDiagram}
              onImageLoad={onImageLoad}
              sourceLine={
                trackSourceLines ? lineOffsetAt(children, diagram.start) + 1 : undefined
              }
            />
          </div>
        )
      })}
      {children.substring(lastEnd).trim() && (
        <MarkdownBody
          validNoteIds={validNoteIds}
          imageSize={imageSize}
          reading={reading}
          onNoteLinkClick={onNoteLinkClick}
          onSetImageSize={onSetImageSize}
          trackSourceLines={trackSourceLines}
          sourceLineOffset={lineOffsetAt(children, lastEnd)}
          documentId={documentId}
          onImageLoad={onImageLoad}
        >
          {children.substring(lastEnd)}
        </MarkdownBody>
      )}
    </div>
  )
}


