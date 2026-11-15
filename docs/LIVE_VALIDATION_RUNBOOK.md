# Live validation runbook: proving the autonomous profile engine against real Google

**Purpose.** Everything FlowQR's autonomy engine does has been tested against test doubles. This runbook is how to find out, safely and in order, whether the real Google APIs behave the way the engine assumes. **Until a person has run it on an authorised test profile and the evidence log in section 9 is filled in, FlowQR must not be described as "autonomous" or "production-ready" for Google writes.**

## 0. What counts as evidence (read this first)

| Tag | Meaning | Proves |
|---|---|---|
| **[MOCKED]** | An automated test against a test double of Google or Places | FlowQR's own logic: policy, approvals, claim, retries, read-back comparison, history, cost limits. **Nothing about Google.** |
| **[DB]** | Real PostgreSQL, real migrations, real row-level security and triggers (also inside the tests) | That the database enforces what the code relies on |
| **[LIVE]** | A real call to Google, recorded with the date, the profile (by name) and the report file | That Google really did what the engine assumes |

The reports written by the tools below say `"mode": "mocked"` or `"mode": "live"`. **Only `"live"` is evidence about Google**, and only for the steps marked `verified_by_read_back: true`. A mocked run can never print `live`.

State on the day this was written: **no [LIVE] write of any kind has been run.** One read-only live check exists (`docs/LAUNCH_REPORT.md`).

**Status on 2026-11-15: BLOCKED — external dependency.** No authorised test Business Profile has been named, so this runbook has not been started and its evidence log (section 9) is empty. Everything that can be prepared is prepared (tool, dry run, authorisation steps, stop conditions, tests with doubles). **No Google behaviour listed in `docs/PHASE_2_FINAL_ACCEPTANCE.md` as unproven becomes proven until a person runs this and fills in section 9.** Keep Admin > Work queue open while running it: failed, blocked or invalidated changes and waiting approvals show there across the platform.

## 1. Hard rules

1. **Never run any step below on a customer's profile or on a profile you have not been told is a test profile.** "It is only a description with a marker" is not authorisation: customers see it, search sees it, and some changes (a post, a reply) are public the moment they exist.
2. A live write needs three deliberate acts by a person: `export FLOWQR_LIVE_WRITE_AUTHORIZED=<locations/N>`, `--confirm-location <locations/N>`, and `--confirm-title "<the profile's real title as Google returns it>"`. The tool prints the title before it sends anything. Dry run is the default.
3. **Stop at the first surprise.** Any step that FAILs, any read-back that does not match, any unexplained Google error: stop, record it, restore by hand if the tool says so, and do not continue to the next stage.
4. Run only inside a time window when someone can check the profile in Google Business Profile by hand afterwards.
5. Keep the Places and Gemini budgets set (section 2) so a mistake cannot become a bill.

## 2. Preconditions (tick each before stage 1)

- [ ] A **test Business Profile** that you own, that no real customer depends on, with a real description already set (the tests restore the original text, so it must not be empty). Write its name here: __________________
- [ ] It is connected in FlowQR (a test business created for this purpose, **not** a customer's) and `api_access` shows `approved` on the connection.
- [ ] The test business has at least one review you are willing to reply to (stage 1 reply step only).
- [ ] `docker compose exec api python -m app.cli preflight` passes; a recent backup exists.
- [ ] `RANK_PROVIDER=google_places` and a key with Places API (New) enabled (only for stage 5), with `RANK_PLATFORM_MONTHLY_CAP` and `RANK_COST_PER_CALL_USD` set.
- [ ] `AI_PLATFORM_HARD_LIMIT_USD`, `AI_TENANT_MONTHLY_BUDGET_USD` and the AI prices are set (otherwise budget stops are not enforced).
- [ ] The stack runs the code being validated: images rebuilt and migrations `0026`, `0027`, `0028` applied.
- [ ] You know how to switch everything off: owner button **Emergency stop** (Autonomy page), or `AUTONOMY_EMERGENCY_STOP=true`, or the platform admin `PUT /admin/autonomy/emergency-stop`.

## 3. Stage 1: what does Google itself accept? (raw API)

Dry run first; it prints exactly what would be sent.

```
docker compose exec api python -m app.cli google-write-test --connection <connection-id> --location locations/<N> --post --photo --profile
# the live run (only after the preconditions, on the test profile):
export FLOWQR_LIVE_WRITE_AUTHORIZED=locations/<N>
docker compose exec -e FLOWQR_LIVE_WRITE_AUTHORIZED api python -m app.cli google-write-test --connection <id> --location locations/<N> \
    --post --photo --profile --reply-review <review-id> --reply-text "<text>" --execute --confirm-location locations/<N> --confirm-title "<exact title>" --report /tmp/stage1.json
```

Each step creates, **reads back**, deletes, and reads back again. Pass criteria: every step `PASS` and `verified_by_read_back: true`; the profile description is back to the original (check it by eye in Google). Record: how long Google took before the read-back matched (the tool waits 2 seconds; if a step needs longer, the engine's read-back needs a retry window, which is a finding, not a pass).

## 4. Stage 2: does FlowQR's engine work through the real API? (governed path)

This is the path owners and the agent use: policy, the person's authorisation, claim, write, an independent read, tamper-evident history. It is the first stage that can support the sentence "an authorised change was executed and verified".

```
docker compose exec api python -m app.cli autonomy-live-test --connection <id> --location locations/<N> --profile --post       # dry run
docker compose exec -e FLOWQR_LIVE_WRITE_AUTHORIZED api python -m app.cli autonomy-live-test --connection <id> --location locations/<N> --profile --post \
    --execute --confirm-location locations/<N> --confirm-title "<exact title>" --report /tmp/stage2.json
```

Pass criteria, all of them: four steps `PASS` (change, restore, publish, delete); each step's action is `executed` with a matching read-back; `history chain intact` for each; the original description is restored (by eye); the test post is gone (by eye). Then open **AI > Autonomy > Activity** and confirm the actions and their records read sensibly.

## 5. Stage 3: the field-by-field behaviours the engine assumes

Do these by hand in the test business (Business info and Opening hours pages, then read the profile in Google), **one at a time**, recording the result each time:

| Check | What to do | Expect | Why it matters |
|---|---|---|---|
| Hours | change one day's hours | read-back equals what was sent; format round-trips | the engine compares canonical hours |
| Secondary category | add one | appears; nothing else changed | Level 2 type |
| Phone / website (existing) | change each | Level 3: refused for an admin, allowed for the owner; read-back matches after Google's normalisation | Google may reformat; if it does, the comparison must be taught |
| Main category | change then change back | owner only; Google may put the profile **under review** | a review state is not a failure and not a success; record exactly what the read shows |
| Description with a phone number or link | try | Google rejects or strips it; engine reports failure, not success | the policy blocks it first; confirm Google agrees |
| Eventual consistency | note delay between write and a read that matches | record seconds | tune the read-back |

## 6. Stage 4: autonomy on the test business

Only after stages 1 to 3 passed. On the **test** business, as its owner:

1. Add a knowledge-base description and services (Business brain). Turn autonomy **on** (Autonomy page). Leave every Level 2 type on "Ask me".
2. Wait for or trigger a scan (`POST /agent/actions/scan`). Expect: a description proposal authorised by Level 1 policy, executed, **read back**, visible in Activity as "Confirmed on Google".
3. Set **Regular opening hours** to "Do it", ask for an hours change: expect it to run on its own and be read back; set it back to "Ask me": expect it to wait for you.
4. Ask for a main-category change: expect it to wait for the owner, **never** run on its own, even with every switch on.
5. Press **Emergency stop** while something is waiting to run: expect it back in "Needs you", nothing sent. Resume.
6. Lower `AI_TENANT_MONTHLY_BUDGET_USD` for the test business to a tiny value: expect the scan to stop before any model call and say why.
7. Over 28 days: confirm the 7, 14 and 28 day ranking follow-ups appear on the action and are worded as observations, never causes.

## 7. Stage 5: the map (geo-grid)

On the test business with a tracked search term and `RANK_PROVIDER` set: create a 3 x 3 map, press **Scan now**, and record: the searches used against the allowance and the real Google bill line for them (this is how `RANK_COST_PER_CALL_USD` gets set honestly); whether the positions look plausible when you search the same phrase on your phone at one of the points; what happens when you scan twice (the second should show a change summary only if something moved by 3 or more positions).

## 8. Stop conditions and rollback

* **Stop** at any FAIL, any read-back mismatch, any Google policy warning on the test profile, or any sign that a step touched something other than the test profile.
* **Restore**: the tools restore their own changes and print "restore it by hand" if a restore does not stick. Compare against the original text you recorded in section 2.
* **Switch off**: Emergency stop (owner), `AUTONOMY_EMERGENCY_STOP=true` (platform), then `docker compose restart worker beat`.
* **Clean up**: delete the test post and photo in Google if a tool reported it could not; remove test replies; keep the report files.

## 9. Evidence log (fill this in; this is the acceptance record)

| Stage | Date | Run by | Profile (name) | Report file | Result | Notes |
|---|---|---|---|---|---|---|
| 1 raw API: post | | | | | | |
| 1 raw API: photo | | | | | | |
| 1 raw API: profile description | | | | | | |
| 1 raw API: reply | | | | | | |
| 2 governed: profile change + restore | | | | | | |
| 2 governed: post + delete | | | | | | |
| 3 hours / categories / phone / website | | | | | | |
| 4 Level 1 autonomous change, verified | | | | | | |
| 4 Level 2 on a standing authorisation | | | | | | |
| 4 Level 3 never autonomous | | | | | | |
| 4 Emergency stop | | | | | | |
| 4 28-day follow-ups | | | | | | |
| 5 map scan and cost | | | | | | |

**FlowQR may be called production-ready for autonomous Google writes only when:** stages 1, 2 and 4 are complete with `live` reports; stage 3 has no unexplained difference between what was sent and what Google read back; every Level 2 type that will be offered to owners has its own successful live read-back; and the open items in `docs/AGENT_AUDIT.md` ("Remaining blockers") are closed or knowingly accepted in writing.

## 10. What the automated tests already cover (so you do not repeat it live)

All of this is [MOCKED] and [DB], in `backend/tests/test_phase1_*.py` and `test_phase15_*.py`: classification of every action type; approvals, expiry, tampering, changed Google values; claim, retries, lost responses, concurrency, duplicates; read-back mismatches; emergency stop, daily limits, budgets, automatic suspension; history integrity and erasure; the ranking feedback loop; geo-grid cost limits and change detection; governed publishing of posts, photos and replies. They show the engine decides and records correctly **given** what a test double returns. They are the reason the live stages can be short.
