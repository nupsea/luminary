import { describe, expect, it } from "vitest"
import { sectionTitle } from "@/components/reader/sectionTitle"

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
