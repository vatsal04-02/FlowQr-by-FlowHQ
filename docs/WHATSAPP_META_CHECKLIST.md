# WhatsApp: things only a person can check with Meta

FlowQR's tests use a mock of Meta. They prove FlowQR behaves correctly **given** what Meta is assumed to do. They do **not** prove what Meta really does. The five checks below need a real Meta account, real approvals and real traffic, so they are for a person to do and record. **None of them has been done. Nothing here is a result.** Fill in each "Result" box yourself, with the date, and do not tick a box you have not seen with your own eyes.

Until a check is done, keep the matching WhatsApp flags off (`WHATSAPP_SENDING_ENABLED`, `WHATSAPP_WEBHOOK_ENABLED`, `WHATSAPP_SIGNUP_ENABLED`) in production.

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
**Why it matters:** every cost figure owners see is an estimate from the table at **WhatsApp prices** (admin). The starting values (India, from 1 Oct 2026: marketing 1.09, utility 0.145, authentication 0.145, service 0.145 with the first 1,000 service messages per number per month free) come from a brief, **not** from Meta's rate card. They are marked UNVERIFIED and owners see a warning until they are checked.

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

When all five are done and recorded, the flags can be considered for switching on for one test business first, then widened. Until then FlowQR is built, tested against a mock, and safe by default, but **unproven against the real Meta**.
