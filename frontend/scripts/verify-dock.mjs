/**
 * The docked assistant, in a real browser.
 *
 * The rung's rule is that asking about a passage does not leave the passage, and
 * that a conversation docked beside a document is that document's own: neither
 * the question nor the scope may reach the Ask page's conversation. Neither
 * property is visible to `tsc` or to a unit test -- both are about two mounted
 * components sharing one store.
 *
 *   make luminary          # app must already be serving
 *   make verify-dock
 *
 * Needs a live model. Exits non-zero if any check fails.
 *
 * It drives the running dev server, so give an edit a moment to land: a run
 * started before HMR applies measures the previous bundle and reports failures
 * that belong to code you have already changed.
 */
import { chromium } from "playwright-core"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"

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

// A question on the Ask page first: it is what must survive everything after.
await page.goto(`${APP}/chat`, { waitUntil: "domcontentloaded" })
await page.waitForTimeout(2500)
const box = page.locator("textarea").last()
await box.click()
await box.fill("What is retrieval augmented generation?")
await box.press("Enter")
await page.waitForTimeout(4000)
const askPageThread = await page.evaluate(() => {
  const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
  return raw.state?.chatThreads?.page?.messages?.length ?? 0
})
check("the Ask page has a conversation", askPageThread > 0, `${askPageThread} messages`)

// Open a document.
const API = process.env.LUMINARY_API ?? "http://localhost:7820"
// Prose, deliberately: the selection check below drags across a paragraph, and
// a PDF's text layer is spans over a canvas.
const doc = await page.evaluate(async (api) => {
  const res = await fetch(`${api}/documents?page=1&page_size=25&sort=last_accessed`)
  const data = await res.json()
  const items = data.items ?? []
  const prose = items
    .filter((d) => ["md", "html", "txt", "epub", "docx"].includes(d.format))
    .sort((a, b) => (b.word_count ?? 0) - (a.word_count ?? 0))
  return prose[0] ?? items[0] ?? null
}, API)
const docId = doc?.id ?? null
if (doc) console.log(`document: ${doc.title} (${doc.format}, ${doc.word_count ?? 0} words)`)
if (!docId) {
  console.log("FAIL: the library is empty")
  await browser.close()
  process.exit(1)
}
await page.goto(`${APP}/library?doc=${docId}`, { waitUntil: "domcontentloaded" })
await page.waitForTimeout(3000)

const ask = page.getByRole("button", { name: "Ask AI", exact: true })
check("the reader panel offers Ask", (await ask.count()) > 0)
if (await ask.count()) {
  await ask.first().click()
  await page.waitForTimeout(1200)
}

// A docked conversation carries no page chrome.
const chrome = await page.evaluate(() => ({
  sessions: document.querySelectorAll('button[title="Hide chat list"], button[title="Show chat list"]').length,
  scopePicker: document.querySelectorAll('button[title="All documents"]').length,
  composers: document.querySelectorAll("textarea").length,
}))
check("no session list in the dock", chrome.sessions === 0)
check("no scope picker in the dock", chrome.scopePicker === 0)
check("the dock has a composer", chrome.composers > 0)

// Ask inside the reader.
const docked = page.locator("textarea").last()
await docked.click()
await docked.fill("Summarise this document in one sentence.")
await docked.press("Enter")
for (let i = 0; i < 40; i++) {
  await page.waitForTimeout(3000)
  const done = await page.evaluate(() => /Ran on this machine|Sent to the cloud/.test(document.body.innerText))
  if (done) break
}

const threads = await page.evaluate((id) => {
  const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
  const all = raw.state?.chatThreads ?? {}
  return {
    keys: Object.keys(all),
    docMessages: all[`doc:${id}`]?.messages?.length ?? 0,
    docScope: all[`doc:${id}`]?.scope ?? null,
    docSelected: all[`doc:${id}`]?.selectedDocId ?? null,
    pageMessages: all.page?.messages?.length ?? 0,
    pageScope: all.page?.scope ?? null,
  }
}, docId)
check("the dock answered into its own thread", threads.docMessages > 0, `${threads.docMessages} messages`)
check("the dock is scoped to its document", threads.docScope === "single" && threads.docSelected === docId)
check("the Ask page's conversation is untouched", threads.pageMessages === askPageThread, `${threads.pageMessages} vs ${askPageThread}`)
check("the Ask page's scope is untouched", threads.pageScope === "all", String(threads.pageScope))
check("the reader is still on the document", page.url().includes(`doc=${docId}`), page.url())

// Selecting a passage and asking about it must not leave the passage.
await page.getByRole("button", { name: "Insights", exact: true }).first().click()
// The prose tab: an EPUB lands in its own viewer and a PDF on its pages, and
// neither is where a paragraph can be dragged across.
const readTab = page.getByRole("button", { name: "Read", exact: true })
if (await readTab.count()) {
  await readTab.first().click()
  await page.waitForTimeout(2500)
}
const para = page.locator("p").filter({ hasText: /[\s\S]{120,}/ }).first()
const paraCount = await para.count()
check("the reader shows a paragraph to select", paraCount > 0)
if (paraCount) {
  const boxRect = await para.boundingBox()
  check("that paragraph is on screen", Boolean(boxRect))
  if (boxRect) {
    await page.mouse.move(boxRect.x + 5, boxRect.y + boxRect.height / 2)
    await page.mouse.down()
    await page.mouse.move(boxRect.x + Math.min(boxRect.width - 5, 320), boxRect.y + boxRect.height / 2, { steps: 12 })
    await page.mouse.up()
    await page.waitForTimeout(800)
    const askAction = page.getByRole("button", { name: "Ask", exact: true })
    check("the selection offers Ask", (await askAction.count()) > 0)
    if (await askAction.count()) {
      await askAction.first().click()
      await page.waitForTimeout(2500)
      const after = await page.evaluate((id) => {
        const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
        const msgs = raw.state?.chatThreads?.[`doc:${id}`]?.messages ?? []
        const tabs = [...document.querySelectorAll("button[aria-pressed]")]
          .filter((b) => b.textContent === "Ask AI")
          .map((b) => b.getAttribute("aria-pressed"))
        return {
          asked: msgs.some((m) => typeof m.text === "string" && m.text.includes("Explain this excerpt")),
          askTabActive: tabs.includes("true"),
          url: location.href,
        }
      }, docId)
      check("asking a passage stays in the reader", after.url.includes(`doc=${docId}`), after.url)
      check("the dock opens on the question", after.askTabActive)
      check("the excerpt reaches this document's conversation", after.asked)
    }
  }
}

// A note taken from a passage keeps where the passage was.
//
// The rung's gate is that a citation survives selection -> note -> resolution,
// and the note is where it was being lost: the composer received a section only
// when a section's own note button was pressed, so a note taken from a
// selection stored the quoted text and no locus at all.
const recording = await page.evaluate(async (api) => {
  const res = await fetch(`${api}/documents?page=1&page_size=50&sort=last_accessed`)
  const data = await res.json()
  return (data.items ?? []).find((d) => ["audio", "video"].includes(d.content_type)) ?? null
}, API)
if (!recording) {
  console.log("  SKIP the note-locus checks: the library holds no recording")
} else {
  console.log(`recording: ${recording.title} (${recording.content_type})`)
  await page.goto(`${APP}/library?doc=${recording.id}`, { waitUntil: "domcontentloaded" })
  await page.waitForTimeout(4000)
  const turn = page.locator("[data-chunk-id]").first()
  const turnCount = await turn.count()
  check("the transcript names its chunks", turnCount > 0)
  if (turnCount) {
    const rect = await turn.boundingBox()
    if (rect) {
      await page.mouse.move(rect.x + 5, rect.y + Math.min(rect.height / 2, 20))
      await page.mouse.down()
      await page.mouse.move(rect.x + Math.min(rect.width - 5, 300), rect.y + Math.min(rect.height / 2, 20), { steps: 12 })
      await page.mouse.up()
      await page.waitForTimeout(800)
      const noteAction = page.getByRole("button", { name: "Note", exact: true })
      check("the selection offers Note", (await noteAction.count()) > 0)
      if (await noteAction.count()) {
        await noteAction.first().click()
        // The composer autosaves on a debounce; give it room to create.
        await page.waitForTimeout(9000)
        const saved = await page.evaluate(async ({ api, docId }) => {
          const res = await fetch(`${api}/notes?page=1&page_size=5`)
          const notes = await res.json()
          return notes.find((n) => n.document_id === docId) ?? null
        }, { api: API, docId: recording.id })
        check("the note was created", Boolean(saved))
        if (saved) {
          check("the note keeps the chunk it came from", Boolean(saved.chunk_id), String(saved.chunk_id))
          check("the note keeps the section it came from", Boolean(saved.section_id), String(saved.section_id))
          // The round trip: the note's own back-link must land on the passage.
          await page.goto(`${APP}/notes`, { waitUntil: "domcontentloaded" })
          await page.waitForTimeout(3000)
          const back = page.getByRole("button", { name: "Go to source" })
          check("the note offers a way back", (await back.count()) > 0)
          if (await back.count()) {
            await back.first().click()
            await page.waitForTimeout(5000)
            const landed = await page.evaluate(() => ({
              url: location.href,
              marks: document.querySelectorAll(".luminary-citation-mark, [data-citation-highlight]").length,
            }))
            check("the back-link opens the reader on the document", landed.url.includes("doc="), landed.url)
            check("the passage is marked when the reader arrives", landed.marks > 0, `${landed.marks} marks`)
          }

          // The check cleans up after itself rather than leaving a note per run.
          await page.evaluate(async ({ api, id }) => {
            await fetch(`${api}/notes/${id}`, { method: "DELETE" })
          }, { api: API, id: saved.id })
          console.log(`  (removed the note this check created: ${saved.id})`)
        }
      }
    }
  }
}

await page.screenshot({ path: ".citation-verify/dock.png" })
console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
await browser.close()
process.exit(failures.length ? 1 : 0)
