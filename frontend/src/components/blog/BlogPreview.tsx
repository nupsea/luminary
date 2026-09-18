// BlogPreview — faithful in-app replica of the Astro site's BlogPost rendering
// (prose-lg / Inter / slate header + KaTeX math). Shared by the publish and
// edit dialogs.

import type { CSSProperties } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"

import "./blogPreview.css"

// Kept in sync with `_IMAGE_SIZE_STYLE` in backend/app/services/blog_service.py
// (render_sized_images) -- this is a preview of what that function turns the
// same `|small|medium|large` alt hint into on the actual published page.
const SIZE_STYLE: Record<string, CSSProperties> = {
  small: { float: "right", maxWidth: 220, width: "100%", margin: "0.25rem 0 1.25rem 1.5rem", borderRadius: 8 },
  medium: { display: "block", maxWidth: 480, width: "100%", margin: "1.5rem auto", borderRadius: 8 },
  large: { display: "block", maxWidth: 800, width: "100%", margin: "1.5rem auto", borderRadius: 8 },
}

function parseSizedAlt(alt?: string): { alt: string; size?: keyof typeof SIZE_STYLE } {
  if (!alt) return { alt: "" }
  const idx = alt.lastIndexOf("|")
  if (idx === -1) return { alt }
  const size = alt.slice(idx + 1)
  if (size === "small" || size === "medium" || size === "large") {
    return { alt: alt.slice(0, idx), size }
  }
  return { alt }
}

function formatHeaderDate(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })
}

export function BlogPreview({
  title,
  description,
  pubDate,
  updatedDate,
  heroImage,
  markdown,
}: {
  title: string
  description: string
  pubDate: string
  updatedDate?: string
  heroImage?: string
  markdown: string
}) {
  return (
    <div className="blog-preview rounded-lg border border-slate-200">
      <article className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-8 text-center">
          <div className="mb-3 text-slate-500">
            <time>{formatHeaderDate(pubDate)}</time>
            {updatedDate && (
              <div className="italic">Last updated on {formatHeaderDate(updatedDate)}</div>
            )}
          </div>
          <h1 className="mb-3 text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            {title || "Untitled"}
          </h1>
          {description && (
            <p className="mx-auto max-w-2xl text-xl text-slate-600">{description}</p>
          )}
          <hr className="mt-6 border-slate-200" />
        </div>
        {heroImage && (
          <img src={heroImage} alt="" className="mb-8 w-full rounded-xl shadow-lg" />
        )}
        <div className="prose prose-lg mx-auto">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={{
              img: ({ src, alt }) => {
                const parsed = parseSizedAlt(alt)
                return (
                  <img
                    src={src}
                    alt={parsed.alt}
                    style={parsed.size ? SIZE_STYLE[parsed.size] : undefined}
                  />
                )
              },
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      </article>
    </div>
  )
}
