import { type ReactNode, useEffect, useId, useState } from "react"
import { Pencil } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import rehypeRaw from "rehype-raw"
import "katex/dist/katex.min.css"
import { API_BASE } from "@/lib/config"
import { findExcalidrawDiagrams, type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { resolveLuminaryAssetUrl } from "@/lib/noteAssets"
import { cn } from "@/lib/utils"

export type ImageSize = "small" | "medium" | "large"

interface MarkdownRendererProps {
  children: string
  className?: string
  /** When provided, note link IDs NOT in this set are rendered as broken (muted red). */
  validNoteIds?: Set<string>
  /** Cap width applied to rendered <img>. Defaults to "medium" so large pasted images don't blow up the page. */
  imageSize?: ImageSize
  /** Reading variant: serif body + roomier spacing (notes/long-form). Default is
   * the compact sans body used in chat answers so they match the UI chrome. */
  serif?: boolean
  onEditExcalidrawDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
  /** When set, [[id|text]] note links become navigable buttons. */
  onNoteLinkClick?: (noteId: string) => void
  /** When set, clicking an image opens a small size picker that writes the
   * |small/medium/large alt pipe back into the source markdown. */
  onSetImageSize?: (src: string, size: ImageSize) => void
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

const NOTE_LINK_MARKER_RE = /\[\[([a-f0-9-]+)\|([^\]]+)\]\]/g

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
          // Without this, a diagram that fails to parse is not just thrown -- mermaid
          // also appends its own "Syntax error in text" bomb graphic to document.body.
          // That orphan outlives this component, so a chat full of malformed diagrams
          // stacks bombs down the page instead of showing the error box below.
          suppressErrorRendering: true,
          theme: document.documentElement.classList.contains("dark") ? "dark" : "default",
        })
        const { svg } = await mermaid.render(renderId, chart)
        if (!cancelled) setSvg(svg)
      } catch (err) {
        // Belt and braces: older mermaid builds ignore suppressErrorRendering and still
        // leave the temporary container behind on failure.
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

function ExcalidrawDiagramPreview({
  diagram,
  index,
  onEdit,
}: {
  diagram: ExcalidrawNoteDiagramRef
  index: number
  onEdit?: (diagram: ExcalidrawNoteDiagramRef) => void
}) {
  return (
    <figure className="not-prose my-5 overflow-hidden rounded-lg border border-border bg-background shadow-sm">
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
          className="mx-auto block max-h-[600px] max-w-[800px] object-contain"
        />
      </div>
    </figure>
  )
}

function MarkdownBody({ children, className, validNoteIds, imageSize = "medium", serif = false, onNoteLinkClick, onSetImageSize }: MarkdownRendererProps) {
  const processed = preprocessLinks(children)
  const [sizeMenu, setSizeMenu] = useState<{ src: string; x: number; y: number } | null>(null)

  return (
    <div className={cn(
      // Two body modes: a compact sans body for chat answers (matches the UI
      // chrome), and a roomy serif reading body for notes/long-form. The serif
      // mode keeps prose's generous default spacing so it doesn't read crowded.
      "prose prose-base dark:prose-invert max-w-none leading-relaxed text-foreground/90",
      serif ? "font-serif" : "font-sans",
      "prose-headings:font-sans prose-headings:font-semibold prose-headings:tracking-tight",
      serif ? "" : "prose-p:my-3 prose-li:my-1 prose-ul:my-4 prose-ol:my-4",
      "prose-img:rounded-lg prose-img:shadow-md prose-img:mx-auto",
      "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
      IMAGE_SIZE_CLASS[imageSize],
      className
    )}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex, rehypeRaw]}
        components={{
          pre: ({ children: preChildren }) => {
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
          },
          img: ({ src, alt }) => {
            const parsed = parseImageAlt(alt)
            const size = parsed.size ?? imageSize
            return (
              <img
                src={src}
                alt={parsed.alt}
                onClick={
                  onSetImageSize && src
                    ? (e) => setSizeMenu({ src, x: e.clientX, y: e.clientY })
                    : undefined
                }
                title={onSetImageSize ? "Click to set display size" : undefined}
                className={cn(
                  "rounded-lg shadow-md mx-auto my-4 block",
                  onSetImageSize && "cursor-pointer",
                  size === "small" && "max-w-[240px] max-h-[200px] object-contain",
                  size === "medium" && "max-w-[480px] max-h-[360px] object-contain",
                  size === "large" && "max-w-[800px] max-h-[600px] object-contain"
                )}
                style={IMAGE_SIZE_STYLE[size]}
              />
            )
          },
          code: ({ children: codeChildren, ...props }) => {
            const text = String(codeChildren)
            const m = text.match(/^\[note:([a-f0-9-]+)\|(.+)\]$/)
            if (m) {
              const [, id, label] = m
              const isBroken = validNoteIds !== undefined && !validNoteIds.has(id)
              if (isBroken) {
                return (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-500 dark:bg-red-950 dark:text-red-400 line-through not-prose">
                    {label}
                  </span>
                )
              }
              if (onNoteLinkClick) {
                return (
                  <button
                    type="button"
                    onClick={() => onNoteLinkClick(id)}
                    className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-indigo-100 text-indigo-700 hover:bg-indigo-200 dark:bg-indigo-900 dark:text-indigo-300 dark:hover:bg-indigo-800 font-medium not-prose cursor-pointer"
                    title="Open linked note"
                  >
                    {label}
                  </button>
                )
              }
              return (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300 font-medium not-prose">
                  {label}
                </span>
              )
            }
            return <code {...props}>{codeChildren}</code>
          },
        }}
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
  )
}

export function MarkdownRenderer({
  children,
  className,
  validNoteIds,
  imageSize = "medium",
  serif = false,
  onEditExcalidrawDiagram,
  onNoteLinkClick,
  onSetImageSize,
}: MarkdownRendererProps) {
  const diagrams = findExcalidrawDiagrams(children)

  if (diagrams.length === 0) {
    return (
      <MarkdownBody className={className} validNoteIds={validNoteIds} imageSize={imageSize} serif={serif} onNoteLinkClick={onNoteLinkClick} onSetImageSize={onSetImageSize}>
        {children}
      </MarkdownBody>
    )
  }

  return (
    <div className={cn("max-w-none", className)}>
      {diagrams.map((diagram, index) => {
        const previousEnd = index === 0 ? 0 : diagrams[index - 1].end
        const before = children.substring(previousEnd, diagram.start)
        return (
          <div key={`${diagram.scenePath}-${diagram.start}`}>
            {before.trim() && (
              <MarkdownBody validNoteIds={validNoteIds} imageSize={imageSize} serif={serif} onNoteLinkClick={onNoteLinkClick} onSetImageSize={onSetImageSize}>
                {before}
              </MarkdownBody>
            )}
            <ExcalidrawDiagramPreview
              diagram={diagram}
              index={index}
              onEdit={onEditExcalidrawDiagram}
            />
          </div>
        )
      })}
      {children.substring(diagrams.at(-1)?.end ?? 0).trim() && (
        <MarkdownBody validNoteIds={validNoteIds} imageSize={imageSize} serif={serif} onNoteLinkClick={onNoteLinkClick} onSetImageSize={onSetImageSize}>
          {children.substring(diagrams.at(-1)?.end ?? 0)}
        </MarkdownBody>
      )}
    </div>
  )
}
