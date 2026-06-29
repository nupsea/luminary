// Luminary brand mark -- the user-provided lantern artwork, background removed,
// in a light-frame variant (light mode) and a white-frame variant (dark mode) so
// it stays visible on either theme. Rendered as an image rather than a redrawn
// glyph because this is the exact reference art. Height-driven; width keeps the
// art's aspect ratio. `className` is forwarded for layout (color classes have no
// effect on the image, which carries its own colors).

import { cn } from "@/lib/utils"
import lanternLight from "@/assets/luminary-lantern-light.png"
import lanternDark from "@/assets/luminary-lantern-dark.png"

interface LuminaryGlyphProps {
  size?: number
  className?: string
}

export function LuminaryGlyph({ size = 24, className }: LuminaryGlyphProps) {
  return (
    <>
      <img
        src={lanternLight}
        alt=""
        aria-hidden="true"
        style={{ height: size, width: "auto" }}
        className={cn("inline-block dark:hidden", className)}
      />
      <img
        src={lanternDark}
        alt=""
        aria-hidden="true"
        style={{ height: size, width: "auto" }}
        className={cn("hidden dark:inline-block", className)}
      />
    </>
  )
}
