import type { Config } from "tailwindcss";

// FlowQR design tokens. The logged-in app follows docs DESIGN.md (soft grey canvas, white cards, one orange accent, black primary
// actions, light + dark). Colours are CSS variables declared in globals.css; see the note on `colors` below.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  // dark: variants follow the app theme on <html data-theme="dark"> (only ever set inside the logged-in app)
  darkMode: ["selector", "[data-theme=\"dark\"]"],
  theme: {
    extend: {
      colors: {
        // Every app colour is a CSS variable (globals.css). Defaults are the original palette, so marketing, auth and public QR pages
        // are unchanged; <html class="fq-app"> (set by the app shell) swaps in the dashboard palette from docs DESIGN.md, light or dark.
        ink: { DEFAULT: "rgb(var(--c-ink) / <alpha-value>)", 800: "rgb(var(--c-ink-800) / <alpha-value>)", 700: "rgb(var(--c-ink-700) / <alpha-value>)", 600: "rgb(var(--c-ink-600) / <alpha-value>)", 500: "rgb(var(--c-ink-500) / <alpha-value>)", 400: "rgb(var(--c-ink-400) / <alpha-value>)", 300: "rgb(var(--c-ink-300) / <alpha-value>)", 200: "rgb(var(--c-ink-200) / <alpha-value>)", 100: "rgb(var(--c-ink-100) / <alpha-value>)", 50: "rgb(var(--c-ink-50) / <alpha-value>)",
          solid: "rgb(var(--c-ink-solid) / <alpha-value>)", on: "rgb(var(--c-on-ink) / <alpha-value>)" },
        brand: { 50: "rgb(var(--c-brand-50) / <alpha-value>)", 100: "rgb(var(--c-brand-100) / <alpha-value>)", 200: "rgb(var(--c-brand-200) / <alpha-value>)", 300: "rgb(var(--c-brand-300) / <alpha-value>)", 400: "rgb(var(--c-brand-400) / <alpha-value>)", 500: "rgb(var(--c-brand-500) / <alpha-value>)", 600: "rgb(var(--c-brand-600) / <alpha-value>)", 700: "rgb(var(--c-brand-700) / <alpha-value>)", 800: "rgb(var(--c-brand-800) / <alpha-value>)", 900: "rgb(var(--c-brand-900) / <alpha-value>)", 950: "rgb(var(--c-brand-950) / <alpha-value>)" },
        flow: { 50: "rgb(var(--c-flow-50) / <alpha-value>)", 100: "rgb(var(--c-flow-100) / <alpha-value>)", 400: "rgb(var(--c-flow-400) / <alpha-value>)", 500: "rgb(var(--c-flow-500) / <alpha-value>)", 600: "rgb(var(--c-flow-600) / <alpha-value>)", 700: "rgb(var(--c-flow-700) / <alpha-value>)" },
        // m = the marketing site palette (docs/marketing-site/DESIGN.md §2). Values live in CSS variables on .mkt.
        m: { bg: "rgb(var(--m-bg) / <alpha-value>)", surface: "rgb(var(--m-surface) / <alpha-value>)", tint: "rgb(var(--m-tint) / <alpha-value>)", tint2: "rgb(var(--m-tint2) / <alpha-value>)", ink: "rgb(var(--m-ink) / <alpha-value>)", ink2: "rgb(var(--m-ink2) / <alpha-value>)", muted: "rgb(var(--m-muted) / <alpha-value>)", muted2: "rgb(var(--m-muted2) / <alpha-value>)", line: "rgb(var(--m-line) / <alpha-value>)", accent: "rgb(var(--m-accent) / <alpha-value>)", accent300: "rgb(var(--m-accent300) / <alpha-value>)", accentText: "rgb(var(--m-accentText) / <alpha-value>)", accentStrong: "rgb(var(--m-accentStrong) / <alpha-value>)", gold: "rgb(var(--m-gold) / <alpha-value>)", navy: "rgb(var(--m-navy) / <alpha-value>)" },
        fq: { DEFAULT: "rgb(var(--c-fq) / <alpha-value>)", hover: "rgb(var(--c-fq-hover) / <alpha-value>)", 50: "rgb(var(--c-fq-50) / <alpha-value>)", 100: "rgb(var(--c-fq-100) / <alpha-value>)" },
        gold: { 50: "#FFF6DC", 100: "#FFE9AE", 400: "#F2B01E", 500: "#E39B0B", 600: "#A56A00", 700: "#8A5600" },
        star: "rgb(var(--c-star) / <alpha-value>)",
        navy: "rgb(var(--c-navy) / <alpha-value>)",
        ok: "rgb(var(--c-ok) / <alpha-value>)",
        // white follows the theme inside the app (a card is white in light mode, near-black in dark). pure.* never changes.
        white: "rgb(var(--c-white) / <alpha-value>)",
        pure: { white: "#FFFFFF", ink: "#131014" },
        red: { 50: "rgb(var(--c-red-50) / <alpha-value>)", 100: "rgb(var(--c-red-100) / <alpha-value>)", 200: "rgb(var(--c-red-200) / <alpha-value>)", 300: "rgb(var(--c-red-300) / <alpha-value>)", 400: "rgb(var(--c-red-400) / <alpha-value>)", 500: "rgb(var(--c-red-500) / <alpha-value>)", 600: "rgb(var(--c-red-600) / <alpha-value>)", 700: "rgb(var(--c-red-700) / <alpha-value>)", 800: "rgb(var(--c-red-800) / <alpha-value>)", 900: "rgb(var(--c-red-900) / <alpha-value>)", 950: "rgb(var(--c-red-950) / <alpha-value>)" }, green: { 50: "rgb(var(--c-green-50) / <alpha-value>)", 100: "rgb(var(--c-green-100) / <alpha-value>)", 200: "rgb(var(--c-green-200) / <alpha-value>)", 300: "rgb(var(--c-green-300) / <alpha-value>)", 400: "rgb(var(--c-green-400) / <alpha-value>)", 500: "rgb(var(--c-green-500) / <alpha-value>)", 600: "rgb(var(--c-green-600) / <alpha-value>)", 700: "rgb(var(--c-green-700) / <alpha-value>)", 800: "rgb(var(--c-green-800) / <alpha-value>)", 900: "rgb(var(--c-green-900) / <alpha-value>)", 950: "rgb(var(--c-green-950) / <alpha-value>)" }, amber: { 50: "rgb(var(--c-amber-50) / <alpha-value>)", 100: "rgb(var(--c-amber-100) / <alpha-value>)", 200: "rgb(var(--c-amber-200) / <alpha-value>)", 300: "rgb(var(--c-amber-300) / <alpha-value>)", 400: "rgb(var(--c-amber-400) / <alpha-value>)", 500: "rgb(var(--c-amber-500) / <alpha-value>)", 600: "rgb(var(--c-amber-600) / <alpha-value>)", 700: "rgb(var(--c-amber-700) / <alpha-value>)", 800: "rgb(var(--c-amber-800) / <alpha-value>)", 900: "rgb(var(--c-amber-900) / <alpha-value>)", 950: "rgb(var(--c-amber-950) / <alpha-value>)" },
        // Dashboard semantic tokens (DESIGN.md §2.1)
        canvas: { DEFAULT: "rgb(var(--c-canvas) / <alpha-value>)", outer: "rgb(var(--c-canvas-outer) / <alpha-value>)" },
        surface: { DEFAULT: "rgb(var(--c-surface) / <alpha-value>)", 2: "rgb(var(--c-surface-2) / <alpha-value>)", 3: "rgb(var(--c-surface-3) / <alpha-value>)" },
        muted: { DEFAULT: "rgb(var(--c-muted) / <alpha-value>)", soft: "rgb(var(--c-muted-soft) / <alpha-value>)" },
        line: "rgb(var(--c-line) / <alpha-value>)",
        accent: { DEFAULT: "rgb(var(--c-accent) / <alpha-value>)", hi: "rgb(var(--c-accent-hi) / <alpha-value>)", lo: "rgb(var(--c-accent-lo) / <alpha-value>)", ink: "rgb(var(--c-accent-ink) / <alpha-value>)", tint: "rgb(var(--c-accent-tint) / <alpha-value>)", edge: "rgb(var(--c-accent-edge) / <alpha-value>)" },
        pos: { DEFAULT: "rgb(var(--c-pos) / <alpha-value>)", tint: "rgb(var(--c-pos-tint) / <alpha-value>)" },
        neg: { DEFAULT: "rgb(var(--c-neg) / <alpha-value>)", tint: "rgb(var(--c-neg-tint) / <alpha-value>)" },
        warn: { DEFAULT: "rgb(var(--c-warn) / <alpha-value>)", tint: "rgb(var(--c-warn-tint) / <alpha-value>)" },
        g: { blue: "#4285F4", red: "#EA4335", yellow: "#FBBC05", green: "#34A853" },
      },
      fontFamily: {
        // One family for everything people read and tap; its mono sibling only for card IDs, tokens and other technical identifiers.
        sans: ["Geist", "system-ui", "-apple-system", "'Segoe UI'", "'Noto Sans Devanagari'", "Roboto", "sans-serif"],
        display: ["Geist", "system-ui", "-apple-system", "'Segoe UI'", "'Noto Sans Devanagari'", "sans-serif"],
        app: ["Inter", "system-ui", "-apple-system", "'Segoe UI'", "'Noto Sans Devanagari'", "Roboto", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontWeight: { semibold: "600", bold: "650", extrabold: "700" },
      borderRadius: { panel: "10px", frame: "32px", card: "28px", tile: "22px", inner: "16px" },
      boxShadow: {
        panel: "0 1px 0 rgba(23,23,25,.03)",
        pop: "0 12px 32px -8px rgba(23,23,25,.24), 0 2px 6px rgba(23,23,25,.06)",
        float: "0 30px 60px -24px rgba(23,23,25,.45), 0 10px 20px -10px rgba(23,23,25,.25)",
        card: "var(--shadow-card)", pill: "var(--shadow-pill)", hero: "var(--shadow-hero)", lift: "var(--shadow-lift)",
      },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        "fade-up": "fade-up .4s cubic-bezier(.22,1,.36,1) both",
      },
    },
  },
  plugins: [],
};
export default config;
