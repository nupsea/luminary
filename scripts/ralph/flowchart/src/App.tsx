import { useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  MarkerType,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import prd from '../../prd-v3.json'

// ── colour palette ──────────────────────────────────────────────
const C = {
  terminal:  { bg: '#16a34a', text: '#fff', border: '#15803d' },
  process:   { bg: '#3b82f6', text: '#fff', border: '#2563eb' },
  decision:  { bg: '#7c3aed', text: '#fff', border: '#6d28d9' },
  gate:      { bg: '#0f172a', text: '#e2e8f0', border: '#334155' },
  fix:       { bg: '#dc2626', text: '#fff', border: '#b91c1c' },
  log:       { bg: '#0891b2', text: '#fff', border: '#0e7490' },
  done:      { bg: '#15803d', text: '#fff', border: '#166534' },
  pending:   { bg: '#1e3a5f', text: '#93c5fd', border: '#2563eb' },
}

const nodeStyle = (c: typeof C[keyof typeof C], extra?: React.CSSProperties) => ({
  background: c.bg,
  color: c.text,
  border: `2px solid ${c.border}`,
  borderRadius: 10,
  padding: '10px 16px',
  fontSize: 12,
  fontWeight: 500,
  textAlign: 'center' as const,
  lineHeight: 1.5,
  minWidth: 180,
  ...extra,
})

const arrow = {
  markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
  style: { stroke: '#64748b', strokeWidth: 2 },
}
const redArrow = {
  markerEnd: { type: MarkerType.ArrowClosed, color: '#dc2626' },
  style: { stroke: '#dc2626', strokeWidth: 1.5, strokeDasharray: '5,3' },
  animated: true,
}

// ── RUN FLOW nodes ──────────────────────────────────────────────
const runNodes: Node[] = [
  {
    id: 'start',
    data: { label: 'Start\nralph invoked with PRD path' },
    position: { x: 380, y: 0 },
    sourcePosition: Position.Bottom,
    style: nodeStyle(C.terminal, { borderRadius: 40, minWidth: 200 }),
  },
  {
    id: 'read-prd',
    data: { label: 'Read PRD\nprd-v3.json' },
    position: { x: 380, y: 100 },
    style: nodeStyle(C.process),
  },
  {
    id: 'find-story',
    data: { label: 'Find first story\nwhere passes = false\nordered by priority' },
    position: { x: 380, y: 210 },
    style: nodeStyle(C.decision, { borderRadius: 4 }),
  },
  {
    id: 'read-plan',
    data: { label: 'Read or create exec plan\ndocs/exec-plans/active/SXXX.md' },
    position: { x: 380, y: 350 },
    style: nodeStyle(C.process),
  },
  {
    id: 'explore',
    data: { label: 'Explore codebase\nGlob + Grep + Read' },
    position: { x: 380, y: 460 },
    style: nodeStyle(C.process),
  },
  {
    id: 'impl-backend',
    data: { label: 'Implement backend\nmodels · db_init · service · router · tests' },
    position: { x: 380, y: 560 },
    style: nodeStyle(C.process),
  },
  {
    id: 'impl-frontend',
    data: { label: 'Implement frontend\ncomponents · hooks · Zustand · Vitest' },
    position: { x: 380, y: 660 },
    style: nodeStyle(C.process),
  },
  {
    id: 'gates',
    data: { label: 'Quality gates\n① ruff check   ② pytest   ③ tsc --noEmit' },
    position: { x: 380, y: 760 },
    style: nodeStyle(C.gate, { borderRadius: 8, minWidth: 260 }),
  },
  {
    id: 'gates-pass',
    data: { label: 'All gates pass?' },
    position: { x: 380, y: 870 },
    style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }),
  },
  {
    id: 'smoke',
    data: { label: 'Run smoke test\nscripts/smoke/SXXX.sh' },
    position: { x: 380, y: 980 },
    style: nodeStyle(C.process),
  },
  {
    id: 'smoke-pass',
    data: { label: 'Smoke exits 0?' },
    position: { x: 380, y: 1080 },
    style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }),
  },
  {
    id: 'reviewer',
    data: { label: 'Run luminary-reviewer agent\n.claude/agents/luminary-reviewer' },
    position: { x: 380, y: 1180 },
    style: nodeStyle(C.process),
  },
  {
    id: 'critical',
    data: { label: 'Critical items?' },
    position: { x: 380, y: 1280 },
    style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }),
  },
  {
    id: 'mark-done',
    data: { label: 'Set passes=true in PRD\nLog entry to progress.txt\nMove exec plan to completed/' },
    position: { x: 380, y: 1390 },
    style: nodeStyle(C.log, { minWidth: 260 }),
  },
  // exit / fix lanes
  {
    id: 'done',
    data: { label: 'Done\nAll stories pass' },
    position: { x: 700, y: 210 },
    style: nodeStyle(C.terminal, { borderRadius: 40 }),
  },
  {
    id: 'fix-gates',
    data: { label: 'Fix failures\nread error output · adjust code' },
    position: { x: 50, y: 870 },
    style: nodeStyle(C.fix),
  },
  {
    id: 'fix-smoke',
    data: { label: 'Debug smoke\ncurl endpoints · check logs' },
    position: { x: 50, y: 1080 },
    style: nodeStyle(C.fix),
  },
  {
    id: 'fix-critical',
    data: { label: 'Fix critical items\nfrom reviewer' },
    position: { x: 50, y: 1280 },
    style: nodeStyle(C.fix),
  },
]

const runEdges: Edge[] = [
  { id: 'e-start-prd',      source: 'start',       target: 'read-prd',     ...arrow },
  { id: 'e-prd-find',       source: 'read-prd',    target: 'find-story',   ...arrow },
  { id: 'e-find-plan',      source: 'find-story',  target: 'read-plan',    label: 'story found',    labelStyle: { fontSize: 11 }, ...arrow },
  { id: 'e-find-done',      source: 'find-story',  target: 'done',         label: 'no stories left', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow, style: { stroke: '#16a34a', strokeWidth: 2 } },
  { id: 'e-plan-explore',   source: 'read-plan',   target: 'explore',      ...arrow },
  { id: 'e-explore-be',     source: 'explore',     target: 'impl-backend', ...arrow },
  { id: 'e-be-fe',          source: 'impl-backend',target: 'impl-frontend',...arrow },
  { id: 'e-fe-gates',       source: 'impl-frontend',target: 'gates',       ...arrow },
  { id: 'e-gates-pass',     source: 'gates',       target: 'gates-pass',   ...arrow },
  { id: 'e-pass-smoke',     source: 'gates-pass',  target: 'smoke',        label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-pass-fix',       source: 'gates-pass',  target: 'fix-gates',    label: 'no',  labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-gates-back', source: 'fix-gates',   target: 'gates',        ...redArrow },
  { id: 'e-smoke-pass',     source: 'smoke',       target: 'smoke-pass',   ...arrow },
  { id: 'e-sp-reviewer',    source: 'smoke-pass',  target: 'reviewer',     label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-sp-fix',         source: 'smoke-pass',  target: 'fix-smoke',    label: 'no',  labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-smoke-back', source: 'fix-smoke',   target: 'impl-backend', ...redArrow },
  { id: 'e-rev-crit',       source: 'reviewer',    target: 'critical',     ...arrow },
  { id: 'e-crit-mark',      source: 'critical',    target: 'mark-done',    label: 'no',  labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-crit-fix',       source: 'critical',    target: 'fix-critical', label: 'yes', labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-crit-back',  source: 'fix-critical',target: 'gates',        ...redArrow },
  { id: 'e-mark-loop',      source: 'mark-done',   target: 'find-story',   label: 'next story', labelStyle: { fontSize: 11, fill: '#0891b2' }, type: 'smoothstep', ...arrow, style: { stroke: '#0891b2', strokeWidth: 2 } },
]

// ── STORY MAP ───────────────────────────────────────────────────
// Dependency groups drive the column layout
// Col 0 (x=60):  P1 S161, P2 S162, P3 S163  -- foundation
// Col 1 (x=340): P4 S170                     -- perf fix (needs S162)
// Col 2 (x=620): P5 S164, P6 S165            -- UI (needs S161/S162)
// Col 3 (x=900): P7 S167, P8 S168            -- graph+norm (needs S162+S165)
// Col 4 (x=1180):P9 S166, P10 S169           -- clustering+flashcards (needs S161+S162)

interface Story {
  id: string
  title: string
  phase: string
  priority: number
  featureRef: string
  passes: boolean
  description: string
  acceptanceCriteria: string[]
}

const stories = prd.stories as Story[]

// short labels for nodes
const shortTitle: Record<string, string[]> = {
  S161: ['S161 · P1', 'Collections', 'Schema + API'],
  S162: ['S162 · P2', 'Hierarchical Tags', 'Shadow Index + API'],
  S163: ['S163 · P3', 'Notes → Kuzu', 'GLiNER entity edges'],
  S170: ['S170 · P4', 'Perf Refactor', 'Vector dim + indexes'],
  S164: ['S164 · P5', 'Collections UI', 'Sidebar + CRUD'],
  S165: ['S165 · P6', 'Tag Browser UI', 'Autocomplete + merge'],
  S167: ['S167 · P7', 'Tag Viz Graph', 'Sigma.js Tags mode'],
  S168: ['S168 · P8', 'Tag Normalizer', 'Embed similarity'],
  S166: ['S166 · P9', 'Clustering', 'HDBSCAN → suggest'],
  S169: ['S169 · P10', 'Deck Gen', 'Collection flashcards'],
}

const storyPositions: Record<string, { x: number; y: number }> = {
  S161: { x: 60,   y: 80  },
  S162: { x: 60,   y: 240 },
  S163: { x: 60,   y: 400 },
  S170: { x: 340,  y: 160 },
  S164: { x: 620,  y: 80  },
  S165: { x: 620,  y: 260 },
  S167: { x: 900,  y: 80  },
  S168: { x: 900,  y: 260 },
  S166: { x: 1180, y: 80  },
  S169: { x: 1180, y: 260 },
}

function storyNode(s: Story): Node {
  const lines = shortTitle[s.id] ?? [s.id, s.title.slice(0, 30)]
  const col = s.passes ? C.done : C.pending
  return {
    id: s.id,
    data: {
      label: (
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 2 }}>{lines[0]}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{lines[1]}</div>
          <div style={{ fontSize: 10, opacity: 0.8 }}>{lines[2]}</div>
          <div style={{
            marginTop: 6, fontSize: 10, fontWeight: 700,
            color: s.passes ? '#86efac' : '#fbbf24',
            background: s.passes ? '#14532d' : '#451a03',
            borderRadius: 4, padding: '1px 6px', display: 'inline-block',
          }}>
            {s.passes ? '✓ passed' : '⏳ pending'}
          </div>
        </div>
      ),
    },
    position: storyPositions[s.id] ?? { x: 0, y: 0 },
    style: {
      background: col.bg,
      color: col.text,
      border: `2px solid ${col.border}`,
      borderRadius: 10,
      padding: '10px 14px',
      minWidth: 190,
    },
  }
}

// dependency edges between stories
const depEdgeStyle = {
  markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' },
  style: { stroke: '#475569', strokeWidth: 1.5 },
  type: 'smoothstep' as const,
}

const storyEdges: Edge[] = [
  // foundation -> perf
  { id: 'e-162-170', source: 'S162', target: 'S170', label: 'index dep', labelStyle: { fontSize: 10 }, ...depEdgeStyle },
  // foundation -> UI
  { id: 'e-161-164', source: 'S161', target: 'S164', ...depEdgeStyle },
  { id: 'e-162-165', source: 'S162', target: 'S165', ...depEdgeStyle },
  // UI -> graph + norm
  { id: 'e-162-167', source: 'S162', target: 'S167', ...depEdgeStyle },
  { id: 'e-165-167', source: 'S165', target: 'S167', label: 'activeTag store', labelStyle: { fontSize: 10 }, ...depEdgeStyle },
  { id: 'e-162-168', source: 'S162', target: 'S168', ...depEdgeStyle },
  { id: 'e-165-168', source: 'S165', target: 'S168', label: 'merge endpoint', labelStyle: { fontSize: 10 }, ...depEdgeStyle },
  // foundation -> clustering + flashcards
  { id: 'e-161-166', source: 'S161', target: 'S166', ...depEdgeStyle },
  { id: 'e-170-166', source: 'S170', target: 'S166', label: '1024-dim vectors', labelStyle: { fontSize: 10 }, ...depEdgeStyle },
  { id: 'e-161-169', source: 'S161', target: 'S169', ...depEdgeStyle },
  { id: 'e-162-169', source: 'S162', target: 'S169', ...depEdgeStyle },
]

// ── LEGEND helpers ───────────────────────────────────────────────
function RunLegend() {
  return (
    <div style={{
      position: 'absolute', bottom: 16, right: 16, zIndex: 10,
      background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
      padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      {([
        [C.terminal.bg, 'Terminal (start / done)'],
        [C.process.bg,  'Process step'],
        [C.decision.bg, 'Decision'],
        [C.gate.bg,     'Quality gates'],
        [C.fix.bg,      'Fix / retry (dashed)'],
        [C.log.bg,      'Persist & loop'],
      ] as [string, string][]).map(([color, label]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 14, height: 14, borderRadius: 3, background: color }} />
          <span style={{ color: '#cbd5e1', fontSize: 11 }}>{label}</span>
        </div>
      ))}
    </div>
  )
}

function StoryLegend({ total, done }: { total: number; done: number }) {
  return (
    <div style={{
      position: 'absolute', bottom: 16, right: 16, zIndex: 10,
      background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
      padding: '10px 14px', minWidth: 180,
    }}>
      <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>
        Phase 1 progress
      </div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 8 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#86efac' }}>{done}</div>
          <div style={{ fontSize: 10, color: '#6ee7b7' }}>passed</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#fbbf24' }}>{total - done}</div>
          <div style={{ fontSize: 10, color: '#fde68a' }}>pending</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#93c5fd' }}>{total}</div>
          <div style={{ fontSize: 10, color: '#bfdbfe' }}>total</div>
        </div>
      </div>
      {/* progress bar */}
      <div style={{ background: '#0f172a', borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{
          width: `${(done / total) * 100}%`, height: '100%',
          background: '#16a34a', borderRadius: 4, transition: 'width 0.4s',
        }} />
      </div>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {([
          [C.done.bg,    '✓ passed'],
          [C.pending.bg, '⏳ pending'],
        ] as [string, string][]).map(([color, label]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: color, border: '1px solid #334155' }} />
            <span style={{ color: '#cbd5e1', fontSize: 11 }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── STORY DETAIL PANEL ───────────────────────────────────────────
function StoryDetail({ story, onClose }: { story: Story; onClose: () => void }) {
  return (
    <div style={{
      position: 'absolute', top: 60, left: 16, zIndex: 20,
      background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
      padding: 16, width: 420, maxHeight: 'calc(100vh - 80px)',
      overflowY: 'auto', boxShadow: '0 8px 32px #0008',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: '#94a3b8', marginBottom: 2 }}>{story.phase}</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>{story.id} · {story.title}</div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}
        >×</button>
      </div>

      <div style={{
        display: 'inline-block', fontSize: 11, fontWeight: 700, borderRadius: 4,
        padding: '2px 8px', marginBottom: 10,
        background: story.passes ? '#14532d' : '#451a03',
        color: story.passes ? '#86efac' : '#fbbf24',
      }}>
        {story.passes ? '✓ passed' : '⏳ pending'}
      </div>

      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 12, lineHeight: 1.6 }}>
        {story.description.slice(0, 400)}{story.description.length > 400 ? '…' : ''}
      </div>

      <div style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>
        Acceptance Criteria ({story.acceptanceCriteria.length})
      </div>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {story.acceptanceCriteria.map((ac, i) => (
          <li key={i} style={{ fontSize: 11, color: '#94a3b8', marginBottom: 5, lineHeight: 1.5 }}>
            {ac}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── APP ──────────────────────────────────────────────────────────
type Tab = 'run' | 'stories'

export default function App() {
  const [tab, setTab] = useState<Tab>('stories')
  const [selectedStory, setSelectedStory] = useState<Story | null>(null)

  const storyNodes = stories.map(storyNode)
  const doneCnt = stories.filter(s => s.passes).length

  const tabStyle = (t: Tab): React.CSSProperties => ({
    padding: '6px 18px', borderRadius: 6, border: 'none', cursor: 'pointer',
    fontSize: 13, fontWeight: 600,
    background: tab === t ? '#3b82f6' : '#1e293b',
    color: tab === t ? '#fff' : '#94a3b8',
    transition: 'background 0.2s',
  })

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#0f172a' }}>
      {/* header */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10,
        background: '#0f172a', borderBottom: '1px solid #1e293b',
        padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <span style={{ color: '#e2e8f0', fontSize: 15, fontWeight: 700 }}>
          Luminary v3 · {prd.branchName}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button style={tabStyle('stories')} onClick={() => setTab('stories')}>
            Story Map ({stories.length})
          </button>
          <button style={tabStyle('run')} onClick={() => setTab('run')}>
            Run Flow
          </button>
        </div>
        {tab === 'stories' && (
          <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>
            Click a story to inspect ACs
          </span>
        )}
      </div>

      {/* canvas */}
      <div style={{ position: 'absolute', top: 48, bottom: 0, left: 0, right: 0 }}>
        {tab === 'run' ? (
          <ReactFlow
            nodes={runNodes}
            edges={runEdges}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{ type: 'smoothstep' }}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1e293b" gap={20} />
            <Controls style={{ background: '#1e293b', border: '1px solid #334155' }} />
            <MiniMap
              style={{ background: '#1e293b', border: '1px solid #334155' }}
              nodeColor={(n) => (n.style as { background?: string })?.background ?? '#3b82f6'}
            />
            <RunLegend />
          </ReactFlow>
        ) : (
          <ReactFlow
            nodes={storyNodes}
            edges={storyEdges}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{ type: 'smoothstep' }}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_evt, node) => {
              const s = stories.find(s => s.id === node.id)
              setSelectedStory(s ?? null)
            }}
          >
            <Background color="#1e293b" gap={20} />
            <Controls style={{ background: '#1e293b', border: '1px solid #334155' }} />
            <MiniMap
              style={{ background: '#1e293b', border: '1px solid #334155' }}
              nodeColor={(n) => (n.style as { background?: string })?.background ?? '#1e3a5f'}
            />
            <StoryLegend total={stories.length} done={doneCnt} />
          </ReactFlow>
        )}
      </div>

      {/* story detail panel */}
      {tab === 'stories' && selectedStory && (
        <StoryDetail story={selectedStory} onClose={() => setSelectedStory(null)} />
      )}
    </div>
  )
}
