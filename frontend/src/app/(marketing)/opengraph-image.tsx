import { ImageResponse } from "next/og";

// One social card for the marketing pages: the FlowQR name and promise on the brand ground. No numbers, no Google marks.
export const alt = "FlowQR by FlowHQ: your Google Business Profile, managed by AI.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OG() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: 80, background: "#F7F5F2", color: "#0B0F2E", fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 36, fontWeight: 600 }}>
          <div style={{ width: 56, height: 56, borderRadius: 16, background: "#FE6A05" }} />FlowQR
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 84, fontWeight: 500, lineHeight: 1, letterSpacing: -3 }}>
          <span>Your Google Business Profile,</span><span style={{ color: "#E05A00" }}>managed by AI.</span>
        </div>
        <div style={{ fontSize: 28, color: "#6B6F82" }}>Google Business Profile, reviews and QR/NFC review cards for local businesses. A FlowHQ product.</div>
      </div>
    ),
    size,
  );
}
