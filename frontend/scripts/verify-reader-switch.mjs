/**
 * Switching documents in the reader starts the new document's panel clean.
 *
 * The reader stayed mounted when the open document changed in-app (search, a
 * citation into another document, a collection link), so the docked note
 * composer kept the previous document's draft and its autosave kept writing to
 * that note. A full page load remounts everything and hides the defect, so the
 * switch here is an in-app navigation.
 *
 *   make dev                  # app must already be serving
 *   node scripts/verify-reader-switch.mjs
 *
 * Creates one note and deletes it. Exits non-zero if any check fails.
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

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message.slice(0, 160)))

const docs = await (await fetch(`${API}/documents?page=1&page_size=25&sort=last_accessed`)).json()
const ready = (docs.items ?? []).filter((d) => d.stage === "complete")
if (ready.length < 2) {
  console.log("FAIL: needs two ingested documents")
  await browser.close()
  process.exit(1)
}
const [a, b] = ready
console.log(`from: ${a.title}\nto:   ${b.title}`)

await page.goto(`${APP}/library?doc=${a.id}`, { waitUntil: "domcontentloaded" })
await page.waitForTimeout(3000)
await page.locator("button[aria-pressed]").filter({ hasText: /^Notes$/ }).first().click()
await page.waitForTimeout(1000)
await page.locator("button").filter({ hasText: /^New note$/ }).first().click()
await page.waitForTimeout(1000)

const marker = `reader-switch-check ${Date.now()}`
const composer = page.locator('[data-testid="docked-note-composer"]')
await composer.locator(".cm-content").click()
await page.keyboard.type(marker)
await page.waitForTimeout(2500) // autosave debounce, so the draft exists as a note

// In-app, the way a citation or the search dialog moves between documents.
await page.evaluate((id) => {
  window.history.pushState({}, "", `/library?doc=${id}`)
  window.dispatchEvent(new PopStateEvent("popstate"))
}, b.id)
await page.waitForTimeout(3000)

const stillShown = await page.evaluate((m) => document.body.innerText.includes(m), marker)
check("the next document's panel does not show the previous document's draft", !stillShown)

// Typing after the switch must not land in the previous document's note.
if (await composer.count()) {
  await composer.locator(".cm-content").click()
  await page.keyboard.type(" typed-after-switch")
  await page.waitForTimeout(2500)
}

const notes = await (await fetch(`${API}/notes`)).json()
const mine = notes.filter((n) => (n.content ?? "").includes(marker))
const leaked = mine.some((n) => n.content.includes("typed-after-switch"))
check("nothing typed after the switch was saved into the previous document's note", !leaked)
check("the draft written on the first document was saved", mine.length === 1, `${mine.length} note(s)`)

// Arriving with a note (Back from the full note page lands on ?doc=&note=), then
// leaving through the library: the next document must not open on that note.
if (mine.length === 1) {
  await page.goto(`${APP}/library?doc=${a.id}&note=${mine[0].id}`, { waitUntil: "domcontentloaded" })
  await page.waitForTimeout(3000)
  check("a document opened with ?note= shows that note",
    await page.evaluate((m) => document.body.innerText.includes(m), marker))
  await page.getByRole("button", { name: /Back to library/ }).first().click()
  await page.waitForTimeout(2000)
  await page.getByText(b.title, { exact: false }).first().click()
  await page.waitForTimeout(3000)
  const onB = await page.evaluate(() => new URLSearchParams(location.search).get("doc"))
  check("the library opened the second document", onB === b.id, onB ?? "no doc")
  check("the second document does not open on the first document's note",
    !(await page.evaluate((m) => document.body.innerText.includes(m), marker)))
}

for (const n of mine) await fetch(`${API}/notes/${n.id}`, { method: "DELETE" })
console.log(`  (removed ${mine.length} note(s) this check created)`)

await browser.close()
console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
process.exit(failures.length ? 1 : 0)
