const lum = (name) => `hsl(var(--lum-${name}) / <alpha-value>)`
const status = (name) => ({ DEFAULT: lum(name), soft: lum(`${name}-soft`), fg: lum(`${name}-fg`) })

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      // Without this, `font-sans` resolves to Tailwind's own default stack
      // while the semantic role classes in index.css use --font-sans, so the
      // app had two near-identical but different sans faces depending on which
      // one a component reached for. One definition, one place.
      fontFamily: {
        sans: "var(--font-sans)",
        serif: "var(--font-serif)",
        mono: "var(--font-mono)",
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        // `--destructive` has always been defined in index.css for both themes,
        // but it was never mapped here -- so `bg-destructive` and friends
        // generated no CSS at all and every destructive style silently did
        // nothing. The visible symptom was a delete confirmation whose
        // "Confirm" button rendered `text-white` on no background: invisible,
        // leaving only "Cancel" and no way to complete the action.
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
        },
        // The Luminary token layer (index.css): roles, never hues.
        canvas: lum("canvas"),
        raised: lum("raised"),
        sunken: lum("sunken"),
        rail: lum("rail"),
        hover: lum("hover"),
        ink: { 1: lum("ink-1"), 2: lum("ink-2"), 3: lum("ink-3") },
        hairline: lum("hairline"),
        "line-strong": lum("line-strong"),
        action: { DEFAULT: lum("action"), fg: lum("action-fg") },
        brand: lum("brand"),
        focus: lum("focus"),
        danger: { DEFAULT: lum("danger"), fg: lum("danger-fg") },
        positive: status("positive"),
        negative: status("negative"),
        caution: status("caution"),
        info: status("info"),
        mode: { recall: lum("mode-recall"), quiz: lum("mode-quiz"), explain: lum("mode-explain") },
        answer: {
          right: lum("positive"),
          "right-soft": lum("positive-soft"),
          "right-fg": lum("positive-fg"),
          wrong: lum("negative"),
          "wrong-soft": lum("negative-soft"),
          "wrong-fg": lum("negative-fg"),
          partial: lum("answer-partial"),
          "partial-soft": lum("answer-partial-soft"),
          "partial-fg": lum("answer-partial-fg"),
        },
        chart: Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((n) => [n, lum(`chart-${n}`)])),
      },
      // Nothing below 10px: the eyebrow is the floor.
      fontSize: {
        eyebrow: ["0.625rem", { lineHeight: "1", letterSpacing: "0.15em" }],
        caption: ["0.75rem", { lineHeight: "1.125rem" }],
        ui: ["0.8125rem", { lineHeight: "1.25rem" }],
        body: ["0.875rem", { lineHeight: "1.375rem" }],
        title: ["0.9375rem", { lineHeight: "1.375rem" }],
        h3: ["1.125rem", { lineHeight: "1.5rem" }],
        h2: ["1.25rem", { lineHeight: "1.75rem" }],
        h1: ["1.875rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em" }],
      },
      borderRadius: {
        xl: "var(--radius-xl)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // Surfaces are flat; only what floats over them casts a shadow.
      boxShadow: {
        overlay: "var(--shadow-lg)",
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}

