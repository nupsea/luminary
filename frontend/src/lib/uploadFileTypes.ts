// What Luminary will accept from a file picker or a drop, and why it won't.
//
// Shared so the dialog's drop zone and the window-wide one cannot disagree
// about which files are allowed. Pure -- unit tested without mounting anything.

import type { ContentTypeValue } from "@/lib/ingestionApi"

export const TEXT_TYPES = [".pdf", ".docx", ".txt", ".md", ".epub"]
export const AUDIO_TYPES = [".mp3", ".m4a", ".wav"]
export const VIDEO_TYPES = [".mp4"]

export interface FormatSupport {
  canAudio: boolean
  canVideo: boolean
}

export function acceptedExtensions({ canAudio, canVideo }: FormatSupport): string[] {
  return [...TEXT_TYPES, ...(canAudio ? AUDIO_TYPES : []), ...(canVideo ? VIDEO_TYPES : [])]
}

export function isKindleClippings(filename: string): boolean {
  return /clippings/i.test(filename)
}

/**
 * The type a *filename* proves, or null when only the content can say.
 *
 * Returning null matters: the backend skips classification entirely for a
 * user-supplied content_type, so anything sent here is final. This used to
 * return "book" for every non-media file, which meant a PDF paper and a
 * markdown textbook both arrived pre-labelled as a novel and the classifier
 * never ran -- auto-detection was unreachable from the upload path no matter
 * how good the rules were.
 *
 * An extension is evidence for media and EPUB and for nothing else. `.pdf`,
 * `.txt`, `.md` and `.docx` each carry every content type there is.
 */
export function detectContentType(filename: string): ContentTypeValue | null {
  const f = filename.toLowerCase()
  if (f.endsWith(".epub")) return "book"
  if (/\.(mp3|m4a|wav)$/.test(f)) return "audio"
  if (f.endsWith(".mp4")) return "video"
  return null
}

/** Map a classified type onto the value the picker actually offers.
 *
 *  The classifier answers in the stored vocabulary (`tech_book`,
 *  `tech_article`, `epub`...) while the picker offers one `technical` option
 *  covering the tech_* variants, because the difference is only chunk sizing.
 *  Without this the detected value matched no option, `selected` was undefined,
 *  and a correctly detected technical book rendered as "Detect automatically" --
 *  detection looked broken precisely when it had worked.
 */
export function toPickerValue(detected: string | null): ContentTypeValue | null {
  if (!detected) return null
  const mapped: Record<string, ContentTypeValue> = {
    tech_book: "technical",
    tech_article: "technical",
    code: "technical",
    epub: "book",
    kindle_clippings: "notes",
  }
  const value = mapped[detected] ?? (detected as ContentTypeValue)
  // Anything the picker cannot show is better left undetected than shown wrong.
  const offered: ContentTypeValue[] = [
    "book",
    "technical",
    "paper",
    "conversation",
    "notes",
    "audio",
    "video",
  ]
  return offered.includes(value) ? value : null
}

export interface Rejection {
  message: string
  // Set when the format is supported but its component is not installed, so the
  // caller can offer the install rather than a dead end.
  componentId?: string
}

/**
 * Why this file cannot be added, or null if it can.
 *
 * A drop that fails silently is indistinguishable from a broken app, which is
 * how an uninstalled transcriber used to present: drop an MP3, nothing happens.
 */
export function describeRejection(filename: string, support: FormatSupport): Rejection | null {
  const lower = filename.toLowerCase()
  const ext = lower.slice(lower.lastIndexOf("."))

  if (acceptedExtensions(support).includes(ext)) return null

  if (AUDIO_TYPES.includes(ext) && !support.canAudio) {
    return {
      message: "Audio needs speech-to-text, which isn't installed yet.",
      componentId: "transcription",
    }
  }
  if (VIDEO_TYPES.includes(ext) && !support.canVideo) {
    return {
      message: "Video needs speech-to-text and ffmpeg, which aren't installed yet.",
      componentId: "transcription",
    }
  }
  return {
    message: `Luminary can't read ${ext || "that kind of"} files. Try ${TEXT_TYPES.join(", ")}.`,
  }
}

/**
 * Tracks nested dragenter/dragleave so an overlay does not flicker.
 *
 * Every child element under the cursor fires its own pair as the pointer moves,
 * so a boolean flag blinks. Counting them and hiding only at zero does not.
 */
export function makeDragDepth() {
  let depth = 0
  return {
    enter: () => ++depth > 0,
    leave: () => --depth > 0,
    reset: () => {
      depth = 0
    },
    get depth() {
      return depth
    },
  }
}

// A drag carrying files, as opposed to selected text or an internal element.
export function carriesFiles(types: readonly string[] | undefined): boolean {
  return Array.from(types ?? []).includes("Files")
}
