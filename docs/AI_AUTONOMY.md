# AI Growth Agent: autonomy matrix

One agent, one business knowledge base ("Business Brain"), six capabilities. They are not six tools: every capability runs through the same workflow and the same approval queue.

```
Data collection → Analysis → Recommendation → AI preparation → Approval → Publishing → Verification → Activity report
   agent            agent        agent            agent          OWNER       system        system          agent
```

The same matrix is served by `GET /api/v1/agent/autonomy` (with live counts for the signed-in business) and shown in the app under **AI › Automations**. It is defined in `backend/app/services/agent/autonomy.py` and checked by `backend/tests/test_autonomy.py`.

## The rule

**Anything the public can see needs a person's approval. This cannot be switched off.** `auto_publish` is always `false`; sending it in a settings request is ignored (tested). Configurable automation is limited to *preparation*: a daily plan, a daily post draft, reply drafts. These are safe by construction because a draft touches nothing outside FlowQR.

I did not add "auto-publish 5-star replies" or similar. It is technically possible and would be policy-compliant for some businesses, but a wrongly worded public reply cannot be recalled, and the value is small next to the risk. It can be added later as an explicit, per-business, off-by-default setting.

## Matrix

| Capability | Does by itself | Needs the owner/admin | How a result is verified | Never |
|---|---|---|---|---|
| **SEO profile optimization** | Reads the live profile; reads Google's own search-term report; scores gaps (description, categories, services, hours); drafts a better description from the Business Brain, checked against approved/prohibited claims | Writing any change to the live profile | Profile is re-read from Google after a change | Invent services, prices, awards or health claims; stuff keywords; change the profile unapproved |
| **Review growth** | Watches review volume and rating; tracks QR/NFC scans and campaign funnels; writes neutral request wording; recommends card placement and campaigns | Creating/changing a campaign or a card's destination | Scans and Google-link clicks are counted from real events; reviews appear only when Google returns them | Write or fake reviews; filter negatives (everyone gets the same Google link); offer rewards for ratings |
| **AI review replies** | Syncs reviews every 30 min; drafts a personal reply from rating, text and Business Brain (if auto-drafting is on); flags health/legal/abuse for a human; retries a failed approved reply for safe reasons | Publishing **every** reply, 5-star included | Counts as published only when Google returns it; a reply Google rejects is shown as rejected, with its policy reason | Publish unapproved; promise, give medical advice or invent facts |
| **Daily Google Posts** | Chooses a topic from offers, season and search terms; drafts one post per location per day (if on); checks claims; suggests a matching real photo (text only); keeps the calendar; retries failed publishes with back-off | Approving a post (this also schedules it) | Marked published only after Google returns the post ID; failures stay visible with the reason | Publish unapproved; invent offers, prices, dates |
| **Photo management** | Reads photos; finds missing categories and stale photos; recommends which genuine photos to add; validates, stores and organises uploads; runs scheduled uploads; re-checks Google until the photo is live | Every upload (you choose the photo; approving schedules it) | Re-read from Google; shown as "Google is processing it" until a live URL exists | Generate images of your premises, team or services; upload anything you did not supply |
| **Performance analytics** | Syncs views, calls, website clicks, directions, search terms; spots trends; builds dashboard and PDF/CSV reports; recommends actions | Nothing (read-only) | Every number comes from Google's Performance API; no data is shown as no data, never as zero | Estimate or fill in missing numbers |

## What runs without anyone clicking

| Job | When | Does |
|---|---|---|
| `sync_due_locations` | every 15 min (each location at its interval, default 30 min) | Pulls reviews |
| `daily_agent` | every 30 min, once per business per day after 6 am local | Refreshes Google data, builds the day's plan, drafts post/replies if enabled |
| `publish_due_posts`, `publish_due_media` | every minute | Sends **approved, due** items to Google; retries with back-off |
| `retry_failed_replies` | every 15 min | Retries approved replies that failed for a temporary reason |
| `check_ranks` | every 6 h | Re-measures local ranking for terms not checked in 7 days, within the monthly cap |
| `notify_by_email` | hourly | Emails the owner about new items waiting |
| `heartbeat`, `ops_watch` | every minute / 15 min | Proves the scheduler and worker run; emails FlowHQ admins when a platform check turns critical |

## What the owner can see

- **AI › Automations**: the matrix above with live counts per workflow stage (read, suggested, drafted, waiting for you, queued, live, confirmed by Google, failed).
- **AI › Approvals**: everything waiting, each with its safety findings.
- **AI › Activity**: every run, every status change (who did it: agent, user, system or Google), failed posts with the reason, queued items with their next retry, photos and whether Google shows them yet.

## Honest limits

- "Autonomous" here means the agent runs the whole loop except the public step. It does not publish on its own.
- Keyword research uses Google's own search-term report for the profile (real, but only terms Google reports for that profile) plus the Business Brain. There is no third-party keyword database; adding one would be a paid data source and a separate decision.
- Photo analysis is metadata-based (categories, ages, counts). It does not look at image content with AI, so it cannot judge photo quality.
- Live Google write behaviour (reply, post, photo, profile change) is covered by contract tests against Google's documented shapes, not yet by a live write. See `PRODUCTION_READINESS.md` for the controlled test.
