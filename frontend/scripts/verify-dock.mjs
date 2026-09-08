/**
 * The docked assistant, in a real browser.
 *
 * The rung's rule is that working on a passage does not leave the passage: the
 * conversation and the note composer are both docked beside the document, no
 * dialog opens over it, and a conversation docked beside a document is that
 * document's own -- neither the question nor the scope may reach the Ask page's
 * conversation. None of that is visible to `tsc` or to a unit test; all of it is
 * about mounted components sharing one store.
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

    // The same paragraph, twice more. Explain was a sheet with a backdrop over
    // the text and Flashcard a dialog in front of it; both are panel faces now.
    // Drag the paragraph again and wait for the action the caller wants. A
    // fixed pause is not enough while an answer is streaming into the panel:
    // one run lost the toolbar to a render and reported a missing button.
    const selectAgain = async (locator) => {
      for (let attempt = 0; attempt < 3; attempt++) {
        await page.mouse.move(boxRect.x + 5, boxRect.y + boxRect.height / 2)
        await page.mouse.down()
        await page.mouse.move(boxRect.x + Math.min(boxRect.width - 5, 320), boxRect.y + boxRect.height / 2, { steps: 12 })
        await page.mouse.up()
        for (let i = 0; i < 8; i++) {
          await page.waitForTimeout(400)
          if (await locator.count()) return true
        }
      }
      return false
    }
    const TAB_LABELS = ["Insights", "Ask AI", "Notes", "Practice", "Explain"]
    const panelState = () => page.evaluate((labels) => ({
      dialogs: document.querySelectorAll('[role="dialog"]').length,
      explanations: document.querySelectorAll('[data-testid="docked-explanation"]').length,
      practice: document.querySelectorAll('[data-testid="docked-practice"]').length,
      feynman: document.querySelectorAll('[data-testid="docked-feynman"]').length,
      scope: document.querySelector('[data-testid="practice-scope"]')?.textContent?.trim() ?? "",
      explained: document.querySelector('[data-testid="explanation-body"]')?.innerText?.trim() ?? "",
      tab: [...document.querySelectorAll("button[aria-pressed]")]
        .filter((b) => labels.includes(b.textContent?.trim()))
        .find((b) => b.getAttribute("aria-pressed") === "true")?.textContent?.trim() ?? null,
      url: location.href,
    }), TAB_LABELS)

    // The panel's own tab is also called Explain; only the action bar's button
    // carries no aria-pressed.
    const explainAction = page.locator("button:not([aria-pressed])").filter({ hasText: /^Explain$/ })
    check("the selection offers Explain", await selectAgain(explainAction))
    if (await explainAction.count()) {
      await explainAction.first().click()
      await page.waitForTimeout(1500)
      const opened = await panelState()
      check("explaining a passage opens no sheet", opened.dialogs === 0, `${opened.dialogs} dialogs`)
      check("the explanation is docked in the panel", opened.explanations === 1, `${opened.explanations} panels`)
      check("the dock opens on the explanation", opened.tab === "Explain", String(opened.tab))
      check("explaining a passage stays in the reader", opened.url.includes(`doc=${docId}`), opened.url)
      // The face is only worth docking if it fills: an empty panel and a
      // covered one are the same thing to the reader.
      let streamed = opened
      for (let i = 0; i < 30; i++) {
        if (streamed.explained.length > 80) break
        await page.waitForTimeout(3000)
        streamed = await panelState()
      }
      check("the explanation streams into the panel", streamed.explained.length > 80,
        `${streamed.explained.length} chars`)
    }

    const cardAction = page.getByRole("button", { name: "Flashcard", exact: true })
    check("the selection offers Flashcard", await selectAgain(cardAction))
    if (await cardAction.count()) {
      await cardAction.first().click()
      await page.waitForTimeout(1200)
      const opened = await panelState()
      check("a flashcard from a passage opens no dialog", opened.dialogs === 0, `${opened.dialogs} dialogs`)
      check("the generator is docked in the panel", opened.practice === 1, `${opened.practice} panels`)
      check("the dock opens on Practice", opened.tab === "Practice", String(opened.tab))
      // The selection is what the cards would be generated from; losing it is
      // how a passage silently becomes the whole document.
      check("the generator is scoped to the selection", /^Selected text/.test(opened.scope), opened.scope)
      // Three states, no blank panel (I-10): a section with no cards of its own
      // has to say so rather than render an empty deck.
      const scopedDeck = await page.locator('[data-testid="deck-summary"]').first()
        .textContent().catch(() => null)
      check("a scoped face still says what is practicable", (scopedDeck ?? "").length > 10,
        (scopedDeck ?? "<nothing>").slice(0, 60))
    }

    // The header's own button is the document-wide arm of the same face. It used
    // to leave the reader for /study; the whole rung is that it must not.
    const headerPractice = page.getByRole("button", { name: "Practice", exact: true })
    check("the header offers Practice", (await headerPractice.count()) > 0)
    if (await headerPractice.count()) {
      await headerPractice.first().click()
      await page.waitForTimeout(1000)
      const opened = await panelState()
      check("Practice opens no dialog", opened.dialogs === 0, `${opened.dialogs} dialogs`)
      check("Practice opens the Practice face", opened.tab === "Practice", String(opened.tab))
      check("the header's arm is scoped to the document", opened.scope === "This document", opened.scope)
      check("Practice stays in the reader", opened.url.includes(`doc=${docId}`), opened.url)
    }

    // The recall loop. Its whole claim is that the answer is not on screen until
    // the learner has committed to something, so the check is
    // question-present-and-answer-absent: an absent answer on its own is also
    // what a runner that failed to start looks like.
    //
    // This one needs a document that already has due cards, which is rarely the
    // prose document the checks above drive. It grades nothing -- predicting and
    // revealing mutate no card -- and deletes the study session it opened, so a
    // run leaves the library as it found it.
    const practicable = await page.evaluate(async (api) => {
      const res = await fetch(`${api}/documents?page=1&page_size=50&sort=last_accessed`)
      const items = (await res.json()).items ?? []
      for (const d of items) {
        const due = await fetch(`${api}/study/due?document_id=${d.id}&limit=1`)
        if (due.ok && (await due.json()).length > 0) return d
      }
      return null
    }, API)
    if (!practicable) {
      console.log("  skip  the recall loop -- no document in this library has a card due")
    } else {
      console.log(`  practising: ${practicable.title}`)
      const sessionsBefore = await page.evaluate(async ([api, id]) => {
        const res = await fetch(`${api}/study/sessions?page=1&page_size=100&document_id=${id}`)
        return ((await res.json()).items ?? []).map((x) => x.id)
      }, [API, practicable.id])

      await page.goto(`${APP}/library?doc=${practicable.id}`, { waitUntil: "domcontentloaded" })
      await page.waitForTimeout(3000)
      const leftTabOf = () => page.evaluate(() =>
        [...document.querySelectorAll("button")]
          .filter((b) => ["Sections", "Read"].includes(b.textContent?.trim()))
          .find((b) => b.className.includes("border-primary"))?.textContent?.trim() ?? null)
      // Start on Sections, so the jump to the source has somewhere to move from.
      const sectionsTab = page.getByRole("button", { name: "Sections", exact: true })
      if (await sectionsTab.count()) await sectionsTab.first().click()
      const practiceTab = page.getByRole("button", { name: "Practice", exact: true })
      if (await practiceTab.count()) await practiceTab.first().click()
      await page.waitForTimeout(2000)

      const deck = await page.locator('[data-testid="deck-summary"]').first().textContent().catch(() => null)
      check("the face opens on the deck, not the generator", /card|practise/i.test(deck ?? ""), (deck ?? "").slice(0, 60))

      const startRecall = page.locator('[data-testid="start-recall"]')
      check("the deck offers a recall run", (await startRecall.count()) > 0)
      let ranSessionId = null
      if (await startRecall.count()) {
        await startRecall.first().click()
        await page.waitForTimeout(2500)
        // The id of the session this run is actually on, so cleanup removes that
        // one and nothing else. Diffing the document's sessions instead would
        // delete any session someone started in the app while this was running,
        // and take their review events down with it.
        ranSessionId = await page.evaluate(() => {
          const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
          return raw.state?.studySessionId ?? null
        })
        const before = await page.evaluate(() => ({
          question: document.querySelector('[data-testid="recall-question"]')?.textContent?.trim() ?? "",
          answers: document.querySelectorAll('[data-testid="recall-answer"]').length,
          predict: document.querySelectorAll('[data-testid^="predict-"]').length,
        }))
        check("a run asks a question", before.question.length > 10, `${before.question.length} chars`)
        check("the answer is not on screen before committing", before.answers === 0, `${before.answers} answers`)
        check("the run asks for a prediction first", before.predict === 3, `${before.predict} buttons`)

        const tabBefore = await leftTabOf()
        await page.locator('[data-testid="predict-good"]').first().click()
        await page.waitForTimeout(1500)
        const after = await page.evaluate(() => ({
          answer: document.querySelector('[data-testid="recall-answer"]')?.innerText?.trim() ?? "",
          grades: document.querySelectorAll('[data-testid^="grade-"]').length,
          jump: document.querySelectorAll('[data-testid="recall-jump"]').length,
        }))
        check("committing reveals the answer", after.answer.length > 0, `${after.answer.length} chars`)
        check("the revealed card can be graded", after.grades === 4, `${after.grades} grades`)
        const tabAfter = await leftTabOf()
        if (after.jump > 0) {
          check("the reveal puts the document on the source passage",
            tabAfter === "Read" && tabBefore !== "Read", `${tabBefore} -> ${tabAfter}`)
        } else {
          console.log("  skip  the reveal puts the document on the source passage -- this card carries no section")
        }
      }

      // Only the session this run opened: one that was already there is someone
      // else's, and the run adopting it is exactly the resume behaviour.
      const removed = ranSessionId !== null && !sessionsBefore.includes(ranSessionId)
        ? await page.evaluate(async ([api, sid]) =>
            (await fetch(`${api}/study/sessions/${sid}`, { method: "DELETE" })).ok, [API, ranSessionId])
        : false
      console.log(removed
        ? `  cleaned up the study session this check opened (${ranSessionId.slice(0, 8)})`
        : "  opened no new study session -- it resumed one that was already there")
      await page.goto(`${APP}/library?doc=${docId}`, { waitUntil: "domcontentloaded" })
      await page.waitForTimeout(2500)
    }

    // Feynman starts a session on mount and `/feynman` has no delete, so this
    // one leaves a practice session behind in the library it runs against --
    // two of them in dev, where StrictMode runs the effect twice.
    // Re-enable with LUMINARY_VERIFY_FEYNMAN=1 when the dock's wiring changes;
    // `readerSurfaces.test.ts` is what holds the "no modal" claim otherwise.
    if (process.env.LUMINARY_VERIFY_FEYNMAN === "1") {
      // The Practice button is offered on a tech book or article and nowhere
      // else, so the prose document this check has been driving cannot show it.
      const tech = await page.evaluate(async (api) => {
        const res = await fetch(`${api}/documents?page=1&page_size=100`)
        const data = await res.json()
        return (data.items ?? []).find((d) => ["tech_book", "tech_article"].includes(d.content_type)) ?? null
      }, API)
      if (!tech) {
        console.log("  SKIP the Feynman checks: the library holds no tech book or article")
      } else {
        console.log(`feynman document: ${tech.title} (${tech.content_type})`)
        await page.goto(`${APP}/library?doc=${tech.id}`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(3500)
        // The section list is where the button is, and it is not the landing tab.
        const sectionsTab = page.getByRole("button", { name: "Sections", exact: true })
        if (await sectionsTab.count()) {
          await sectionsTab.first().click()
          await page.waitForTimeout(1500)
        }
        const practiceBtn = page.locator('button[title^="Explain this section in your own words"]')
        check("a section offers Practice", (await practiceBtn.count()) > 0)
        if (await practiceBtn.count()) {
          await practiceBtn.first().click()
          await page.waitForTimeout(6000)
          const opened = await panelState()
          check("a Feynman session opens no dialog", opened.dialogs === 0, `${opened.dialogs} dialogs`)
          check("the session is docked in the panel", opened.feynman === 1, `${opened.feynman} panels`)
          check("the dock opens on the session", opened.tab === "Practice", String(opened.tab))
        }
      }
    } else {
      console.log("  SKIP the Feynman checks: they create a session with no way to remove it (LUMINARY_VERIFY_FEYNMAN=1)")
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
        await page.waitForTimeout(1500)

        // The rung's rule: nothing opens over the document.
        const capture = await page.evaluate(() => ({
          dialogs: document.querySelectorAll('[role="dialog"]').length,
          composers: document.querySelectorAll('[data-testid="docked-note-composer"]').length,
          onNotes: [...document.querySelectorAll("button[aria-pressed]")]
            .some((b) => b.textContent === "Notes" && b.getAttribute("aria-pressed") === "true"),
          raw: document.querySelector(".cm-content")?.innerText ?? "",
          // What the draft holds, measured independently of how it is drawn.
          lines: document.querySelectorAll(".cm-line").length,
          // The composer renders as it writes: the quote's markers are gone
          // from the DOM, and its lines carry the rendered class instead.
          quoted: document.querySelectorAll(".cm-md-quote").length,
        }))
        check("taking a note opens no dialog", capture.dialogs === 0, `${capture.dialogs} dialogs`)
        check("the composer is docked in the panel", capture.composers === 1, `${capture.composers} composers`)
        check("the dock opens on the note", capture.onNotes)
        check("the composer holds the captured passage", capture.lines >= 3, `${capture.lines} lines`)
        // The quoted line renders as a quote and shows no marker. The line the
        // cursor is on keeps its source, so this reads the passage's own line.
        check("the composer renders the markdown it holds",
          capture.quoted >= 3 && !capture.raw.includes('> "'), `${capture.quoted} quote lines`)

        // A docked composer outlives the capture that opened it, so the next
        // one has to land in the draft rather than be dropped on the floor.
        const second = page.locator("[data-chunk-id]").nth(1)
        check("the transcript has a second passage to take", (await second.count()) > 0)
        if (await second.count()) {
          // Off screen, boundingBox still answers and the drag happens outside
          // the window -- which reads as "no selection" rather than as a miss.
          await second.scrollIntoViewIfNeeded()
          await page.waitForTimeout(600)
          const r2 = await second.boundingBox()
          if (r2) {
            await page.mouse.move(r2.x + 5, r2.y + Math.min(r2.height / 2, 20))
            await page.mouse.down()
            await page.mouse.move(r2.x + Math.min(r2.width - 5, 300), r2.y + Math.min(r2.height / 2, 20), { steps: 12 })
            await page.mouse.up()
            await page.waitForTimeout(800)
            const noteAgain = page.getByRole("button", { name: "Note", exact: true })
            check("the second selection offers Note", (await noteAgain.count()) > 0)
            if (await noteAgain.count()) {
              await noteAgain.first().click()
              await page.waitForTimeout(1500)
              const appended = await page.evaluate(() => ({
                composers: document.querySelectorAll('[data-testid="docked-note-composer"]').length,
                lines: document.querySelectorAll(".cm-line").length,
              }))
              check("a second capture appends to the open note", appended.lines > capture.lines,
                `${capture.lines} -> ${appended.lines} lines`)
              check("a second capture opens no second composer", appended.composers === 1,
                `${appended.composers} composers`)
            }
          }
        }

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

          // Done closes the composer, and the panel's own list is where the
          // note then is -- the reader never went to the notes page for it.
          const doneBtn = page.getByRole("button", { name: "Done", exact: true })
          if (await doneBtn.count()) {
            await doneBtn.first().click()
            await page.waitForTimeout(2500)
          }
          // The panel's own tab, not the nav rail's Notes link.
          const notesTab = page.locator("button[aria-pressed]").filter({ hasText: /^Notes$/ })
          if (await notesTab.count()) {
            await notesTab.first().click()
            await page.waitForTimeout(1500)
          }
          const listed = await page.evaluate(() => ({
            composers: document.querySelectorAll('[data-testid="docked-note-composer"]').length,
            rows: document.querySelectorAll('[data-testid="docked-notes-list"] li').length,
          }))
          check("Done closes the composer", listed.composers === 0, `${listed.composers} composers`)
          check("the panel lists the note it just took", listed.rows > 0, `${listed.rows} rows`)

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
