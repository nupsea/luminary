import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import { ConversationNotes } from "./ConversationNotes"

const html = (content: string) => renderToStaticMarkup(<ConversationNotes content={content} />)

// The shape a talk produces, fenced exactly as the model returns it.
const TALK = `\`\`\`json
{
  "timeline": ["Opens on why agents changed the workflow"],
  "points": ["Delegating to several agents at once"],
  "references": ["nanoGPT"]
}
\`\`\``

describe("ConversationNotes", () => {
  it("renders the talk shape as sections rather than a JSON blob", () => {
    const out = html(TALK)
    expect(out).toContain("Delegating to several agents at once")
    expect(out).toContain("nanoGPT")
    // Structural, because the text assertions above pass either way: markdown
    // renders the fence to `<pre>` with the same words inside it, and escapes
    // the quotes, so asserting on the JSON's own characters catches nothing.
    // A code block is exactly what the reader saw before.
    expect(out).not.toContain("<pre")
    expect(out).toContain("<li")
  })

  it("renders a meeting's owners with its action items", () => {
    const out = html(
      JSON.stringify({
        timeline: ["Kickoff"],
        decisions: ["Ship behind a flag"],
        action_items: [{ owner: "Platform", task: "Add the migration" }],
      })
    )
    expect(out).toContain("Ship behind a flag")
    expect(out).toContain("Platform")
    expect(out).toContain("Add the migration")
  })

  it("falls back to the source text when the model returned prose", () => {
    // Any prompt can come back as prose. A blank panel would be a worse answer
    // than the text the model actually produced.
    const out = html("The speaker argues that agents change the unit of work.")
    expect(out).toContain("agents change the unit of work")
  })

  it("falls back when the object parses but carries nothing recognisable", () => {
    const out = html('{"summary": "wrong keys entirely"}')
    expect(out).toContain("wrong keys entirely")
  })

  it("drops non-string entries instead of rendering undefined", () => {
    const out = html(JSON.stringify({ points: ["real point", null, 7, ""] }))
    expect(out).toContain("real point")
    expect(out).not.toContain("undefined")
    expect(out).not.toContain(">7<")
  })
})
