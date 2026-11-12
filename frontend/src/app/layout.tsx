import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: { default: "FlowQR by FlowHQ - Reviews, replies and QR/NFC cards", template: "%s | FlowQR" },
  description: "AI-powered reputation and review management for local businesses. Unique QR/NFC review cards, AI-assisted writing and human-approved replies.",
  robots: { index: true, follow: true },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#F4F2EE" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..600&family=Noto+Sans+Devanagari:wght@400;600&display=swap" />
      </head>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">Skip to content</a>
        <AuthProvider><ToastProvider><div id="main">{children}</div></ToastProvider></AuthProvider>
      </body>
    </html>
  );
}
