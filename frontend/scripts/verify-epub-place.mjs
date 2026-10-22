/**
 * An EPUB reopens where reading stopped, keeps its bookmark, and follows links
 * between chapters.
 *
 * Two defects here passed every unit test: the place was saved a block early
 * because images loading above it moved the text without a scroll event, and
 * each re-render rewrote the chapter's innerHTML (React 19 compares the
 * `{__html}` object by identity), wiping the bookmark marker and any selection.
 *
 *   make dev                  # app must already be serving
 *   node scripts/verify-epub-place.mjs        # LUMINARY_DOC=<id> to pick the book
 *
 * Restores the book's saved place and bookmark. Exits non-zero if any check fails.
 */
import { chromium } from "playwright-core"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
const API = process.env.LUMINARY_API ?? "http://localhost:7820"
const BLOCKS = "p, li, dt, dd, pre, figure, table, blockquote, h1, h2, h3, h4, h5, h6, div[data-type='equation']"

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
  docId = (docs.items ?? []).find((d) => d.format === "epub" && d.stage === "complete")?.id
}
if (!docId) {
  console.log("FAIL: needs an ingested EPUB (or LUMINARY_DOC)")
  process.exit(1)
}
const api = (path, init) => fetch(`${API}/documents/${docId}${path}`, init)
const json = (body) => ({ headers: { "content-type": "application/json" }, body: JSON.stringify(body) })

const saved = await api("/position").then((r) => (r.ok ? r.json() : null))
await api("/bookmark", { method: "DELETE" })
await api("/position", { method: "POST", ...json({}) })

// The longest chapter, so there is somewhere to scroll to.
const toc = (await (await api("/epub/toc")).json()).chapters
const longest = toc.reduce((a, b) => (b.word_count > a.word_count ? b : a))
console.log(`book: ${docId}\nchapter: ${longest.chapter_index} ${longest.title} (${longest.word_count} words)`)

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message.slice(0, 160)))
await page.addInitScript(() => {
  window.__contentRewrites = 0
  new MutationObserver((muts) => {
    for (const m of muts) if (m.target.classList?.contains("epub-reader-content")) window.__contentRewrites++
  }).observe(document, { subtree: true, childList: true })
})

const settle = () => page.waitForTimeout(3000)
const topBlock = () =>
  page.evaluate((selector) => {
    const c = document.querySelector(".epub-reader-content").parentElement
    const line = c.getBoundingClientRect().top + 16
    let found = null
    for (const b of c.querySelectorAll(selector)) if (b.getBoundingClientRect().top <= line) found = b
    return (found?.textContent ?? "").trim().slice(0, 60)
  }, BLOCKS)
const scrollBy = (dy) =>
  page.evaluate((y) => document.querySelector(".epub-reader-content").parentElement.scrollBy(0, y), dy)
// The reader's own scrolling: only this moves the saved place.
async function wheel(dy) {
  await page.locator(".epub-reader-content").hover()
  for (let left = dy; left !== 0;) {
    const step = Math.sign(left) * Math.min(Math.abs(left), 1000)
    await page.mouse.wheel(0, step)
    left -= step
    await page.waitForTimeout(50)
  }
}
const savedPlace = async () => {
  const p = await (await api("/position")).json()
  return `${p.last_epub_chapter_index}/${p.last_epub_block_index}`
}

async function run() {
  await page.goto(`${APP}/library?doc=${docId}`, { waitUntil: "domcontentloaded" })
  await page.waitForSelector(".epub-reader-content", { timeout: 30000 })
  await page.locator("button", { hasText: longest.title }).first().click()
  await settle()
  check("picking a chapter from the contents leaves the saved place alone", (await savedPlace()) === "null/null",
    await savedPlace())
  await wheel(await page.evaluate(() =>
    Math.round(document.querySelector(".epub-reader-content").parentElement.scrollHeight * 0.4)))
  await settle()
  const readHere = await topBlock()
  let pos = await (await api("/position")).json()
  check("scrolling saves the chapter and the block inside it",
    pos.last_epub_chapter_index === longest.chapter_index && pos.last_epub_block_index > 0,
    `chapter ${pos.last_epub_chapter_index} block ${pos.last_epub_block_index}`)

  await page.reload({ waitUntil: "domcontentloaded" })
  await page.waitForSelector(".epub-reader-content", { timeout: 30000 })
  await settle()
  check("reopening resumes at the block where reading stopped", (await topBlock()) === readHere,
    `${JSON.stringify(readHere)} vs ${JSON.stringify(await topBlock())}`)

  // A hidden Book View has no layout, and once saved its last block as the place.
  const beforeHiding = pos.last_epub_block_index
  await page.getByRole("button", { name: "Read", exact: true }).first().click()
  await settle()
  pos = await (await api("/position")).json()
  check("hiding the Book View leaves the saved place alone", pos.last_epub_block_index === beforeHiding,
    `block ${beforeHiding} -> ${pos.last_epub_block_index}`)
  await page.getByRole("button", { name: "Book View", exact: true }).first().click()
  await settle()

  await page.getByRole("button", { name: "Bookmark this place" }).click()
  await page.waitForTimeout(800)
  pos = await (await api("/position")).json()
  check("the bookmark is the place on screen",
    pos.epub_bookmark_chapter_index === longest.chapter_index && pos.epub_bookmark_block_index === pos.last_epub_block_index,
    `chapter ${pos.epub_bookmark_chapter_index} block ${pos.epub_bookmark_block_index}`)

  const rewritesBefore = await page.evaluate(() => window.__contentRewrites)
  for (let i = 0; i < 10; i++) { await scrollBy(600); await page.waitForTimeout(150) }
  await scrollBy(-6000)
  await page.waitForTimeout(500)
  check("scrolling never rewrites the chapter's HTML",
    (await page.evaluate(() => window.__contentRewrites)) === rewritesBefore)
  check("the bookmarked block stays marked", (await page.locator(".epub-reader-content [data-bookmark]").count()) === 1)

  const link = page.locator(".epub-reader-content a[data-chapter][href^='#']:not([href='#'])").first()
  if (await link.count()) {
    const target = await link.evaluate((a) => ({ chapter: Number(a.dataset.chapter), id: a.getAttribute("href").slice(1) }))
    await link.evaluate((a) => a.scrollIntoView({ block: "center" }))
    await wheel(100)
    await settle()
    const beforeLink = await savedPlace()
    await link.click()
    // Long enough for the other chapter to load and a place reported there to be saved.
    await settle()
    await settle()
    check("following a link leaves the saved place alone", (await savedPlace()) === beforeLink,
      `${beforeLink} -> ${await savedPlace()}`)
    const offset = await page.evaluate((id) => {
      const el = document.getElementById(id)
      const c = document.querySelector(".epub-reader-content")?.parentElement
      return el && c ? Math.round(el.getBoundingClientRect().top - c.getBoundingClientRect().top) : null
    }, target.id)
    check("a link into another chapter opens that chapter at its target",
      offset !== null && Math.abs(offset) < 40, `chapter ${target.chapter} #${target.id} at ${offset}px`)
  } else {
    console.log("  skip no link into another chapter in this chapter")
}

  // Away from the bookmark for certain: scrolling down and back up by the same
  // distance in a long chapter lands on it again.
  await page.evaluate(() => document.querySelector(".epub-reader-content").parentElement.scrollTo({ top: 0, behavior: "instant" }))
  await page.waitForTimeout(1000)
  await page.getByRole("button", { name: /Go to your bookmark/ }).click()
  await settle()
  check("go-to-bookmark returns to the bookmarked block", (await topBlock()) === readHere)

  await wheel(3000)
  await settle()
  const readOn = await topBlock()
  await page.reload({ waitUntil: "domcontentloaded" })
  await page.waitForSelector(".epub-reader-content", { timeout: 30000 })
  await settle()
  check("reopening goes where reading stopped, not to the bookmark", readOn !== readHere && (await topBlock()) === readOn,
    `${JSON.stringify(readOn)} vs ${JSON.stringify(await topBlock())}`)
}

try {
  await run()
} catch (e) {
  check("the run finished", false, e.message.split("\n")[0])
} finally {
  await browser.close()
}

await api("/bookmark", { method: "DELETE" })
if (saved) {
  await api("/position", { method: "POST", ...json(saved) })
  if (saved.epub_bookmark_chapter_index != null) {
    await api("/bookmark", { method: "PUT", ...json({ epub_chapter_index: saved.epub_bookmark_chapter_index, epub_block_index: saved.epub_bookmark_block_index ?? 0 }) })
  }
}
console.log("  (restored the book's saved place and bookmark)")
console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
process.exit(failures.length ? 1 : 0)
