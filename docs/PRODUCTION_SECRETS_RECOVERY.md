# Production secrets: what must be kept off the server, and how to recover

The database backup (`deploy/backup.sh`) holds data. These items are NOT in it, and a restore on a new server cannot work without the first two.

| Secret | Where it lives | What is lost without it |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | `/opt/flowqr/.env.production` | Every stored Google connection (OAuth tokens are encrypted with it, `app/core/security.py` `TokenCipher`) becomes unreadable. Each business must reconnect Google. Passwords, reviews, cards and the rest of the data are NOT affected. |
| Backup passphrase | `/opt/flowqr/.backup.pass` | The encrypted backups cannot be opened. This is the one that makes the backups useless. |
| `SECRET_KEY` | `.env.production` | Signed values stop validating: OAuth flow cookies in progress, anonymous-visitor hashes. Sessions are in the database and survive. Replaceable without data loss. |
| SMTP / Google OAuth secrets | `.env.production` | Replaceable from the providers' consoles. |

Fingerprint of the current `TOKEN_ENCRYPTION_KEY` (safe to write down, it reveals nothing): **`6b20880edab67a25`**.

## Store the key and the passphrase (once, by the owner, in the owner's own terminal)

Never paste either into a chat, a ticket or Git. Run these on the VPS yourself and copy the output straight into a password manager entry (two separate entries: "FlowQR TOKEN_ENCRYPTION_KEY" and "FlowQR backup passphrase"):

```
ssh flowqr@201.18.202.128
grep '^TOKEN_ENCRYPTION_KEY=' /opt/flowqr/.env.production | cut -d= -f2-      # copy this value
cat /opt/flowqr/.backup.pass                                                    # copy this value
clear; history -c                                                               # remove them from the terminal
```

## Prove the copy is good, without showing it

In the password manager, copy the key value to the clipboard, then on any trusted machine:

```
printf '%s' "$(pbpaste)" | sha256sum | cut -c1-16        # macOS; on Linux: xclip -o | sha256sum | cut -c1-16; on Windows PowerShell: see below
```

It must print `6b20880edab67a25`. If it does not, the copy is wrong (a trailing space or newline is the usual cause): fix it before relying on it.
PowerShell: `$k=Get-Clipboard; $b=[Text.Encoding]::UTF8.GetBytes($k.Trim()); -join ([Security.Cryptography.SHA256]::Create().ComputeHash($b)[0..7] | % { $_.ToString('x2') })`

## Recovery

1. New server, same layout (`/opt/flowqr`), FlowQR project name `flowqr-production`.
2. Put the saved `TOKEN_ENCRYPTION_KEY` and the other settings back into a new `.env.production` (`chmod 600`). The key MUST be identical.
3. Restore the newest backup: fetch the off-site copy, then `deploy/restore.sh` (it asks you to type `yes`, because it replaces the database). Prove it first with `deploy/verify-restore.sh --from-remote`.
4. Start the stack, check `/api/ready`, sign in, and open a business that had Google connected: it must still show connected. If it shows "reconnect", the key is wrong.

## Rules

* Do not connect real Google Business Profile credentials for customers until the key is saved and the fingerprint check above has passed. Today the database holds 0 stored Google tokens, so nothing is at risk yet.
* `.env.production.bak-*` and `backups/env.production.*` on the server are mode 600 copies that also contain the key and other secrets. They are on the SAME disk, so they are not a backup. Delete them once the off-site copy exists and a restore has been proven.
* Never rotate `TOKEN_ENCRYPTION_KEY` without a migration that re-encrypts stored tokens: swapping it silently disconnects every Google connection.
