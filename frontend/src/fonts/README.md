# Self-hosted fonts

These five files are served from FlowQR's own domain (loaded with `next/font/local` in `src/app/layout.tsx`), so a visitor's browser never contacts Google's font servers, and the
build does not either. (They were first loaded with `next/font/google`, which downloads at build time; on Vercel that failed unpredictably because Google sometimes answers with
extension-less font URLs that Next 15.5's loader cannot read.)

| File | Family | Axis | Subset | Licence |
|---|---|---|---|---|
| geist-latin.woff2 | Geist | variable 100-900 | Latin | SIL OFL 1.1 |
| geist-mono-latin.woff2 | Geist Mono | variable 100-900 | Latin | SIL OFL 1.1 |
| inter-latin.woff2 | Inter | variable 100-900 | Latin | SIL OFL 1.1 |
| plus-jakarta-sans-700-latin.woff2 | Plus Jakarta Sans | 700 (the wordmark only) | Latin | SIL OFL 1.1 |
| plus-jakarta-sans-latin-wght.woff2 | Plus Jakarta Sans | variable 200-800 | Latin | SIL OFL 1.1 |
| plus-jakarta-sans-latin-ext-wght.woff2 | Plus Jakarta Sans | variable 200-800 | Latin Extended (holds the rupee sign, U+20B9) | SIL OFL 1.1 |
| noto-sans-devanagari.woff2 | Noto Sans Devanagari | variable 100-900 | Devanagari (U+0900-097F and a few related) | SIL OFL 1.1 |

Characters outside these subsets (for example Latin Extended letters) use the system font. To change a font, replace the file and keep the `variable` name in `layout.tsx`.
