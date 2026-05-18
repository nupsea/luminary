// Renders a single chat message: user text, assistant markdown, cards, or scope-change divider.
// Owns the per-message ornaments: citations, web sources, transparency panel,
// source-citation chips, and image thumbnails.

import { Badge } from "@/components/ui/badge"
import { GapResultCard } from "@/components/GapResultCard"
import type { GapCardData } from "@/components/GapResultCard"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { QuizQuestionCard } from "@/components/QuizQuestionCard"
import { Skeleton } from "@/components/ui/skeleton"
import { SourceCitationChips } from "@/components/SourceCitationChips"
import type { SourceCitation } from "@/components/SourceCitationChips"
import { TeachBackResultCard } from "@/components/TeachBackResultCard"
import type { TeachBackCardData } from "@/components/TeachBackResultCard"
import { API_BASE } from "@/lib/config"

import { CONFIDENCE_BADGE } from "./constants"
import { TransparencyPanel } from "./TransparencyPanel"
import type { ChatMessage, QuizCardData } from "./types"

interface MessageBubbleProps {
  msg: ChatMessage
  effectiveDocId: string | null
  onQuizSubmit: (text: string) => void
  navigateToCitation: (c: SourceCitation) => void
}

export function MessageBubble({ msg, effectiveDocId, onQuizSubmit, navigateToCitation }: MessageBubbleProps) {
  if (msg.type === "divider") {
    return (
      <div className="flex items-center gap-3 py-1">
        <div className="h-px flex-1 bg-border" />
        <span className="text-xs text-muted-foreground">{msg.text}</span>
        <div className="h-px flex-1 bg-border" />
      </div>
    )
  }

  return (
    <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-3 ${msg.role === "user"
            ? "bg-slate-100 text-slate-900"
            : "border border-border bg-white text-foreground shadow-sm"
          }`}
      >
        {msg.type === "card" && msg.cardData !== undefined ? (
          msg.cardData.type === "quiz_question" ? (
            <QuizQuestionCard
              question={(msg.cardData as QuizCardData).question}
              contextHint={(msg.cardData as QuizCardData).context_hint}
              documentId={(msg.cardData as QuizCardData).document_id}
              error={(msg.cardData as QuizCardData).error}
              onSubmit={onQuizSubmit}
            />
          ) : msg.cardData.type === "teach_back_result" ? (
            <TeachBackResultCard data={msg.cardData as TeachBackCardData} />
          ) : msg.cardData.type === "gap_result" ? (
            <GapResultCard data={msg.cardData as GapCardData} documentId={effectiveDocId ?? undefined} />
          ) : (
            <p className="text-xs text-muted-foreground">Unknown card type</p>
          )
        ) : msg.not_found ? (
          <p className="text-sm text-blue-600">
            This information was not found in the selected content.
          </p>
        ) : msg.role === "user" ? (
          <p className="whitespace-pre-wrap text-sm">{msg.text}</p>
        ) : msg.isStreaming && msg.text === "" ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-40" />
          </div>
        ) : (
          <div className="[&_p]:text-sm [&_p]:leading-relaxed [&_p]:my-1
              [&_ol]:text-sm [&_ol]:my-1 [&_ol]:pl-5 [&_ol]:list-decimal
              [&_ul]:text-sm [&_ul]:my-1 [&_ul]:pl-5 [&_ul]:list-disc
              [&_li]:my-0.5
              [&_strong]:font-semibold
              [&_h1]:text-base [&_h1]:font-semibold [&_h1]:mt-2 [&_h1]:mb-1
              [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-2 [&_h2]:mb-1
              [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-1">
            <MarkdownRenderer>{msg.text}</MarkdownRenderer>
            {msg.isStreaming && <span className="animate-pulse">▍</span>}
          </div>
        )}

        {!msg.isStreaming && msg.citations && msg.citations.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {msg.citations.map((c, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  title={c.excerpt}
                >
                  {c.document_title
                    ? `${c.document_title.slice(0, 20)}${c.document_title.length > 20 ? "…" : ""} · p.${c.page}`
                    : `p.${c.page}`}
                  {c.version_mismatch && (
                    <span className="ml-1 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                      Version mismatch
                    </span>
                  )}
                </span>
              ))}
            </div>
            {msg.confidence && (
              <Badge variant={CONFIDENCE_BADGE[msg.confidence]}>
                {msg.confidence} confidence
              </Badge>
            )}
          </div>
        )}

        {!msg.isStreaming && msg.web_sources && msg.web_sources.length > 0 && (
          <div className="mt-2 space-y-1">
            <span className="text-xs font-medium text-muted-foreground">Web sources:</span>
            {msg.web_sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate text-xs text-blue-600 hover:underline"
                title={s.title}
              >
                [Web: {s.domain}] {s.title}
              </a>
            ))}
          </div>
        )}

        {!msg.isStreaming && msg.transparency && (
          <TransparencyPanel transparency={msg.transparency} />
        )}

        {!msg.isStreaming && (
          <SourceCitationChips
            citations={msg.source_citations ?? []}
            navigateToCitation={navigateToCitation}
          />
        )}

        {!msg.isStreaming && msg.image_ids && msg.image_ids.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {msg.image_ids.map((id) => (
              <img
                key={id}
                src={`${API_BASE}/images/${id}/raw`}
                alt="Diagram from document"
                className="h-24 w-auto rounded border border-border object-contain"
                loading="lazy"
                onError={(e) => {
                  ;(e.currentTarget as HTMLImageElement).style.display = "none"
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
