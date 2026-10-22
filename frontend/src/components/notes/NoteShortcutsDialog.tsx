import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { Keyboard } from "lucide-react"
import { NoteShortcuts } from "./NoteShortcuts"

export interface NoteShortcutsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function NoteShortcutsDialog({ open, onOpenChange }: NoteShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col overflow-hidden p-6">
        <NoteShortcuts
          surface="page"
          heading={
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Keyboard className="h-4 w-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold">Note Editor Shortcuts</DialogTitle>
                <DialogDescription className="text-xs text-muted-foreground">
                  Works across macOS, Windows, Linux, Desktop App & Web
                </DialogDescription>
              </div>
            </div>
          }
        />
      </DialogContent>
    </Dialog>
  )
}
