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
  // Held from the click that starts a recording until its transcription settles.
  const busyRef = useRef(false)
  const streamRef = useRef<MediaStream | null>(null)

  const stopTracks = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }, [])

  const startRecording = useCallback(async () => {
    // A second click while the permission prompt is open started a second
    // recorder that was never stopped, and its header-less chunks leaked into
    // every later recording.
    if (busyRef.current) return
    busyRef.current = true
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        toast.error("Audio recording is not supported in this environment.")
        busyRef.current = false
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      let mimeType: string | undefined
      if (typeof MediaRecorder.isTypeSupported === "function") {
        mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((t) =>
          MediaRecorder.isTypeSupported(t),
        )
      }

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const chunks: Blob[] = []

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunks.push(e.data)
        }
      }

      recorder.onstop = async () => {
        stopTracks()
        // The container the browser actually wrote, which may differ from the one asked for.
        const type = recorder.mimeType || mimeType || "audio/webm"
        const blob = new Blob(chunks, { type })
        if (blob.size < 500) {
          busyRef.current = false
          return
        }

        setIsTranscribing(true)
        const formData = new FormData()
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm"
        formData.append("file", blob, `voice_recording.${ext}`)
        // Whisper guesses the language of a short clip badly; the UI locale is the hint.
        const language = navigator.language?.split("-")[0]
        if (language) formData.append("language", language)

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
          busyRef.current = false
        }
      }

      recorder.onerror = () => {
        stopTracks()
        setIsRecording(false)
        busyRef.current = false
        toast.error("Recording failed. Try again.")
      }

      recorder.start(250) // slice chunks every 250ms
      mediaRecorderRef.current = recorder
      setIsRecording(true)
    } catch (err: unknown) {
      stopTracks()
      busyRef.current = false
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
