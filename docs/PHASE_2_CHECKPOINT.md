# Phase 2 checkpoint (2026-11-15)

**What this is.** Phases 0, 1, 1.5 and 2 were built without ever being committed: at the start of this pass `git status` showed **393 entries** (138 modified, 199 untracked, 16 renamed, 32 renamed and modified, 7 deleted, 1 renamed and deleted) on top of the last commit `1118cd7`. This file records how they were classified and checkpointed. Nothing was discarded, rewritten, force-pushed, merged or pushed.

## Branch and safety

* Branch: `phase-2/commercial-readiness` (a dedicated development branch; the main branch for pull requests is `claude/admiring-edison-e9a7s3`).
* `git reset` (mixed) was used once, to unstage the earlier partial staging; it does not touch the working tree.
* No `--force`, no history rewrite, no merge, no push. The remote branch does not have these commits. Push with `git push -u origin phase-2/commercial-readiness` when you want CI to run.
* Tag `phase-2-checkpoint` marks the first checkpoint tip (`481f77c`, local only).
* The running development stack was not touched.

## Classification of the 393 entries

| Class | What | Commit |
|---|---|---|
| Database and configuration core | migrations 0018 to 0030 (the first untracked ones were from earlier phases), SQLAlchemy models, schemas, `core/config.py`, requirements | `0300636` (36 files) |
| Backend behaviour | services, API routers, workers, CLI and operator tools, the AI quality evaluation harness, poster assets, `release_gates.json` | `432d7f9` (89 files) |
| Backend tests | Phase 0 to 2 test files and the AI baselines. Google, Places, payments and AI are test doubles | `fdd7b1f` (47 files) |
| Marketing site | public landing, pricing, legal pages, brand assets, content, marketing screenshots, landing browser test | `61c09d3` (105 files) |
| Product application | grouped navigation (Overview, GBP Manager, AI, Settings), Growth Agent, Autonomy control centre, geo-grid map, plans and admin pages; the many `renamed` entries are route moves | `126ab0a` (165 files) |
| Browser tests | the new or changed browser (E2E) test files | `13b802f` (9 files) |
| Documentation | audits, runbooks, deployment, recovery, environment variables, Phase 2 report | `c4c1b85` (29 files) |
| Configuration and CI | compose files, `.env.example`, deploy scripts, `.github/workflows/ci.yml` (never run), `.gitignore`, README | `481f77c` |
| This pass's work (security fixes, work queue, onboarding step, staging fixes, docs, evidence, tests) | see section "After the checkpoint" | listed below |

The eight commits group the tree by area. **They are a checkpoint, not a history of how the code evolved**: only the tip of the branch was ever tested as a whole, so an intermediate commit is not guaranteed to build or pass on its own.

## Things that were looked for and what was found

| Looked for | Result |
|---|---|
| Real secrets in the files to be committed | none. The only key-shaped strings are test fixtures (`rzp_test_abcdefghij`, `rzp_live_abcdefghij` in `test_config_guard.py`) that exist to test the config guard |
| Secrets anywhere in the **full history** (27 commits, all branches): Google API keys, OAuth client secrets, Razorpay keys, private keys, GitHub and Slack tokens | none |
| Environment files tracked | only `.env.example` |
| Ignored files that hold secrets or data | `.env`, `.env.bak-before-mailsink` and `backups/` (database backups, one encrypted, one not): all ignored by `.gitignore`, none committed. `backups/` also holds this pass's read-only dump of the development database; delete it when it is no longer needed |
| Generated or temporary files | `frontend/.next/`, `node_modules/`, `__pycache__/`, `tsconfig.tsbuildinfo` ignored. A stray file named `nul` (a Windows redirect artefact containing a landing-page tool's JSON) is now ignored (`/nul`) and was not committed |
| Large files | the largest committed binaries are marketing screenshots and the poster template PNG (about 1 MB each); `frontend/public` 2.9 MB and `docs/marketing-site` 9.9 MB in total. Acceptable for now; move the screenshots out of the repository if it grows |
| Unrelated changes | the marketing-site rework, the navigation restructure and Phases 0 to 1.5 are unrelated to commercial readiness in intent but are part of the same working tree; they were committed in their own commits rather than dropped |
| Exposed credentials outside git | one: the Places API key pasted into a chat earlier is in the ignored `.env`. **Rotate it** (`docs/SECURITY_AUDIT.md` finding 7) |

## After the checkpoint

Commits made in this pass after `481f77c` are listed by `git log --oneline 481f77c..HEAD`. They contain: the security fixes and tests (`docs/PHASE_2_SECURITY_AUDIT.md`), the admin Work queue, spending-ceiling and emergency-stop screens, the wizard's last step, the Caddy, build and robots fixes found on staging, the configurable keyword limit and Compose pass-through of the Places controls, provider-neutral payment wording, the staging scripts, and the documents and evidence in `docs/`.

## To review before merging

1. `docs/PHASE_2_FINAL_ACCEPTANCE.md` (what is and is not proven) and `docs/PHASE_2_SECURITY_AUDIT.md`.
2. `git diff 1118cd7 481f77c --stat` is large; read it by commit.
3. The privacy page now says payments are "handled by a licensed payment provider (not yet switched on)" instead of naming Razorpay: needs legal review.
