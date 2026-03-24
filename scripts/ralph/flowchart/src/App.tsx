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

// ── colour palette ──────────────────────────────────────────────
const C = {
  terminal:  { bg: '#16a34a', text: '#fff', border: '#15803d' },
  process:   { bg: '#3b82f6', text: '#fff', border: '#2563eb' },
  decision:  { bg: '#7c3aed', text: '#fff', border: '#6d28d9' },
  gate:      { bg: '#0f172a', text: '#e2e8f0', border: '#334155' },
  fix:       { bg: '#dc2626', text: '#fff', border: '#b91c1c' },
  log:       { bg: '#0891b2', text: '#fff', border: '#0e7490' },
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

// ── nodes ────────────────────────────────────────────────────────
const nodes: Node[] = [
  // ── column A: main flow (x=380)
  {
    id: 'start',
    data: { label: 'Start\nralph invoked with PRD path' },
    position: { x: 380, y: 0 },
    sourcePosition: Position.Bottom,
    style: nodeStyle(C.terminal, { borderRadius: 40, minWidth: 200 }),
  },
  {
    id: 'read-prd',
    data: { label: 'Read PRD\nprd-vN.json' },
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

  // ── column B: done exit (x=700)
  {
    id: 'done',
    data: { label: 'Done\nAll stories pass' },
    position: { x: 700, y: 210 },
    style: nodeStyle(C.terminal, { borderRadius: 40 }),
  },

  // ── column C: fix lanes (x=50)
  {
    id: 'fix-gates',
    data: { label: 'Fix failures\nread error output\nadjust code' },
    position: { x: 50, y: 870 },
    style: nodeStyle(C.fix),
  },
  {
    id: 'fix-smoke',
    data: { label: 'Debug smoke\ncurl endpoints\ncheck logs' },
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

// ── edges ────────────────────────────────────────────────────────
const arrow = {
  markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
  style: { stroke: '#64748b', strokeWidth: 2 },
}
const redArrow = {
  markerEnd: { type: MarkerType.ArrowClosed, color: '#dc2626' },
  style: { stroke: '#dc2626', strokeWidth: 1.5, strokeDasharray: '5,3' },
  animated: true,
}

const edges: Edge[] = [
  { id: 'e-start-prd',      source: 'start',        target: 'read-prd',      ...arrow },
  { id: 'e-prd-find',       source: 'read-prd',      target: 'find-story',    ...arrow },

  // decision: find-story
  { id: 'e-find-plan',      source: 'find-story',    target: 'read-plan',
    label: 'story found', labelStyle: { fontSize: 11 }, ...arrow },
  { id: 'e-find-done',      source: 'find-story',    target: 'done',
    label: 'no stories left', labelStyle: { fontSize: 11, fill: '#16a34a' },
    sourceHandle: null, ...arrow, style: { stroke: '#16a34a', strokeWidth: 2 } },

  { id: 'e-plan-explore',   source: 'read-plan',     target: 'explore',       ...arrow },
  { id: 'e-explore-be',     source: 'explore',       target: 'impl-backend',  ...arrow },
  { id: 'e-be-fe',          source: 'impl-backend',  target: 'impl-frontend', ...arrow },
  { id: 'e-fe-gates',       source: 'impl-frontend', target: 'gates',         ...arrow },
  { id: 'e-gates-pass',     source: 'gates',         target: 'gates-pass',    ...arrow },

  // decision: gates-pass
  { id: 'e-pass-smoke',     source: 'gates-pass',    target: 'smoke',
    label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-pass-fix',       source: 'gates-pass',    target: 'fix-gates',
    label: 'no', labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-gates-back', source: 'fix-gates',     target: 'gates',         ...redArrow },

  { id: 'e-smoke-pass',     source: 'smoke',         target: 'smoke-pass',    ...arrow },

  // decision: smoke-pass
  { id: 'e-sp-reviewer',    source: 'smoke-pass',    target: 'reviewer',
    label: 'yes', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-sp-fix',         source: 'smoke-pass',    target: 'fix-smoke',
    label: 'no', labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-smoke-back', source: 'fix-smoke',     target: 'impl-backend',  ...redArrow },

  { id: 'e-rev-crit',       source: 'reviewer',      target: 'critical',      ...arrow },

  // decision: critical
  { id: 'e-crit-mark',      source: 'critical',      target: 'mark-done',
    label: 'no', labelStyle: { fontSize: 11, fill: '#16a34a' }, ...arrow },
  { id: 'e-crit-fix',       source: 'critical',      target: 'fix-critical',
    label: 'yes', labelStyle: { fontSize: 11, fill: '#dc2626' }, ...arrow },
  { id: 'e-fix-crit-back',  source: 'fix-critical',  target: 'gates',         ...redArrow },

  // loop back
  {
    id: 'e-mark-loop',
    source: 'mark-done',
    target: 'find-story',
    label: 'next story',
    labelStyle: { fontSize: 11, fill: '#0891b2' },
    type: 'smoothstep',
    ...arrow,
    style: { stroke: '#0891b2', strokeWidth: 2 },
  },
]

export default function App() {
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#0f172a' }}>
      <div style={{
        position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
        zIndex: 10, color: '#e2e8f0', fontSize: 18, fontWeight: 700, letterSpacing: 0.5,
        textShadow: '0 1px 4px #0008',
      }}>
        Ralph Run Flow — Luminary v3
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
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
      </ReactFlow>

      {/* legend */}
      <div style={{
        position: 'absolute', bottom: 16, right: 16, zIndex: 10,
        background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
        padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        {[
          [C.terminal.bg, 'Terminal (start / done)'],
          [C.process.bg,  'Process step'],
          [C.decision.bg, 'Decision'],
          [C.gate.bg,     'Quality gates'],
          [C.fix.bg,      'Fix / retry (dashed)'],
          [C.log.bg,      'Persist & loop'],
        ].map(([color, label]) => (
          <div key={label as string} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: color as string }} />
            <span style={{ color: '#cbd5e1', fontSize: 11 }}>{label as string}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
