import type { Config } from "tailwindcss";

/** Meshcore design tokens.
 *
 *  Two deliberate decisions here do most of the visual work:
 *
 *  1. The surface ramp is warm-neutral, not pure grey. The accent is a warm
 *     terracotta (#d97757); against true neutral greys it reads as an
 *     accident, and against slightly warm ones it reads as a palette. Every
 *     step carries a few points more red than blue.
 *
 *  2. `zinc` is REDEFINED rather than avoided. The app already writes
 *     `text-zinc-400` in about twenty files, and Tailwind's stock zinc is a
 *     cool blue-grey that fought the warm surfaces everywhere it appeared.
 *     Overriding the ramp fixes every one of those sites at once, with no
 *     class renaming and no chance of missing a file.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Surfaces, darkest first. 975 is the sidebar, 900 the canvas,
        // 850 raised cards, 800 controls, 700/600 borders.
        ink: {
          975: "#0f0f0e",
          950: "#141413",
          900: "#1a1a19",
          850: "#201f1e",
          800: "#272624",
          750: "#2f2e2b",
          700: "#383734",
          600: "#4a4844",
          500: "#6b6862",
        },
        // Warm greys for text and hairlines, replacing Tailwind's cool ramp.
        zinc: {
          50: "#faf9f7",
          100: "#f2f1ee",
          200: "#e4e2dd",
          300: "#cbc8c1",
          400: "#a5a29b",
          500: "#87847d",
          600: "#6d6a64",
          700: "#52504b",
          800: "#3b3a36",
          900: "#272624",
          950: "#1a1a19",
        },
        accent: {
          DEFAULT: "#d97757",
          soft: "#e5906f",
          deep: "#c2603f",
          dim: "#3a2820",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.375rem",
      },
      boxShadow: {
        // Dark UIs get depth from a lifted top edge plus a soft drop, not
        // from a heavier drop shadow — which on near-black just looks muddy.
        raised:
          "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,0.4)",
        panel: "0 8px 24px -8px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.35)",
        pop: "0 16px 40px -12px rgba(0,0,0,0.7), 0 2px 8px rgba(0,0,0,0.4)",
      },
      animation: {
        "pulse-dot": "pulseDot 1.6s ease-in-out infinite",
        "fade-in": "fadeIn 0.25s ease-out",
        "slide-up": "slideUp 0.28s cubic-bezier(0.16, 1, 0.3, 1)",
        "slide-in-right": "slideInRight 0.24s cubic-bezier(0.16, 1, 0.3, 1)",
        shimmer: "shimmer 1.4s ease-in-out infinite",
      },
      keyframes: {
        pulseDot: {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "1" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { opacity: "0", transform: "translateX(16px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "0.7" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
