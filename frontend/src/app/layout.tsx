import type { Metadata, Viewport } from "next";
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
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#F4F2EE" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* App pages only: put the dashboard palette and the saved light/dark choice on <html> before first paint (no flash). */}
        <script dangerouslySetInnerHTML={{ __html: themeBootScript(APP_PREFIXES) }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Inter:wght@400;500;600&family=Geist+Mono:wght@400..600&family=Noto+Sans+Devanagari:wght@400;600&display=swap" />
      </head>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">Skip to content</a>
        <AuthProvider><ToastProvider><div id="main">{children}</div></ToastProvider></AuthProvider>
      </body>
    </html>
  );
}
