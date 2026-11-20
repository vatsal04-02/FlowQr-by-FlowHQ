# WhatsApp: things only a person can check with Meta

FlowQR's tests use a mock of Meta. They prove FlowQR behaves correctly **given** what Meta is assumed to do. They do **not** prove what Meta really does. The checks below need a real Meta account, real approvals and real traffic, so they are for a person to do and record. **None of them has been done. Nothing here is a result.** Fill in each "Result" box yourself, with the date, and do not tick a box you have not seen with your own eyes.

Until a check is done, keep the matching WhatsApp flags off (`WHATSAPP_SENDING_ENABLED`, `WHATSAPP_WEBHOOK_ENABLED`, `WHATSAPP_SIGNUP_ENABLED`) in production.

---

## 0. DO THIS FIRST: coexistence, echo events and the web inbox
**Why it matters:** this decides whether FlowQR's web inbox is an optional extra or the **only place** an owner can reply. Many owners already use the WhatsApp Business app on their phone. If Meta does not let the same number run on the phone app and the Cloud API at once (coexistence), then once a business is connected its owner can answer customers only in FlowQR's inbox. If it does, the inbox must also cope with messages typed on the phone: FlowQR reads Meta's "echo" events for those (`smb_message_echoes`), but **the shape of that event is written from documentation and has never been seen from real traffic**. The inbox, takeover and the assistant's "a person is already replying" rule all depend on it.

**Do:** with a real shop number that is already in use on the WhatsApp Business app, complete the connection. Then check, and record exactly what you see:
1. Is coexistence allowed for an Indian number, and what does Meta say or require?
2. Does the number keep working in the phone app after it is connected? What can and cannot be done there?
3. A customer writes: does it show in the phone app, in FlowQR's inbox, or both?
4. The owner replies **in the phone app**: does a webhook event reach FlowQR, with which field name and which fields (to, id, timestamp, type, text)? Does it appear in the inbox as "WhatsApp Business app"?
5. The owner replies **from FlowQR's inbox**: does it appear in the phone app?
6. Anything that stops working (broadcast lists, status, labels, chat history), and what Meta says about the 24-hour window when both are in use.

**Record:** what Meta allowed, the real echo event body (with the customer's number removed), and whether FlowQR's reading of it matched. If it did not match, `ingest_echo` in `services/whatsapp/conversations.py` and the echo part of `sanitize` in `webhook.py` must be corrected before conversations are switched on for anyone.

Result: ______________________  Date: ____________

(Item 3 below, "coexistence and the connection check", is about the connection check only; this item is about the inbox.)

---

## 1. Template approvals, and the category Meta gives each message
**Why it matters:** Meta decides the category (marketing, utility, authentication) of every template, not FlowQR. Marketing costs about seven times as much as utility in the starting prices (1.09 against 0.145 rupees), and a marketing message needs the customer's offers consent. FlowQR sends a message only to customers whose consent matches the category **Meta reports**, so a wrong assumption here changes both cost and who may be messaged.

**Do:** from a test business connected to a real test number, press "Prepare my messages" and also submit the offer message and the two sign-up confirmations (`include_offer`, `include_optin`). When Meta has answered, open **WhatsApp > Messages** (or call "Check with WhatsApp") and read the category Meta assigned to each of these fixed messages:
`flowqr_review_followup_en`, `flowqr_enquiry_ack_en`, `flowqr_enquiry_followup_en`, `flowqr_offer_en`, `flowqr_optin_confirm_en`, `flowqr_optin_confirm_offers_en`.

**Record:** for each message: approved or rejected, the category Meta assigned, the rejection reason if any, the date.

**If Meta's category differs from what FlowQR expects** (for example the review request comes back as marketing): that is handled safely already (it is then sent only to customers who agreed to offers), but the cost estimate and the set-up wording should be reviewed, and the wording of the message may need to change so Meta treats it as utility.

| Message | Result (approved / rejected) | Category Meta assigned | Date |
|---|---|---|---|
| review follow-up | | | |
| enquiry acknowledgement | | | |
| enquiry follow-up | | | |
| offer | | | |
| sign-up confirmation | | | |
| sign-up confirmation (offers) | | | |

## 2. Real India prices against the price table
**Why it matters:** every cost figure owners see is an estimate from the table at **WhatsApp prices** (admin). The starting values (India, from 1 Oct 2026: marketing 1.09, utility 0.145, authentication 0.145, service 0.145 with the first 1,000 service messages per number per month free) come from AiSensy's pricing page (the source note on each row says so), **not** from Meta's rate card. They are marked UNVERIFIED and owners see a warning until they are checked.

**Do:** open Meta's own published rate card for India (and the billing pages of the test account). For each of the four categories compare the rate, the effective date and any free allowance with the table. Where they match, use **Record a check** on that row (the screen keeps every check; it never edits the price). Where they differ, **Add a new price** with the correct number, date and source, then record a check on the new row. Also confirm how Meta bills in practice (per delivered message, and what happens to the free service allowance).

**Record:** the page you used, its date, and what you changed.

| Category | Matches the table? | Correct rate / date / free allowance if not | Checked by, date |
|---|---|---|---|
| marketing | | | |
| utility | | | |
| authentication | | | |
| service | | | |

## 3. WhatsApp Business app coexistence in India, and the connection check
**Why it matters:** many shops already use the WhatsApp Business app on their phone. Whether a number can be used with the Cloud API and the phone app at the same time ("coexistence") depends on Meta's rules for the country and account, and it may change how Meta reports the number's status. FlowQR's connection check decides whether sending is allowed; a number that looks fine to Meta but reads as unhealthy to FlowQR (or the reverse) would block sends or let them through wrongly.

**Do:** with a real shop number that is already on the WhatsApp Business app, complete the connection and watch what **WhatsApp > Connect** says, then use **Check connection**. Note whether Meta allows coexistence for an Indian number, what the shop can still do in the phone app, and what the connection status and quality rating show before and after.

**Record:** what Meta allowed, any warnings shown, the status FlowQR displayed, and whether the shop's phone app kept working.

Result: ______________________  Date: ____________

## 4. The embedded sign-up window, with real scripts and approval
**Why it matters:** connecting a business is done in Meta's own window loaded from Meta's script. That needs FlowQR to be an approved Meta Tech Provider with the sign-up configuration and the correct app domain settings. Tests use a stand-in. Only a real run proves the window opens, returns the right account and number, and that FlowQR's server checks (state, token exchange, account ownership) accept it.

**Do:** with the real app id and configuration id set in the server environment (never in the browser or the repository), run the whole connect flow with a real business login: open the window, pick or add a number, finish, and confirm the business shows as connected with the right number. Also try closing the window early and denying a permission, and confirm each gives a calm message and no half-connected state.

**Record:** whether the app is approved to onboard other businesses, any extra Meta review still needed, and any step that failed.

Result: ______________________  Date: ____________

## 5. Webhook signature checking and duplicate delivery, with real Meta traffic
**Why it matters:** FlowQR verifies Meta's signature on the raw request body and processes each delivery once. Tests sign messages with a test secret. Real Meta traffic proves the secret, the raw-body handling behind the real proxy and Caddy, and how often Meta really repeats a delivery.

**Do:** with the real app secret configured, send real messages to and from a test number (including a STOP reply, a sign-up message and a status update such as delivered and read). Confirm each arrives, is stored once, and that a wrong signature is refused. Look at the webhook events table for the same event arriving more than once and confirm nothing was counted or sent twice. Do this behind the production reverse proxy, not only locally.

**Record:** whether signatures verified on real traffic, any duplicate deliveries seen and how they were handled, and any events that did not arrive.

Result: ______________________  Date: ____________

---

## 6. A template whose link is not the business's own domain
**Why it matters:** with click tracking on (Pro), the review request carries a FlowQR link (`https://api.flowqr.site/api/v1/l/...`) in the message, not the business's own Google review link. Meta looks at the domains links point to. A link on a domain that is not the sender's own may be treated differently: the template could be refused, held back for longer, or given a different category (marketing instead of utility), which changes the price (about seven times) and who may be messaged.

**Do:** with a real test business on the Pro add-on, send for approval the review request exactly as FlowQR sends it with a tracked link (and, to compare, with the plain Google review link). Record: whether Meta approved each one, how long it took, which **category** Meta assigned to each, and any warning or rejection reason. Also check whether the template's sample link (an example in the template) needs to be on the same domain as the live links, and whether using a separate short domain (see "Moving tracked links to a separate domain later" in `docs/WHATSAPP_AUTOMATION.md`) changes the answer.

**Record:**

| Message | Approved or refused | Category Meta assigned | Time to decide | Notes or reason |
|---|---|---|---|---|
| review request, plain Google link | | | | |
| review request, FlowQR link on api.flowqr.site | | | | |
| review request, FlowQR link on a separate short domain (if tried) | | | | |

Result: ______________________  Date: ____________

---

## 7. Is a business-specific AI assistant allowed under Meta's AI provider terms?
**Why it matters:** the conversation assistant (Phase 8) answers customers with an AI model. Meta's terms for the WhatsApp Business Platform have rules about AI chatbots and about AI providers. FlowQR's design is a **business-specific** assistant: it answers only from the business's own information, refuses general-assistant requests, hands off to a person, and never behaves as a general-purpose chatbot. Whether that fits Meta's current wording is a question for Meta's current terms and, if unclear, Meta support, not for this code.

**Do:** read Meta's current WhatsApp Business Solution Terms and Business Messaging Policy, and ask Meta (support or your partner contact) in writing whether this use is allowed: who the "AI provider" is in this setup (FlowQR, the model provider, or both), whether the model provider's involvement changes the answer, and any disclosure Meta requires (FlowQR already says "automated assistant" in the first reply).

**Record:** the document and clause, the date, the written answer if you asked.

Result: ______________________  Date: ____________

## 8. Real service-message pricing and the 1,000 free allowance
**Why it matters:** a reply inside the 24-hour window is a "service" message. The price table assumes service messages are billable from 1 Oct 2026 with the first 1,000 per number per month free, at 0.145 rupees afterwards. Those numbers are the starting values from AiSensy's pricing page, **not from Meta**, and are shown to owners as unverified estimates.

**Do:** from Meta's own rate card and your billing page, confirm: the service-message price for India, the date it starts, the free allowance and whether it is per number or per account, how the month is counted, and whether messages sent to a customer who started the conversation through an ad are treated differently. Use "Record a check" on the **service** row in the admin WhatsApp prices screen, or add a corrected price.

Result: ______________________  Date: ____________

## 9. The free entry-point window length (click-to-WhatsApp ads and page buttons)
**Why it matters:** when a customer starts a chat from an ad or a page button, Meta gives a free window. Sources disagree about its length (72 hours, or 7 days from 21 Sep 2026). FlowQR (Phase 11) will treat it as a dated, unverified setting and count those messages as free only once it is verified.

**Do:** find the current length in Meta's documentation and confirm it on a real test conversation's billing. Record the date it applies from.

Result: ______________________  Date: ____________

## 10. The category Meta gives appointment reminders (needed before Phase 9 sends any)
**Why it matters:** reminders are fixed approved templates. If Meta calls them utility they can go to customers who agreed to visit updates. If Meta calls them marketing, or the category is not yet known, FlowQR fails closed (like greetings) and also needs offers consent, which booking-only customers do not have, so they would not get reminders.

**Do:** when the reminder templates exist, submit them, then record the category Meta assigns and the time it took.

Result: ______________________  Date: ____________

## 11. The assistant evaluation (before it is switched on for any real business)
See "Assistant evaluation" in `docs/WHATSAPP_AUTOMATION.md`: a fixed set of about 50 prompts with a written pass mark, run against the real model. **No result is recorded here until someone has run it and seen it.**

| Model and version | Date run | Prompts passed | Hard-fail categories all passed? | Run by |
|---|---|---|---|---|
| | | | | |

---

When all of the above are done and recorded, the flags can be considered for switching on for one test business first, then widened. Until then FlowQR is built, tested against a mock, and safe by default, but **unproven against the real Meta**.
