// Per-card teach-back input + inline feedback + retry.
// Owns the speech-recognition lifecycle and the submitted/evaluating/result UI states.

import { motion } from "framer-motion"
import { ArrowRight, BookOpen, Loader2, Mic, MicOff } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { isButtonActivation, isTypingTarget } from "@/lib/keyboard"
import { type Flashcard, type TeachbackResultItem } from "@/lib/studyApi"

import { InlineTeachbackFeedback } from "./InlineTeachbackFeedback"
import {
  SpeechRecognitionAPI,
  type SpeechRecognitionEvent,
  type SpeechRecognitionInstance,
} from "./speechRecognition"

interface TeachbackPanelProps {
  card: Flashcard
  onNext: () => void
  onSubmitAsync: (cardId: string, question: string, explanation: string) => void
  onEndSession: () => void
  currentResult: TeachbackResultItem | null
  isEvaluating: boolean
  previousAttempt: TeachbackResultItem | null
}

export function TeachbackPanel({
  card,
  onNext,
  onSubmitAsync,
  onEndSession,
  currentResult,
  isEvaluating,
  previousAttempt,
}: TeachbackPanelProps) {
  const [explanation, setExplanation] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const manualStopRef = useRef(false)
  // Latch: the outgoing panel keeps its window listener alive during the exit
  // animation, and onNext increments the reviewed count -- fire it exactly once.
  const advancedRef = useRef(false)

  function nextOnce() {
    if (advancedRef.current) return
    advancedRef.current = true
    onNext()
  }

  useEffect(() => {
    return () => {
      manualStopRef.current = true
      recognitionRef.current?.stop()
    }
  }, [])

  function toggleRecording() {
    if (isRecording) {
      manualStopRef.current = true
      recognitionRef.current?.stop()
      setIsRecording(false)
      return
    }
    if (!SpeechRecognitionAPI) return
    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"

    manualStopRef.current = false
    let finalTranscript = ""
    recognition.onresult = (e: SpeechRecognitionEvent) => {
      let interim = ""
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const segment = e.results[i][0].transcript
        if (e.results[i].isFinal) {
          finalTranscript += segment
        } else {
          interim += segment
        }
      }
      setExplanation(finalTranscript + interim)
    }

    recognition.onend = () => {
      if (!manualStopRef.current) {
        setExplanation(finalTranscript)
      }
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognition.onerror = () => {
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsRecording(true)
  }

  function handleSubmit() {
    if (!explanation.trim()) return
    onSubmitAsync(card.id, card.question, explanation.trim())
    setSubmitted(true)
  }

  function handleRetry() {
    setExplanation("")
    setSubmitted(false)
  }

  const showForm = !submitted
  const showEvaluating = submitted && !currentResult && isEvaluating
  const evalErrored = submitted && currentResult != null && currentResult.status === "error"
  const showResult = submitted && currentResult != null && currentResult.status === "complete"
  const showError = evalErrored || (submitted && !isEvaluating && !currentResult)
  const failed = showResult && (currentResult.score ?? 0) < 60
  const canRetry = showError || failed

  // Post-submit keys: Enter advances to the next card, R retries where a retry
  // is offered. The form stage is textarea-driven (Ctrl/Cmd+Enter submits there).
  useEffect(() => {
    if (showForm) return
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return
      if (isButtonActivation(e)) return
      if (e.key === "Enter") {
        e.preventDefault()
        nextOnce()
        return
      }
      if (canRetry && (e.key === "r" || e.key === "R")) {
        e.preventDefault()
        handleRetry()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showForm, canRetry, onNext])

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {/* Previous attempt banner -- shown when card was re-queued */}
      {previousAttempt && !submitted && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950/30">
          <p className="mb-2 text-xs font-semibold text-amber-800 dark:text-amber-300">
            Previous attempt -- score {previousAttempt.score}/100
          </p>
          <InlineTeachbackFeedback result={previousAttempt} />
          <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
            Try explaining again with the feedback above in mind.
          </p>
        </div>
      )}

      {/* Card question in a distinct card */}
      <div className="rounded-xl border border-violet-200 bg-violet-50/50 p-5 dark:border-violet-800 dark:bg-violet-950/20">
        <div className="mb-2 flex items-center gap-2">
          <BookOpen size={14} className="text-violet-500" />
          <span className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
            Explain this concept
          </span>
        </div>
        <MarkdownRenderer className="text-base font-medium text-foreground">
          {card.question}
        </MarkdownRenderer>
      </div>

      {/* Input form */}
      {showForm && (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">
            Explain the answer in your own words -- as if teaching someone else:
          </p>
          <div className="relative">
            <textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  handleSubmit()
                  return
                }
                // The autofocused textarea swallows the session-level Esc: with a
                // draft, Esc just leaves the field (second Esc ends); empty, it
                // ends the session directly.
                if (e.key === "Escape") {
                  e.preventDefault()
                  if (explanation.trim()) e.currentTarget.blur()
                  else onEndSession()
                }
              }}
              placeholder="Type your explanation here..."
              className="h-36 w-full resize-none rounded-lg border border-border bg-background p-4 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-violet-400"
              autoFocus
            />
            <button
              type="button"
              onClick={toggleRecording}
              disabled={!SpeechRecognitionAPI}
              title={
                SpeechRecognitionAPI
                  ? isRecording
                    ? "Stop recording"
                    : "Start voice input"
                  : "Voice input not supported in this browser"
              }
              className="absolute right-3 top-3 rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isRecording ? (
                <MicOff size={16} className="animate-pulse text-destructive" />
              ) : (
                <Mic size={16} />
              )}
            </button>
          </div>
          {isRecording && (
            <p className="text-xs text-destructive">Recording... click the mic again to stop.</p>
          )}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSubmit}
              disabled={!explanation.trim()}
              data-kbnav
              className="self-start rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Submit Explanation
            </button>
            <p className="text-[11px] text-muted-foreground">Ctrl/⌘+Enter to submit</p>
          </div>
        </div>
      )}

      {/* Evaluating spinner */}
      {showEvaluating && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-4">
          <div className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin text-violet-500" />
            <span className="text-sm text-muted-foreground">
              Evaluating your explanation...
            </span>
          </div>
          <div className="flex items-center gap-2">
            <p className="text-[11px] text-muted-foreground">Enter for next card</p>
            <button
              onClick={nextOnce}
              data-kbnav
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              title="Results will appear in the session summary"
            >
              Next Card
              <ArrowRight size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Evaluation error */}
      {showError && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border-2 border-red-300 bg-red-50 p-4 dark:border-red-700 dark:bg-red-950/40"
        >
          <p className="mb-3 text-center text-sm font-semibold text-red-800 dark:text-red-300">
            Evaluation failed. Your answer was recorded -- you can continue.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={nextOnce}
              autoFocus
              data-kbnav
              className="flex items-center gap-2 rounded-lg bg-red-600 px-6 py-2.5 text-sm font-bold text-white hover:bg-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Next Card <ArrowRight size={18} />
            </button>
            <button
              onClick={handleRetry}
              data-kbnav
              className="rounded-lg border-2 border-red-300 px-5 py-2.5 text-sm font-semibold text-red-800 hover:bg-red-100 dark:border-red-700 dark:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Try Again
            </button>
          </div>
          <p className="mt-3 text-center text-[11px] text-red-700 dark:text-red-400/80">
            Enter for next card · R to retry
          </p>
        </motion.div>
      )}

      {/* Inline result feedback + action banner */}
      {showResult && (
        <>
          <div className="rounded-lg border border-border bg-card p-4">
            <InlineTeachbackFeedback result={currentResult} />
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className={`rounded-lg p-4 ${
              failed
                ? "border-2 border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-950/40"
                : "border-2 border-green-400 bg-green-50 dark:border-green-600 dark:bg-green-950/40"
            }`}
          >
            <p
              className={`mb-3 text-center text-sm font-semibold ${
                failed
                  ? "text-amber-800 dark:text-amber-300"
                  : "text-green-800 dark:text-green-300"
              }`}
            >
              {failed
                ? "Review the feedback and try again, or continue."
                : "Solid explanation. Move on to the next card."}
            </p>
            <div className="flex items-center justify-center gap-3">
              <motion.button
                onClick={nextOnce}
                autoFocus
                data-kbnav
                initial={{ scale: 0.95 }}
                animate={{ scale: 1 }}
                className={`flex items-center gap-2 rounded-lg px-8 py-3 text-base font-bold shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
                  failed
                    ? "bg-amber-600 text-white hover:bg-amber-700"
                    : "bg-green-600 text-white hover:bg-green-700"
                }`}
              >
                Next Card <ArrowRight size={20} />
              </motion.button>
              {failed && (
                <button
                  onClick={handleRetry}
                  data-kbnav
                  className="rounded-lg border-2 border-amber-400 px-6 py-3 text-sm font-semibold text-amber-800 hover:bg-amber-100 dark:border-amber-600 dark:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  Try Again
                </button>
              )}
            </div>
            <p
              className={`mt-3 text-center text-[11px] ${
                failed
                  ? "text-amber-700 dark:text-amber-400/80"
                  : "text-green-700 dark:text-green-400/80"
              }`}
            >
              {failed ? "Enter for next card · R to retry" : "Enter for next card"}
            </p>
          </motion.div>
        </>
      )}
    </div>
  )
}
