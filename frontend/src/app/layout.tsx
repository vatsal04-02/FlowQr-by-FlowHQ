import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui/Toast";
import { APP_PREFIXES } from "@/lib/nav";
import { themeBootScript } from "@/lib/theme-boot";

export const metadata: Metadata = {
  title: { default: "FlowQR — Google reviews and review cards for local businesses", template: "%s | FlowQR" },
  description: "Get found on Google, get genuine reviews and manage your online presence in one place. Google Business management, an AI Review Assistant, QR/NFC review cards and human-approved replies and posts.",
  robots: { index: true, follow: true },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#F4F2EE" };

// Fonts are files in this repository (src/fonts, see its README), served from FlowQR's own domain: a visitor's browser never contacts Google's font servers (which would send their IP
// address and browser details to Google before they have agreed to anything), and neither does the build. The CSS variables are what tailwind.config.ts and globals.css use.
const geist = localFont({ src: "../fonts/geist-latin.woff2", weight: "100 900", variable: "--font-geist", display: "swap" });
const geistMono = localFont({ src: "../fonts/geist-mono-latin.woff2", weight: "100 900", variable: "--font-geist-mono", display: "swap" });
const inter = localFont({ src: "../fonts/inter-latin.woff2", weight: "100 900", variable: "--font-inter", display: "swap" });
const jakarta = localFont({ src: "../fonts/plus-jakarta-sans-700-latin.woff2", weight: "700", variable: "--font-jakarta", display: "swap" });
const devanagari = localFont({ src: "../fonts/noto-sans-devanagari.woff2", weight: "100 900", variable: "--font-devanagari", display: "swap", preload: false }); // Hindi review page only

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${geist.variable} ${geistMono.variable} ${inter.variable} ${jakarta.variable} ${devanagari.variable}`}>
      <head>
        {/* App pages only: put the dashboard palette and the saved light/dark choice on <html> before first paint (no flash). */}
        <script dangerouslySetInnerHTML={{ __html: themeBootScript(APP_PREFIXES) }} />
      </head>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">Skip to content</a>
        <AuthProvider><ToastProvider><div id="main">{children}</div></ToastProvider></AuthProvider>
      </body>
    </html>
  );
}
