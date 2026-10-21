import { epubPlaceOf, type EpubPlace } from "../epubPlace"
import type { ReadingPosition } from "../ResumeBanner"

// A section counts as the reading position once the reader has stayed on it this long.
export const POSITION_SETTLE_MS = 10_000

/**
 * Saves the latest value once it has held for `settleMs`, and never the same value twice running.
 *
 * Fed by the Read view's current section. An observer attached when the document loaded
 * found no section elements (they arrive with a second query), never ran again, and so
 * saved no position: no resume offer, and chapter backfill (#231) never saw a book being read.
 */
export function settledSaver<T>(save: (value: T) => void, settleMs = POSITION_SETTLE_MS) {
  let saved: T | undefined
  let timer: ReturnType<typeof setTimeout> | undefined

  function stop() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  return {
    reach(value: T) {
      stop()
      if (value === saved) return
      timer = setTimeout(() => {
        timer = undefined
        saved = value
        save(value)
      }, settleMs)
    },
    stop,
  }
}

/**
 * Where the reader is, in each view a document has. The server keeps one row for all of
 * them, and a save replaces the whole row, so every save carries every view's place.
 */
export interface ReadPlace {
  sectionId: string | null
  heading: string | null
  pdfPage: number | null
  epubPlace: EpubPlace | null
}

export const NOWHERE: ReadPlace = { sectionId: null, heading: null, pdfPage: null, epubPlace: null }

export function placeOfPosition(pos: ReadingPosition): ReadPlace {
  return {
    sectionId: pos.last_section_id,
    heading: pos.last_section_heading,
    pdfPage: pos.last_pdf_page,
    epubPlace: epubPlaceOf(pos.last_epub_chapter_index, pos.last_epub_block_index),
  }
}

/** What was read this session wins; the saved place fills every view not yet read. */
export function withSaved(read: ReadPlace, saved: ReadPlace): ReadPlace {
  return {
    sectionId: read.sectionId ?? saved.sectionId,
    heading: read.heading ?? saved.heading,
    pdfPage: read.pdfPage ?? saved.pdfPage,
    epubPlace: read.epubPlace ?? saved.epubPlace,
  }
}

export function positionBody(place: ReadPlace) {
  return {
    last_section_id: place.sectionId,
    last_section_heading: place.heading,
    last_pdf_page: place.pdfPage,
    last_epub_chapter_index: place.epubPlace?.chapter ?? null,
    last_epub_block_index: place.epubPlace?.block ?? null,
  }
}
