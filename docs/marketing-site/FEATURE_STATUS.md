# Feature status (what the marketing site may claim)

Checked against the code on 13 Nov 2026. "Built" means the code exists and is covered by tests; Google features were tested with mocked Google plus one live read-only check (writes untested live). Anything not Built is marked **Coming soon** on the site.

| Feature | Status | On the site |
|---|---|---|
| Google review sync, reviews inbox, filters | Built (needs the business's authorised Google connection) | Shown |
| AI reply drafts + owner approval, "replied" only after Google confirms | Built | Shown |
| Google Posts (draft, approve, schedule) | Built | Shown |
| Photos per location | Built | Shown |
| Performance insights from Google | Built | Shown |
| AI Review Assistant (stars, topics, draft from the customer's answers, edit, copy to Google) | Built | Shown |
| English, Hindi, Hinglish on the review page | Built | Shown |
| Voice input on the review page | **Not built** | Coming soon chip |
| QR + NFC cards, permanent link, pre-printed stock, scan-to-activate, reassign, pause/retire | Built (NFC not tested on physical tags) | Shown, as "tap or scan" |
| Separate QR / NFC analytics | Built | Shown |
| Branded poster PNG/SVG/PDF | Built | Shown |
| AI Growth Agent: daily plan, recommendations, approvals, activity log, business knowledge, automations | Built | Shown |
| Local rank tracking (position among Google Maps results around the location for words the owner picks) and Google's own search terms for the profile, plus plain-language profile fixes | Built (covered by tests; positions are measured, never guaranteed, and are not what every searcher sees) | Shown on the home strip as "Local rankings" and "Local SEO" |
| Multi-location, team access per location | Built | Shown |
| Book-a-demo leads (`POST /api/v1/public/leads`) | Built (this change) | Demo form |
| WhatsApp inbox, leads, appointments, follow-ups, campaigns | **Not built** ("Setup required" screens only) | Coming soon, FAQ only |
| Social (Facebook/Instagram) publishing | **Not built** | Not claimed |
| Card ordering with online payment | Partial: card price is a config value; ordering flag exists | "Contact us for pricing" unless the price is configured |
