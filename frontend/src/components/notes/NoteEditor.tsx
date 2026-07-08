import { useMemo, useRef, useState } from "react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteDiagramDialog } from "@/components/NoteDiagramDialog"
import { type MarkdownEditorHandle } from "@/components/notes/MarkdownCodeEditor"
import {
  MarkdownSplitEditor,
  type MarkdownSplitLayout,
} from "@/components/notes/MarkdownSplitEditor"
import { setImageSizeInMarkdown } from "@/components/notes/markdownEditorCommands"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import { type SlashCommandConfig } from "@/components/notes/slashCommands"
import { API_BASE } from "@/lib/config"
import { uploadNoteAsset } from "@/lib/noteAssets"
import {
  replaceExcalidrawDiagram,
  type ExcalidrawNoteDiagramRef,
} from "@/lib/noteDiagrams"

export type NoteEditorLayout = MarkdownSplitLayout

export interface NoteEditorProps {
  content: string
  onContentChange: (next: string) => void
  layout?: NoteEditorLayout
  autoFocus?: boolean
  imageVariant?: (path: string) => string
  editorClassName?: string
  linkCompletion?: NoteLinkCompletionConfig
}

export function NoteEditor({
  content,
  onContentChange,
  layout = "splitter",
  autoFocus,
  imageVariant = (path) => `![Pasted Image|medium](${path})`,
  editorClassName,
  linkCompletion,
}: NoteEditorProps) {
  const editorRef = useRef<MarkdownEditorHandle | null>(null)

  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<ExcalidrawNoteDiagramRef | null>(null)

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      onContentChange(replaceExcalidrawDiagram(content, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    editorRef.current?.insertBlock(markdown)
  }

  function openDiagramEditor(ref: ExcalidrawNoteDiagramRef) {
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
  }

  const slashCommands = useMemo<SlashCommandConfig>(
    () => ({
      onDrawDiagram: () => {
        setEditingDiagramRef(null)
        setDiagramOpen(true)
      },
    }),
    [],
  )

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <MarkdownSplitEditor
          layout={layout}
          content={content}
          onContentChange={onContentChange}
          editorRef={editorRef}
          placeholder="Write your note in Markdown... Type / for blocks, [[ to link notes"
          autoFocus={autoFocus}
          onPasteImage={async (file) => {
            const data = await uploadNoteAsset(file)
            return imageVariant(data.path)
          }}
          editorClassName={editorClassName}
          linkCompletion={linkCompletion}
          slashCommands={slashCommands}
          preview={
            content.trim() ? (
              <MarkdownRenderer
                serif
                onEditExcalidrawDiagram={openDiagramEditor}
                onSetImageSize={(src, size) =>
                  onContentChange(setImageSizeInMarkdown(content, src, size, API_BASE))
                }
              >
                {content}
              </MarkdownRenderer>
            ) : (
              <p className="text-muted-foreground italic text-sm">Preview will appear here...</p>
            )
          }
        />
      </div>
      <NoteDiagramDialog
        open={diagramOpen}
        onOpenChange={setDiagramOpen}
        scenePath={editingDiagramRef?.scenePath}
        onSaved={handleDiagramSaved}
      />
    </>
  )
}
