/**
 * A note open in the reader's docked panel leads back to the document's notes and on to the
 * next one, saving what was typed first; opening a note does not rewrite its sources.
 *
 * With a note open the panel showed only that note: the Notes tab and the "N notes" chip were
 * already the current face, and Done went wherever the panel was before. And the composer sent
 * this document as the note's only source, so opening a two-source note dropped the other.
 *
 *   make dev                  # app must already be serving
 *   node scripts/verify-note-nav.mjs
 *
 * Creates three notes and deletes them. Needs two ingested documents, no model.
 */
import { chromium } from "playwright-core"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
const API = process.env.LUMINARY_API ?? "http://localhost:7820"

async function launch() {
  for (const channel of [undefined, "chrome", "msedge", "chromium"]) {
    try { return await chromium.launch(channel ? { channel } : {}) } catch { /* try next */ }
  }
  throw new Error("No Chromium-family browser. Install one with `npx playwright install chromium`.")
}

const failures = []
function check(name, ok, detail = "") {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${detail ? ` -- ${detail}` : ""}`)
  if (!ok) failures.push(name)
}

const docs = await (await fetch(`${API}/documents?page=1&page_size=25&sort=last_accessed`)).json()
const ready = (docs.items ?? []).filter((d) => d.stage === "complete")
if (ready.length < 2) {
  console.log("FAIL: needs two ingested documents")
  process.exit(1)
}
const [a, b] = ready
console.log(`document: ${a.title}`)

const stamp = Date.now()
async function createNote(title, sources) {
  const resp = await fetch(`${API}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: `${title} body`,
      title,
      document_id: sources[0],
      source_document_ids: sources,
    }),
  })
  return resp.json()
}
const created = []
for (const [i, sources] of [[a.id], [a.id, b.id], [a.id]].entries()) {
  created.push(await createNote(`note-nav-check ${stamp} ${i}`, sources))
}
const twoSource = created[1]

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message.slice(0, 160)))
const composer = page.locator('[data-testid="docked-note-composer"]')
const openTitle = () => composer.locator("input").first().inputValue()

try {
  await page.goto(`${APP}/library?doc=${a.id}&note=${twoSource.id}`, { waitUntil: "domcontentloaded" })
  await page.waitForTimeout(4000)
  check("the panel opens on the note", (await openTitle()) === twoSource.title, await openTitle())
  const after = await (await fetch(`${API}/notes/${twoSource.id}`)).json()
  check("opening a two-source note keeps both sources",
    after.source_document_ids.length === 2, JSON.stringify(after.source_document_ids))

  const positionLabel = composer.getByText(/\d+ of \d+/)
  const hasNav = (await positionLabel.count()) > 0
  check("the open note shows its place among the document's notes", hasNav,
    hasNav ? await positionLabel.first().innerText() : "no position shown")
  if (!hasNav) throw new Error("no note navigation to exercise")

  const marker = ` typed-before-next-${stamp}`
  await composer.locator(".cm-content").click()
  await page.keyboard.press("End")
  await page.keyboard.type(marker)
  const before = await openTitle()
  const next = composer.getByRole("button", { name: "Next note" })
  const prev = composer.getByRole("button", { name: "Previous note" })
  const step = (await next.isDisabled()) ? prev : next
  await step.click()
  await page.waitForTimeout(2000)
  const moved = await openTitle()
  check("Next/Previous opens another note in place", moved !== before, `${before} -> ${moved}`)
  const saved = await (await fetch(`${API}/notes/${twoSource.id}`)).json()
  check("what was typed before moving on was saved", saved.content.includes(marker.trim()))
  check("the note it moved to shows its own text, not the last one's",
    !(await composer.innerText()).includes(marker.trim()))

  await composer.getByRole("button", { name: "All notes" }).click()
  await page.waitForTimeout(1500)
  check("All notes returns to the document's list",
    (await page.locator('[data-testid="docked-notes-list"]').count()) === 1 && (await composer.count()) === 0)
} catch (e) {
  // A run cut short by a failed check reports that check; anything else is a crash.
  if (failures.length === 0) throw e
} finally {
  for (const n of created) await fetch(`${API}/notes/${n.id}`, { method: "DELETE" })
  console.log(`  (removed ${created.length} note(s) this check created)`)
  await browser.close()
}

console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
process.exit(failures.length ? 1 : 0)
