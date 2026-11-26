/**
 * Every surface in light and dark, at desktop and phone width, plus a keyboard pass.
 *
 * The design-system work changes how nearly every element looks, and no unit test can
 * see that. Each phase runs this before and after and the two sets are compared side
 * by side; the keyboard pass lists controls that take focus with no visible ring.
 *
 *   make luminary   # or make dev: the app must already be serving
 *   make ui-snapshots SNAP_LABEL=before
 *
 * Env: LUMINARY_URL (default http://localhost:5173), LUMINARY_API (default
 * http://localhost:7820), SNAP_LABEL (default "snap"). Read-only: it navigates, presses
 * Tab and opens the settings drawer, and never clicks anything that writes.
 */
import { chromium } from "playwright-core"
import fs from "node:fs"
import path from "node:path"

const APP = process.env.LUMINARY_URL ?? "http://localhost:5173"
const API = process.env.LUMINARY_API ?? "http://localhost:7820"
const LABEL = process.env.SNAP_LABEL ?? "snap"
const OUT = path.resolve(import.meta.dirname, "../.ui-snapshots", LABEL)
const MANIFEST = path.resolve(import.meta.dirname, "../../surface-manifest.json")

const THEMES = ["light", "dark"]
const WIDTHS = [
  { name: "desktop", width: 1280, height: 860 },
  { name: "phone", width: 390, height: 844 },
]
const TAB_STOPS = 40

async function launch() {
  for (const channel of [undefined, "chrome", "msedge", "chromium"]) {
    try {
      return await chromium.launch(channel ? { channel } : {})
    } catch {
      // try the next installed browser
    }
  }
  throw new Error("No Chromium-family browser could be launched (npx playwright install chromium).")
}

async function firstId(url, pick) {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    return pick(await res.json()) ?? null
  } catch {
    return null
  }
}

// A route with a parameter is captured with the first real row, or skipped and reported.
async function resolveParams() {
  return {
    ":id": await firstId(`${API}/documents?page=1&page_size=1`, (d) => d.items?.[0]?.id),
    ":noteId": await firstId(`${API}/notes?limit=1`, (d) => (Array.isArray(d) ? d[0]?.id : d.items?.[0]?.id)),
    ":collectionId": await firstId(`${API}/collections/tree`, (d) => d?.[0]?.id),
  }
}

function routes(params) {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"))
  const out = []
  for (const s of manifest.surfaces) {
    const route = s.frontend?.route
    if (!route) continue
    let filled = route
    let missing = null
    for (const m of route.match(/:[A-Za-z]+/g) ?? []) {
      const value = m === ":id" && route.startsWith("/collections") ? params[":collectionId"] : params[m]
      if (!value) missing = m
      else filled = filled.replace(m, value)
    }
    out.push({ id: s.id, route: filled, missing })
  }
  return out
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {})
  await page.waitForTimeout(900)
}

async function setTheme(page, theme) {
  await page.evaluate((t) => localStorage.setItem("luminary-theme", t), theme)
}

// Visible focus: an outline or a ring drawn as box-shadow. The pass stops at the first
// rich-text editor: it can take Tab as an indent, and this script never writes.
async function focusPass(page) {
  const stops = []
  for (let i = 0; i < TAB_STOPS; i++) {
    await page.keyboard.press("Tab")
    const info = await page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body) return null
      if (el.isContentEditable) {
        el.blur()
        return { stop: true, tag: el.tagName.toLowerCase() }
      }
      const cs = getComputedStyle(el)
      const ring =
        (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) ||
        (cs.boxShadow && cs.boxShadow !== "none")
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "")
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 50)
      return { tag: el.tagName.toLowerCase(), role: el.getAttribute("role"), name, ring: Boolean(ring) }
    })
    if (!info) break
    if (info.stop) {
      stops.push({ tag: info.tag, name: "(editable field: pass stopped here)", ring: true })
      break
    }
    stops.push(info)
  }
  return stops
}

fs.mkdirSync(OUT, { recursive: true })
const browser = await launch()
const report = { label: LABEL, app: APP, at: new Date().toISOString(), routes: [], focus: {} }
const list = routes(await resolveParams())

for (const size of WIDTHS) {
  const page = await browser.newPage({ viewport: { width: size.width, height: size.height } })
  await page.goto(APP)
  for (const theme of THEMES) {
    await setTheme(page, theme)
    for (const r of list) {
      if (r.missing) continue
      await page.goto(APP + r.route)
      await settle(page)
      const file = `${r.id}-${theme}-${size.name}.png`
      await page.screenshot({ path: path.join(OUT, file) })
      report.routes.push({ id: r.id, route: r.route, theme, size: size.name, file })
    }
    if (size.name === "desktop") {
      await page.goto(APP + "/")
      await settle(page)
      const gear = page.locator("button:has(svg.lucide-settings)").first()
      if (await gear.count()) {
        await gear.click()
        await settle(page)
        await page.screenshot({ path: path.join(OUT, `settings-drawer-${theme}-desktop.png`) })
        await page.keyboard.press("Escape")
      }
    }
  }
  if (size.name === "desktop") {
    await setTheme(page, "light")
    for (const r of list) {
      if (r.missing) continue
      await page.goto(APP + r.route)
      await settle(page)
      report.focus[r.id] = await focusPass(page)
    }
  }
  await page.close()
}
await browser.close()

report.skipped = list.filter((r) => r.missing).map((r) => `${r.id} (no ${r.missing} in this library)`)
const noRing = Object.entries(report.focus).flatMap(([id, stops]) =>
  stops.filter((s) => !s.ring).map((s) => `${id}: <${s.tag}> ${s.name || "(unnamed)"}`),
)
report.focus_without_ring = noRing
fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2))

console.log(`${report.routes.length} screenshots in ${OUT}`)
if (report.skipped.length) console.log(`skipped: ${report.skipped.join(", ")}`)
console.log(`focus stops without a visible ring: ${noRing.length}`)
for (const line of noRing.slice(0, 30)) console.log(`  ${line}`)
