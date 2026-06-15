// BlogPreview — faithful in-app replica of the Astro site's BlogPost rendering
// (prose-lg / Inter / slate header + KaTeX math). Shared by the publish and
// edit dialogs.

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"

import "./blogPreview.css"

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
          >
            {markdown}
          </ReactMarkdown>
        </div>
      </article>
    </div>
  )
}
