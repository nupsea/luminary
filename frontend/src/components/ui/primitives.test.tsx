import { renderToStaticMarkup } from "react-dom/server"
import { Pencil } from "lucide-react"
import { describe, expect, it } from "vitest"
import { cn } from "@/lib/utils"
import DesignGallery from "@/dev/DesignGallery"
import { Badge } from "./badge"
import { Button, IconButton } from "./button"
import { Chip } from "./chip"
import { Progress } from "./progress"
import { SegmentedControl } from "./segmented-control"
import { Tooltip } from "./tooltip"

const html = (node: React.ReactElement) => renderToStaticMarkup(node)

describe("cn", () => {
  it("keeps a type-scale size beside an ink colour", () => {
    expect(cn("text-ui", "text-ink-2")).toBe("text-ui text-ink-2")
  })

  it("lets a later type-scale size replace an earlier one", () => {
    expect(cn("text-body", "text-caption")).toBe("text-caption")
  })

  it("treats shadow-overlay as a shadow", () => {
    expect(cn("shadow-overlay", "shadow-none")).toBe("shadow-none")
  })
})

describe("Button", () => {
  it("is type=button so it never submits a form by accident", () => {
    expect(html(<Button>Go</Button>)).toContain('type="button"')
  })

  it("draws its variant from role tokens", () => {
    expect(html(<Button variant="primary">Go</Button>)).toContain("bg-action")
    expect(html(<Button variant="danger">Go</Button>)).toContain("bg-danger")
  })

  it("shows a shortcut hint hidden from screen readers", () => {
    expect(html(<Button kbd="Enter">Go</Button>)).toMatch(/<kbd[^>]*aria-hidden="true"[^>]*>Enter<\/kbd>/)
  })
})

describe("IconButton", () => {
  it("names itself with its label", () => {
    expect(html(<IconButton label="Edit"><Pencil /></IconButton>)).toContain('aria-label="Edit"')
  })

  it("cannot be written without a label", () => {
    // @ts-expect-error an icon-only button needs a name
    const node = <IconButton><Pencil /></IconButton>
    expect(node).toBeTruthy()
  })
})

describe("Tooltip", () => {
  it("returns the trigger untouched when there is nothing to say", () => {
    expect(html(<Tooltip content=""><span>x</span></Tooltip>)).toBe("<span>x</span>")
  })

  it("wires the trigger when there is", () => {
    expect(html(<Tooltip content="Why"><button>x</button></Tooltip>)).toContain('data-state="closed"')
  })
})

describe("Chip", () => {
  it("announces selection through aria-pressed", () => {
    expect(html(<Chip selected>All</Chip>)).toContain('aria-pressed="true"')
    expect(html(<Chip>All</Chip>)).toContain('aria-pressed="false"')
  })
})

describe("SegmentedControl", () => {
  const options = [
    { value: "easy", label: "Easy" },
    { value: "hard", label: "Hard" },
  ]
  const tabStops = (value: string) =>
    [...html(<SegmentedControl label="Difficulty" value={value} options={options} onChange={() => {}} />).matchAll(
      /aria-checked="(\w+)" tabindex="(-?\d)"/g,
    )].map((m) => [m[1], m[2]])

  it("is a labelled radio group with one tab stop, on the selection", () => {
    const out = html(<SegmentedControl label="Difficulty" value="hard" options={options} onChange={() => {}} />)
    expect(out).toContain('role="radiogroup" aria-label="Difficulty"')
    expect(tabStops("hard")).toEqual([["false", "-1"], ["true", "0"]])
  })

  it("keeps the first option reachable when nothing is selected", () => {
    expect(tabStops("missing")).toEqual([["false", "0"], ["false", "-1"]])
  })
})

describe("Progress", () => {
  it("clamps and reports its value", () => {
    expect(html(<Progress value={140} label="Today" />)).toContain('aria-valuenow="100"')
    expect(html(<Progress value={-5} />)).toContain('aria-valuenow="0"')
  })
})

describe("Badge", () => {
  it("defaults to neutral", () => {
    expect(html(<Badge>x</Badge>)).toContain("text-ink-2")
  })
})

describe("the design gallery", () => {
  // Same rule the ratchet enforces in source, checked on what the primitives actually render.
  const RAW_PALETTE =
    /\b(?:bg|text|border|ring|fill|stroke)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/
  const out = html(<DesignGallery />)

  it("renders every primitive with role tokens only", () => {
    expect(out).not.toMatch(RAW_PALETTE)
    expect(out).not.toMatch(/#[0-9a-fA-F]{6}\b/)
  })

  it("would catch a raw palette class", () => {
    expect(`<span class="bg-red-500">`).toMatch(RAW_PALETTE)
  })
})
