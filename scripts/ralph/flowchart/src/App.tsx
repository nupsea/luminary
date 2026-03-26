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

// ── RUN FLOW ────────────────────────────────────────────────────
const runNodes: Node[] = [
  { id: 'start',        data: { label: 'Start\nralph invoked with PRD path' }, position: { x: 380, y: 0 },    sourcePosition: Position.Bottom, style: nodeStyle(C.terminal, { borderRadius: 40, minWidth: 200 }) },
  { id: 'read-prd',     data: { label: 'Read PRD\nprd-v3.json' },              position: { x: 380, y: 100 },  style: nodeStyle(C.process) },
  { id: 'find-story',   data: { label: 'Find first story\nwhere passes=false\nordered by priority' }, position: { x: 380, y: 210 }, style: nodeStyle(C.decision, { borderRadius: 4 }) },
  { id: 'read-plan',    data: { label: 'Read or create exec plan\ndocs/exec-plans/active/SXXX.md' }, position: { x: 380, y: 350 }, style: nodeStyle(C.process) },
  { id: 'explore',      data: { label: 'Explore codebase\nGlob + Grep + Read' }, position: { x: 380, y: 460 }, style: nodeStyle(C.process) },
  { id: 'impl-backend', data: { label: 'Implement backend\nmodels · service · router · tests' }, position: { x: 380, y: 560 }, style: nodeStyle(C.process) },
  { id: 'impl-frontend',data: { label: 'Implement frontend\ncomponents · hooks · Zustand' }, position: { x: 380, y: 660 }, style: nodeStyle(C.process) },
  { id: 'gates',        data: { label: 'Quality gates\nruff · pytest · tsc' }, position: { x: 380, y: 760 }, style: nodeStyle(C.gate, { borderRadius: 8, minWidth: 260 }) },
  { id: 'gates-pass',   data: { label: 'All gates pass?' }, position: { x: 380, y: 870 }, style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }) },
  { id: 'smoke',        data: { label: 'Run smoke test\nscripts/smoke/SXXX.sh' }, position: { x: 380, y: 980 }, style: nodeStyle(C.process) },
  { id: 'smoke-pass',   data: { label: 'Smoke exits 0?' }, position: { x: 380, y: 1080 }, style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }) },
  { id: 'reviewer',     data: { label: 'Run luminary-reviewer agent' }, position: { x: 380, y: 1180 }, style: nodeStyle(C.process) },
  { id: 'critical',     data: { label: 'Critical items?' }, position: { x: 380, y: 1280 }, style: nodeStyle(C.decision, { borderRadius: 4, minWidth: 160 }) },
  { id: 'mark-done',    data: { label: 'Set passes=true\nUpdate flowchart status\nCommit + move exec plan' }, position: { x: 380, y: 1390 }, style: nodeStyle(C.log, { minWidth: 260 }) },
  { id: 'done',         data: { label: 'Done\nAll stories pass' }, position: { x: 700, y: 210 }, style: nodeStyle(C.terminal, { borderRadius: 40 }) },
  { id: 'fix-gates',    data: { label: 'Fix failures\nread errors · adjust code' }, position: { x: 50, y: 870 },  style: nodeStyle(C.fix) },
  { id: 'fix-smoke',    data: { label: 'Debug smoke\ncurl endpoints · check logs' }, position: { x: 50, y: 1080 }, style: nodeStyle(C.fix) },
  { id: 'fix-critical', data: { label: 'Fix critical items\nfrom reviewer' }, position: { x: 50, y: 1280 }, style: nodeStyle(C.fix) },
]

const runEdges: Edge[] = [
  { id: 'e-start-prd',      source: 'start',        target: 'read-prd',      ...arrow },
  { id: 'e-prd-find',       source: 'read-prd',     target: 'find-story',    ...arrow },
  { id: 'e-find-plan',      source: 'find-story',   target: 'read-plan',     label: 'story found',    labelStyle: { fontSize: 11 }, ...arrow },
  { id: 'e-find-done',      source: 'find-story',   target: 'done',          label: 'no stories left', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow, style: { stroke: '#16a34a', strokeWidth: 2 } },
  { id: 'e-plan-explore',   source: 'read-plan',    target: 'explore',       ...arrow },
  { id: 'e-explore-be',     source: 'explore',      target: 'impl-backend',  ...arrow },
  { id: 'e-be-fe',          source: 'impl-backend', target: 'impl-frontend', ...arrow },
  { id: 'e-fe-gates',       source: 'impl-frontend',target: 'gates',         ...arrow },
  { id: 'e-gates-pass',     source: 'gates',        target: 'gates-pass',    ...arrow },
  { id: 'e-pass-smoke',     source: 'gates-pass',   target: 'smoke',         label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-pass-fix',       source: 'gates-pass',   target: 'fix-gates',     label: 'no',  labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-gates-back', source: 'fix-gates',    target: 'gates',         ...redArrow },
  { id: 'e-smoke-pass',     source: 'smoke',        target: 'smoke-pass',    ...arrow },
  { id: 'e-sp-reviewer',    source: 'smoke-pass',   target: 'reviewer',      label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-sp-fix',         source: 'smoke-pass',   target: 'fix-smoke',     label: 'no',  labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-smoke-back', source: 'fix-smoke',    target: 'impl-backend',  ...redArrow },
  { id: 'e-rev-crit',       source: 'reviewer',     target: 'critical',      ...arrow },
  { id: 'e-crit-mark',      source: 'critical',     target: 'mark-done',     label: 'no',  labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-crit-fix',       source: 'critical',     target: 'fix-critical',  label: 'yes', labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-crit-back',  source: 'fix-critical', target: 'gates',         ...redArrow },
  { id: 'e-mark-loop',      source: 'mark-done',    target: 'find-story',    label: 'next story', labelStyle: { fontSize: 11, fill: '#0891b2' }, type: 'smoothstep', ...arrow, style: { stroke: '#0891b2', strokeWidth: 2 } },
]

// ── STORY MAP ───────────────────────────────────────────────────
interface Story {
  id: string; title: string; phase: string; priority: number
  featureRef: string; passes: boolean; description: string; acceptanceCriteria: string[]
}

const stories = prd.stories as Story[]

const shortTitle: Record<string, string[]> = {
  S161: ['S161 P1',  'Collections',       'Schema + API'],
  S162: ['S162 P2',  'Hierarchical Tags', 'Shadow Index + API'],
  S163: ['S163 P3',  'Notes to Kuzu',     'GLiNER + chat context'],
  S170: ['S170 P4',  'Perf Refactor',     'Vector dim + indexes'],
  S164: ['S164 P5',  'Collections UI',    'Sidebar + CRUD'],
  S165: ['S165 P6',  'Tag Browser UI',    'Autocomplete + merge'],
  S167: ['S167 P7',  'Tag Viz Graph',     'Sigma.js Tags mode'],
  S168: ['S168 P8',  'Tag Normalizer',    'Embed similarity'],
  S166: ['S166 P9',  'Clustering',        'HDBSCAN + suggest'],
  S169: ['S169 P10', 'Deck Gen',          'Collection flashcards'],
  S171: ['S171 P11', 'Note Links',        'Bidirectional Zettelkasten'],
  S172: ['S172 P12', 'Notes in Viz',      'NOTE nodes in graph'],
  S173: ['S173 P13', 'Collection Health', 'Cohesion + gaps'],
  S174: ['S174 P14', 'Export',            'Obsidian + Anki'],
  S175: ['S175 P15', 'Multi-doc Notes',   'Dual entity edges'],
  S176: ['S176 P16', 'Notes Reader UX',   'Wider panel + tag nav'],
  S177: ['S177 P17', 'Progress Tab',      'Monitoring renamed'],
  S178: ['S178 P18', 'Study Cleanup',     'Smart Generate + merge'],
  S179: ['S179 P19', 'Smart Flashcards',  'Context-aware gen'],
  S180: ['S180 P20', 'Chat Simplify',     'Settings drawer'],
  S181: ['S181 P21', 'Viz Overhaul',      'View Options + Select All'],
  S182: ['S182 P22', 'YouTube Reader',    'Transcript parity'],
  S183: ['S183 P23', 'Learning Tab Slim', 'Stats bar + doc-first'],
}

// Layout: Phase 1 cols x=60..1180, Phase 2 row y=580, Phase 3 row y=820
const storyPositions: Record<string, { x: number; y: number }> = {
  S161: { x: 60,   y: 60  }, S162: { x: 60,   y: 220 }, S163: { x: 60,   y: 380 },
  S170: { x: 340,  y: 140 },
  S164: { x: 620,  y: 60  }, S165: { x: 620,  y: 240 },
  S167: { x: 900,  y: 60  }, S168: { x: 900,  y: 240 },
  S166: { x: 1180, y: 60  }, S169: { x: 1180, y: 240 },
  S171: { x: 60,   y: 580 }, S172: { x: 380,  y: 580 }, S173: { x: 700,  y: 580 },
  S174: { x: 1020, y: 580 }, S175: { x: 1340, y: 580 },
  S176: { x: 60,   y: 820 }, S177: { x: 320,  y: 820 }, S178: { x: 580,  y: 820 },
  S179: { x: 840,  y: 820 }, S180: { x: 1100, y: 820 }, S181: { x: 1360, y: 820 },
  S182: { x: 1620, y: 820 }, S183: { x: 1880, y: 820 },
}

// Phase label nodes (left column, non-clickable)
const phaseLabels: Node[] = [
  { id: 'ph1', selectable: false, data: { label: (<div><div style={{ fontSize: 11, fontWeight: 800 }}>PHASE 1</div><div style={{ fontSize: 10, opacity: 0.7 }}>Note Organization</div><div style={{ fontSize: 10, opacity: 0.7 }}>S161-S170</div></div>) }, position: { x: -190, y: 180 }, style: { background: '#1e1b4b', color: '#a5b4fc', border: '2px solid #3730a3', borderRadius: 8, padding: '8px 12px', minWidth: 130 } },
  { id: 'ph2', selectable: false, data: { label: (<div><div style={{ fontSize: 11, fontWeight: 800 }}>PHASE 2</div><div style={{ fontSize: 10, opacity: 0.7 }}>Note Intelligence</div><div style={{ fontSize: 10, opacity: 0.7 }}>S171-S175</div></div>) }, position: { x: -190, y: 590 }, style: { background: '#1e1b4b', color: '#a5b4fc', border: '2px solid #3730a3', borderRadius: 8, padding: '8px 12px', minWidth: 130 } },
  { id: 'ph3', selectable: false, data: { label: (<div><div style={{ fontSize: 11, fontWeight: 800 }}>PHASE 3</div><div style={{ fontSize: 10, opacity: 0.7 }}>UX Polish</div><div style={{ fontSize: 10, opacity: 0.7 }}>S176-S183</div></div>) }, position: { x: -190, y: 830 }, style: { background: '#1e1b4b', color: '#a5b4fc', border: '2px solid #3730a3', borderRadius: 8, padding: '8px 12px', minWidth: 130 } },
]

function storyNode(s: Story): Node {
  const lines = shortTitle[s.id] ?? [s.id, s.title.slice(0, 28), '']
  const col = s.passes ? C.done : C.pending
  return {
    id: s.id,
    data: {
      label: (
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 2 }}>{lines[0]}</div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{lines[1]}</div>
          <div style={{ fontSize: 10, opacity: 0.8 }}>{lines[2]}</div>
          <div style={{ marginTop: 6, fontSize: 10, fontWeight: 700, color: s.passes ? '#86efac' : '#fbbf24', background: s.passes ? '#14532d' : '#451a03', borderRadius: 4, padding: '1px 6px', display: 'inline-block' }}>
            {s.passes ? '✓ passed' : '⏳ pending'}
          </div>
        </div>
      ),
    },
    position: storyPositions[s.id] ?? { x: 0, y: 0 },
    style: { background: col.bg, color: col.text, border: `2px solid ${col.border}`, borderRadius: 10, padding: '10px 14px', minWidth: 190 },
  }
}

const depEdge = { markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' }, style: { stroke: '#475569', strokeWidth: 1.5 }, type: 'smoothstep' as const }
const ph2Edge = { markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' }, style: { stroke: '#6366f1', strokeWidth: 1.5, strokeDasharray: '6,3' }, type: 'smoothstep' as const }

const storyEdges: Edge[] = [
  // Phase 1 internal
  { id: 'e-162-170', source: 'S162', target: 'S170', label: 'index dep', labelStyle: { fontSize: 10 }, ...depEdge },
  { id: 'e-161-164', source: 'S161', target: 'S164', ...depEdge },
  { id: 'e-162-165', source: 'S162', target: 'S165', ...depEdge },
  { id: 'e-162-167', source: 'S162', target: 'S167', ...depEdge },
  { id: 'e-165-167', source: 'S165', target: 'S167', label: 'activeTag', labelStyle: { fontSize: 10 }, ...depEdge },
  { id: 'e-162-168', source: 'S162', target: 'S168', ...depEdge },
  { id: 'e-165-168', source: 'S165', target: 'S168', label: 'merge ep', labelStyle: { fontSize: 10 }, ...depEdge },
  { id: 'e-161-166', source: 'S161', target: 'S166', ...depEdge },
  { id: 'e-170-166', source: 'S170', target: 'S166', label: '1024-dim', labelStyle: { fontSize: 10 }, ...depEdge },
  { id: 'e-161-169', source: 'S161', target: 'S169', ...depEdge },
  { id: 'e-162-169', source: 'S162', target: 'S169', ...depEdge },
  // Phase 1 -> Phase 2
  { id: 'e-163-172', source: 'S163', target: 'S172', label: 'NOTE nodes', labelStyle: { fontSize: 10 }, ...ph2Edge },
  { id: 'e-161-173', source: 'S161', target: 'S173', ...ph2Edge },
  { id: 'e-161-174', source: 'S161', target: 'S174', ...ph2Edge },
  { id: 'e-163-175', source: 'S163', target: 'S175', label: 'DERIVED_FROM', labelStyle: { fontSize: 10 }, ...ph2Edge },
  // Phase 2 internal
  { id: 'e-171-172', source: 'S171', target: 'S172', ...depEdge },
]

// ── LEGENDS ─────────────────────────────────────────────────────
function RunLegend() {
  return (
    <div style={{ position: 'absolute', bottom: 16, right: 16, zIndex: 10, background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      {([
        [C.terminal.bg, 'Terminal'], [C.process.bg, 'Process'], [C.decision.bg, 'Decision'],
        [C.gate.bg, 'Quality gates'], [C.fix.bg, 'Fix / retry'], [C.log.bg, 'Persist + loop'],
      ] as [string, string][]).map(([color, label]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 14, height: 14, borderRadius: 3, background: color }} />
          <span style={{ color: '#cbd5e1', fontSize: 11 }}>{label}</span>
        </div>
      ))}
    </div>
  )
}

function StoryLegend({ total, done, p1Done, p2Done, p3Done }: { total: number; done: number; p1Done: number; p2Done: number; p3Done: number }) {
  return (
    <div style={{ position: 'absolute', bottom: 16, right: 16, zIndex: 10, background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', minWidth: 200 }}>
      <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 700, marginBottom: 10 }}>Overall progress</div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
        {([['#86efac', '#6ee7b7', done, 'passed'], ['#fbbf24', '#fde68a', total - done, 'pending'], ['#93c5fd', '#bfdbfe', total, 'total']] as [string, string, number, string][]).map(([fg, sub, n, label]) => (
          <div key={label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: fg }}>{n}</div>
            <div style={{ fontSize: 10, color: sub }}>{label}</div>
          </div>
        ))}
      </div>
      <div style={{ background: '#0f172a', borderRadius: 4, height: 8, overflow: 'hidden', marginBottom: 10 }}>
        <div style={{ width: `${(done / total) * 100}%`, height: '100%', background: '#16a34a', borderRadius: 4 }} />
      </div>
      {([['Phase 1', p1Done, 10, '#818cf8'], ['Phase 2', p2Done, 5, '#34d399'], ['Phase 3', p3Done, 8, '#fb923c']] as [string, number, number, string][]).map(([label, cnt, tot, color]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
          <span style={{ color: '#94a3b8', fontSize: 11, flex: 1 }}>{label}</span>
          <span style={{ color: cnt === tot ? '#86efac' : '#fbbf24', fontSize: 11, fontWeight: 700 }}>{cnt}/{tot}</span>
        </div>
      ))}
    </div>
  )
}

// ── STORY DETAIL ─────────────────────────────────────────────────
function StoryDetail({ story, onClose }: { story: Story; onClose: () => void }) {
  return (
    <div style={{ position: 'absolute', top: 60, left: 16, zIndex: 20, background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 16, width: 420, maxHeight: 'calc(100vh - 80px)', overflowY: 'auto', boxShadow: '0 8px 32px #0008' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: '#94a3b8', marginBottom: 2 }}>{story.phase}</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>{story.id} · {story.title}</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 18, padding: 2 }}>x</button>
      </div>
      <div style={{ display: 'inline-block', fontSize: 11, fontWeight: 700, borderRadius: 4, padding: '2px 8px', marginBottom: 10, background: story.passes ? '#14532d' : '#451a03', color: story.passes ? '#86efac' : '#fbbf24' }}>
        {story.passes ? 'passed' : 'pending'}
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 12, lineHeight: 1.6 }}>
        {story.description.slice(0, 400)}{story.description.length > 400 ? '...' : ''}
      </div>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>Acceptance Criteria ({story.acceptanceCriteria.length})</div>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {story.acceptanceCriteria.map((ac, i) => (
          <li key={i} style={{ fontSize: 11, color: '#94a3b8', marginBottom: 5, lineHeight: 1.5 }}>{ac}</li>
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

  const p1 = stories.filter(s => parseInt(s.id.slice(1)) <= 170)
  const p2 = stories.filter(s => { const n = parseInt(s.id.slice(1)); return n >= 171 && n <= 175 })
  const p3 = stories.filter(s => parseInt(s.id.slice(1)) >= 176)
  const doneCnt = stories.filter(s => s.passes).length
  const p1Done = p1.filter(s => s.passes).length
  const p2Done = p2.filter(s => s.passes).length
  const p3Done = p3.filter(s => s.passes).length

  const allStoryNodes = [...stories.map(storyNode), ...phaseLabels]

  const tabBtn = (t: Tab): React.CSSProperties => ({
    padding: '6px 18px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
    background: tab === t ? '#3b82f6' : '#1e293b', color: tab === t ? '#fff' : '#94a3b8',
  })

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#0f172a' }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10, background: '#0f172a', borderBottom: '1px solid #1e293b', padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ color: '#e2e8f0', fontSize: 15, fontWeight: 700 }}>Luminary v3 · {prd.branchName}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button style={tabBtn('stories')} onClick={() => setTab('stories')}>Story Map · {doneCnt}/{stories.length} done</button>
          <button style={tabBtn('run')} onClick={() => setTab('run')}>Run Flow</button>
        </div>
        {tab === 'stories' && <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>Click a story node to inspect ACs</span>}
      </div>

      <div style={{ position: 'absolute', top: 48, bottom: 0, left: 0, right: 0 }}>
        {tab === 'run' ? (
          <ReactFlow nodes={runNodes} edges={runEdges} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2} maxZoom={2} defaultEdgeOptions={{ type: 'smoothstep' }} proOptions={{ hideAttribution: true }}>
            <Background color="#1e293b" gap={20} />
            <Controls style={{ background: '#1e293b', border: '1px solid #334155' }} />
            <MiniMap style={{ background: '#1e293b', border: '1px solid #334155' }} nodeColor={(n) => (n.style as { background?: string })?.background ?? '#3b82f6'} />
            <RunLegend />
          </ReactFlow>
        ) : (
          <ReactFlow nodes={allStoryNodes} edges={storyEdges} fitView fitViewOptions={{ padding: 0.1 }} minZoom={0.08} maxZoom={2} defaultEdgeOptions={{ type: 'smoothstep' }} proOptions={{ hideAttribution: true }}
            onNodeClick={(_evt, node) => {
              const s = stories.find(s => s.id === node.id)
              setSelectedStory(s ?? null)
            }}>
            <Background color="#1e293b" gap={20} />
            <Controls style={{ background: '#1e293b', border: '1px solid #334155' }} />
            <MiniMap style={{ background: '#1e293b', border: '1px solid #334155' }} nodeColor={(n) => (n.style as { background?: string })?.background ?? '#1e3a5f'} />
            <StoryLegend total={stories.length} done={doneCnt} p1Done={p1Done} p2Done={p2Done} p3Done={p3Done} />
          </ReactFlow>
        )}
      </div>

      {tab === 'stories' && selectedStory && (
        <StoryDetail story={selectedStory} onClose={() => setSelectedStory(null)} />
      )}
    </div>
  )
}
