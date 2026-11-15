"use client";
import { useEffect } from "react";

/** Something broke while drawing this page. The data is untouched; offer a retry and a way out. Technical detail goes to the console only. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error("FlowQR page error", error.digest ?? "", error.message); }, [error]);
  return (
    <main className="grid min-h-[60dvh] place-items-center px-5 py-10 text-[#0D0A10] dark:text-[#F2EFF5]">
      <div role="alert" className="w-full max-w-md rounded-[28px] bg-white p-8 text-center shadow-[0_1px_2px_rgba(19,16,20,.04),0_12px_32px_-14px_rgba(19,16,20,.10)] dark:bg-[#17141A]">
        <h1 className="text-[28px] font-semibold leading-8 tracking-[-.02em]">Something went wrong</h1>
        <p className="mt-3 text-[#6B676D] dark:text-[#B3AFB8]">This page couldn&rsquo;t be shown. Nothing was lost or changed. Try again, and if it keeps happening, tell us{error.digest ? ` the code ${error.digest}` : ""}.</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button type="button" onClick={reset} className="inline-flex min-h-11 items-center rounded-full bg-[#131014] px-6 text-sm font-semibold text-white dark:bg-[#F2EFF5] dark:text-[#131014]">Try again</button>
          <a href="/overview" className="inline-flex min-h-11 items-center rounded-full bg-[#F3F0F4] px-6 text-sm font-semibold text-[#0D0A10] dark:bg-[#1F1B24] dark:text-[#F2EFF5]">Go to dashboard</a>
        </div>
      </div>
    </main>
  );
}
