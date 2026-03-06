/**
 * MarkdownRenderer — wraps react-markdown with remark-gfm and rehype-highlight.
 *
 * Usage: <MarkdownRenderer>{markdownString}</MarkdownRenderer>
 *
 * Applies Tailwind prose classes so all markdown elements are styled consistently.
 * rehype-highlight adds syntax highlighting to fenced code blocks.
 */

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"

interface MarkdownRendererProps {
  children: string
  className?: string
}

export function MarkdownRenderer({ children, className }: MarkdownRendererProps) {
  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
