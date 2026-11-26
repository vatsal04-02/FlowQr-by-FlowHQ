# AI benchmark results (2026-11-14/15)

What was run: the production generation code (and the pre-upgrade code kept in `backend/app/ai_eval/legacy.py`) on 56 invented benchmark cases (7 kinds of business; replies, posts, descriptions and customer review drafts; English, Hindi, Hinglish), against the real Gemini API with the key in `.env`. Scoring is deterministic (`backend/app/ai_eval/metrics.py`); no model judged another model. Prices are Google's published paid-tier prices read on 2026-11-15 (https://ai.google.dev/gemini-api/docs/pricing, redirected to aistudio.google.com/docs/pricing): `gemini-3.5-flash-lite` $0.30 in / $2.50 out per 1M tokens; `gemini-3.1-flash-lite` $0.25 / $1.50; `gemini-3.8-flash` $0.75 / $3.75 until 31 Dec 2026, then $1.50 / $7.50. No verified price was found for `gemini-3.5-flash`, so its cost is not computed.

"clean" = zero unsupported claims, no retry-worthy quality issue, right language, compliant. It is a **proxy for "usable as is"**, not the owner Acceptance Rate (that needs real owners; see AI_INTELLIGENCE.md).

## 1. Old prompts vs new prompts, same model (`gemini-3.5-flash-lite`, your configured model) - run A

Both variants rescored with the same final metric code. n = 28 replies, 14 posts, 7 descriptions per variant.

| Task | Variant | clean | composite | factual | relevance | repetition | language | helpful | cost / output | model calls / output |
|---|---|---|---|---|---|---|---|---|---|---|
| Replies | old | 82% | 0.92 | 1.00 | 0.70 | 0.79 | 1.00 | 1.00 | $0.00030 | 1.00 |
| Replies | new | 96% | 0.93 | 1.00 | 0.66 | 0.84 | 1.00 | 1.00 | $0.00043 | 1.11 |
| Posts | old | 79% | 0.94 | 0.98 | 0.93 | 0.80 | 1.00 | 0.71 | $0.00034 | 1.00 |
| Posts | new | 86% | 0.97 | 0.98 | 1.00 | 0.94 | 1.00 | 0.93 | $0.00061 | 1.14 |
| Descriptions | old | 14% | 0.91 | 0.95 | 1.00 | 0.90 | **0.43** | 1.00 | $0.00041 | 1.00 |
| Descriptions | new | 100% | 0.97 | 1.00 | 0.86 | 0.98 | **1.00** | 0.93 | $0.00067 | 1.29 |

## 2. Final prompts, confirmation run - run C

Run after the last prompt wording change (one security-marker sentence), also the only run with valid latency (run A paced its calls, so its latency column is not meaningful).

| Model | Task | n | clean | composite | relevance | repetition | language | helpful | p50 latency | cost / output | cost / clean output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite (current) | Replies | 28 | 100% | 0.95 | 0.75 | 0.90 | 1.00 | 1.00 | 1.1 s | $0.00041 | $0.00041 |
| gemini-3.5-flash-lite | Posts | 14 | 100% | 0.99 | 1.00 | 0.95 | 1.00 | 0.86 | 1.4 s | $0.00062 | $0.00062 |
| gemini-3.5-flash-lite | Descriptions | 7 | 100% | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.1 s | $0.00060 | $0.00060 |
| gemini-3.1-flash-lite | Replies | 28 | 96% | 0.92 | 0.66 | 0.71 | 1.00 | 0.96 | 1.9 s | $0.00034 | $0.00036 |
| gemini-3.1-flash-lite | Posts | 14 | 79% | 0.98 | 1.00 | 0.96 | 1.00 | 1.00 | 1.8 s | $0.00041 | $0.00052 |
| gemini-3.1-flash-lite | Descriptions | 7 | 71% | 0.94 | 0.86 | 0.98 | **0.71** | 0.93 | 2.6 s | $0.00053 | $0.00074 |

## 3. What this shows, and what it does not

- **Descriptions: a real, large improvement.** The old prompt never stated the business's language, so Hindi and Hinglish businesses received English descriptions in 4 of 7 cases. That is fixed (language 0.43 to 1.00) and is not a metric artifact.
- **Replies: fewer failures, not better writing that the metric can see.** Clean 82% to 96-100%, less repetition (0.79 to 0.84-0.90), fewer stock phrases. The composite barely moves (0.92 to 0.93-0.95). Relevance (does the reply pick up a detail of the review) did **not** improve (0.70 to 0.66-0.75): the new prompt asks the model to paraphrase rather than echo the review, which a literal-word metric cannot reward. I read about a dozen of each variant's outputs by hand and the new replies looked more specific and less templated, but that is a small, informal reading, not a measurement.
- **Posts: more varied and more useful, same safety.** Repetition 0.80 to 0.94, helpfulness 0.71 to 0.93, clean 79% to 86-100%. Factual accuracy was already high and stayed so.
- **Run-to-run noise is real.** The same new code scored 86% clean on posts in run A and 100% in run C (n = 14, temperature 0.8, plus one wording change). Differences of about 10-15 points at these sample sizes are within noise. Descriptions (n = 7) are anecdotal.
- **Cost.** New prompts send more context: +37% (replies), +82% (posts), +46% (descriptions) per output on the same model, because input tokens roughly doubled. All are fractions of a cent: about $0.0004-0.0006 per output. Cost per *clean* output is roughly flat for replies and up for posts. This is the price of grounding in real reviews, posts and profile data; it is not free.
- **Model choice: no change recommended.** `gemini-3.5-flash-lite` (your configured model) is faster (1.1-1.4 s vs 1.8-2.6 s p50) and scored equal or better than `gemini-3.1-flash-lite` on every task; the cheaper model wrote 2 of 7 Hinglish/Hindi descriptions in the wrong language and had a compliance miss in posts. Its saving is about $0.0001 per output.
- **`gemini-3.5-flash` and `gemini-3.8-flash` could not be benchmarked.** Both hit this key's daily quota during run B (`quota_exhausted`), after earlier calls to `gemini-3.8-flash` returned HTTP 400 (cause unconfirmed; the quota error masked it, possibly the `thinkingLevel: minimal` setting). Their rows in run B are failures of the key, not of the models, and are excluded from every conclusion. The benchmark should be re-run when quota resets or on a paid key; the command is in `docs/AI_INTELLIGENCE.md`.
- **Hindi/Hinglish.** Both flash-lite models produced correct-script, natural-reading replies and posts in every Hindi and Hinglish case except the three description failures above. Whether native speakers find them natural is **not measured**: no one has rated them.
- **Customer review drafts** (unchanged by this work) were scored once under the new metric: 6 of 7 produced a draft in run A (the seventh was refused by the assistant's own fact checks, as designed); the assistant takes about 2.7 model calls per draft on this model because its own rules retry, which is where most of its cost goes (about $0.0018 per draft).

## 4. Metric corrections (read this before trusting any number)

The first live run exposed bugs in my scoring, found by reading the outputs, not by the numbers alone. Corrected, and **all runs rescored with the same corrected code** (the original scoring is kept in `run-A-first-scoring-metric-v1.json` for transparency):

1. Verified offers' prices and end dates were not counted as known facts, so a correct "valid until 2027-06-30" was flagged as an invented number.
2. Times like "9:00" were flagged as a new number "00".
3. Hinglish pronouns at the start of a sentence ("Hum", "Aapka") were flagged as invented names; Hindi numerals were counted as numbers.
4. A positive reply was credited as helpful only if it contained "thank"; "It is wonderful to hear...", "It means a lot..." and "बहुत अच्छा लगा" scored 0. The new prompt (rightly) discourages starting with "Thank you for your feedback", so this penalised the improvement.
5. "waiting" did not match "waited" when checking whether a reply picked up a detail of the review.
6. An ISO date was read as a phone number; Hindi text was judged against English service names.

Corrections 4 and 5 and part of 6 favour the new prompts; I applied them because the flagged outputs were plainly fine. The honest consequence: the metric was tuned once after seeing real outputs, so it is less independent than a metric fixed beforehand. The regression baselines are recorded under metric version 2 and the human rating sheets (`*.rating-sheet.csv`) exist so a person can check the scoring itself.

## 4b. Reply precision change (2026-11-26): 5-case live check only, full benchmark still owed

**Live check (5 cases, gemini-3.5-flash-lite, `--limit 5`: physio 1-4 and dental 1, so English, an English complaint, two Hinglish and one Hindi):** 5 of 5 clean, 1 model call each (no retries), composite 0.98, no unsupported claims, about $0.00054 per reply. The invented benchmark text only was sent; the terms flag was set for that one process (`GEMINI_DATA_TERMS_VERIFIED=true`), not in any file or on the server. Five cases cannot be compared with run C (28 cases) and show nothing about native-speaker naturalness: this is a smoke test, not a measured improvement. The paragraph below describes the change; the full 28-case run and a native-speaker rating are still owed.

The reply prompt and checks were tightened (precision rules and one worked example per language and kind of review in `services/ai/craft.py`, stricter Hindi/Hinglish/English rules, a wider Hinglish detector, and new checks in `quality.assess_reply`: invented numbers and names, tum/tu, Sir/Madam, cut-off text, placeholders, stiff English, repeated words, wrong mood). The four reply prompt hashes in `tests/ai_baselines/prompt_hashes.json` were re-recorded for it. **The live benchmark has not been run on the new prompts** (no `GEMINI_API_KEY` where the change was made), so there is no measured claim that replies improved. What was checked without a model: the 28 recorded real replies still score at or above their floors, and none of them trips a new retry-level check (one uses "I", which is only a note). Before relying on the change, run `python -m app.cli ai-eval --models gemini-3.5-flash-lite --variants current --tasks reply ...`, compare with run C above, and have a native Hindi/Hinglish speaker rate the Hindi and Hinglish cases in the rating sheet.

## 5. Files

`run-A-old-vs-new-prompts.json` (full outputs and per-output metrics), `run-C-final-prompts-two-models.json`, `run-B-other-models-quota-blocked.json`, the two `.rating-sheet.csv` files (columns for a human reviewer: usable_as_is yes/no, score 1-5, notes). Re-run: `python -m app.cli ai-eval --models <m1,m2> --variants current --price <m>=<in>,<out> --rpm 15`; rescore a saved run with `ai-eval-rescore`; compare with a human's ratings with `ai-eval-human`.
