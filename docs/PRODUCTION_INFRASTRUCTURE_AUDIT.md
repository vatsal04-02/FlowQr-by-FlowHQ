# Production infrastructure audit: Hostinger VPS `201.18.202.128` (flowqr.site)

**Status: BLOCKED. The VPS has NOT been inspected.** No working SSH access exists from the machine this was prepared on: `root@201.18.202.128` and `ubuntu@201.18.202.128` both answered `Permission denied (publickey)` with the keys in `~/.ssh` (including `gkp_hostinger`). Nothing was run on the server, nothing was changed on it, and nothing in this file describes its current state except the three DNS facts at the end, which were read from the public internet.

This document will be completed from the output of the read-only audit script, `deploy/vps/audit.sh`. The server hosts other applications (the Geeta Krishna Physiotherapy infrastructure, n8n, Grist) behind an existing Caddy; **FlowQR must not disturb any of them.**

## How to unblock (pick one)

1. **Give me a deploy login.** On the VPS, as a sudo-capable user, create a dedicated user and add this machine's NEW key (generate it with `ssh-keygen -t ed25519 -f ~/.ssh/flowqr_deploy -C flowqr-deploy` and send me only the `.pub` text): `adduser --disabled-password flowqr && usermod -aG docker flowqr && install -d -m700 -o flowqr -g flowqr /home/flowqr/.ssh && echo '<public key>' >> /home/flowqr/.ssh/authorized_keys`. A user in the `docker` group can control every container on the host, so use a user you are comfortable with and tell me if you want a narrower setup. Do **not** change SSH daemon settings for this.
2. **Run the audit yourself** and paste the output: `bash audit.sh | tee flowqr-vps-audit.txt` (the script is in `deploy/vps/`; it only reads).

## What the audit script collects (all read-only)

Host and kernel; memory, swap, disk and `docker system df`; CPU count; **listening ports** (who owns 80, 443 and the port FlowQR wants, 18000); Docker and Compose versions; **every container**, **every Compose project and its working directory**, networks, volumes, images; per-container memory and CPU right now; **how the existing Caddy runs** (host service or container) and the site addresses in its Caddyfile; what the three names resolve to; where existing backups live and how old they are; firewall status (status only); SSH daemon settings (read only); time sync; the contents of `/opt`.

## Decisions the audit result will drive

| Question | Why it matters | Safe default if unanswered |
|---|---|---|
| RAM and disk free | the container memory ceilings in the overlay add up to about 3 GB (PostgreSQL 1 GB, API 768 MB, worker 768 MB, Redis and scheduler 256 MB each; real use is lower, measure it), plus a few GB of disk. **If the server is short, stop and report; do not deploy an unstable system** | do not deploy |
| Is port 18000 free? Is 8000 used? | The overlay publishes the API on `127.0.0.1:${FLOWQR_API_PORT:-18000}` | change `FLOWQR_API_PORT` |
| Is Caddy a host service or a container, and which Caddyfile? | Decides the upstream address in `deploy/vps/Caddyfile.flowqr-api` (`127.0.0.1:18000` or `host.docker.internal:18000`) and how to reload without interrupting other sites | add a block, `caddy validate`, `caddy reload`; never replace the file |
| Existing backups of the other apps | FlowQR's backups must not collide with or rely on them | separate directory `/opt/flowqr/backups` |
| Firewall rules | Only 80 and 443 should be open; **no firewall change will be made without approval** | none |

## Isolation design (already written, validated with `docker compose config`)

`deploy/vps/docker-compose.vps.yml`, used only with `-p flowqr-production --env-file .env.production`: its own Compose project, network (`flowqr-production_default`), volumes (`flowqr-production_pgdata`, `_redisdata`) and PostgreSQL and Redis instances; **no reverse proxy**; the frontend is not started (it is on Vercel); **only the API is published, and only on `127.0.0.1`**; PostgreSQL, Redis, worker and scheduler publish nothing; memory ceilings per container so a fault cannot starve the neighbours. Deployment directory `/opt/flowqr`.

## What is known from outside (public DNS, read 2026-11-15)

* `flowqr.site` is registered with **GoDaddy** (name servers `ns27.domaincontrol.com`, `ns28.domaincontrol.com`). The apex currently resolves to `3.33.130.190` and `15.197.148.33` (GoDaddy's default parking addresses, not this VPS).
* `www.flowqr.site` is an alias that resolves to `15.197.148.33` (also a GoDaddy default).
* `api.flowqr.site` has **no DNS record**.
* DNS must be edited by you in GoDaddy: see `docs/PRODUCTION_DEPLOYMENT_REPORT.md` section "DNS".
