import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import ReactMarkdown from "react-markdown"
import type { PluggableList } from "unified"
import { SOURCE_LINE_ATTR, rehypeSourceLine } from "./rehypeSourceLine"

/**
 * Guards how the plugin is *wired*, not what it does. Calling
 * `rehypeSourceLine(offset)` and putting the result in a plugin list type-checks
 * and passes a direct unit test, but unified calls every entry as an attacher —
 * so the already-applied transformer runs with no tree and throws out of
 * <Markdown>, unmounting the whole app. Only a render catches it.
 */
function render(rehypePlugins: PluggableList) {
  return renderToStaticMarkup(<ReactMarkdown rehypePlugins={rehypePlugins}>{"# One\n\ntwo\n"}</ReactMarkdown>)
}

describe("rehypeSourceLine wiring", () => {
  it("renders and stamps source lines when passed as [plugin, options]", () => {
    const html = render([[rehypeSourceLine, 0]])
    expect(html).toContain(`${SOURCE_LINE_ATTR}="1"`)
    expect(html).toContain(`${SOURCE_LINE_ATTR}="3"`)
  })

  it("applies the line offset", () => {
    expect(render([[rehypeSourceLine, 10]])).toContain(`${SOURCE_LINE_ATTR}="11"`)
  })

  it("renders with no options", () => {
    expect(render([rehypeSourceLine])).toContain(`${SOURCE_LINE_ATTR}="1"`)
  })
})
