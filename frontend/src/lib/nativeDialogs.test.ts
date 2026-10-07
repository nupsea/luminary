/**
 * No window.confirm / alert / prompt anywhere in the app.
 *
 * The desktop shell's WKWebView (wry) implements none of WKUIDelegate's
 * JavaScript panels, so confirm() returns false without showing anything:
 * removing a highlight silently did nothing there while working in a browser.
 */
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"

import { describe, expect, it } from "vitest"

const SRC = join(import.meta.dirname, "..")
const NATIVE_DIALOG = /(?<![.\w])(confirm|alert|prompt)\(|window\.(confirm|alert|prompt)\(/

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    if (!/\.tsx?$/.test(name) || name.includes(".test.") || name === "api.ts") return []
    return [path]
  })
}

describe("native dialogs", () => {
  it("are never called", () => {
    const offenders = sources(SRC).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line) => (/^\s*\*/.test(line) ? "" : line.replace(/\/\/.*$/, "")))
        .flatMap((line, i) => (NATIVE_DIALOG.test(line) ?[`${relative(SRC, path)}:${i + 1}: ${line.trim()}`] : [])),
    )
    expect(offenders).toEqual([])
  })
})
