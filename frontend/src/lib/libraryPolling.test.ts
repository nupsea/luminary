// The card must move while work runs, and the page must go quiet when it does not.

import { describe, expect, it } from "vitest"

import {
  LIBRARY_POLL_MS,
  isDocumentBusy,
  libraryRefetchInterval,
} from "./libraryPolling"

const done = { stage: "complete", enrichment_status: "done" }

describe("isDocumentBusy", () => {
  it("is busy while enrichment is outstanding, even once ingestion is complete", () => {
    // The reported case: the card read a finished state while the toast beside it
    // counted down tasks still running on that same document.
    expect(isDocumentBusy({ stage: "complete", enrichment_status: "running" })).toBe(true)
    expect(isDocumentBusy({ stage: "complete", enrichment_status: "pending" })).toBe(true)
  })

  it("is busy while ingestion has not settled, whatever enrichment says", () => {
    expect(isDocumentBusy({ stage: "enriching", enrichment_status: null })).toBe(true)
    expect(isDocumentBusy({ stage: "parsing", enrichment_status: "done" })).toBe(true)
  })

  it("treats skipped as settled, not as work outstanding", () => {
    // A component that was never installed is actionable but not in progress;
    // polling for it would never stop.
    expect(isDocumentBusy({ stage: "complete", enrichment_status: "skipped" })).toBe(false)
  })

  it("treats a failed document as settled", () => {
    expect(isDocumentBusy({ stage: "failed", enrichment_status: null })).toBe(false)
  })

  it("is not busy when everything is done", () => {
    expect(isDocumentBusy(done)).toBe(false)
  })
})

describe("libraryRefetchInterval", () => {
  it("polls when any single row is busy", () => {
    const items = [done, done, { stage: "complete", enrichment_status: "running" }]
    expect(libraryRefetchInterval(items)).toBe(LIBRARY_POLL_MS)
  })

  it("stops entirely once nothing is outstanding", () => {
    // false, not a large number: a settled library should make no requests at all,
    // and this page is where the app sits for long stretches.
    expect(libraryRefetchInterval([done, done])).toBe(false)
  })

  it("stops on an empty or missing page rather than polling forever", () => {
    expect(libraryRefetchInterval([])).toBe(false)
    expect(libraryRefetchInterval(undefined)).toBe(false)
  })
})
