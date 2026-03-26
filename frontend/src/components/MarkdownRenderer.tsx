/**
 * MarkdownRenderer — wraps react-markdown with remark-gfm and rehype-highlight.
 *
 * Usage: <MarkdownRenderer>{markdownString}</MarkdownRenderer>
 *
 * Applies Tailwind prose classes so all markdown elements are styled consistently.
 * rehype-highlight adds syntax highlighting to fenced code blocks.
 *
 * S171: [[id|text]] note link markers are preprocessed into backtick-wrapped
 * `[note:id|text]` tokens. The custom `code` component handler intercepts these
 * and renders them as inline chips:
 *   - indigo chip when validNoteIds is undefined or the id is in the set
 *   - muted-red chip with strikethrough when validNoteIds is provided and id is absent
 */

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"

interface MarkdownRendererProps {
  children: string
  className?: string
  /** When provided, note link IDs NOT in this set are rendered as broken (muted red). */
  validNoteIds?: Set<string>
}

const NOTE_LINK_MARKER_RE = /\[\[([a-f0-9-]+)\|([^\]]+)\]\]/g

/**
 * Replace [[id|text]] markers with `[note:id|text]` so the custom `code`
 * component can intercept and render them as chips. Plain code blocks are
 * unaffected since the sentinel `[note:` prefix is unique.
 */
function preprocessLinks(content: string): string {
  return content.replace(
    NOTE_LINK_MARKER_RE,
    (_m, id, text) => `\`[note:${id}|${text}]\``
  )
}

export function MarkdownRenderer({ children, className, validNoteIds }: MarkdownRendererProps) {
  const processed = preprocessLinks(children)

  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
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
