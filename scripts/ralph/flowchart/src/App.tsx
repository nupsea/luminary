import { useState, useEffect, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
} from '@xyflow/react'
import type { Node, NodeMouseHandler } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './App.css'

// ── Types ──────────────────────────────────────────────────────────────────

interface Story {
  id: string
  title: string
  phase: number | string
  priority: number
  description: string
  acceptanceCriteria: string[]
  passes: boolean
  type?: string
}

type StoryStatus = 'done' | 'active' | 'gate' | 'pending'
type PrdVersion = 'v1' | 'v2'

// ── Constants ──────────────────────────────────────────────────────────────

// v1 numeric phases
const V1_PHASE_NAMES: Record<number, string> = {
  1: 'Phase 1 — Core Infrastructure',
  2: 'Phase 2 — Knowledge & Search',
  3: 'Phase 3 — Learning Engine',
  4: 'Phase 4 — Monitoring',
  5: 'Phase 5 — Code & Polish',
  6: 'Phase 6 — Bugfixes & Hardening',
  7: 'Phase 7 — Book Learning Vertical',
  8: 'Phase 8 — Books, Conversations & Polish',
}

// v2 string phases map to display name (identity — they're already good strings)
// Colors keyed by phase identifier (number for v1, string for v2)
type PhaseColor = { bg: string; border: string; label: string }

const V1_PHASE_COLORS: Record<number, PhaseColor> = {
  1: { bg: '#eff6ff', border: '#bfdbfe', label: '#1d4ed8' },
  2: { bg: '#faf5ff', border: '#e9d5ff', label: '#6d28d9' },
  3: { bg: '#fff7ed', border: '#fed7aa', label: '#c2410c' },
  4: { bg: '#f0fdf4', border: '#bbf7d0', label: '#15803d' },
  5: { bg: '#fafafa', border: '#e5e5e5', label: '#404040' },
  6: { bg: '#fdf2f8', border: '#f0abfc', label: '#a21caf' },
  7: { bg: '#fff8f1', border: '#fdba74', label: '#c2410c' },
  8: { bg: '#f0f9ff', border: '#7dd3fc', label: '#0369a1' },
}

const V2_PHASE_COLORS: Record<string, PhaseColor> = {
  'V2A — Hierarchical Knowledge': { bg: '#eff6ff', border: '#bfdbfe', label: '#1d4ed8' },
  'V2B — Agentic Chat':           { bg: '#faf5ff', border: '#e9d5ff', label: '#6d28d9' },
  'V2C — Quality Gates':          { bg: '#f0fdf4', border: '#bbf7d0', label: '#15803d' },
}

const DEFAULT_PHASE_COLOR: PhaseColor = { bg: '#f8fafc', border: '#cbd5e1', label: '#475569' }

function getPhaseColor(phase: number | string): PhaseColor {
  if (typeof phase === 'number') return V1_PHASE_COLORS[phase] ?? DEFAULT_PHASE_COLOR
  return V2_PHASE_COLORS[phase] ?? DEFAULT_PHASE_COLOR
}

function getPhaseName(phase: number | string): string {
  if (typeof phase === 'number') return V1_PHASE_NAMES[phase] ?? `Phase ${phase}`
  return phase  // v2 phases are already descriptive strings
}

const STATUS_STYLES: Record<StoryStatus, {
  bg: string; border: string; idColor: string
  titleColor: string; badge: string; badgeBg: string; badgeColor: string
}> = {
  done: {
    bg: '#f0fdf4', border: '#4ade80', idColor: '#15803d',
    titleColor: '#14532d', badge: '✓ Done', badgeBg: '#dcfce7', badgeColor: '#15803d',
  },
  active: {
    bg: '#eff6ff', border: '#60a5fa', idColor: '#1d4ed8',
    titleColor: '#1e3a8a', badge: '▶ Active', badgeBg: '#dbeafe', badgeColor: '#1d4ed8',
  },
  gate: {
    bg: '#fefce8', border: '#fbbf24', idColor: '#92400e',
    titleColor: '#78350f', badge: '⛔ Gate', badgeBg: '#fef3c7', badgeColor: '#92400e',
  },
  pending: {
    bg: '#f9fafb', border: '#e5e7eb', idColor: '#9ca3af',
    titleColor: '#6b7280', badge: 'Pending', badgeBg: '#f3f4f6', badgeColor: '#9ca3af',
  },
}

const NODE_W = 192
const NODE_H = 74
const H_GAP = 14
const V_GAP = 10
const STORIES_PER_ROW = 6
const PADDING = 22
const LABEL_H = 42
const PHASE_V_GAP = 44

// ── Node Components ────────────────────────────────────────────────────────

function StoryNode({ data }: { data: { story: Story; status: StoryStatus } }) {
  const s = STATUS_STYLES[data.status]
  const title = data.story.title.length > 46
    ? data.story.title.slice(0, 46) + '…'
    : data.story.title

  return (
    <div className="story-node" style={{ background: s.bg, borderColor: s.border }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0, pointerEvents: 'none' }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0, pointerEvents: 'none' }} />
      <div className="sn-top">
        <span className="sn-id" style={{ color: s.idColor }}>{data.story.id}</span>
        <span className="sn-badge" style={{ background: s.badgeBg, color: s.badgeColor }}>
          {s.badge}
        </span>
      </div>
      <div className="sn-title" style={{ color: s.titleColor }}>{title}</div>
    </div>
  )
}

function PhaseBg({ data }: {
  data: { label: string; bg: string; border: string; labelColor: string; w: number; h: number }
}) {
  return (
    <div style={{
      width: data.w,
      height: data.h,
      background: data.bg,
      border: `2px solid ${data.border}`,
      borderRadius: 12,
    }}>
      <div className="phase-label" style={{ color: data.labelColor }}>
        {data.label}
      </div>
    </div>
  )
}

const nodeTypes = { story: StoryNode, phaseBg: PhaseBg }

// ── Layout Builder ─────────────────────────────────────────────────────────

function buildNodes(stories: Story[]): Node[] {
  const sorted = [...stories].sort((a, b) => a.priority - b.priority)
  const activeId = sorted.find(s => !s.passes)?.id
  const nodes: Node[] = []
  let y = 0

  // Group by phase preserving insertion order (priority-sorted stories determine order)
  const phaseOrder: (number | string)[] = []
  const phaseMap = new Map<number | string, Story[]>()
  for (const s of sorted) {
    if (!phaseMap.has(s.phase)) {
      phaseOrder.push(s.phase)
      phaseMap.set(s.phase, [])
    }
    phaseMap.get(s.phase)!.push(s)
  }

  for (const phase of phaseOrder) {
    const ps = phaseMap.get(phase)!
    if (!ps.length) continue

    const rows = Math.ceil(ps.length / STORIES_PER_ROW)
    const cols = Math.min(ps.length, STORIES_PER_ROW)
    const bgW = cols * (NODE_W + H_GAP) - H_GAP + PADDING * 2
    const bgH = LABEL_H + rows * (NODE_H + V_GAP) - V_GAP + PADDING * 2
    const pc = getPhaseColor(phase)
    const phaseName = getPhaseName(phase)

    nodes.push({
      id: `bg-${phase}`,
      type: 'phaseBg',
      position: { x: 0, y },
      data: { label: phaseName, bg: pc.bg, border: pc.border, labelColor: pc.label, w: bgW, h: bgH },
      selectable: false,
      draggable: false,
      zIndex: 0,
    })

    ps.forEach((story, i) => {
      const col = i % STORIES_PER_ROW
      const row = Math.floor(i / STORIES_PER_ROW)
      const isGate = story.type === 'demo-review'
      const status: StoryStatus = story.passes
        ? 'done'
        : isGate
          ? 'gate'
          : story.id === activeId
            ? 'active'
            : 'pending'
      nodes.push({
        id: story.id,
        type: 'story',
        position: {
          x: PADDING + col * (NODE_W + H_GAP),
          y: y + LABEL_H + PADDING + row * (NODE_H + V_GAP),
        },
        data: { story, status },
        draggable: false,
        zIndex: 1,
      })
    })

    y += bgH + PHASE_V_GAP
  }

  return nodes
}

// ── Detail Panel ───────────────────────────────────────────────────────────

function DetailPanel({ story, onClose }: { story: Story; onClose: () => void }) {
  const status: StoryStatus = story.passes ? 'done' : 'pending'
  const s = STATUS_STYLES[status]

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={e => e.stopPropagation()}>
        <div className="panel-header">
          <span className="panel-id" style={{ color: s.idColor }}>{story.id}</span>
          <span className="panel-badge" style={{ background: s.badgeBg, color: s.badgeColor }}>
            {s.badge}
          </span>
          <span className="panel-phase">{story.phase} · Priority {story.priority}</span>
          <button className="panel-close" onClick={onClose}>×</button>
        </div>
        <h2 className="panel-title">{story.title}</h2>
        <div className="panel-section">
          <h3>Acceptance Criteria</h3>
          <ul>
            {story.acceptanceCriteria.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
        <div className="panel-section">
          <h3>Description</h3>
          <p>{story.description.slice(0, 600)}{story.description.length > 600 ? '…' : ''}</p>
        </div>
      </div>
    </div>
  )
}

// ── App ────────────────────────────────────────────────────────────────────

interface PrdData {
  stories: Story[]
  branchName: string
}

export default function App() {
  const [v1Data, setV1Data] = useState<PrdData | null>(null)
  const [v2Data, setV2Data] = useState<PrdData | null>(null)
  const [activePrd, setActivePrd] = useState<PrdVersion>('v2')
  const [selected, setSelected] = useState<Story | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const fetchAll = () => {
    const load = (url: string) =>
      fetch(url + '?t=' + Date.now())
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)

    Promise.allSettled([load('/prd.json'), load('/prd-v2.json')]).then(([r1, r2]) => {
      const d1: PrdData | null = r1.status === 'fulfilled' ? r1.value : null
      const d2: PrdData | null = r2.status === 'fulfilled' ? r2.value : null
      setV1Data(d1)
      setV2Data(d2)
      // Auto-select: prefer the PRD with pending stories; default to v2 if exists
      if (d2?.stories?.some(s => !s.passes)) setActivePrd('v2')
      else if (d1?.stories?.some(s => !s.passes)) setActivePrd('v1')
      else if (d2) setActivePrd('v2')
      setUpdatedAt(new Date())
    })
  }

  useEffect(() => {
    fetchAll()
    const timer = setInterval(fetchAll, 15_000)
    return () => clearInterval(timer)
  }, [])

  const current = activePrd === 'v2' ? v2Data : v1Data
  const stories = current?.stories ?? []
  const branchName = current?.branchName ?? ''

  const nodes = useMemo(() => buildNodes(stories), [stories])

  const done = stories.filter(s => s.passes).length
  const total = stories.length
  const pct = total ? Math.round((done / total) * 100) : 0
  const activeStory = [...stories].sort((a, b) => a.priority - b.priority).find(s => !s.passes)

  const onNodeClick: NodeMouseHandler = (_, node) => {
    if (node.type === 'story') {
      setSelected((node.data as { story: Story }).story)
    }
  }

  if (!v1Data && !v2Data) {
    return <div className="loading">Loading Luminary PRD…</div>
  }

  return (
    <div className="app">
      <header className="hdr">
        <div className="hdr-left">
          <h1>Luminary</h1>
          <span className="branch">{branchName}</span>
          {/* PRD version toggle */}
          <div className="prd-toggle">
            {v1Data && (
              <button
                className={`prd-btn ${activePrd === 'v1' ? 'prd-btn-active' : ''}`}
                onClick={() => setActivePrd('v1')}
              >
                v1
              </button>
            )}
            {v2Data && (
              <button
                className={`prd-btn ${activePrd === 'v2' ? 'prd-btn-active' : ''}`}
                onClick={() => setActivePrd('v2')}
              >
                v2
              </button>
            )}
          </div>
        </div>
        <div className="hdr-center">
          <div className="prog-label">{done} / {total} stories complete &nbsp;·&nbsp; {pct}%</div>
          <div className="prog-track">
            <div className="prog-fill" style={{ width: `${pct}%` }} />
          </div>
          {activeStory && (
            <div className="active-label">
              Active: <strong>{activeStory.id}</strong> — {
                activeStory.title.length > 52
                  ? activeStory.title.slice(0, 52) + '…'
                  : activeStory.title
              }
            </div>
          )}
        </div>
        <div className="hdr-right">
          <div className="legend">
            <span className="leg leg-done">✓ Done</span>
            <span className="leg leg-active">▶ Active</span>
            <span className="leg leg-gate">⛔ Gate</span>
            <span className="leg leg-pending">Pending</span>
          </div>
          {updatedAt && (
            <div className="updated">Auto-refreshes every 15s · {updatedAt.toLocaleTimeString()}</div>
          )}
        </div>
      </header>

      <div className="flow">
        <ReactFlow
          nodes={nodes}
          edges={[]}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.04 }}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag
          panOnScroll
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick
          minZoom={0.08}
          maxZoom={2}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#d1d5db" />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={node => {
              if (node.type !== 'story') return 'transparent'
              const st = (node.data as { status: StoryStatus }).status
              return st === 'done' ? '#4ade80' : st === 'active' ? '#60a5fa' : st === 'gate' ? '#fbbf24' : '#e5e7eb'
            }}
            style={{ border: '1px solid #e5e7eb', borderRadius: 8 }}
          />
        </ReactFlow>
      </div>

      {selected && <DetailPanel story={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
