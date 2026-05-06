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
  onEditExcalidrawDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
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

function MermaidBlock({ chart }: { chart: string }) {
  const generatedId = useId()
  const [svg, setSvg] = useState("")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function renderMermaid() {
      try {
        setError(null)
        const mermaid = (await import("mermaid")).default
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: document.documentElement.classList.contains("dark") ? "dark" : "default",
        })
        const { svg } = await mermaid.render(`mermaid-${generatedId.replace(/:/g, "")}`, chart)
        if (!cancelled) setSvg(svg)
      } catch (err) {
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

function MarkdownBody({ children, className, validNoteIds, imageSize = "medium" }: MarkdownRendererProps) {
  const processed = preprocessLinks(children)

  return (
    <div className={cn(
      "prose prose-base dark:prose-invert max-w-none font-serif leading-relaxed text-foreground/90",
      "prose-headings:font-sans prose-headings:font-bold prose-headings:tracking-tight",
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
            let size: ImageSize = imageSize
            if (alt && alt.includes("|")) {
              const parts = alt.split("|")
              const potentialSize = parts[1].trim().toLowerCase()
              if (["small", "medium", "large"].includes(potentialSize)) {
                size = potentialSize as ImageSize
              }
            }
            return (
              <img
                src={src}
                alt={alt}
                className={cn(
                  "rounded-lg shadow-md mx-auto my-4 block",
                  size === "small" && "max-w-[240px] max-h-[200px] object-contain",
                  size === "medium" && "max-w-[480px] max-h-[360px] object-contain",
                  size === "large" && "max-w-[800px] max-h-[600px] object-contain"
                )}
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
    </div>
  )
}

export function MarkdownRenderer({
  children,
  className,
  validNoteIds,
  imageSize = "medium",
  onEditExcalidrawDiagram,
}: MarkdownRendererProps) {
  const diagrams = findExcalidrawDiagrams(children)

  if (diagrams.length === 0) {
    return (
      <MarkdownBody className={className} validNoteIds={validNoteIds} imageSize={imageSize}>
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
              <MarkdownBody validNoteIds={validNoteIds} imageSize={imageSize}>
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
        <MarkdownBody validNoteIds={validNoteIds} imageSize={imageSize}>
          {children.substring(diagrams.at(-1)?.end ?? 0)}
        </MarkdownBody>
      )}
    </div>
  )
}
