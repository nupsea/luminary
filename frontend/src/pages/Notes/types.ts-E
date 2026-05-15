// Type interfaces consumed by Notes.tsx and its sub-components.
// API shapes sourced from generated `src/types/api.ts` (audit #15);
// only types not represented in the OpenAPI schema stay inline.

import type { components } from "@/types/api"

export type Note = components["schemas"]["NoteResponse"]
export type GroupInfo = components["schemas"]["GroupInfo"]
export type TagInfo = components["schemas"]["app__schemas__notes__TagInfo"]
export type GroupsData = components["schemas"]["GroupsResponse"]
export type Clip = components["schemas"]["ClipResponse"]
export type ClusterNotePreview = components["schemas"]["ClusterNotePreview"]
export type ClusterSuggestion = components["schemas"]["ClusterSuggestionResponse"]
export type NoteSearchItem = components["schemas"]["NoteSearchItem"]
export type NoteSearchResponse = components["schemas"]["NoteSearchResponse"]

// Local-only: minimal 2-field subset for the document picker; the
// generated DocumentListItem carries many more fields the picker
// doesn't need.
export interface DocumentItem {
  id: string
  title: string
}

// Local-only: simplified recursive shape used by the in-page tree UI.
// The generated CollectionTreeItem carries display metadata (color,
// icon, counts) the simplified tree doesn't render.
export interface CollectionTreeNode {
  id: string
  name: string
  children?: CollectionTreeNode[]
}

