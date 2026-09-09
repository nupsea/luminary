// The chat with nothing in it yet.

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"

export function ChatEmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="relative flex h-16 w-16 items-center justify-center">
        <div className="lum-halo absolute inset-0 rounded-full bg-gradient-to-br from-primary/25 to-purple-500/20 blur-xl" />
        <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/10 to-purple-500/10">
          <LuminaryGlyph size={30} />
        </div>
      </div>
      <div className="space-y-1.5">
        <h2 className="lum-h3">{title}</h2>
        <p className="mx-auto max-w-sm text-sm leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </div>
  )
}
