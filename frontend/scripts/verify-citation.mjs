/**
 * Citation deep-links, in a real browser, across document types.
 *
 * The unit suite cannot cover this and has twice said the feature worked while
 * the app showed nothing. Which component renders a document depends on its
 * format — transcripts use YouTubeTranscriptView, PDFs open the PDF viewer,
 * everything else the universal reader — and `tsc` type-checks every one of them
 * identically. Four separate causes were found here that no test could see:
 * whitespace the chunk text collapsed, breadcrumbs the prose never contains, a
 * landing tab that hid the passage, and sections that render only when scrolled
 * into view.
 *
 *   make luminary            # app must already be serving
 *   make verify-citation
 *
 * Asks one question across the whole library, clicks every source chip it gets
 * back, and reports whether each one marked its passage. Needs a live model, so
 * it is a manual check rather than a CI gate. Exits non-zero if any chip fails.
 */
import { chromium } from "playwright-core"
import fs from "node:fs"
import path from "node:path"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
// Screenshots beside the run: a citation that "marked" can still have landed
// somewhere useless, and the picture is the only way to see that.
const OUT = path.resolve(import.meta.dirname, "../.citation-verify")
fs.mkdirSync(OUT, { recursive: true })
const QUESTION =
  process.env.LUMINARY_QUESTION ??
  "What are the main ideas across my documents about optimisation and retrieval?"

async function launch() {
  for (const channel of [undefined, "chrome", "msedge", "chromium"]) {
    try { return await chromium.launch(channel ? { channel } : {}) } catch { /* try next */ }
  }
  throw new Error("No Chromium-family browser. Install one with `npx playwright install chromium`.")
}

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message.slice(0, 160)))

await page.goto(`${APP}/chat`, { waitUntil: "networkidle" })
await page.waitForTimeout(1200)
const box = page.locator("textarea").last()
await box.click()
await box.fill(QUESTION)
await box.press("Enter")
console.log(`asked: ${QUESTION}`)

// A citation chip is the only button whose title carries a multi-line tooltip.
async function chips() {
  const out = []
  for (const h of await page.locator("button[title]").all()) {
    const t = await h.getAttribute("title")
    if (t && t.includes("\n")) out.push({ h, t })
  }
  return out
}

let found = []
for (let i = 0; i < 120 && found.length === 0; i++) {
  found = await chips()
  if (!found.length) await page.waitForTimeout(3000)
}
if (found.length === 0) {
  console.log("FAIL: the answer produced no source chips")
  await browser.close()
  process.exit(1)
}

const titles = found.map((f) => f.t)
let marked = 0
let inView = 0
for (let i = 0; i < titles.length; i++) {
  // Re-open the chat between clicks: clicking navigates away, and the persisted
  // session rehydrates its chips.
  if (i > 0) {
    await page.goto(`${APP}/chat`, { waitUntil: "networkidle" })
    for (let w = 0; w < 25; w++) {
      if ((await chips()).length > i) break
      await page.waitForTimeout(1000)
    }
  }
  const current = await chips()
  if (current.length <= i) {
    console.log(`  chip ${i}: unavailable after reload`)
    continue
  }
  await current[i].h.click()
  await page.waitForTimeout(7000)
  // Two ways a passage can be marked: wrapped in the prose and transcript views,
  // drawn as an overlay on the PDF page. Either counts.
  const shown = await page.evaluate(() => {
    const mark = document.querySelector(".luminary-citation-mark, [data-citation-highlight]")
    const rect = mark?.getBoundingClientRect()
    // Marked is not the same as delivered: a highlight the reader has to hunt
    // for reads as no highlight at all, so measure how much of it is on screen.
    const onScreen = rect
      ? Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0)
      : 0
    const zoom = document.querySelector('button[aria-label="Zoom presets"]')
    return {
      inText: document.querySelectorAll(".luminary-citation-mark").length,
      onPage: document.querySelectorAll("[data-citation-highlight]").length,
      inView: Boolean(rect) && onScreen >= Math.min(rect.height, 40),
      zoom: zoom ? zoom.textContent.trim() : null,
    }
  })
  const total = shown.inText + shown.onPage
  if (total > 0) marked++
  if (shown.inView) inView++
  const how = shown.onPage > 0 ? "on the page" : shown.inText > 0 ? "in the text" : "NOT MARKED"
  await page.screenshot({ path: path.join(OUT, `chip-${i}.png`) })
  const label = titles[i].split("\n")[0].slice(0, 44)
  const where = shown.inView ? "in view" : total > 0 ? "OFF SCREEN" : "-"
  console.log(`  chip ${i} [${label}] ${how}, ${where}${shown.zoom ? `, zoom ${shown.zoom}` : ""}`)
}

console.log(`\nmarked ${marked}/${titles.length}, in view ${inView}/${titles.length}`)
console.log(`screenshots in ${OUT}`)
await browser.close()
process.exit(marked === titles.length && inView === titles.length ? 0 : 1)
