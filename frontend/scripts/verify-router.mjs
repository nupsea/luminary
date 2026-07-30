/**
 * Client-side routing smoke test against a running app, in a real browser.
 *
 * Routing is the one layer `tsc --noEmit` and the unit suite cannot cover: the
 * component/hook API type-checks identically across react-router majors, so a
 * behavioural regression (history stack, location.state, param cleanup) only
 * shows up at runtime. Re-run this after any react-router bump.
 *
 *   make luminary          # app must already be serving
 *   make verify-router
 *
 * Env: LUMINARY_URL (default http://localhost:5173), LUMINARY_API
 * (default http://localhost:7820). Exits non-zero if any check fails.
 */
import { chromium } from "playwright-core"
import fs from "node:fs"
import path from "node:path"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
const API = process.env.LUMINARY_API ?? "http://localhost:7820"
const OUT = path.resolve(import.meta.dirname, "../.router-verify")

const results = []
const consoleMsgs = []
let shotIndex = 0

function check(name, pass, detail) {
  results.push({ name, status: pass ? "pass" : "fail", detail })
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`)
}
function skip(name, why) {
  results.push({ name, status: "skip", detail: why })
  console.log(`SKIP  ${name} — ${why}`)
}

async function launch() {
  // Prefer Playwright's own Chromium; fall back to a locally installed browser
  // so this runs on a machine that never ran `playwright install`.
  const attempts = [undefined, "chrome", "msedge", "chromium"]
  let lastErr
  for (const channel of attempts) {
    try {
      return await chromium.launch(channel ? { channel } : {})
    } catch (err) {
      lastErr = err
    }
  }
  throw new Error(
    `No Chromium-family browser could be launched. Install one with ` +
      `\`npx playwright install chromium\`.\nLast error: ${lastErr?.message}`
  )
}

async function json(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  return res.json()
}

const browser = await launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on("console", (m) => {
  if (m.type() === "warning" || m.type() === "error")
    consoleMsgs.push({ type: m.type(), text: m.text().slice(0, 500), at: page.url() })
})
page.on("pageerror", (e) => consoleMsgs.push({ type: "pageerror", text: String(e).slice(0, 500), at: page.url() }))

const here = () => {
  const u = new URL(page.url())
  return u.pathname + u.search
}
async function settle(ms = 1200) {
  await page.waitForLoadState("networkidle").catch(() => {})
  await page.waitForTimeout(ms)
}
async function shot(label) {
  await page.screenshot({ path: `${OUT}/${String(++shotIndex).padStart(2, "0")}-${label}.png` })
}
const backButton = () => page.locator("button", { hasText: /^Back to / }).first()
async function backLabel() {
  const b = backButton()
  return (await b.count()) ? (await b.innerText()).trim() : null
}
const chars = async () => (await page.locator("body").innerText()).trim().length

fs.rmSync(OUT, { recursive: true, force: true })
fs.mkdirSync(OUT, { recursive: true })

// -- 1. every tab-rail destination -------------------------------------------
await page.goto(`${APP}/`, { waitUntil: "networkidle" })
await settle()
const rail = await page
  .locator("nav a")
  .evaluateAll((els) => els.map((e) => ({ href: new URL(e.href).pathname, label: (e.getAttribute("title") ?? e.innerText).trim().split("\n")[0] })))
check("app shell renders a tab rail", rail.length > 0, `${rail.length} destinations`)
await shot("home")

for (const { href, label } of rail) {
  const link = page.locator(`nav a[href="${href}"]`).first()
  await link.click()
  await settle(900)
  const current = await link.evaluate((e) => e.getAttribute("aria-current"))
  const size = await chars()
  check(`rail → ${href} (${label})`, here() === href && current === "page" && size > 50, `url=${here()} aria-current=${current} chars=${size}`)
  await shot(`rail${href.replace(/\//g, "_")}`)
}

// -- 2. history stack --------------------------------------------------------
const trail = rail.map((r) => r.href).filter((h) => h !== "/").slice(0, 5)
if (trail.length < 4) {
  skip("browser Back/Forward", `needs 4+ rail destinations, found ${trail.length}`)
} else {
  await page.goto(`${APP}/`, { waitUntil: "networkidle" })
  await settle(700)
  for (const t of trail) {
    await page.locator(`nav a[href="${t}"]`).first().click()
    await settle(700)
  }
  const back = []
  for (let i = 0; i < 3; i++) {
    await page.goBack()
    await settle(600)
    back.push(here())
  }
  const expectBack = trail.slice(0, -1).reverse().slice(0, 3)
  check("browser Back x3 replays the history stack", JSON.stringify(back) === JSON.stringify(expectBack), `${back.join(" → ")} (expected ${expectBack.join(" → ")})`)

  const fwd = []
  for (let i = 0; i < 2; i++) {
    await page.goForward()
    await settle(600)
    fwd.push(here())
  }
  const expectFwd = expectBack.slice(0, -1).reverse()
  check("browser Forward x2 replays the history stack", JSON.stringify(fwd) === JSON.stringify(expectFwd), `${fwd.join(" → ")} (expected ${expectFwd.join(" → ")})`)
  check("view re-renders after history navigation", (await chars()) > 100, `chars=${await chars()}`)
  await shot("after-history")
}

// -- 3. deep links -----------------------------------------------------------
const doc = (await json(`${API}/documents?page=1&page_size=1`).catch(() => ({ items: [] }))).items?.[0]
if (!doc) {
  skip("document deep link", "library is empty")
} else {
  // /library/doc/:id is an alias that Navigate-replaces to /library?doc=, which
  // the library page then strips — so landing on a bare /library is correct.
  // The reader affordances, not the URL, are the proof it resolved.
  const readerOpen = async () =>
    (await page.locator("button", { hasText: /^Back to library$/ }).count()) > 0 &&
    (await page.getByText("Sections", { exact: true }).count()) > 0
  for (const label of ["pasted URL", "hard reload"]) {
    await page.goto(`${APP}/library/doc/${doc.id}`, { waitUntil: "networkidle" })
    await settle(1800)
    check(`deep-link /library/doc/:id opens the reader (${label})`, await readerOpen(), `url=${here()}`)
  }
  await shot("deeplink-doc")
}

const notes = await json(`${API}/notes`).catch(() => [])
const note = Array.isArray(notes) ? notes[0] : notes?.items?.[0]
if (!note) {
  skip("note deep link", "no notes exist")
} else {
  const target = `/notes/${note.id}`
  // The note body lives in a CodeMirror instance, which body.innerText does not
  // report — assert on the editor content, or an empty editor reads as a pass.
  const editorChars = async () => ((await page.locator(".cm-content").first().innerText().catch(() => "")) ?? "").trim().length
  for (const label of ["pasted URL", "hard refresh"]) {
    if (label === "pasted URL") await page.goto(APP + target, { waitUntil: "networkidle" })
    else await page.reload({ waitUntil: "networkidle" })
    await settle(1500)
    check(`deep-link /notes/:noteId loads the note (${label})`, here() === target && (await editorChars()) > 0, `url=${here()} editorChars=${await editorChars()}`)
  }
  await shot("deeplink-note")

  // A render crash inside a route unmounts the whole root and leaves a blank
  // page with the URL intact, so URL-only assertions miss it entirely.
  const mounted = async () => (await page.evaluate(() => document.getElementById("root")?.children.length ?? 0)) > 0
  const preview = page.locator('button[title="Show preview pane"]')
  if (!(await preview.count())) {
    skip("preview pane keeps the app mounted", "no preview toggle on this note")
  } else {
    await preview.click()
    await settle(2000)
    check("toggling the preview pane keeps the app mounted", (await mounted()) && (await editorChars()) > 0, `rootChildren=${await page.evaluate(() => document.getElementById("root")?.children.length ?? 0)} editorChars=${await editorChars()}`)
    await shot("note-preview-pane")
  }
}

await page.goto(`${APP}/no-such-route-exists`, { waitUntil: "networkidle" })
await settle(1200)
check("unknown route self-heals to /", here() === "/", `landed ${here()}`)

// -- 4. location.state.from round trip ---------------------------------------
// Hub cards navigate with { state: { from: "/" } }; useBackNavigation turns that
// into a labelled back affordance. Both are invisible to the type checker.
// Some hub cards open a launcher dialog instead of navigating, so try the
// candidates in turn rather than assuming the first one routes.
const candidates = page.locator("main button", { hasText: /in Study|card session|review now/i })
const candidateCount = Math.min(await candidates.count(), 4)
let routed = null
for (let i = 0; i < candidateCount; i++) {
  await page.goto(`${APP}/`, { waitUntil: "networkidle" })
  await settle(1800)
  const card = candidates.nth(i)
  if (!(await card.count())) continue
  const text = (await card.innerText()).trim().replace(/\n/g, " ").slice(0, 50)
  await card.click()
  await settle(1500)
  if (here() !== "/" && (await backLabel())) {
    routed = { text, url: here(), label: await backLabel() }
    break
  }
}
if (!routed) {
  skip("Hub card → state.from back button", `no navigating study card among ${candidateCount} candidate(s)`)
} else {
  check("Hub card → destination renders a state.from back button", routed.label === "Back to Home", `clicked "${routed.text}" → url=${routed.url} label="${routed.label}"`)
  await shot("state-from-back-label")
  if (routed.label === "Back to Home") {
    await backButton().click()
    await settle(1200)
    check("back button (navigate(-1)) returns to the origin", here() === "/", `landed ${here()}`)
  }
}

// -- 5. setSearchParams(replace, state) preserves state ----------------------
// The library strips ?doc/?section_id/?page after opening a document. The state
// must ride through that replace, or the back affordance dies on deep links.
await page.goto(`${APP}/`, { waitUntil: "networkidle" })
await settle(1800)
const progressCard = await page.evaluate(() => {
  const b = [...document.querySelectorAll("main li > button, main button")].find(
    (el) => /\d+%/.test(el.innerText ?? "") && (el.innerText ?? "").trim().length > 5
  )
  if (!b) return null
  b.click()
  return b.innerText.trim().replace(/\n/g, " ").slice(0, 50)
})
if (!progressCard) {
  skip("?doc= cleanup preserves location.state", "no in-progress document card on the hub")
} else {
  await settle(1800)
  const cleaned = here()
  const label = await backLabel()
  check("?doc= is stripped by setSearchParams(replace: true)", cleaned.startsWith("/library") && !cleaned.includes("doc="), `clicked "${progressCard}" → ${cleaned}`)
  check("location.state.from survives the param cleanup", label === "Back to Home", `label="${label}"`)
  await shot("param-cleanup")
  await page.goBack()
  await settle(1200)
  check("replace: true left no extra history entry", here() === "/", `one Back landed on ${here()}`)
}

// -- 6. router diagnostics ---------------------------------------------------
const routerMsgs = consoleMsgs.filter((m) => /router|<Link>|useNavigate|future flag|v7_|relative splat|startTransition|hydrat/i.test(m.text))
check("no react-router warnings in the console", routerMsgs.length === 0, `${routerMsgs.length} router-related message(s)`)

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify({ app: APP, ran_at: new Date().toISOString(), results, consoleMsgs }, null, 2))
await browser.close()

const failed = results.filter((r) => r.status === "fail")
const passed = results.filter((r) => r.status === "pass")
const skipped = results.filter((r) => r.status === "skip")
console.log(`\n${passed.length} passed, ${failed.length} failed, ${skipped.length} skipped`)
if (consoleMsgs.length) {
  console.log(`\nconsole warnings/errors (${consoleMsgs.length}, router-related: ${routerMsgs.length}):`)
  for (const m of consoleMsgs.slice(0, 20)) console.log(`  [${m.type}] ${m.text}  @${m.at}`)
}
console.log(`\nScreenshots and results.json: ${OUT}`)
process.exit(failed.length ? 1 : 0)
