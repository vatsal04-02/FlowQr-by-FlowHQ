# FlowQR integrations API (version 2026-11-20)

For businesses on the WhatsApp **Pro** add-on, once FlowQR has switched integrations on. An owner or admin makes keys and webhook endpoints in **WhatsApp > Integrations**. Nothing here sends a WhatsApp message by itself: it adds customers, records visits and enquiries and creates bookings, and it tells your system when things happen.

## Authentication

Send a key as `Authorization: Bearer fqk_...`. A key belongs to one business, has scopes, a rate limit (10 to 600 requests a minute, default 60) and an optional expiry, and can be revoked at once. It is shown **once**, when it is made; FlowQR keeps only a hash. A revoked, expired, unknown or malformed key all get the same `401`. A key stops working immediately if the business leaves Pro or the platform switch is turned off (`403 integrations_off`).

| Scope | Allows |
|---|---|
| `customers:write` | `POST /customers` |
| `visits:write` | `POST /visits` |
| `enquiries:write` | `POST /enquiries` |
| `bookings:write` | `POST /bookings` |

Base path: `/api/v1/integrations/v1`. `GET /me` shows which business, scopes and limit a key has (a safe way to test a new key).

## Idempotency

Every `POST` needs an `Idempotency-Key` header (8 to 64 letters, digits, `-`, `_`, `.`, `:`). A retry with the same key and the same body returns the **first answer** (same status code, header `Idempotent-Replay: true`) and does nothing twice. The same key with a different body is refused (`422 idempotency_conflict`). A request that failed is not remembered, so fix the cause and retry with the same key. Answers are kept 48 hours.

## Consent: nothing here creates it by itself

Adding a customer, recording a visit or enquiry, or creating a booking records **no consent**. To record that a customer agreed, send:

```json
{"phone": "+919876543210", "name": "Asha",
 "consent": {"purposes": ["utility"], "agreed": true, "evidence": "Ticked the WhatsApp box at checkout on 12 Nov"}}
```

`agreed` must be `true` and `evidence` must say **how** they agreed (at least 10 characters). This is the same attested rule as an owner typing a customer in (consent source `api_integration`). Purposes are `utility` (updates about their visit), `marketing` (offers) and `occasion` (greetings); each is a separate agreement. Someone who replied STOP cannot be added back this way (`409 opted_out`). A request that is refused changes nothing.

## Endpoints

`POST /customers` `{phone, name?, tags?, consent?}` creates or updates a customer by phone number. `POST /visits` `{phone, visited_at?}` records a visit (within the last 60 days, not in the future) and, if the review-request helper is on and the customer agreed to updates, schedules its one neutral message. `POST /enquiries` `{phone, name?, consent?}`. `POST /bookings` `{phone, name?, service (name or id), date "YYYY-MM-DD", time "HH:MM" (India time), note?}` uses the same server-side rules as the owner calendar (hours, closed days, capacity, buffers, least notice), and answers `409 slot_taken` rather than double-booking.

Unknown fields are refused (`422`), so a typo is never silently ignored. Errors are `{"detail": {"code": "...", "message": "..."}}`.

## Webhooks (events sent to you)

An endpoint is an `https://` address (port 443 or 8443) that resolves only to **public** addresses. Private, loopback, link-local and cloud-metadata addresses and internal names are refused when you add it **and again immediately before every send**; redirects are never followed, and the connection goes to the address that was just checked (with your host name used for TLS and the `Host` header). FlowQR sends a `POST` with a JSON body and these headers:

* `X-FlowQR-Event`: the event type. `X-FlowQR-Delivery`: this delivery's id.
* `X-FlowQR-Signature: t=<unix seconds>,v1=<hex>` where `v1 = HMAC-SHA256(secret, "<t>." + raw body)`. Check it with a constant-time comparison and reject a `t` that is too old (for example more than 5 minutes) to stop replays. The signing secret (`whsec_...`) is shown once; you can replace it.
* Answer with any `2xx` to acknowledge. Anything else (or a timeout of 8 seconds) is retried after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours, and then the delivery is marked dead (you can try it again from the screen). `410 Gone` switches the endpoint off. Ten dead deliveries in a row also switch it off.

Every event has the same envelope, so a connector (for example Shopify or Razorpay) can be added later with no change to it. **None is built.**

```json
{"id": "uuid (the same for every endpoint)", "type": "booking.created", "api_version": "2026-11-20",
 "created_at": "2026-11-20T10:00:00+00:00", "business_id": "uuid", "data": {}}
```

| `type` | `data` |
|---|---|
| `message.status` | `message_id`, `status` (sent, delivered, read, failed), `error_code`, `kind`, `category`, `customer_id`, `customer_phone` |
| `contact.opted_out` | `at`, `customer_id`, `customer_phone` (the customer replied STOP) |
| `conversation.created` | `conversation_id`, `source`, `customer_id`, `customer_phone` |
| `booking.created` / `booking.updated` | `change` (created, rescheduled, cancelled, done, no_show), `booking` {`id`, `code`, `status`, `service`, `starts_at`, `ends_at`, `source`}, `customer_id`, `customer_phone` |
| `ping` | the screen's "Send a test" |

**No event ever contains message text.** Events are written in the same transaction as the thing that happened and sent by a background worker, so a slow receiver never slows FlowQR down, and an event for something that was rolled back is never sent.
