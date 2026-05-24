// Luminary lantern glyph -- the brand mark.
//
// Paths sized to fill ~80% of the 24x24 viewBox (the previous draft only
// used ~40%, which is why it rendered tiny inside its containers). Stroke
// 2 + a bigger filled diamond flame gives the icon visual weight that
// holds up at sidebar sizes (18px) and reads clearly at hub-header sizes
// (28px+).

interface LuminaryGlyphProps {
  size?: number
  className?: string
}

export function LuminaryGlyph({ size = 24, className }: LuminaryGlyphProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {/* Suspension hook */}
      <path d="M12 2 V 4" />
      {/* Crossbar yoke */}
      <path d="M8 4 H 16" />
      {/* Lantern body: large rounded rectangle */}
      <path d="M5 7 Q 5 5.5 6.5 5.5 H 17.5 Q 19 5.5 19 7 V 19 Q 19 20.5 17.5 20.5 H 6.5 Q 5 20.5 5 19 Z" />
      {/* Side rails framing the flame */}
      <path d="M8.5 5.5 V 20.5" opacity="0.5" />
      <path d="M15.5 5.5 V 20.5" opacity="0.5" />
      {/* Filled diamond flame -- the load-bearing detail */}
      <path d="M12 8 L 15 13 L 12 18 L 9 13 Z" fill="currentColor" />
      {/* Base flange */}
      <path d="M4 22 H 20" />
    </svg>
  )
}
