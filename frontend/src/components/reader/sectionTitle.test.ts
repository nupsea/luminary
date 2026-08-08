import { describe, expect, it } from "vitest"
import { hasAuthoredHeading, sectionTitle, usableSections } from "@/components/reader/sectionTitle"

describe("sectionTitle", () => {
  it("relabels a Google Docs anchor id from the section text", () => {
    expect(
      sectionTitle({
        heading: "_r9szt46p8rxa",
        preview: "15 Apache Airflow® 3 Best Practices: ETL and ELT Pipelines Task-oriented approach The task-oriented approach is the most common way",
      }),
    ).not.toContain("_r9szt46p8rxa")
  })

  it("keeps a real heading untouched", () => {
    expect(sectionTitle({ heading: "Chapter 2: Models", preview: "x" })).toBe("Chapter 2: Models")
  })

  it("never returns empty, even with nothing to derive from", () => {
    expect(sectionTitle({ heading: "_r9szt46p8rxa", preview: "" })).toBeTruthy()
    expect(sectionTitle({ heading: "", preview: "" })).toBe("(Untitled section)")
  })
})

describe("usableSections", () => {
  it("drops stray glyphs while keeping the real headings (Sutton)", () => {
    const out = usableSections([
      { heading: "Reinforcement Learning", preview: "" },
      { heading: "c", preview: "" },
      { heading: "g", preview: "" },
      { heading: "our move{", preview: "" },
      { heading: "Summary", preview: "" },
    ])
    expect(out.map(s => s.heading)).toEqual(["Reinforcement Learning", "Summary"])
  })

  it("keeps every entry when all headings are anchor ids (ETL Airflow)", () => {
    const out = usableSections([
      { heading: "_r9szt46p8rxa", preview: "Task-oriented approach The task-oriented approach is" },
      { heading: "_uw3vhlxngjid", preview: "Figure 6. Graph view of the simple my_dag DAG" },
    ])
    expect(out).toHaveLength(2)
    expect(out.every(s => !s.heading.startsWith("_"))).toBe(true)
  })

  it("never empties the panel, even when nothing can be relabelled", () => {
    const out = usableSections([{ heading: "c", preview: "" }, { heading: "g", preview: "" }])
    expect(out).toHaveLength(2)
  })
})

describe("hasAuthoredHeading", () => {
  it("accepts a heading the source wrote", () => {
    expect(hasAuthoredHeading({ heading: "CHAPTER I. Down the Rabbit-Hole" })).toBe(true)
  })

  it("rejects an unlabelled section rather than deriving one", () => {
    // The reading flow must draw nothing here. sectionTitle still returns a
    // derived label for the contents panel, which needs an entry to navigate.
    expect(hasAuthoredHeading({ heading: "" })).toBe(false)
    expect(hasAuthoredHeading({})).toBe(false)
  })

  it("rejects anchor-id headings from Google Docs exports", () => {
    expect(hasAuthoredHeading({ heading: "_r9szt46p8rxa" })).toBe(false)
  })
})
