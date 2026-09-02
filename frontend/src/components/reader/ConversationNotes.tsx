// The Notes tab's renderer. `conversation` is the one summary mode whose prompt
// asks for a JSON object rather than prose (`summarizer.py` MODE_INSTRUCTIONS),
// so markdown-rendering it shows the reader a fenced JSON blob.
//
// Two shapes reach here, and which one arrives is the backend's decision, not a
// setting: a meeting has decisions and owners, a talk has points and references.
// Anything the model omits is simply absent.

import { MarkdownRenderer } from "@/components/MarkdownRenderer"

interface ActionItem {
  owner?: string
  task?: string
}

interface ConversationSummary {
  timeline?: unknown
  decisions?: unknown
  points?: unknown
  references?: unknown
  action_items?: unknown
}

const FENCE = /^\s*```(?:json)?\s*|\s*```\s*$/g

/** The object the model returned, or null if this is not one.
 *
 *  Never throws: a model may return prose for any prompt, and a blank panel
 *  would be a worse answer than the text it actually produced.
 */
function parseConversationSummary(content: string): ConversationSummary | null {
  const stripped = (content || "").replace(FENCE, "").trim()
  if (!stripped.startsWith("{")) return null
  try {
    const parsed: unknown = JSON.parse(stripped)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
    return parsed as ConversationSummary
  } catch {
    return null
  }
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((v): v is string => typeof v === "string" && v.trim().length > 0)
}

function actionList(value: unknown): ActionItem[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (v): v is ActionItem => Boolean(v) && typeof v === "object" && !Array.isArray(v)
  )
}

function Section({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <section className="space-y-1.5">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      <ul className="ml-4 list-disc space-y-1 text-sm">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

export function ConversationNotes({ content }: { content: string }) {
  const parsed = parseConversationSummary(content)
  if (!parsed) return <MarkdownRenderer>{content}</MarkdownRenderer>

  const timeline = textList(parsed.timeline)
  const decisions = textList(parsed.decisions)
  const points = textList(parsed.points)
  const references = textList(parsed.references)
  const actions = actionList(parsed.action_items)

  // Parsed to an object with nothing recognisable in it. Showing the source
  // beats showing an empty panel that looks like a finished summary.
  if (
    timeline.length + decisions.length + points.length + references.length + actions.length ===
    0
  ) {
    return <MarkdownRenderer>{content}</MarkdownRenderer>
  }

  return (
    <div className="space-y-4">
      <Section title="Timeline" items={timeline} />
      <Section title="Key Points" items={points} />
      <Section title="Decisions" items={decisions} />
      {actions.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Action Items
          </h3>
          <ul className="ml-4 list-disc space-y-1 text-sm">
            {actions.map((a, i) => (
              <li key={i}>
                {a.owner ? <span className="font-medium">{a.owner}: </span> : null}
                {a.task ?? ""}
              </li>
            ))}
          </ul>
        </section>
      )}
      <Section title="References" items={references} />
    </div>
  )
}
