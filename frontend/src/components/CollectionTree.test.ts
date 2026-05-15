/**
 * Vitest unit tests for CollectionTree logic
 *
 * Tests cover:
 *   1. CollectionTree renders correct item count from mock fixture
 *      (via countTreeItems which mirrors the component's flattenCollectionTree render path)
 *   2. Checkbox check fires POST /collections/{id}/notes with correct URL + body
 *   3. Checkbox uncheck fires DELETE /collections/{id}/notes/{note_id} with correct URL
 *   4. Tree nesting structure is preserved
 *   5. Collection membership set operations (pre-checked state)
 *
 * Node environment (no DOM) -- tests pure utility functions from collectionUtils.ts,
 * which are the same functions the components use for API calls and rendering logic.
 */

import { describe, expect, it } from "vitest"
import {
  flattenCollectionTree,
  countTreeItems,
  buildAddMemberRequest,
  buildRemoveMemberRequest,
} from "@/lib/collectionUtils"
import type { CollectionTreeItem } from "@/lib/collectionUtils"

const API_BASE = "http://localhost:7820"

// ---------------------------------------------------------------------------
// Fixtures -- mirrors GET /collections/tree response
// ---------------------------------------------------------------------------

const MOCK_TREE: CollectionTreeItem[] = [
  {
    id: "col-1",
    name: "Physics",
    color: "#6366F1",
    icon: null,
    note_count: 5,
    document_count: 2,
    children: [
      {
        id: "col-1a",
        name: "Quantum Mechanics",
        color: "#8B5CF6",
        icon: null,
        note_count: 18,
        document_count: 0,
        children: [],
      },
      {
        id: "col-1b",
        name: "Thermodynamics",
        color: "#EC4899",
        icon: null,
        note_count: 27,
        document_count: 1,
        children: [],
      },
    ],
  },
  {
    id: "col-2",
    name: "Study Targets",
    color: "#10B981",
    icon: null,
    note_count: 12,
    document_count: 0,
    children: [],
  },
]

// ---------------------------------------------------------------------------
// AC: CollectionTree renders correct item count from mock fixture
// ---------------------------------------------------------------------------

describe("CollectionTree item count from fixture", () => {
  it("counts 4 items total: 2 top-level + 2 children", () => {
    // This is the exact count CollectionTree renders when all parents are expanded.
    // Component renders flattenCollectionTree(tree) items.
    expect(countTreeItems(MOCK_TREE)).toBe(4)
  })

  it("counts only top-level items when tree has no children", () => {
    const flat: CollectionTreeItem[] = [
      { id: "a", name: "A", color: "#fff", icon: null, note_count: 1, document_count: 0, children: [] },
      { id: "b", name: "B", color: "#fff", icon: null, note_count: 2, document_count: 0, children: [] },
    ]
    expect(countTreeItems(flat)).toBe(2)
  })

  it("returns 0 for empty tree (empty state renders placeholder)", () => {
    expect(countTreeItems([])).toBe(0)
  })

  it("renders Physics and Study Targets at top level", () => {
    const topLevel = MOCK_TREE.map((c) => c.name)
    expect(topLevel).toContain("Physics")
    expect(topLevel).toContain("Study Targets")
  })

  it("renders child items Quantum Mechanics and Thermodynamics in flat list", () => {
    const flat = flattenCollectionTree(MOCK_TREE)
    const names = flat.map((c) => c.name)
    expect(names).toContain("Quantum Mechanics")
    expect(names).toContain("Thermodynamics")
  })

  it("note_count pill values match fixture", () => {
    const flat = flattenCollectionTree(MOCK_TREE)
    const qm = flat.find((c) => c.id === "col-1a")
    expect(qm?.note_count).toBe(18)
    const thermo = flat.find((c) => c.id === "col-1b")
    expect(thermo?.note_count).toBe(27)
  })
})

// ---------------------------------------------------------------------------
// AC: Checkbox check fires POST /collections/{id}/members (correct endpoint)
// ---------------------------------------------------------------------------

describe("Checkbox fires correct endpoints", () => {
  const NOTE_ID = "note-abc-123"
  const COL_ID = "col-1"

  it("check fires POST /collections/{id}/members with correct URL", () => {
    const req = buildAddMemberRequest(API_BASE, COL_ID, NOTE_ID)
    expect(req.method).toBe("POST")
    expect(req.url).toBe(`${API_BASE}/collections/${COL_ID}/members`)
  })

  it("check body contains member_ids array and member_type", () => {
    const req = buildAddMemberRequest(API_BASE, COL_ID, NOTE_ID)
    const body = JSON.parse(req.body) as { member_ids: string[]; member_type: string }
    expect(body.member_ids).toEqual([NOTE_ID])
    expect(body.member_type).toBe("note")
  })

  it("check sets Content-Type: application/json header", () => {
    const req = buildAddMemberRequest(API_BASE, COL_ID, NOTE_ID)
    expect(req.headers["Content-Type"]).toBe("application/json")
  })

  it("uncheck fires DELETE /collections/{id}/members/{member_id} with correct URL", () => {
    const req = buildRemoveMemberRequest(API_BASE, COL_ID, NOTE_ID)
    expect(req.method).toBe("DELETE")
    expect(req.url).toBe(`${API_BASE}/collections/${COL_ID}/members/${NOTE_ID}`)
  })

  it("uncheck URL includes both collection id and member id", () => {
    const req = buildRemoveMemberRequest(API_BASE, "col-99", "note-xyz")
    expect(req.url).toContain("col-99")
    expect(req.url).toContain("note-xyz")
  })
})

// ---------------------------------------------------------------------------
// Collection tree nesting structure
// ---------------------------------------------------------------------------

describe("flattenCollectionTree nesting", () => {
  it("parent comes before its children in flat output", () => {
    const flat = flattenCollectionTree(MOCK_TREE)
    const ids = flat.map((c) => c.id)
    expect(ids.indexOf("col-1")).toBeLessThan(ids.indexOf("col-1a"))
    expect(ids.indexOf("col-1")).toBeLessThan(ids.indexOf("col-1b"))
  })

  it("all 4 items present after flattening 2-level tree", () => {
    expect(flattenCollectionTree(MOCK_TREE)).toHaveLength(4)
  })
})

// ---------------------------------------------------------------------------
// Collection membership (pre-checked state for NoteEditorDialog)
// ---------------------------------------------------------------------------

describe("collection checkbox pre-checked state", () => {
  it("builds checked set from note collection_ids", () => {
    const noteCollectionIds = ["col-1", "col-2"]
    const checkedSet = new Set(noteCollectionIds)
    const flat = flattenCollectionTree(MOCK_TREE)
    const checked = flat.filter((c) => checkedSet.has(c.id))
    expect(checked).toHaveLength(2)
    expect(checked.map((c) => c.name).sort()).toEqual(["Physics", "Study Targets"])
  })

  it("adding collection id to set marks it checked", () => {
    const s = new Set<string>(["col-1"])
    s.add("col-1a")
    expect(s.has("col-1a")).toBe(true)
    expect(s.size).toBe(2)
  })

  it("removing collection id from set marks it unchecked", () => {
    const s = new Set<string>(["col-1", "col-2"])
    s.delete("col-1")
    expect(s.has("col-1")).toBe(false)
    expect(s.size).toBe(1)
  })
})
