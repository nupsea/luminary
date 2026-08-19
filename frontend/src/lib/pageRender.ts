/**
 * Render a page in the desktop shell's hidden webview.
 *
 * Only pages that *compute* their content need this. Measured across four
 * JavaScript-heavy articles, rendering changed nothing on three of them; on the
 * fourth it was the difference between 0 and 78 figures. Everywhere without a
 * desktop shell — the browser dev server, Docker, the script installs — this
 * returns null and the backend's static fetch is the whole story, which measured
 * 100% of prose and headings on 8 of 9 test articles.
 *
 * Never throws: a page that will not render is not a broken article.
 */

import { logger } from "@/lib/logger"

/** Rendering is slower than a fetch, so it must not hold an import open. */
const RENDER_BUDGET_MS = 35_000

interface TauriBridge {
  core?: { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> }
}

function bridge(): TauriBridge["core"] | null {
  const injected = (window as unknown as { __TAURI__?: TauriBridge }).__TAURI__
  return injected?.core?.invoke ? injected.core : null
}

/** Whether a hidden webview is available to render with. */
export function canRender(): boolean {
  return bridge() !== null
}

/**
 * Why an import took the path it did.
 *
 * `unavailable` is the normal answer everywhere without a desktop shell, and is
 * not a fault. It is reported anyway because a silent fallback is
 * indistinguishable from a silent failure -- which is exactly what cost two test
 * rounds to work out.
 */
export type RenderState = "ok" | "unavailable" | "failed"

export interface RenderOutcome {
  html: string | null
  state: RenderState
  /**
   * Why, when the state is not `ok`.
   *
   * This travels to the backend rather than the console. A rejected invoke
   * reports itself only to the page, and the desktop shell has no console
   * anyone reads -- so a shell-side failure was indistinguishable from a page
   * that needed no rendering, and cost three test rounds to identify.
   */
  detail?: string
}

/** Distinguishes a timeout from an answer, without unwrapping a union at the call site. */
const TIMED_OUT = Symbol("render-timeout")

/**
 * The DOM after the page's scripts have run, or null when unavailable.
 *
 * The budget is a second line of defence: the shell already times out, and this
 * guards against a shell that never answers at all.
 */
export async function renderPage(url: string): Promise<RenderOutcome> {
  const core = bridge()
  if (!core?.invoke) return { html: null, state: "unavailable" }

  try {
    const html = await Promise.race([
      core.invoke("render_page", { url }),
      new Promise<typeof TIMED_OUT>((resolve) =>
        setTimeout(() => resolve(TIMED_OUT), RENDER_BUDGET_MS),
      ),
    ])
    if (typeof html === "string" && html.trim()) return { html, state: "ok" }
    const detail =
      html === TIMED_OUT
        ? `the shell did not answer within ${RENDER_BUDGET_MS}ms`
        : "the shell returned no document"
    logger.info("[render] falling back to the static fetch", detail)
    return { html: null, state: "failed", detail }
  } catch (err) {
    const detail = String(err)
    logger.info("[render] falling back to the static fetch", detail)
    return { html: null, state: "failed", detail }
  }
}
