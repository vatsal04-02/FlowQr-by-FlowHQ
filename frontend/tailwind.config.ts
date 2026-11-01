import type { Config } from "tailwindcss";

// FlowQR brand tokens. Blue = primary actions, orange = FlowQR accent, multicolour dots = Google-inspired accents
// (decorative only; never used to imply Google endorsement).
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#EEF4FE", 100: "#DCE8FD", 200: "#B9D1FB", 300: "#8AB2F7", 400: "#5B90F0",
          500: "#2F6FE4", 600: "#1A5FD0", 700: "#154CA8", 800: "#143F86", 900: "#13366B",
        },
        flow: { 50: "#FFF4EC", 100: "#FFE5D1", 400: "#FF8A3D", 500: "#F26B1D", 600: "#D9560B", 700: "#B14409" },
        ink: { DEFAULT: "#0F172A", 700: "#334155", 500: "#475569", 400: "#64748B", 300: "#94A3B8", 200: "#CBD5E1", 100: "#E2E8F0", 50: "#F1F5F9" },
        g: { blue: "#4285F4", red: "#EA4335", yellow: "#FBBC05", green: "#34A853" },
      },
      fontFamily: {
        sans: ["'Open Sans'", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Poppins", "'Open Sans'", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)",
        pop: "0 8px 30px rgba(15,23,42,.12)",
      },
      borderRadius: { xl2: "1rem" },
    },
  },
  plugins: [],
};
export default config;
