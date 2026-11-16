import Link from "next/link";

/** The page doesn't exist. Plain words, one way back. (Uses its own colours: this page can be reached from marketing, the app or a stale link.) */
export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center bg-[#F2EFF3] px-5 py-10 text-[#0D0A10]">
      <div className="w-full max-w-md rounded-[28px] bg-white p-8 text-center shadow-[0_1px_2px_rgba(19,16,20,.04),0_12px_32px_-14px_rgba(19,16,20,.10)]">
        <p className="text-sm font-medium text-[#6B676D]">Error 404</p>
        <h1 className="mt-2 text-[32px] font-semibold leading-9 tracking-[-.02em]">This page doesn&rsquo;t exist</h1>
        <p className="mt-3 text-[#6B676D]">The link may be old or mistyped. Your data is safe, and your cards and QR codes are not affected.</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Link href="/overview" className="inline-flex min-h-11 items-center rounded-full bg-[#131014] px-6 text-sm font-semibold text-white">Go to your dashboard</Link>
          <Link href="/" className="inline-flex min-h-11 items-center rounded-full bg-[#F3F0F4] px-6 text-sm font-semibold">Home</Link>
        </div>
      </div>
    </main>
  );
}
