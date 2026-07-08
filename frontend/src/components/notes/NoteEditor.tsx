import { useRef, useState } from "react"
import { ChevronUp, Wrench } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteDiagramDialog } from "@/components/NoteDiagramDialog"
import { type MarkdownEditorHandle } from "@/components/notes/MarkdownCodeEditor"
import {
  MarkdownSplitEditor,
  type MarkdownSplitLayout,
} from "@/components/notes/MarkdownSplitEditor"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import { MermaidCheatSheet } from "@/components/notes/MermaidCheatSheet"
import { MermaidQuickInsert } from "@/components/notes/MermaidQuickInsert"
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
  showToolbar?: boolean
  showImageSize?: boolean
  autoFocus?: boolean
  imageVariant?: (path: string) => string
  editorClassName?: string
  linkCompletion?: NoteLinkCompletionConfig
}

const IMAGE_SIZES = ["small", "medium", "large"] as const

export function NoteEditor({
  content,
  onContentChange,
  layout = "splitter",
  showToolbar = true,
  showImageSize = true,
  autoFocus,
  imageVariant = (path) => `![Pasted Image|medium](${path})`,
  editorClassName,
  linkCompletion,
}: NoteEditorProps) {
  const editorRef = useRef<MarkdownEditorHandle | null>(null)

  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<ExcalidrawNoteDiagramRef | null>(null)
  const [toolbarOpen, setToolbarOpen] = useState(true)

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      onContentChange(replaceExcalidrawDiagram(content, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    editorRef.current?.insertBlock(markdown)
  }

  function insertImageSizeMarkdown(size: (typeof IMAGE_SIZES)[number]) {
    editorRef.current?.replaceSelection((selectedText) => {
      const match = selectedText.match(/!\[([^\]]*?)\]\((.*?)\)/)
      if (match) {
        const altClean = match[1].split("|")[0].trim() || "Image"
        return `![${altClean}|${size}](${match[2]})`
      }
      return `![Image|${size}](url)`
    })
  }

  function openDiagramEditor(ref: ExcalidrawNoteDiagramRef) {
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
  }

  const editorToolbar = showToolbar ? (
    <>
      <div className="flex items-center justify-between gap-2">
        {toolbarOpen ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {showImageSize && (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground">Image spec:</span>
                {IMAGE_SIZES.map((size) => (
                  <button
                    key={size}
                    type="button"
                    onClick={() => insertImageSizeMarkdown(size)}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium hover:bg-accent text-foreground capitalize"
                  >
                    {size}
                  </button>
                ))}
              </div>
            )}
            <MermaidQuickInsert
              onInsert={(markdown) => editorRef.current?.insertBlock(markdown)}
              onDraw={() => {
                setEditingDiagramRef(null)
                setDiagramOpen(true)
              }}
            />
          </div>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={() => setToolbarOpen((v) => !v)}
          className="shrink-0 rounded border border-border bg-background p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          title={toolbarOpen ? "Hide formatting tools" : "Show formatting tools"}
          aria-label={toolbarOpen ? "Hide formatting tools" : "Show formatting tools"}
        >
          {toolbarOpen ? <ChevronUp size={12} /> : <Wrench size={12} />}
        </button>
      </div>
      {toolbarOpen && <MermaidCheatSheet />}
    </>
  ) : null

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <MarkdownSplitEditor
          layout={layout}
          content={content}
          onContentChange={onContentChange}
          editorRef={editorRef}
          editorToolbar={editorToolbar}
          placeholder="Write your note in Markdown..."
          autoFocus={autoFocus}
          onPasteImage={async (file) => {
            const data = await uploadNoteAsset(file)
            return imageVariant(data.path)
          }}
          editorClassName={editorClassName}
          linkCompletion={linkCompletion}
          preview={
            content.trim() ? (
              <MarkdownRenderer serif onEditExcalidrawDiagram={openDiagramEditor}>
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
