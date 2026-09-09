import { Loader2, Mic, Square } from "lucide-react"
import { useAudioRecorder } from "@/hooks/useAudioRecorder"
import { useCapability } from "@/hooks/useSetup"
import { cn } from "@/lib/utils"

export interface VoiceRecordButtonProps {
  onTranscribed: (text: string) => void
  label?: string
  recordingLabel?: string
  className?: string
  size?: "sm" | "default"
  title?: string
}

export function VoiceRecordButton({
  onTranscribed,
  label,
  recordingLabel = "Listening...",
  className,
  size = "default",
  title = "Dictate with voice (Whisper)",
}: VoiceRecordButtonProps) {
  const { isRecording, isTranscribing, toggleRecording } = useAudioRecorder({
    onTranscribed,
  })
  // The installer ships no transcriber -- faster-whisper pulls GPL code, so it
  // is a component the user adds afterwards. Offering the mic before then gets
  // a recording made and thrown away against a `uv sync` message.
  const dictation = useCapability("dictation")

  const isSmall = size === "sm"

  if (!dictation.available) return null

  return (
    <button
      type="button"
      onClick={toggleRecording}
      disabled={isTranscribing}
      title={isRecording ? "Stop recording" : title}
      className={cn(
        "relative inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:pointer-events-none disabled:opacity-50",
        isSmall ? "h-7 px-2 text-xs" : "h-8 px-2.5 text-xs",
        isRecording
          ? "border border-red-500/40 bg-red-500/10 text-red-600 animate-pulse hover:bg-red-500/20 dark:text-red-400"
          : isTranscribing
          ? "border border-border bg-muted/60 text-muted-foreground"
          : "border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground",
        className,
      )}
    >
      {isTranscribing ? (
        <>
          <Loader2 size={isSmall ? 12 : 14} className="animate-spin text-primary" />
          {label && <span>Transcribing...</span>}
        </>
      ) : isRecording ? (
        <>
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500" />
          </span>
          <Square size={isSmall ? 10 : 12} className="fill-current text-red-600 dark:text-red-400" />
          <span>{recordingLabel}</span>
        </>
      ) : (
        <>
          <Mic size={isSmall ? 13 : 15} />
          {label && <span>{label}</span>}
        </>
      )}
    </button>
  )
}
