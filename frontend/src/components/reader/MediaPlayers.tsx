import { Pause, Play } from "lucide-react"
import type React from "react"

import { formatMmSs } from "./mediaUtils"

interface AudioMiniPlayerProps {
  audioRef: React.RefObject<HTMLAudioElement | null>
  audioUrl: string
  playing: boolean
  currentTime: number
  duration: number
  onPlayPause: () => void
  onSeek: (t: number) => void
  onTimeUpdate: () => void
  onLoadedMetadata: () => void
  onEnded: () => void
}

export function AudioMiniPlayer({
  audioRef,
  audioUrl,
  playing,
  currentTime,
  duration,
  onPlayPause,
  onSeek,
  onTimeUpdate,
  onLoadedMetadata,
  onEnded,
}: AudioMiniPlayerProps) {
  return (
    <div className="flex items-center gap-3 border-t border-border bg-background px-6 py-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audioRef}
        src={audioUrl}
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={onLoadedMetadata}
        onEnded={onEnded}
      />

      <button
        onClick={onPlayPause}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? <Pause size={14} /> : <Play size={14} />}
      </button>

      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {formatMmSs(currentTime)}
      </span>

      <input
        type="range"
        min={0}
        max={duration || 0}
        step={0.5}
        value={currentTime}
        onChange={(e) => onSeek(parseFloat(e.target.value))}
        className="flex-1 accent-primary"
        aria-label="Audio seek"
      />

      <span className="w-10 shrink-0 text-xs tabular-nums text-muted-foreground">
        {formatMmSs(duration)}
      </span>
    </div>
  )
}

interface VideoPlayerProps {
  videoRef: React.RefObject<HTMLVideoElement | null>
  videoUrl: string
}

export function VideoPlayer({ videoRef, videoUrl }: VideoPlayerProps) {
  return (
    <div className="mb-4 overflow-hidden rounded-lg border border-border bg-black">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={videoRef} src={videoUrl} controls className="w-full" />
    </div>
  )
}
