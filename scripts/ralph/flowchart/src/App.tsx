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
  phase: number
  priority: number
  description: string
  acceptanceCriteria: string[]
  passes: boolean
}

type StoryStatus = 'done' | 'active' | 'pending'

// ── Constants ──────────────────────────────────────────────────────────────

const PHASE_NAMES: Record<number, string> = {
  1: 'Phase 1 — Core Infrastructure',
  2: 'Phase 2 — Knowledge & Search',
  3: 'Phase 3 — Learning Engine',
  4: 'Phase 4 — Monitoring',
  5: 'Phase 5 — Code & Polish',
  6: 'Phase 6 — Bugfixes & Hardening',
}

const PHASE_COLORS: Record<number, { bg: string; border: string; label: string }> = {
  1: { bg: '#eff6ff', border: '#bfdbfe', label: '#1d4ed8' },
  2: { bg: '#faf5ff', border: '#e9d5ff', label: '#6d28d9' },
  3: { bg: '#fff7ed', border: '#fed7aa', label: '#c2410c' },
  4: { bg: '#f0fdf4', border: '#bbf7d0', label: '#15803d' },
  5: { bg: '#fafafa', border: '#e5e5e5', label: '#404040' },
  6: { bg: '#fdf2f8', border: '#f0abfc', label: '#a21caf' },
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

  const phases = [...new Set(sorted.map(s => s.phase))].sort((a, b) => a - b)
  for (const phase of phases) {
    const ps = sorted.filter(s => s.phase === phase)
    if (!ps.length) continue

    const rows = Math.ceil(ps.length / STORIES_PER_ROW)
    const cols = Math.min(ps.length, STORIES_PER_ROW)
    const bgW = cols * (NODE_W + H_GAP) - H_GAP + PADDING * 2
    const bgH = LABEL_H + rows * (NODE_H + V_GAP) - V_GAP + PADDING * 2
    const pc = PHASE_COLORS[phase]

    nodes.push({
      id: `bg-${phase}`,
      type: 'phaseBg',
      position: { x: 0, y },
      data: { label: PHASE_NAMES[phase], bg: pc.bg, border: pc.border, labelColor: pc.label, w: bgW, h: bgH },
      selectable: false,
      draggable: false,
      zIndex: 0,
    })

    ps.forEach((story, i) => {
      const col = i % STORIES_PER_ROW
      const row = Math.floor(i / STORIES_PER_ROW)
      const status: StoryStatus = story.passes ? 'done' : story.id === activeId ? 'active' : 'pending'
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
          <span className="panel-phase">Phase {story.phase} · Priority {story.priority}</span>
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

export default function App() {
  const [stories, setStories] = useState<Story[]>([])
  const [branchName, setBranchName] = useState('')
  const [selected, setSelected] = useState<Story | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const fetchPrd = () => {
    fetch('/prd.json?t=' + Date.now())
      .then(r => r.json())
      .then(data => {
        setStories(data.stories ?? [])
        setBranchName(data.branchName ?? '')
        setUpdatedAt(new Date())
      })
      .catch(console.error)
  }

  useEffect(() => {
    fetchPrd()
    const timer = setInterval(fetchPrd, 15_000)
    return () => clearInterval(timer)
  }, [])

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

  if (!stories.length) {
    return <div className="loading">Loading Luminary PRD…</div>
  }

  return (
    <div className="app">
      <header className="hdr">
        <div className="hdr-left">
          <h1>Luminary</h1>
          <span className="branch">{branchName}</span>
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
              return st === 'done' ? '#4ade80' : st === 'active' ? '#60a5fa' : '#e5e7eb'
            }}
            style={{ border: '1px solid #e5e7eb', borderRadius: 8 }}
          />
        </ReactFlow>
      </div>

      {selected && <DetailPanel story={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
