// Drop a file anywhere on the window to add it.
//
// The only drop target used to be inside the Add Content dialog, so a file had
// to be dropped onto a surface the user first had to know to open. Dropping on
// the app -- the obvious gesture -- did nothing.

import { useEffect, useRef, useState } from "react"
import { Upload } from "lucide-react"
import { toast } from "sonner"

import { capabilityOf, useCapabilities } from "@/hooks/useSetup"
import { carriesFiles, describeRejection, makeDragDepth } from "@/lib/uploadFileTypes"
import { useAppStore } from "@/store"

export function WindowDropZone() {
  const [active, setActive] = useState(false)
  const openUploadDialog = useAppStore((s) => s.openUploadDialog)
  const { data: caps } = useCapabilities()
  const support = {
    canAudio: capabilityOf(caps, "audio_ingest").available,
    canVideo: capabilityOf(caps, "video_ingest").available,
  }

  // Read through a ref: re-subscribing the window listeners on every capability
  // refetch would drop an in-flight drag.
  const supportRef = useRef(support)
  supportRef.current = support

  useEffect(() => {
    const depth = makeDragDepth()

    const onEnter = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      setActive(depth.enter())
    }
    const onOver = (e: DragEvent) => {
      // Without this the browser navigates to the file instead of dropping it.
      if (carriesFiles(e.dataTransfer?.types)) e.preventDefault()
    }
    const onLeave = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      setActive(depth.leave())
    }
    const onDrop = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      e.preventDefault()
      depth.reset()
      setActive(false)

      const file = e.dataTransfer?.files?.[0]
      if (!file) return

      const rejection = describeRejection(file.name, supportRef.current)
      if (rejection) {
        toast.error(rejection.message, {
          description: rejection.componentId
            ? "Install it from the setup screen, then try again."
            : undefined,
        })
        return
      }
      openUploadDialog(file)
    }

    window.addEventListener("dragenter", onEnter)
    window.addEventListener("dragover", onOver)
    window.addEventListener("dragleave", onLeave)
    window.addEventListener("drop", onDrop)
    return () => {
      window.removeEventListener("dragenter", onEnter)
      window.removeEventListener("dragover", onOver)
      window.removeEventListener("dragleave", onLeave)
      window.removeEventListener("drop", onDrop)
    }
  }, [openUploadDialog])

  if (!active) return null

  return (
    <div className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-primary/50 bg-card px-10 py-8">
        <Upload size={28} className="text-primary" />
        <p className="text-sm font-medium text-foreground">Drop to add to your library</p>
      </div>
    </div>
  )
}
