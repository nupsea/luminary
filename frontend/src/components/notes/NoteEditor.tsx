import { useCallback, useDeferredValue, useMemo, useRef, useState, type RefObject } from "react"
import { MarkdownRenderer, type ImageSize } from "@/components/MarkdownRenderer"
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
import { annotationTarget, isAnnotatedImage, replaceExcalidrawDiagram, type AnnotationTarget } from "@/lib/noteDiagrams"

export type NoteEditorLayout = MarkdownSplitLayout

export interface NoteEditorProps {
  content: string
  onContentChange: (next: string) => void
  layout?: NoteEditorLayout
  autoFocus?: boolean
  imageVariant?: (path: string) => string
  editorClassName?: string
  linkCompletion?: NoteLinkCompletionConfig
  /** External handle (outline navigation); defaults to an internal ref. */
  editorRef?: RefObject<MarkdownEditorHandle | null>
  onOpenShortcuts?: () => void
  onNoteLinkClick?: (noteId: string) => void
}

export function NoteEditor({
  content,
  onContentChange,
  layout = "splitter",
  autoFocus,
  imageVariant = (path) => `![Pasted Image|medium](${path})`,
  editorClassName,
  linkCompletion,
  editorRef: externalEditorRef,
  onOpenShortcuts,
  onNoteLinkClick,
}: NoteEditorProps) {
  const internalEditorRef = useRef<MarkdownEditorHandle | null>(null)
  const editorRef = externalEditorRef ?? internalEditorRef
  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<
    AnnotationTarget | null
  >(null)

  const contentRef = useRef(content)
  contentRef.current = content

  // In split mode, defer preview rendering so typing remains 100% fluid and concurrent
  const deferredContent = useDeferredValue(content)
  const previewContent = layout === "splitter" ? deferredContent : content

  const handleSetImageSize = useCallback(
    (src: string, size: ImageSize) => {
      onContentChange(setImageSizeInMarkdown(contentRef.current, src, size, API_BASE))
    },
    [onContentChange],
  )

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      onContentChange(replaceExcalidrawDiagram(content, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    editorRef.current?.insertBlock(markdown)
  }

  function openDiagramEditor(ref: AnnotationTarget) {
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
  }

  function handleAnnotateImage(src: string) {
    const ref = annotationTarget(contentRef.current, src, API_BASE)
    if (ref) openDiagramEditor(ref)
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
          onEditDiagram={openDiagramEditor}
          onAnnotateImage={openDiagramEditor}
          onOpenShortcuts={onOpenShortcuts}
          onNoteLinkClick={onNoteLinkClick}
          preview={
            previewContent.trim() ? (
              <MarkdownRenderer
                reading
                trackSourceLines
                bracketMath={false}
                onNoteLinkClick={onNoteLinkClick}
                onEditExcalidrawDiagram={openDiagramEditor}
                onSetImageSize={handleSetImageSize}
                onAnnotateImage={handleAnnotateImage}
              >
                {previewContent}
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
        scenePath={editingDiagramRef && "scenePath" in editingDiagramRef ? editingDiagramRef.scenePath : null}
        imagePath={editingDiagramRef && "imagePath" in editingDiagramRef ? editingDiagramRef.imagePath : null}
        annotated={
          editingDiagramRef !== null &&
          ("imagePath" in editingDiagramRef || isAnnotatedImage(editingDiagramRef))
        }
        size={editingDiagramRef?.size}
        onSaved={handleDiagramSaved}
      />
    </>
  )
}
