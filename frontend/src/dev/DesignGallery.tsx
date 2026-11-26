import { useState } from "react"
import { Archive, Check, Inbox, Pencil, Play, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Badge, type BadgeVariant } from "@/components/ui/badge"
import { Button, IconButton } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState } from "@/components/ui/empty-state"
import { Eyebrow, SectionHeading } from "@/components/ui/heading"
import { Input, Select, Textarea } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"
import { Progress } from "@/components/ui/progress"
import { SegmentedControl } from "@/components/ui/segmented-control"
import { StatPill } from "@/components/ui/stat-pill"

// Class names spelled out in full so Tailwind generates them.
const SWATCHES = [
  ["canvas", "bg-canvas"], ["raised", "bg-raised"], ["sunken", "bg-sunken"], ["rail", "bg-rail"],
  ["hover", "bg-hover"], ["hairline", "bg-hairline"], ["line-strong", "bg-line-strong"],
  ["ink-1", "bg-ink-1"], ["ink-2", "bg-ink-2"], ["ink-3", "bg-ink-3"], ["action", "bg-action"],
  ["brand", "bg-brand"], ["focus", "bg-focus"], ["danger", "bg-danger"],
  ["positive", "bg-positive"], ["negative", "bg-negative"], ["caution", "bg-caution"], ["info", "bg-info"],
  ["recall", "bg-mode-recall"], ["quiz", "bg-mode-quiz"], ["explain", "bg-mode-explain"],
  ["chart-1", "bg-chart-1"], ["chart-2", "bg-chart-2"], ["chart-3", "bg-chart-3"], ["chart-4", "bg-chart-4"],
  ["chart-5", "bg-chart-5"], ["chart-6", "bg-chart-6"], ["chart-7", "bg-chart-7"], ["chart-8", "bg-chart-8"],
] as const

const TYPE_SCALE = [
  ["h1", "text-h1 font-bold"], ["h2", "text-h2 font-semibold"], ["h3", "text-h3 font-semibold"],
  ["title", "text-title font-semibold"], ["body", "text-body"], ["ui", "text-ui"],
  ["caption", "text-caption"], ["eyebrow", "text-eyebrow font-bold uppercase"],
] as const

const BADGES: BadgeVariant[] = ["neutral", "brand", "info", "positive", "negative", "caution"]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t border-hairline pt-6">
      <Eyebrow>{title}</Eyebrow>
      {children}
    </section>
  )
}

const Row = ({ children }: { children: React.ReactNode }) => (
  <div className="flex flex-wrap items-center gap-3">{children}</div>
)

export default function DesignGallery() {
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")
  const [scope, setScope] = useState("all")

  return (
    <div className="h-full overflow-y-auto bg-canvas">
      <div className="mx-auto max-w-4xl space-y-8 px-8 py-10">
        <header className="space-y-1">
          <Eyebrow>Luminary</Eyebrow>
          <h1 className="text-h1 font-bold text-ink-1">Design system</h1>
        </header>

        <Section title="Colour">
          <div className="grid grid-cols-4 gap-3 sm:grid-cols-8">
            {SWATCHES.map(([name, cls]) => (
              <div key={name} className="space-y-1">
                <div className={`h-10 rounded-md border border-hairline ${cls}`} />
                <p className="text-caption text-ink-2">{name}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Type">
          <div className="space-y-2">
            {TYPE_SCALE.map(([name, cls]) => (
              <div key={name} className="flex items-baseline gap-4">
                <span className="w-16 shrink-0 text-caption text-ink-2">{name}</span>
                <span className={`text-ink-1 ${cls}`}>Retrieval beats rereading</span>
              </div>
            ))}
            <p className="font-serif text-body text-ink-1">Serif carries content: a passage, a card, a quote.</p>
          </div>
        </Section>

        <Section title="Button">
          {(["sm", "md"] as const).map((size) => (
            <Row key={size}>
              <Button variant="primary" size={size} kbd="Enter"><Play />Start</Button>
              <Button variant="secondary" size={size}><Plus />Add</Button>
              <Button variant="ghost" size={size}>Skip</Button>
              <Button variant="danger" size={size}><Trash2 />Delete</Button>
              <Button variant="primary" size={size} disabled>Disabled</Button>
            </Row>
          ))}
          <Row>
            <IconButton label="Edit"><Pencil /></IconButton>
            <IconButton label="Archive" variant="secondary"><Archive /></IconButton>
            <IconButton label="Done" variant="primary" size="md"><Check /></IconButton>
            <IconButton label="Delete" variant="danger"><Trash2 /></IconButton>
          </Row>
        </Section>

        <Section title="Choice">
          <Row>
            {["all", "Designing Data-Intensive Applications", "Gita"].map((s) => (
              <Chip key={s} selected={scope === s} onClick={() => setScope(s)} count={s === "all" ? 91 : 12}>
                {s === "all" ? "Everything" : s}
              </Chip>
            ))}
            <Chip disabled>Disabled</Chip>
          </Row>
          <SegmentedControl
            label="Difficulty"
            value={difficulty}
            onChange={setDifficulty}
            options={[
              { value: "easy", label: "Easy", tip: "Wrong answers are clearly wrong" },
              { value: "medium", label: "Medium" },
              { value: "hard", label: "Hard", tip: "Wrong answers sit close to the truth" },
            ]}
          />
        </Section>

        <Section title="Status">
          <Row>
            {BADGES.map((v) => <Badge key={v} variant={v}>{v}</Badge>)}
          </Row>
          <Row>
            <StatPill value={91} label="due" tone="action" tip="Reviews scheduled for today" />
            <StatPill value={10} label="new" />
            <StatPill value="4/5" label="days" tone="positive" />
            <span className="text-ui text-ink-2">Press <Kbd>?</Kbd> for shortcuts</span>
          </Row>
          <div className="grid max-w-sm gap-2">
            <Progress value={64} label="Today" />
            <Progress value={30} tone="positive" label="Week" />
            <Progress value={85} tone="caution" label="Budget" />
          </div>
          <Row>
            <Button onClick={() => toast.success("Card saved")}>Success toast</Button>
            <Button onClick={() => toast.error("Could not reach the model", { description: "Ollama is not running." })}>
              Error toast
            </Button>
            <Button onClick={() => toast("Quiz ready", { action: { label: "Open", onClick: () => {} } })}>
              Action toast
            </Button>
          </Row>
        </Section>

        <Section title="Input">
          <div className="grid max-w-md gap-3">
            <Input placeholder="Search your library" aria-label="Search" />
            <Input defaultValue="Not a number" aria-invalid aria-label="Invalid" />
            <Input disabled placeholder="Disabled" aria-label="Disabled" />
            <Select aria-label="Model" defaultValue="qwen">
              <option value="qwen">qwen3.5:4b</option>
              <option value="gemma">gemma3:4b</option>
            </Select>
            <Textarea placeholder="Explain it in your own words" aria-label="Explanation" />
          </div>
        </Section>

        <Section title="Layout">
          <SectionHeading
            title="Shelves"
            count={4}
            action={<Button variant="ghost"><Plus />New shelf</Button>}
          />
          <div className="rounded-lg border border-hairline">
            <EmptyState
              icon={Inbox}
              title="Nothing due"
              hint="New cards arrive tomorrow."
              action={<Button variant="secondary">Practise a chapter</Button>}
            />
          </div>
        </Section>
      </div>
    </div>
  )
}
