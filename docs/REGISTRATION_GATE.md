# Registration gate

Owner decision 2026-11-15: a production FlowQR must not accept public sign-ups until the owner turns that on deliberately.

## Modes (`REGISTRATION_MODE`)

| Mode | Who can create a NEW account or business |
|---|---|
| `closed` | Nobody, except addresses in `PLATFORM_ADMIN_EMAILS` (so the first administrator can exist). |
| `allowlist` | Addresses on the allowlist, plus `PLATFORM_ADMIN_EMAILS`. **This is the default whenever `APP_ENV` is `staging` or `production` and the variable is empty.** |
| `open` | Anyone. The default only for `development`/`test`. In production it needs `REGISTRATION_MODE=open` written on purpose. |

An unknown value (a typo such as `public` or `true`) is treated as `closed`, and the production config guard refuses to start with it.

## Where the allowlist comes from (all are merged)

1. `REGISTRATION_ALLOWLIST` in the environment (comma/space separated). Needs an API restart to change.
2. The database list an administrator manages, no restart needed:
   - Admin API (platform admin only): `GET /api/v1/admin/registration`, `POST /api/v1/admin/registration/allowlist {"email","note"}`, `DELETE /api/v1/admin/registration/allowlist/{id}`.
   - Command line on the server: `python -m app.cli registration` (shows mode and list), `--add EMAIL [--note TEXT]`, `--remove EMAIL`.
3. `PLATFORM_ADMIN_EMAILS` (always allowed, in every mode).

Removing an address stops *new* registration with it. An account that already exists is untouched and keeps logging in.

## Where it is enforced (backend only; the frontend is advisory)

One module, `backend/app/services/registration.py`, called from every place an account or business can be created:

| Path | Hook |
|---|---|
| `POST /auth/register` (email + password) | `gate_new_account(..., "password")`, **before** the "already registered" answer |
| Google sign-in / sign-up (`/auth/google/callback`, new-account branch) | `gate_new_account(..., "google")`; refusal redirects to `/login?google_error=registration_restricted` |
| `POST /tenants` (create a business, which is what onboarding calls) | `assert_can_create_business`: outside `open`, the user must be listed **and have a verified email** (or be a platform admin); `closed` → platform admin only |

Signing in (password or Google) for an existing account never goes through the gate. There is no other endpoint that inserts a `User` (staff invitations create no user: the invitee registers through the same gate, so **an invited staff member's address must be on the allowlist in `allowlist`/`closed` mode**).

## Security properties (each is a test in `backend/tests/test_registration_gate.py`)

- **Normalisation:** addresses are Unicode NFKC-normalised, trimmed and lower-cased before comparison, on both the list and the incoming address. `+tag` aliases and look-alike characters from other scripts do **not** match a listed address.
- **No listing oracle:** a refused address gets the same `403 registration_restricted` whether the mode is `closed` or the address is merely not listed, and the check runs before the "already exists" (409) answer. The public `GET /auth/registration` returns only the mode.
- **Brute-force limit:** more than 5 refusals in 15 minutes from one client address → `429`.
- **Audit:** every attempt is recorded (`registration.allowed`, `registration.rejected`) with the route (`password`/`google`/`business`), the mode, the client IP, and for rejections only a 16-character hash of the address plus its domain, never the address. Admin list changes are audited as `admin.registration_allow` / `admin.registration_disallow`.
- **Admin safety:** being on a list grants no privilege. Administrator rights still require a verified email (an unverified account with an admin address is not an administrator).
- **Squatting:** an unverified account on an approved address cannot create a business (`403 email_not_verified`), so a third party who registers an approved address first cannot spend its trial.
- **Existing data is never altered:** the migration only adds a table; no rows in existing tables change.

## Known limitation (disclosed)

A *permitted* address can tell it is permitted, because registration succeeds. A fully zero-knowledge design would need invitation links (a signed single-use token mailed to the approved address). That is not built; the controls above (identical refusals, gate-before-409, rate limit, audit, verified-only business creation) bound what a stranger can learn. Say if you want invitation links.

## Operating it

```
# who may register right now
docker compose -p flowqr-production exec api python -m app.cli registration
# approve a business owner
docker compose -p flowqr-production exec api python -m app.cli registration --add owner@clinic.example --note "pilot clinic"
# stop approving someone (existing account keeps working)
docker compose -p flowqr-production exec api python -m app.cli registration --remove owner@clinic.example
```

Production values: `REGISTRATION_MODE=allowlist`, `REGISTRATION_ALLOWLIST=` (empty; use the CLI or Admin API), `PLATFORM_ADMIN_EMAILS=<owner address>`. The first administrator registers with that address, verifies the mailbox, then `set-admin-password`/signs in.

Migration: `0032_registration_allowlist` (new table `registration_allowlist`, grants to the app role; no RLS because it is not tenant data). Rollback: `alembic downgrade 0031` drops it (the list is lost; nothing else changes).
