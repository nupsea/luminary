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

/** "N of M reviewed" has to be arithmetic, wherever a run is on screen.
 *
 * This exists because the same defect shipped twice from two different counters.
 * The first read "4 of 3 reviewed" because the in-run tally counted submissions;
 * that was fixed and checked -- but only on the SUMMARY, and only on a fresh
 * run. The resume path keeps a tally of its own, seeded from one teach-back row
 * per attempt, and read "30 of 15 reviewed" on a run holding 30 attempts across
 * 5 cards. So the assertion belongs to the rendered number, at every point it
 * can be reached, rather than to any one of the counters behind it.
 *
 * It never returns quietly. The first version did -- it looked for the runner's
 * ratio, found a summary instead, and printed nothing at all on the resumed run,
 * which is the path that had the bug. A check that finds nothing to assert is a
 * check that cannot fail, so both faces are handled and anything else FAILS.
 *
 * The third instance was not arithmetic at all: "7 of 8 reviewed" on a document
 * holding three cards, because replacing the deck deleted five the run had
 * planned and their review events stayed behind. Internally consistent, and
 * wrong -- which is why `deckCap` comes from the deck endpoint rather than from
 * the session the header is drawn from. */
async function checkProgressHeader(page, where, plannedFallback = null, deckCap = null) {
  const seen = await page.evaluate(() => {
    const run = document.querySelector('[data-testid="recall-runner"]')
    const out = document.querySelector('[data-testid="recall-readout"]')
    const ratio = /(\d+)\s+of\s+(\d+)\s+reviewed/i.exec(run?.innerText ?? "")
    const stat = /REVIEWED\s*\n?\s*(\d+)/i.exec(out?.innerText ?? "")
    return {
      face: run ? "runner" : out ? "readout" : "none",
      ratio: ratio ? [Number(ratio[1]), Number(ratio[2])] : null,
      reviewed: stat ? Number(stat[1]) : null,
    }
  })
  const name = `${where} never claims more reviewed than it holds`
  if (seen.ratio) {
    check(name, seen.ratio[0] <= seen.ratio[1], `${seen.ratio[0]} of ${seen.ratio[1]}`)
  } else if (seen.reviewed !== null && plannedFallback !== null) {
    // The summary prints REVIEWED without a denominator; the run's plan is it.
    check(name, seen.reviewed <= plannedFallback,
      `${seen.reviewed} reviewed, ${plannedFallback} planned`)
  } else {
    check(name, false, `nothing to count on the ${seen.face} face`)
  }
  if (deckCap === null) return
  // The denominator against the DECK, from a different endpoint than the one
  // the header is built from. Without this the run's own total is checked
  // against a number the same session state produced, which is no check at all:
  // a plan holding five cards a replacement had deleted read "7 of 8 reviewed"
  // over a deck of three, and every count on that screen agreed with itself.
  const total = seen.ratio ? seen.ratio[1] : seen.reviewed
  check(`${where} counts no card the deck no longer holds`,
    total !== null && total <= deckCap, `${total} counted, ${deckCap} in the deck`)
}

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })

// What the page itself says went wrong. Without this a broken render shows up
// only as the check downstream of it failing, and the cause is invisible: a
// query added to one docked face took out the notes list, and the harness could
// report the symptom and nothing else.
const pageErrors = []
page.on("pageerror", (err) => pageErrors.push(`pageerror: ${err.message}`))
page.on("console", (msg) => {
  if (msg.type() === "error") pageErrors.push(`console: ${msg.text().slice(0, 300)}`)
})
// A bare "404 (Not Found)" in the console names no URL, which is the half of
// the message that matters when a new route shadows an old one.
page.on("response", (res) => {
  if (res.status() >= 400) pageErrors.push(`HTTP ${res.status()} ${res.url()}`)
})
page.on("requestfailed", (req) => pageErrors.push(`REQFAIL ${req.method()} ${req.url()} -- ${req.failure()?.errorText}`))
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

// Dictation is a component the installer does not carry, so an absent mic is
// correct on a machine without the transcriber and a defect on one with it.
// The capability decides which, and the run says which way it went: a mic check
// that silently skips is how a missing button shipped on two docked faces while
// the same button was on screen everywhere else.
const dictation = await page.evaluate(async (api) => {
  try {
    const r = await fetch(`${api}/setup/capabilities`)
    if (!r.ok) return null
    return (await r.json())?.dictation?.available ?? null
  } catch { return null }
}, API)
console.log(
  dictation === null
    ? "  note  the dictation capability could not be read; the mic checks are skipped"
    : dictation
    ? "  note  dictation is installed, so every docked face that takes typing must offer the mic"
    : "  SKIP the mic checks: the transcriber is not installed (Settings -> Speech to text)",
)
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

    // The bar is deliberately narrower than it was: Note, Flashcard and Clip
    // were each a second way to reach a face that is now docked beside the
    // text. Read the bar's own buttons rather than the page's -- a section row
    // carries a Note control too, and counting those would pass this check
    // while the bar still offered one. The swatches carry no text, so a bar
    // with only them would read as empty here; the count guards that.
    await selectAgain(page.locator('[data-testid="selection-action-bar"]'))
    const bar = page.locator('[data-testid="selection-action-bar"]')
    const barActions = await bar.locator("button")
      .evaluateAll((els) => els.map((e) => e.textContent?.trim()).filter(Boolean))
    check("the selection bar is the one the reader asked for",
      barActions.length > 0 && !["Note", "Flashcard", "Clip"].some((a) => barActions.includes(a)),
      barActions.join(" | ") || "<no bar>")
    check("the selection still offers Explain and Ask",
      ["Explain", "Ask"].every((a) => barActions.includes(a)), barActions.join(" | "))
    // Highlighting is the only passage-capture the bar has left, so its
    // swatches are load-bearing rather than decoration.
    const swatches = await bar.locator('button[title^="Highlight"]').count()
    check("the selection still offers the highlight swatches", swatches === 4, `${swatches} swatches`)

    // Practice and Chat were removed from the header: each showed a face already
    // in the tab bar, and Practice's extra trick -- arming the whole document --
    // is the Practice face's own "Use the whole document" control. Read the
    // header's own actions, since a section row carries a Practice button too.
    const headerActions = await page.locator('[data-testid="reader-header-actions"] button')
      .evaluateAll((els) => els.map((e) => e.textContent?.trim()).filter(Boolean))
    check("the header carries no duplicate of a panel tab",
      !headerActions.includes("Practice") && !headerActions.includes("Chat"),
      headerActions.join(" | ") || "<none>")

    // The face itself is reached from the tab, and the rung is unchanged: it
    // used to leave the reader for /study, and it must not.
    const practiceTab = page.locator("button[aria-pressed]").filter({ hasText: /^Practice$/ })
    check("the panel offers the Practice face", (await practiceTab.count()) > 0)
    if (await practiceTab.count()) {
      await practiceTab.first().click()
      await page.waitForTimeout(1000)
      const opened = await panelState()
      check("Practice opens no dialog", opened.dialogs === 0, `${opened.dialogs} dialogs`)
      check("Practice opens the Practice face", opened.tab === "Practice", String(opened.tab))
      check("the face is scoped to the document", opened.scope === "This document", opened.scope)
      check("Practice stays in the reader", opened.url.includes(`doc=${docId}`), opened.url)

    }

    // A goal's own Study button scopes the face to that goal's section rather
    // than leaving for /study. Driven from the goals panel and not the page,
    // because a section row carries a Practice button that does the same thing
    // -- passing on that one would say nothing about this path.
    //
    // The document is found rather than assumed: objectives are extracted only
    // from a tech book's chapter openings, so the document these checks read
    // has none, and a check keyed to it would have skipped in silence forever.
    const withGoal = await page.evaluate(async (api) => {
      for (let pageNo = 1; pageNo <= 4; pageNo++) {
        const res = await fetch(`${api}/documents?page=${pageNo}&page_size=50&sort=last_accessed`)
        const items = (await res.json()).items ?? []
        if (items.length === 0) break
        for (const d of items) {
          const objs = await fetch(`${api}/documents/${d.id}/objectives`)
          if (!objs.ok) continue
          const list = (await objs.json()).objectives ?? []
          if (list.some((o) => !o.covered)) return d
        }
      }
      return null
    }, API)
    if (!withGoal) {
      console.log("  skip  the goal scope -- no document in this library has an uncovered chapter goal")
    } else {
      console.log(`  goals: ${withGoal.title}`)
      await page.goto(`${APP}/library?doc=${withGoal.id}`, { waitUntil: "domcontentloaded" })
      await page.waitForTimeout(4000)
      const goalStudy = page.locator('[data-testid="chapter-goals"] button').filter({ hasText: /^Study$/ })
      check("the reader shows the document's chapter goals", (await goalStudy.count()) > 0)
      if (await goalStudy.count()) {
        await goalStudy.first().click()
        await page.waitForTimeout(1800)
        const scoped = await panelState()
        check("a goal's Study button opens the Practice face", scoped.tab === "Practice", String(scoped.tab))
        check("it scopes the face to the goal's section, not the document",
          scoped.scope !== "" && scoped.scope !== "This document", scoped.scope || "<no scope>")
        check("and it never leaves the reader for /study",
          scoped.url.includes(`doc=${withGoal.id}`) && !scoped.url.includes("/study"), scoped.url)
      }
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
      // How many cards this document actually has. A run can plan a subset of
      // the deck and never more than it.
      const deckSize = await page.evaluate(async ([api, id]) => {
        const res = await fetch(`${api}/flashcards/${id}`)
        return res.ok ? ((await res.json()) ?? []).length : null
      }, [API, practicable.id])
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

      // The runs on this document, in the reader. The Study page lists the same
      // rows from the same endpoint; a dock that cannot show them is a surface
      // where a learner can start a run and never find it again.
      const historyMounted = await page
        .locator('[data-testid="docked-session-history"]')
        .count()
      check("the Practice face lists this document's runs", historyMounted === 1, String(historyMounted))
      if (historyMounted === 1) {
        const listed = await page
          .locator('[data-testid="docked-session-history"] input[type="checkbox"]')
          .count()
        const reported = await fetch(
          `${API}/study/sessions?document_id=${docId}&page=1&page_size=50`,
        )
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null)
        // The bulk bar's "Select all" carries a checkbox of its own, so a list
        // of N runs holds N+1; an empty list renders no bar at all.
        const shown = listed === 0 ? 0 : listed - 1
        check(
          "the reader's run list matches the record",
          reported !== null && shown === Math.min(reported.total, 50),
          `dock ${shown}, api ${reported?.total ?? "unreachable"}`,
        )
      }

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

      // The teach-back arm is off by default: a submission is scored, and the
      // first attempt on a card applies an FSRS review of its own, so a run of
      // it advances the schedule of every card it touches and no delete undoes
      // that -- deleting the session removes the events, not the card state.
      // (Re-answers do not reschedule, so the retry checks below are free; the
      // first pass over each card is not.)
      // LUMINARY_VERIFY_TEACHBACK=1 turns it on; that is how the arm was measured.
      let explainSessionId = null
      if (process.env.LUMINARY_VERIFY_TEACHBACK !== "1") {
        // Said, not silent. A whole arm sitting out is a fact about the run, and
        // reading a log of nothing but "ok" lines gave no way to tell that the
        // teach-back checks -- including the fresh run's progress header -- had
        // never executed.
        console.log(
          "  SKIP the teach-back arm: it submits a real explanation (LUMINARY_VERIFY_TEACHBACK=1)",
        )
      }
      if (process.env.LUMINARY_VERIFY_TEACHBACK === "1") {
        // Back to the deck first: the recall run above is still mounted, and
        // this block skipped in silence when it looked for a start button that
        // the running card had replaced.
        await page.goto(`${APP}/library?doc=${practicable.id}`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(3000)
        const toPractice = page.getByRole("button", { name: "Practice", exact: true })
        if (await toPractice.count()) await toPractice.first().click()
        await page.waitForTimeout(2000)
        const startExplain = page.locator('[data-testid="start-explain"]')
        check("the deck offers an explain run", (await startExplain.count()) > 0)
        if (await startExplain.count()) {
          await startExplain.first().click()
          await page.waitForTimeout(2500)
          explainSessionId = await page.evaluate(() => {
            const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
            return raw.state?.studySessionId ?? null
          })
          await checkProgressHeader(page, "a fresh run", null, deckSize)
          const ta = page.locator('[data-testid="recall-runner"] textarea')
          check("the explain arm asks for an explanation", (await ta.count()) === 1)
          if (dictation) {
            check("the docked teach-back answer offers the mic",
              (await page.locator('[data-testid="recall-runner"] button[title*="Speak your explanation"]').count()) === 1)
          }
          if (await ta.count()) {
            await ta.fill("The maximum of a linear objective sits at a vertex, so interior points can be skipped.")
            await page.getByRole("button", { name: /Submit and compare/ }).click()
            await page.waitForTimeout(1500)
            const mid = await page.evaluate(() => {
              const t = document.querySelector('[data-testid="recall-runner"]')?.innerText ?? ""
              return {
                grades: document.querySelectorAll('[data-testid^="grade-"]').length,
                next: document.querySelectorAll('[data-testid="teachback-next"]').length,
                said: /what you said/i.test(t),
                expected: /expected answer/i.test(t),
              }
            })
            // Grading here would review the card twice: the evaluator already
            // applies one when it scores.
            check("a scored card is not graded by hand as well", mid.grades === 0,
              `${mid.grades} grade buttons`)
            check("the run can move on while it is still scoring", mid.next === 1)
            check("the reveal shows what the learner said", mid.said)
            check("the reveal names the expected answer", mid.expected)

            // Re-answering the same card. Deleting the session instead would
            // take its rows and review events but leave the card's FSRS state
            // already advanced, so the retry has to be in place.
            // Wait for a verdict, but do not require one: evaluation is a local
            // LLM call that sometimes comes back unscored, and a check that goes
            // red on that is noise which would hide a real regression.
            let scored = false
            for (let k = 0; k < 25; k++) {
              await page.waitForTimeout(3000)
              const t = await page.evaluate(() =>
                document.querySelector('[data-testid="recall-runner"]')?.innerText ?? "")
              if (/\d+\/100/.test(t)) { scored = true; break }
              if (/could not be scored/i.test(t)) break
            }
            const retry = page.locator('[data-testid="teachback-retry"]')
            check("a scored card can be answered again", (await retry.count()) === 1)
            if (await retry.count()) {
              await retry.first().click()
              await page.waitForTimeout(1200)
              const again = await page.evaluate(() => {
                const t = document.querySelector('[data-testid="recall-runner"]')
                const ta = t?.querySelector("textarea")
                return {
                  box: t?.querySelectorAll("textarea").length ?? 0,
                  empty: (ta?.value ?? "x") === "",
                  keptVerdict: /your last attempt/i.test(t?.innerText ?? ""),
                }
              })
              check("answering again clears the box", again.box === 1 && again.empty,
                `${again.box} boxes, empty=${again.empty}`)
              if (scored) {
                check("the last verdict stays in view to improve on", again.keptVerdict)
              } else {
                console.log("  skip  the last verdict stays in view -- this attempt came back unscored")
              }

              // The summary after a re-answer. One row per CARD, carrying the
              // score that stands: listing both attempts put the same question
              // on screen twice, at 10/100 and at 45/100, and averaged the two
              // into a figure for a run of one card.
              if (await ta.count()) {
                await ta.fill(
                  "The objective is linear, so its optimum lies on the boundary of the " +
                  "feasible region and therefore at one of its vertices.")
                await page.getByRole("button", { name: /Submit and compare/ }).click()
                await page.waitForTimeout(2000)
                const next = page.locator('[data-testid="teachback-next"]')
                if (await next.count()) {
                  await next.first().click()
                  await page.waitForTimeout(2500)
                }
                // Walk to the end so the summary is on screen. Bounded by the
                // CLOCK, not by a turn count: a card being scored offers neither
                // a textarea nor a next button, so on a slow model every one of
                // the 25 turns this used to allow was spent waiting, the run
                // never reached its readout, and the whole summary block below
                // skipped without a word. Twenty minutes of checks that could
                // not fail.
                const walkUntil = Date.now() + 8 * 60 * 1000
                while (
                  Date.now() < walkUntil &&
                  !(await page.locator('[data-testid="recall-readout"]').count())
                ) {
                  const n = page.locator('[data-testid="teachback-next"]')
                  const s = page.locator('[data-testid="recall-runner"] textarea')
                  if (await s.count()) {
                    await s.fill("A vertex of the feasible region carries the optimum.")
                    await page.getByRole("button", { name: /Submit and compare/ }).click()
                    await page.waitForTimeout(2000)
                  } else if (await n.count()) {
                    await n.first().click()
                    await page.waitForTimeout(1500)
                  } else {
                    await page.waitForTimeout(1500)
                  }
                }
                // Said out loud either way. The summary checks below are the
                // ones that caught "4 of 3 reviewed", and a run that never got
                // to the readout must not report their absence as success.
                const reachedSummary =
                  (await page.locator('[data-testid="recall-readout"]').count()) > 0
                check(
                  "the run reaches its summary",
                  reachedSummary,
                  // Only when it did not. `check` prints whatever detail it is
                  // given, so a fixed string put a failure message beside a
                  // passing line.
                  reachedSummary ? "" : "walked the full budget without the readout appearing",
                )
                // Straight to the backend, not through the page: a relative
                // /api path inside the SPA answers with index.html, and the
                // check then dies on "<!doctype" instead of reporting anything.
                const plannedInRun = explainSessionId
                  ? await fetch(`${API}/study/sessions/${explainSessionId}/remaining-cards`)
                      .then((r) => (r.ok ? r.json() : null))
                      .then((d) => d?.planned_count ?? Number.MAX_SAFE_INTEGER)
                      .catch(() => Number.MAX_SAFE_INTEGER)
                  : Number.MAX_SAFE_INTEGER
                if (await page.locator('[data-testid="recall-readout"]').count()) {
                  const readout = await page.evaluate(() => {
                    const el = document.querySelector('[data-testid="recall-readout"]')
                    const text = el?.innerText ?? ""
                    // Card identity, not question wording: this deck holds cards
                    // that ask nearly the same thing, and comparing text called
                    // two of them one card listed twice.
                    const questions = [...el.querySelectorAll("[data-testid='readout-retry']")]
                      .map((b) => b.getAttribute("data-card-id") ?? "")
                    return {
                      retries: document.querySelectorAll('[data-testid="readout-retry"]').length,
                      addMore: document.querySelectorAll('[data-testid="readout-add-3"]').length,
                      reviewed: /REVIEWED\s*\n?\s*(\d+)/i.exec(text)?.[1] ?? "?",
                      dupes: questions.length - new Set(questions).size,
                      text: text.slice(0, 400),
                    }
                  })
                  check("the summary lists a re-answered card once",
                    readout.dupes === 0, `${readout.dupes} duplicate rows`)
                  check("the summary offers to add more to this run",
                    readout.addMore === 1, `${readout.addMore} add buttons`)
                  // Not "reviewed === rows": a continuous run carries the cards
                  // answered in earlier sittings too, so reviewed legitimately
                  // exceeds what this sitting submitted. What must never happen
                  // is the count running past the cards in the run -- the
                  // screenshot that started this said REVIEWED 4 over 3 cards.
                  check("reviewed never exceeds the cards in the run",
                    Number(readout.reviewed) <= plannedInRun,
                    `reviewed=${readout.reviewed} planned=${plannedInRun}`)

                  // Expanding a row must show what the card says next to the
                  // verdict on it. These were a flip -- one replaced the other --
                  // and a learner deciding whether a score is fair is comparing
                  // the two, which cannot be done one at a time from memory.
                  const row = page.locator('[data-testid="readout-retry"]').first()
                  if (await row.count()) {
                    await page.locator('[data-testid="result-row"]').first().click()
                    await page.waitForTimeout(400)
                    const together = await page.evaluate(() => ({
                      answer: document.querySelectorAll(
                        '[data-testid="expected-answer"]').length,
                      breakdown: [...document.querySelectorAll("p")]
                        .filter((p) => /why this score/i.test(p.textContent ?? "")).length,
                    }))
                    check("an expanded card shows its answer beside the verdict",
                      together.answer >= 1 && together.breakdown >= 1,
                      `answer=${together.answer} breakdown=${together.breakdown}`)
                  }
                }
              }
            }
          }
        }
      }

      // Wait for this run's evaluations to land before moving on.
      //
      // Not politeness: the checks after this one take a note, and creating a
      // note awaits an LLM tagger inside the request (notes.py). The runtime
      // serves one call at a time, so a run that walked its whole deck leaves a
      // queue of teach-back evaluations that the note save then sits behind,
      // and the composer hangs on "Saving...". That failure is real -- a learner
      // who practises and then writes a note hits it -- but it is not what the
      // notes checks are for, and a check that makes later checks fail hides
      // more than it finds. Bounded, because a stuck evaluation must not stop
      // the suite from reporting everything else.
      if (explainSessionId) {
        const settleBy = Date.now() + 120_000
        for (;;) {
          const pending = await fetch(
            `${API}/study/sessions/${explainSessionId}/teachback-results`,
          )
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => (d?.results ?? []).filter((r) => r.status === "pending").length)
            .catch(() => 0)
          if (!pending) break
          if (Date.now() > settleBy) {
            console.log(`  note  ${pending} evaluation(s) still running; not waiting further`)
            break
          }
          await page.waitForTimeout(3000)
        }
      }

      // Leaving a run open and coming back to it. The panel used to offer only
      // "start", while starting silently adopted the open session -- so the
      // learner was dropped mid-run with no explanation. Grades nothing.
      if (ranSessionId !== null) {
        await page.goto(`${APP}/library?doc=${practicable.id}`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(3000)
        const backToPractice = page.getByRole("button", { name: "Practice", exact: true })
        if (await backToPractice.count()) await backToPractice.first().click()
        await page.waitForTimeout(2000)
        // The model that writes the cards is nameable from here. "Auto" follows
        // Settings; picking one overrides only this surface, and the confirm
        // text for a replacement names it so a fresh set is never written by a
        // model the learner did not choose.
        const modelPick = await page.evaluate(() => {
          const sel = [...document.querySelectorAll("select")].find((s) =>
            s.closest("label")?.innerText?.includes("Model:"))
          return {
            present: Boolean(sel),
            auto: sel?.options?.[0]?.text?.startsWith("Auto") ?? false,
            choices: sel?.options?.length ?? 0,
          }
        })
        check("the deck names the model that writes its cards", modelPick.present)
        check("and defaults to following Settings", modelPick.auto,
          `first option: ${modelPick.choices} options`)

        // Start over replaces the scope's deck. It is opened and cancelled here,
        // never confirmed: a check that deletes the library's cards to prove it
        // can is not a check anyone can afford to run twice.
        const startOver = page.locator('[data-testid="regenerate-cards"]')
        check("the deck offers a way to start over", (await startOver.count()) === 1)
        if (await startOver.count()) {
          await startOver.first().click()
          await page.waitForTimeout(500)
          const confirm = await page.evaluate(() => {
            const el = document.querySelector('[data-testid="regenerate-confirm"]')
            return { shown: Boolean(el), text: el?.innerText ?? "" }
          })
          check("start over asks before deleting anything", confirm.shown)
          check("it says what is lost", /cannot be undone/i.test(confirm.text))
          const keep = page.getByRole("button", { name: /Keep them/ })
          if (await keep.count()) await keep.first().click()
          await page.waitForTimeout(400)
          check("declining leaves the deck alone",
            (await page.locator('[data-testid="regenerate-confirm"]').count()) === 0)
        }

        const openRun = await page.locator('[data-testid="open-run"]').first()
          .textContent().catch(() => null)
        check("an abandoned run is offered back", /left a .* run open/i.test(openRun ?? ""),
          (openRun ?? "<nothing>").slice(0, 60))
        // What the panel OWES the learner is the most recent run they left, which
        // is not necessarily the one this check just abandoned -- any older stale
        // session in the library would be newer than nothing. Re-derive it rather
        // than assume, or this check passes only on a clean library.
        const expectedResume = await page.evaluate(async ([api, id]) => {
          const res = await fetch(`${api}/study/sessions?page=1&page_size=5&document_id=${id}&status=incomplete`)
          return ((await res.json()).items ?? [])[0]?.id ?? null
        }, [API, practicable.id])
        const resume = page.locator('[data-testid="resume-run"]')
        if (await resume.count()) {
          await resume.first().click()
          await page.waitForTimeout(2500)
          const resumed = await page.evaluate(() => {
            const raw = JSON.parse(localStorage.getItem("luminary-app-store") ?? "{}")
            return {
              sessionId: raw.state?.studySessionId ?? null,
              // Either face counts: a run whose cards were all answered resumes
              // to its summary, which is the run, not the deck.
              running:
                document.querySelectorAll('[data-testid="recall-runner"]').length +
                document.querySelectorAll('[data-testid="recall-readout"]').length,
            }
          })
          // The same session, not merely "a" session: resuming used to fall
          // through to creating a fresh one when the target had gone, under a
          // button that said it was picking the old one back up.
          check("picking it back up returns the run it offered",
            resumed.sessionId !== null && resumed.sessionId === expectedResume,
            `${String(resumed.sessionId).slice(0, 8)} vs ${String(expectedResume).slice(0, 8)}`)
          check("the resumed run is on screen", resumed.running === 1, `${resumed.running} faces`)
          // A resumed run can land on either face, and the summary carries no
          // denominator of its own -- so the plan comes from the session.
          const resumedPlanned = resumed.sessionId
            ? await fetch(`${API}/study/sessions/${resumed.sessionId}/remaining-cards`)
                .then((r) => (r.ok ? r.json() : null))
                .then((d) => d?.planned_count ?? null)
                .catch(() => null)
            : null
          await checkProgressHeader(page, "a resumed run", resumedPlanned, deckSize)
        }
      }

      // Only the session this run opened: one that was already there is someone
      // else's, and the run adopting it is exactly the resume behaviour.
      const mine = [ranSessionId, explainSessionId].filter(
        (sid) => sid !== null && !sessionsBefore.includes(sid),
      )
      const removed = await page.evaluate(async ([api, ids]) => {
        const gone = []
        for (const sid of ids) {
          if ((await fetch(`${api}/study/sessions/${sid}`, { method: "DELETE" })).ok) gone.push(sid)
        }
        return gone
      }, [API, mine])
      console.log(removed.length > 0
        ? `  cleaned up ${removed.length} study session${removed.length === 1 ? "" : "s"} this check opened (${removed.map((x) => x.slice(0, 8)).join(", ")})`
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

// A passage captured from the reader keeps where the passage was.
//
// The rung's gate is that a citation survives selection -> capture -> resolution.
// Highlighting is the whole of that path now: Note, Flashcard and Clip have all
// left the selection bar, so a swatch is the only way a passage is kept, and a
// capture that records no section cannot be resolved back to anything.
const recording = await page.evaluate(async (api) => {
  const res = await fetch(`${api}/documents?page=1&page_size=50&sort=last_accessed`)
  const data = await res.json()
  return (data.items ?? []).find((d) => ["audio", "video"].includes(d.content_type)) ?? null
}, API)
if (!recording) {
  console.log("  SKIP the capture-locus checks: the library holds no recording")
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
      const before = await page.evaluate(async ({ api, docId }) => {
        const res = await fetch(`${api}/annotations?document_id=${docId}`)
        return (await res.json()).map((a) => a.id)
      }, { api: API, docId: recording.id })

      await page.mouse.move(rect.x + 5, rect.y + Math.min(rect.height / 2, 20))
      await page.mouse.down()
      await page.mouse.move(rect.x + Math.min(rect.width - 5, 300), rect.y + Math.min(rect.height / 2, 20), { steps: 12 })
      await page.mouse.up()
      await page.waitForTimeout(800)

      // The swatch carries no label, so it is addressed by the title the bar
      // gives it -- and a disabled swatch has a different one, which is the
      // failure this check is here to catch.
      const swatch = page.locator('[data-testid="selection-action-bar"] button[title="Highlight yellow"]')
      check("the transcript selection offers a highlight swatch", (await swatch.count()) > 0)
      if (await swatch.count()) {
        await swatch.first().click()
        await page.waitForTimeout(2500)
        const dialogs = await page.evaluate(() => document.querySelectorAll('[role="dialog"]').length)
        check("highlighting a passage opens no dialog", dialogs === 0, `${dialogs} dialogs`)

        // Identified by what was not there before, never by position: the
        // endpoint's order is not this check's to assume, and asserting the
        // locus of the wrong row would pass while the new one stored nothing.
        const saved = await page.evaluate(async ({ api, docId, known }) => {
          const res = await fetch(`${api}/annotations?document_id=${docId}`)
          const fresh = (await res.json()).filter((a) => !known.includes(a.id))
          return fresh.length === 1 ? fresh[0] : null
        }, { api: API, docId: recording.id, known: before })
        check("the highlight was created", Boolean(saved), saved ? saved.id : "no single new annotation")
        if (saved) {
          check("the highlight keeps the section it came from", Boolean(saved.section_id), String(saved.section_id))
          check("the highlight keeps the words it was taken from",
            typeof saved.selected_text === "string" && saved.selected_text.length > 0,
            String(saved.selected_text).slice(0, 60))

          // The reader offers it back without leaving the document: the header's
          // highlight control only appears once there is one to manage.
          await page.reload({ waitUntil: "domcontentloaded" })
          await page.waitForTimeout(4000)
          const manage = page.getByTitle("Manage highlights")
          check("the reader offers the highlight back", (await manage.count()) > 0)
          if (await manage.count()) {
            await manage.first().click()
            await page.waitForTimeout(1000)
            const listedText = await page.evaluate(() => document.body.innerText)
            check("the panel lists the highlight it just took",
              listedText.includes(String(saved.selected_text).trim().slice(0, 30)))
          }

          // The Notes face lost nothing by losing Clip: it is still where a note
          // is written, and it is the only way in now.
          const notesTab = page.locator("button[aria-pressed]").filter({ hasText: /^Notes$/ })
          if (await notesTab.count()) {
            await notesTab.first().click()
            await page.waitForTimeout(1500)
          }
          const canWrite = await page.evaluate(() =>
            [...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === "New note"))
          check("the panel still offers a way to write a note", canWrite)

          // Dictating into a note is the same feature on the full note page and
          // in the panel, and the panel is where a reader is. An empty draft is
          // discarded when it closes, so opening one leaves nothing behind --
          // nothing is typed into it here for that reason.
          if (canWrite && dictation) {
            const newNote = page.locator("button").filter({ hasText: /^New note$/ })
            await newNote.first().click()
            await page.waitForTimeout(1200)
            const composer = page.locator('[data-testid="docked-note-composer"]')
            check("the Notes face opens a docked composer", (await composer.count()) === 1)
            check("the docked note composer offers the mic",
              (await composer.locator('button[title*="Dictate"]').count()) === 1)
          }

          // The check cleans up after itself rather than leaving one per run.
          await page.evaluate(async ({ api, id }) => {
            await fetch(`${api}/annotations/${id}`, { method: "DELETE" })
          }, { api: API, id: saved.id })
          console.log(`  (removed the highlight this check created: ${saved.id})`)
        }
      }
    }
  }
}

await page.screenshot({ path: ".citation-verify/dock.png" })
if (failures.length && pageErrors.length) {
  console.log("\nwhat the page reported while these ran:")
  for (const e of [...new Set(pageErrors)].slice(0, 8)) console.log(`  ${e}`)
}
console.log(failures.length ? `\n${failures.length} failed` : "\nall checks passed")
await browser.close()
process.exit(failures.length ? 1 : 0)
