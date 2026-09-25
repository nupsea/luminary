import { useState } from "react"
import { Loader2, Mic, Square } from "lucide-react"
import { InstallComponentButton } from "@/components/setup/InstallComponentButton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  variant?: "default" | "pill" | "icon"
}

export function VoiceRecordButton({
  onTranscribed,
  label,
  recordingLabel = "Listening...",
  className,
  size = "default",
  title = "Dictate with voice (Whisper)",
  variant = "default",
}: VoiceRecordButtonProps) {
  const { isRecording, isTranscribing, toggleRecording } = useAudioRecorder({
    onTranscribed,
  })
  // The installer ships no transcriber -- faster-whisper pulls GPL code, so it
  // is a component the user adds afterwards. Until then the mic offers the
  // install rather than recording: hidden, nobody learned dictation existed.
  const dictation = useCapability("dictation")
  const [offering, setOffering] = useState(false)

  const isSmall = size === "sm"
  const isIcon = variant === "icon"
  const sizing = isIcon
    ? isSmall
      ? "h-7 w-7 shrink-0"
      : "h-8 w-8 shrink-0"
    : isSmall
      ? "h-7 px-2.5 text-xs"
      : "h-8 px-3 text-xs"

  if (!dictation.available) {
    return (
      <>
        <button
          type="button"
          onClick={() => setOffering(true)}
          title="Dictation needs speech to text"
          aria-label="Dictation needs speech to text"
          className={cn(
            "inline-flex items-center justify-center gap-1.5 rounded-md border border-dashed border-border/80 bg-background/80 font-medium text-muted-foreground/70 transition-all hover:bg-accent hover:text-foreground",
            sizing,
            className,
          )}
        >
          <Mic size={isSmall ? 13 : 15} className="shrink-0" />
          {!isIcon && label && <span>{label}</span>}
        </button>
        <Dialog open={offering} onOpenChange={setOffering}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Dictation needs speech to text</DialogTitle>
              <DialogDescription>
                A one-time download that turns your voice into text on this computer. Nothing
                you say leaves it.
              </DialogDescription>
            </DialogHeader>
            <InstallComponentButton componentId="transcription" onInstalled={() => setOffering(false)} />
          </DialogContent>
        </Dialog>
      </>
    )
  }

  return (
    <button
      type="button"
      onClick={toggleRecording}
      disabled={isTranscribing}
      title={isRecording ? "Stop recording" : title}
      aria-label={isRecording ? "Stop recording" : title}
      className={cn(
        "group relative inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:pointer-events-none disabled:opacity-50",
        sizing,
        isRecording
          ? "border border-rose-500/40 bg-rose-500/10 text-rose-600 shadow-[0_0_12px_rgba(244,63,94,0.12)] hover:bg-rose-500/20 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-400 dark:hover:bg-rose-950/60"
          : isTranscribing
          ? "border border-primary/30 bg-primary/10 text-primary"
          : "border border-border/80 bg-background/80 text-muted-foreground hover:border-border hover:bg-accent hover:text-foreground shadow-xs",
        className,
      )}
    >
      {isTranscribing ? (
        <>
          <Loader2 size={isSmall ? 12 : 14} className="animate-spin text-primary shrink-0" />
          {!isIcon && <span className="text-xs font-medium text-primary">Transcribing...</span>}
        </>
      ) : isRecording ? (
        isIcon ? (
          <>
            <span className="flex h-3.5 items-center justify-center gap-[2px] px-0.5 group-hover:hidden" aria-hidden="true">
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-1" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-2" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-3" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-4" />
            </span>
            <Square size={isSmall ? 10 : 11} className="hidden group-hover:block fill-current text-rose-600 dark:text-rose-400" />
          </>
        ) : (
          <span className="flex items-center gap-1.5 font-medium tracking-tight">
            <span className="flex h-3.5 items-center gap-[2px] px-0.5" aria-hidden="true">
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-1" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-2" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-3" />
              <span className="w-[2px] rounded-full bg-rose-500 dark:bg-rose-400 lum-voice-bar-4" />
            </span>
            <span className="text-xs">{recordingLabel}</span>
            <span className="flex items-center justify-center rounded-sm bg-rose-500/20 p-0.5 text-rose-600 dark:text-rose-400 group-hover:bg-rose-500/30">
              <Square size={isSmall ? 8 : 9} className="fill-current" />
            </span>
          </span>
        )
      ) : (
        <>
          <Mic size={isSmall ? 13 : 15} className="shrink-0" />
          {!isIcon && label && <span>{label}</span>}
        </>
      )}
    </button>
  )
}
