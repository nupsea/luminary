import { useState, useRef, useCallback } from "react"
import { toast } from "sonner"
import { apiPost, detailFromError } from "@/lib/apiClient"

export interface UseAudioRecorderOptions {
  onTranscribed: (text: string) => void
}

export function useAudioRecorder({ onTranscribed }: UseAudioRecorderOptions) {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const stopTracks = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }, [])

  const startRecording = useCallback(async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        toast.error("Audio recording is not supported in this environment.")
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // Pick best supported MIME type
      let mimeType = "audio/webm"
      if (typeof MediaRecorder.isTypeSupported === "function") {
        if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
          mimeType = "audio/webm;codecs=opus"
        } else if (MediaRecorder.isTypeSupported("audio/webm")) {
          mimeType = "audio/webm"
        } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
          mimeType = "audio/mp4"
        }
      }

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunksRef.current.push(e.data)
        }
      }

      recorder.onstop = async () => {
        stopTracks()
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" })
        if (blob.size < 500) {
          // Extremely short or empty recording; ignore
          return
        }

        setIsTranscribing(true)
        const formData = new FormData()
        const ext = mimeType.includes("mp4") ? "mp4" : "webm"
        formData.append("file", blob, `voice_recording.${ext}`)

        try {
          const data = await apiPost<{ text?: string }>("/audio/transcribe", formData)
          if (data.text && data.text.trim()) {
            onTranscribed(data.text.trim())
          } else {
            toast.info("No speech detected.")
          }
        } catch (err: unknown) {
          const error = detailFromError(err, "Could not transcribe audio")
          toast.error(error.message)
        } finally {
          setIsTranscribing(false)
        }
      }

      recorder.start(250) // slice chunks every 250ms
      mediaRecorderRef.current = recorder
      setIsRecording(true)
    } catch (err: unknown) {
      stopTracks()
      const msg = err instanceof Error ? err.message : "Microphone access denied or unavailable."
      toast.error(msg)
    }
  }, [onTranscribed, stopTracks])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop()
    }
    setIsRecording(false)
  }, [])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording()
    } else {
      void startRecording()
    }
  }, [isRecording, startRecording, stopRecording])

  return {
    isRecording,
    isTranscribing,
    startRecording,
    stopRecording,
    toggleRecording,
  }
}
