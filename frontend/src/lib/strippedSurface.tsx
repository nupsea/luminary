// Build-time replacement for dev-tier surfaces on public/labs bundles. The vite
// config aliases stripped component paths here so their code never ships; the
// nav rail and router filter them out before this would ever render.
export default function StrippedSurface() {
  return null
}
