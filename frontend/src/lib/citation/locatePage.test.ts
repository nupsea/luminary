// Finding the page a citation names, when it does not name one.

import { describe, expect, it, vi } from "vitest"

import { locateCitationPage } from "./locatePage"

const PAGES: Record<number, string> = {
  1: "Title page and abstract.",
  2: "Introduction to the method and its background.",
  3: "The analysis is conducted on the SDS dataset, and the results are in Table 4.",
  4: "Conclusion and references.",
}
const getPageText = async (p: number) => PAGES[p] ?? ""
const words = "The analysis is conducted on the SDS dataset".split(" ")

describe("locateCitationPage", () => {
  it("finds the page holding the passage when the citation carries none", () => {
    // pdf_page_number is null whenever ingestion could not attribute the chunk to
    // a sheet; a viewer opening at page 1 would then highlight nothing.
    return expect(locateCitationPage(words, { pageCount: 4, getPageText })).resolves.toBe(3)
  })

  it("tries the citation's own page first, and stops there", async () => {
    const spy = vi.fn(getPageText)
    await locateCitationPage(words, { pageCount: 4, getPageText: spy, preferredPage: 3 })
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith(3)
  })

  it("falls back to a scan when the named page is wrong", () => {
    return expect(
      locateCitationPage(words, { pageCount: 4, getPageText, preferredPage: 1 }),
    ).resolves.toBe(3)
  })

  it("returns null when no page holds the passage", () => {
    return expect(
      locateCitationPage("nothing like this anywhere".split(" "), { pageCount: 4, getPageText }),
    ).resolves.toBeNull()
  })

  it("skips a page that will not yield text rather than failing the scan", async () => {
    const flaky = async (p: number) => {
      if (p === 2) throw new Error("extraction failed")
      return PAGES[p] ?? ""
    }
    await expect(locateCitationPage(words, { pageCount: 4, getPageText: flaky })).resolves.toBe(3)
  })

  it("abandons the scan when the reader navigates away", async () => {
    const spy = vi.fn(getPageText)
    await expect(
      locateCitationPage(words, { pageCount: 4, getPageText: spy, isCancelled: () => true }),
    ).resolves.toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it("does nothing without words or pages", async () => {
    await expect(locateCitationPage([], { pageCount: 4, getPageText })).resolves.toBeNull()
    await expect(locateCitationPage(words, { pageCount: 0, getPageText })).resolves.toBeNull()
  })
})
