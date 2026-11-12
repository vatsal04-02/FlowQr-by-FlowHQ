import type { Config } from "tailwindcss";

// FlowQR design tokens.
//   ink   = warm graphite neutrals (text, borders, page "warm white" = ink-50)
//   brand = cobalt: the one interactive colour (primary actions, links, selection, focus)
//   flow  = FlowHQ orange: the parent brand mark and the physical card's identity edge. Restrained: never a button or link.
//   gold  = NFC / tap signal and Google review stars. Nothing else.
//   ok / amber / red = status only (Tailwind amber and red are used directly).
// Contrast on white: ink-500 7.5:1, ink-400 5.6:1, ink-300 3.5:1 (control borders), brand-600 8.0:1, flow-700 5.7:1, gold-600 4.5:1.
// ink-200 and lighter are separators only and are never relied on to identify a control.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#171719", 800: "#232326", 700: "#3B3A38", 500: "#57554F", 400: "#6B6860", 300: "#8C8880", 200: "#D8D5CE", 100: "#E8E5DF", 50: "#F4F2EE" },
        brand: {
          50: "#EDF2FD", 100: "#D8E3FB", 200: "#B4C8F6", 300: "#86A5EE", 400: "#4F78E0",
          500: "#2F5ECE", 600: "#1B46B8", 700: "#163A96", 800: "#122F78", 900: "#0E2559", 950: "#0A1A40",
        },
        flow: { 50: "#FFF4EC", 100: "#FFE5D1", 400: "#FF8A3D", 500: "#F26B1D", 600: "#D9560B", 700: "#B14409" },
        gold: { 50: "#FFF6DC", 100: "#FFE9AE", 400: "#F2B01E", 500: "#E39B0B", 600: "#A56A00", 700: "#8A5600" },
        star: "#F2B01E",
        ok: "#0B7A55",
      },
      fontFamily: {
        // One family for everything people read and tap; its mono sibling only for card IDs, tokens and other technical identifiers.
        sans: ["Geist", "system-ui", "-apple-system", "'Segoe UI'", "'Noto Sans Devanagari'", "Roboto", "sans-serif"],
        display: ["Geist", "system-ui", "-apple-system", "'Segoe UI'", "'Noto Sans Devanagari'", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontWeight: { semibold: "600", bold: "650", extrabold: "700" },
      borderRadius: { panel: "10px" },
      boxShadow: {
        panel: "0 1px 0 rgba(23,23,25,.03)",
        pop: "0 12px 32px -8px rgba(23,23,25,.24), 0 2px 6px rgba(23,23,25,.06)",
        float: "0 30px 60px -24px rgba(23,23,25,.45), 0 10px 20px -10px rgba(23,23,25,.25)",
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
