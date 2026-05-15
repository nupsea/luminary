/**
 * Vitest unit tests for TagTree and TagAutocomplete logic
 *
 * Tests cover:
 *   1. TagTree renders correct nesting from mock GET /tags/tree fixture
 *   2. TagAutocomplete fires and renders results (URL construction)
 *   3. Tag breadcrumb parsing (root/child display)
 *   4. Merge request construction
 *   5. Filter merge options (exclude source, match query)
 *
 * Node environment (no DOM) -- tests pure utility functions from tagUtils.ts.
 */

import { describe, expect, it } from "vitest"
import {
  countTagTreeItems,
  flattenTagTree,
  parseTagBreadcrumb,
  buildMergeRequest,
  buildAutocompleteUrl,
  filterMergeOptions,
  filterTagTree,
  highlightMatch,
} from "@/lib/tagUtils"
import type { TagTreeItem, AutocompleteResult } from "@/lib/tagUtils"

const API_BASE = "http://localhost:7820"

// ---------------------------------------------------------------------------
// Fixtures -- mirrors GET /tags/tree response
// ---------------------------------------------------------------------------

const MOCK_TAG_TREE: TagTreeItem[] = [
  {
    id: "programming",
    display_name: "programming",
    parent_tag: null,
    note_count: 34,
    children: [
      {
        id: "programming/python",
        display_name: "python",
        parent_tag: "programming",
        note_count: 18,
        children: [],
      },
      {
        id: "programming/go",
        display_name: "go",
        parent_tag: "programming",
        note_count: 9,
        children: [],
      },
      {
        id: "programming/rust",
        display_name: "rust",
        parent_tag: "programming",
        note_count: 7,
        children: [],
      },
    ],
  },
  {
    id: "science",
    display_name: "science",
    parent_tag: null,
    note_count: 15,
    children: [
      {
        id: "science/physics",
        display_name: "physics",
        parent_tag: "science",
        note_count: 8,
        children: [],
      },
    ],
  },
]

// ---------------------------------------------------------------------------
// AC: TagTree renders correct nesting from fixture
// ---------------------------------------------------------------------------

describe("TagTree nesting from fixture", () => {
  it("counts 6 items total: 2 top-level + 3 children of programming + 1 child of science", () => {
    expect(countTagTreeItems(MOCK_TAG_TREE)).toBe(6)
  })

  it("returns 0 for empty tree (empty state renders placeholder)", () => {
    expect(countTagTreeItems([])).toBe(0)
  })

  it("top-level items are programming and science", () => {
    const topIds = MOCK_TAG_TREE.map((t) => t.id)
    expect(topIds).toContain("programming")
    expect(topIds).toContain("science")
  })

  it("programming has 3 children: python, go, rust", () => {
    const prog = MOCK_TAG_TREE.find((t) => t.id === "programming")
    expect(prog?.children).toHaveLength(3)
    const childIds = prog?.children.map((c) => c.id) ?? []
    expect(childIds).toContain("programming/python")
    expect(childIds).toContain("programming/go")
    expect(childIds).toContain("programming/rust")
  })

  it("note_count pill values match fixture", () => {
    const flat = flattenTagTree(MOCK_TAG_TREE)
    const python = flat.find((t) => t.id === "programming/python")
    expect(python?.note_count).toBe(18)
    const go = flat.find((t) => t.id === "programming/go")
    expect(go?.note_count).toBe(9)
  })

  it("flattenTagTree preserves parent-before-child order", () => {
    const flat = flattenTagTree(MOCK_TAG_TREE)
    const ids = flat.map((t) => t.id)
    expect(ids.indexOf("programming")).toBeLessThan(ids.indexOf("programming/python"))
    expect(ids.indexOf("science")).toBeLessThan(ids.indexOf("science/physics"))
  })

  it("flattenTagTree includes all 6 items", () => {
    expect(flattenTagTree(MOCK_TAG_TREE)).toHaveLength(6)
  })
})

// ---------------------------------------------------------------------------
// AC: TagAutocomplete fires autocomplete request
// ---------------------------------------------------------------------------

describe("TagAutocomplete request construction", () => {
  it("builds correct URL for plain query", () => {
    const url = buildAutocompleteUrl(API_BASE, "prog")
    expect(url).toBe(`${API_BASE}/tags/autocomplete?q=prog`)
  })

  it("URL-encodes slash prefix for child-only results", () => {
    const url = buildAutocompleteUrl(API_BASE, "programming/")
    expect(url).toBe(`${API_BASE}/tags/autocomplete?q=programming%2F`)
  })

  it("URL-encodes empty string (returns all tags)", () => {
    const url = buildAutocompleteUrl(API_BASE, "")
    expect(url).toBe(`${API_BASE}/tags/autocomplete?q=`)
  })
})

// ---------------------------------------------------------------------------
// AC: Tag breadcrumb parsing
// ---------------------------------------------------------------------------

describe("parseTagBreadcrumb", () => {
  it("flat tag returns root only, no rest", () => {
    const result = parseTagBreadcrumb("programming")
    expect(result.root).toBe("programming")
    expect(result.rest).toBeNull()
  })

  it("hierarchical tag splits at first slash", () => {
    const result = parseTagBreadcrumb("programming/python")
    expect(result.root).toBe("programming")
    expect(result.rest).toBe("/python")
  })

  it("deeply nested tag splits at first slash", () => {
    const result = parseTagBreadcrumb("science/physics/quantum")
    expect(result.root).toBe("science")
    expect(result.rest).toBe("/physics/quantum")
  })
})

// ---------------------------------------------------------------------------
// AC: Merge request construction
// ---------------------------------------------------------------------------

describe("buildMergeRequest", () => {
  it("returns POST method", () => {
    const req = buildMergeRequest(API_BASE, "ml", "machine-learning")
    expect(req.method).toBe("POST")
  })

  it("targets /tags/merge endpoint", () => {
    const req = buildMergeRequest(API_BASE, "ml", "machine-learning")
    expect(req.url).toBe(`${API_BASE}/tags/merge`)
  })

  it("body contains source_tag_id and target_tag_id", () => {
    const req = buildMergeRequest(API_BASE, "ml", "machine-learning")
    const body = JSON.parse(req.body) as { source_tag_id: string; target_tag_id: string }
    expect(body.source_tag_id).toBe("ml")
    expect(body.target_tag_id).toBe("machine-learning")
  })

  it("sets Content-Type application/json header", () => {
    const req = buildMergeRequest(API_BASE, "src", "tgt")
    expect(req.headers["Content-Type"]).toBe("application/json")
  })
})

// ---------------------------------------------------------------------------
// AC: filterMergeOptions excludes source and filters by query
// ---------------------------------------------------------------------------

describe("filterMergeOptions", () => {
  const TAGS: AutocompleteResult[] = [
    { id: "ml", display_name: "machine learning", parent_tag: null, note_count: 10 },
    { id: "programming/python", display_name: "python", parent_tag: "programming", note_count: 5 },
    { id: "science", display_name: "science", parent_tag: null, note_count: 3 },
  ]

  it("excludes the source tag from results", () => {
    const results = filterMergeOptions(TAGS, "ml", "")
    expect(results.map((t) => t.id)).not.toContain("ml")
  })

  it("returns all except source when query is empty", () => {
    const results = filterMergeOptions(TAGS, "ml", "")
    expect(results).toHaveLength(2)
  })

  it("filters by partial id match", () => {
    const results = filterMergeOptions(TAGS, "ml", "prog")
    expect(results).toHaveLength(1)
    expect(results[0].id).toBe("programming/python")
  })

  it("filters by partial display_name match", () => {
    const results = filterMergeOptions(TAGS, "ml", "sci")
    expect(results).toHaveLength(1)
    expect(results[0].id).toBe("science")
  })

  it("respects limit parameter", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      id: `tag-${i}`,
      display_name: `Tag ${i}`,
      parent_tag: null,
      note_count: 1,
    }))
    const results = filterMergeOptions(many, "tag-0", "", 5)
    expect(results).toHaveLength(5)
  })
})

// ---------------------------------------------------------------------------
// TagTree search input filters tags by substring match
// ---------------------------------------------------------------------------

const DEEP_TAG_TREE: TagTreeItem[] = [
  {
    id: "science",
    display_name: "science",
    parent_tag: null,
    note_count: 20,
    children: [
      {
        id: "science/biology",
        display_name: "biology",
        parent_tag: "science",
        note_count: 10,
        children: [
          {
            id: "science/biology/genetics",
            display_name: "genetics",
            parent_tag: "science/biology",
            note_count: 5,
            children: [],
          },
        ],
      },
      {
        id: "science/physics",
        display_name: "physics",
        parent_tag: "science",
        note_count: 8,
        children: [],
      },
    ],
  },
  {
    id: "programming",
    display_name: "programming",
    parent_tag: null,
    note_count: 15,
    children: [
      {
        id: "programming/python",
        display_name: "python",
        parent_tag: "programming",
        note_count: 7,
        children: [],
      },
    ],
  },
]

describe("S190: filterTagTree substring match", () => {
  it("returns all items when query is empty", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "")
    expect(result).toHaveLength(2)
    expect(result[0].matched).toBe(true)
  })

  it("filters to matching tags by display_name", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "genetics")
    // science/biology/genetics matches, parents included for context
    expect(result).toHaveLength(1) // only science tree
    expect(result[0].id).toBe("science")
    expect(result[0].matched).toBe(false) // parent is dimmed
    expect(result[0].children).toHaveLength(1) // biology
    expect(result[0].children[0].matched).toBe(false) // biology is dimmed
    expect(result[0].children[0].children).toHaveLength(1) // genetics
    expect(result[0].children[0].children[0].matched).toBe(true)
  })

  it("filters by id (full slug) match", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "science/biology")
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe("science")
    // biology matches by id, genetics also matches by id (contains "science/biology")
    expect(result[0].children[0].matched).toBe(true)
  })

  it("returns empty array when nothing matches", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "xyz123")
    expect(result).toHaveLength(0)
  })

  it("match is case-insensitive", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "PHYSICS")
    expect(result).toHaveLength(1) // science tree
    const physics = result[0].children.find((c) => c.id === "science/physics")
    expect(physics?.matched).toBe(true)
  })
})

describe("S190: parent chain shown for deeply nested matching tags", () => {
  it("genetics match includes science > biology parent chain", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "genetics")
    expect(result).toHaveLength(1)
    // science (dimmed) > biology (dimmed) > genetics (matched)
    const science = result[0]
    expect(science.id).toBe("science")
    expect(science.matched).toBe(false)
    const biology = science.children[0]
    expect(biology.id).toBe("science/biology")
    expect(biology.matched).toBe(false)
    const genetics = biology.children[0]
    expect(genetics.id).toBe("science/biology/genetics")
    expect(genetics.matched).toBe(true)
  })

  it("physics match excludes biology subtree", () => {
    const result = filterTagTree(DEEP_TAG_TREE, "physics")
    expect(result).toHaveLength(1)
    const science = result[0]
    // Only physics branch remains, not biology
    expect(science.children).toHaveLength(1)
    expect(science.children[0].id).toBe("science/physics")
  })
})

describe("S190: highlightMatch segments", () => {
  it("highlights matching substring", () => {
    const segs = highlightMatch("genetics", "net")
    expect(segs).toHaveLength(3)
    expect(segs[0]).toEqual({ text: "ge", highlight: false })
    expect(segs[1]).toEqual({ text: "net", highlight: true })
    expect(segs[2]).toEqual({ text: "ics", highlight: false })
  })

  it("highlights at start of string", () => {
    const segs = highlightMatch("python", "py")
    expect(segs).toHaveLength(2)
    expect(segs[0]).toEqual({ text: "py", highlight: true })
    expect(segs[1]).toEqual({ text: "thon", highlight: false })
  })

  it("highlights at end of string", () => {
    const segs = highlightMatch("python", "thon")
    expect(segs).toHaveLength(2)
    expect(segs[0]).toEqual({ text: "py", highlight: false })
    expect(segs[1]).toEqual({ text: "thon", highlight: true })
  })

  it("returns full text unhighlighted when no match", () => {
    const segs = highlightMatch("python", "xyz")
    expect(segs).toEqual([{ text: "python", highlight: false }])
  })

  it("case-insensitive highlight", () => {
    const segs = highlightMatch("Python", "PY")
    expect(segs).toHaveLength(2)
    expect(segs[0]).toEqual({ text: "Py", highlight: true })
  })

  it("returns full text when query is empty", () => {
    const segs = highlightMatch("python", "")
    expect(segs).toEqual([{ text: "python", highlight: false }])
  })
})
