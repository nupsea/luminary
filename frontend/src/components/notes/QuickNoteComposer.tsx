/**
 * The sheet-shaped NoteComposer: what a page that has no room beside it opens.
 * A reader with a panel docks the same composer instead.
 */

import { NoteComposer, type NoteComposerProps } from "@/components/notes/NoteComposer"

export type QuickNoteComposerProps = Omit<NoteComposerProps, "variant" | "captureKey">

export function QuickNoteComposer(props: QuickNoteComposerProps) {
  return <NoteComposer {...props} variant="sheet" />
}
