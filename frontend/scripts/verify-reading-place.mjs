/**
 * Only the reader's own scrolling moves the saved reading place.
 *
 * A citation from Ask opens the reader on the cited section. Saved after the
 * Read view's dwell, that section replaced where reading had stopped, and the
 * resume offer and chapter backfill followed it.
 *
 *   make dev                  # app must already be serving
 *   node scripts/verify-reading-place.mjs     # LUMINARY_DOC=<id> to pick the document
 *
 * Restores the document's saved place. Exits non-zero if any check fails.
 */
import { chromium } from "playwright-core"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
const API = process.env.LUMINARY_API ?? "http://localhost:7820"
// Past the Read view's dwell (POSITION_SETTLE_MS), so a section that would be saved is.
const DWELL_PAST_MS = 12_000

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

let docId = process.env.LUMINARY_DOC
if (!docId) {
  const docs = await (await fetch(`${API}/documents?page=1&page_size=100`)).json()
  docId = (docs.items ?? []).find((d) => d.format !== "pdf" && d.stage === "complete")?.id
}
if (!docId) {
  console.log("FAIL: needs an ingested document (or LUMINARY_DOC)")
  process.exit(1)
}
const api = (path, init) => fetch(`${API}/documents/${docId}${path}`, init)
const json = (body) => ({ headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
const savedSection = async () => (await (await api("/position")).json()).last_section_id

const sections = (await (await api("")).json()).sections
if (sections.length < 3) {
  console.log("FAIL: needs a document with at least three sections")
  process.exit(1)
}
const saved = await api("/position").then((r) => (r.ok ? r.json() : null))
const readTo = sections[0]
const cited = sections[Math.floor(sections.length / 2)]
await api("/position", { method: "POST", ...json({ last_section_id: readTo.id, last_section_heading: readTo.heading }) })
console.log(`document: ${docId}\nread to: ${readTo.heading}\ncited: ${cited.heading}`)

const browser = await launch()
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message.slice(0, 160)))
  await page.goto(`${APP}/library?doc=${docId}&section_id=${cited.id}`, { waitUntil: "domcontentloaded" })
  const citedEl = page.locator(`#read-sec-${cited.id}`)
  await citedEl.waitFor({ timeout: 30000 })
  await page.waitForTimeout(DWELL_PAST_MS)
  let now = await savedSection()
  check("a cited section is not saved as the reading place", now === readTo.id, `saved ${now}`)

  await citedEl.hover()
  for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, 300); await page.waitForTimeout(150) }
  await page.waitForTimeout(DWELL_PAST_MS)
  now = await savedSection()
  check("scrolling on from it saves the section being read", now != null && now !== readTo.id, `saved ${now}`)
} finally {
  await browser.close()
  await api("/position", { method: "POST", ...json(saved ?? {}) })
  console.log("  (restored the document's saved place)")
}
console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
process.exit(failures.length ? 1 : 0)
