"use client";

/** Last resort: the root layout itself failed. Has to bring its own <html> and inline styles. */
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#F2EFF3", color: "#0D0A10", display: "grid", minHeight: "100dvh", placeItems: "center", padding: 20 }}>
        <div role="alert" style={{ maxWidth: 420, background: "#fff", borderRadius: 28, padding: 32, textAlign: "center" }}>
          <h1 style={{ fontSize: 26, margin: 0 }}>FlowQR hit a problem</h1>
          <p style={{ color: "#6B676D" }}>Nothing was lost. Please try again in a moment.</p>
          <button type="button" onClick={reset} style={{ minHeight: 44, padding: "0 24px", borderRadius: 999, border: 0, background: "#131014", color: "#fff", fontWeight: 600, cursor: "pointer" }}>Try again</button>
        </div>
      </body>
    </html>
  );
}
