/**
 * Design-token ratchet: styling debt already in the tree may only shrink.
 *
 * Counts, per file, the ways a component can bypass the Luminary token layer: a raw
 * Tailwind palette colour, a hex colour, an arbitrary font size or spacing value, an
 * off-scale radius or shadow, and a hand-styled <button>. design-baseline.json holds
 * today's counts. A file that goes above its count fails, and so does one that went
 * below it until the baseline is lowered, so the file shrinks as screens migrate.
 *
 *   node scripts/check-design-tokens.mjs           # check (make ci)
 *   node scripts/check-design-tokens.mjs --prune   # lower counts that dropped; never raises
 *   node scripts/check-design-tokens.mjs --report  # totals per category
 */
import fs from "node:fs"
import path from "node:path"

const ROOT = path.resolve(import.meta.dirname, "..")
const SRC = path.join(ROOT, "src")
const BASELINE = path.join(import.meta.dirname, "design-baseline.json")

const HUES =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
const PREFIXES =
  "bg|text|border|border-[trblxy]|ring|ring-offset|from|via|to|fill|stroke|outline|divide|accent|decoration|shadow|placeholder|caret"

// Each check names what the token layer replaces it with, so a failure says what to do.
const CHECKS = {
  raw_palette: {
    re: new RegExp(`(?<![\\w-])(?:[a-z0-9-]+:)*(?:${PREFIXES})-(?:(?:${HUES})-\\d{2,3}|white|black)\\b`, "g"),
    fix: "use a role token (text-ink-2, bg-positive-soft, border-hairline...)",
  },
  hex_color: {
    re: /(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b|["'`]#[0-9a-fA-F]{3}["'`]/g,
    fix: "read the colour from a CSS token, never a literal",
  },
  arbitrary_font_size: {
    re: /\btext-\[\d[^\]]*\]/g,
    fix: "use the type scale (text-eyebrow, text-caption, text-ui, text-body...)",
  },
  arbitrary_spacing: {
    re: /(?<![\w-])(?:[a-z0-9-]+:)*-?(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|gap-x|gap-y|space-x|space-y|top|left|right|bottom|inset|inset-x|inset-y)-\[[^\]]+\]/g,
    fix: "use the 4px spacing scale",
  },
  off_scale_radius: {
    re: /(?<![\w-])(?:[a-z0-9-]+:)*rounded(?:-[trblse]{1,2})?-(?:2xl|3xl|\[[^\]]+\])/g,
    fix: "use rounded-sm, -md, -lg, -xl or -full",
  },
  surface_shadow: {
    re: /(?<![\w-])(?:[a-z0-9-]+:)*shadow(?:-(?:md|lg|xl|2xl|inner))?(?![\w-])/g,
    fix: "surfaces are flat; overlays use shadow-overlay",
  },
  raw_button: {
    re: /<button\b/g,
    fix: "use Button or IconButton from components/ui",
    skip: (rel) => rel.startsWith("components/ui/"),
  },
}

function sourceFiles(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...sourceFiles(full))
    else if (/\.(tsx?|jsx?)$/.test(entry.name) && !/\.test\.|\.d\.ts$/.test(entry.name)) out.push(full)
  }
  return out
}

// Generated: regenerated from the OpenAPI schema, never hand-styled.
const EXEMPT = new Set(["types/api.ts"])

function measure(text, rel) {
  const counts = {}
  for (const [name, check] of Object.entries(CHECKS)) {
    if (check.skip?.(rel)) continue
    const n = (text.match(check.re) ?? []).length
    if (n) counts[name] = n
  }
  return counts
}

function measureTree() {
  const result = {}
  for (const name of Object.keys(CHECKS)) result[name] = {}
  for (const file of sourceFiles(SRC)) {
    const rel = path.relative(SRC, file).split(path.sep).join("/")
    if (EXEMPT.has(rel)) continue
    for (const [name, n] of Object.entries(measure(fs.readFileSync(file, "utf8"), rel))) {
      result[name][rel] = n
    }
  }
  return result
}

function sorted(obj) {
  return Object.fromEntries(Object.keys(obj).sort().map((k) => [k, obj[k]]))
}

const args = new Set(process.argv.slice(2))
const now = measureTree()

if (args.has("--report")) {
  for (const [name, files] of Object.entries(now)) {
    const total = Object.values(files).reduce((a, b) => a + b, 0)
    console.log(`${name.padEnd(22)} ${String(total).padStart(5)} in ${Object.keys(files).length} files`)
  }
  process.exit(0)
}

if (args.has("--init")) {
  const out = Object.fromEntries(Object.entries(now).map(([k, v]) => [k, sorted(v)]))
  fs.writeFileSync(BASELINE, JSON.stringify(out, null, 2) + "\n")
  console.log(`design baseline written: ${BASELINE}`)
  process.exit(0)
}

const base = JSON.parse(fs.readFileSync(BASELINE, "utf8"))
const grew = []
const shrank = []
for (const [name, files] of Object.entries(now)) {
  const allowed = base[name] ?? {}
  for (const [file, n] of Object.entries(files)) {
    if (n > (allowed[file] ?? 0)) grew.push(`${name}: ${file} has ${n}, baseline ${allowed[file] ?? 0} — ${CHECKS[name].fix}`)
  }
  for (const [file, n] of Object.entries(allowed)) {
    if ((files[file] ?? 0) < n) shrank.push([name, file, files[file] ?? 0])
  }
}

if (args.has("--prune")) {
  if (grew.length) {
    console.error("refusing to prune while the tree has new offenders:\n  " + grew.join("\n  "))
    process.exit(1)
  }
  for (const [name, file, n] of shrank) {
    if (n === 0) delete base[name][file]
    else base[name][file] = n
  }
  const out = Object.fromEntries(Object.entries(base).map(([k, v]) => [k, sorted(v)]))
  fs.writeFileSync(BASELINE, JSON.stringify(out, null, 2) + "\n")
  console.log(`design baseline lowered for ${shrank.length} entries`)
  process.exit(0)
}

if (grew.length || shrank.length) {
  if (grew.length) console.error("New styling outside the token layer:\n  " + grew.join("\n  "))
  if (shrank.length) {
    console.error(
      "Debt paid but the baseline still allows it; run `node scripts/check-design-tokens.mjs --prune`:\n  " +
        shrank.map(([name, file, n]) => `${name}: ${file} now ${n}`).join("\n  "),
    )
  }
  process.exit(1)
}
console.log("design ratchet OK")
