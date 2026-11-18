#!/usr/bin/env bash
# Append the reviewed go.flowqr.site block (permanent QR/NFC redirect domain) to the EXISTING Caddy's Caddyfile, validate the whole configuration, then gracefully reload.
# Same procedure and same privilege requirement as apply-caddy.sh: run as the user that owns the Caddyfile (`deploy`) or root; it needs no other privilege.
#   bash /opt/flowqr/deploy/vps/apply-caddy-go.sh            apply
#   bash /opt/flowqr/deploy/vps/apply-caddy-go.sh --dry-run  check everything, change nothing
# Safe to run twice (does nothing if go.flowqr.site is already there). If validation fails the original file is restored in place and Caddy is NOT reloaded. Never restarts Caddy, never touches another site.
# ROLLBACK (as the same user): the script prints the backup path; `cat <backup> > /home/deploy/GKP-Final-Build/Caddyfile` (in place, NOT mv/cp over it: the container bind-mounts the file), then
#   docker exec gkp-final-build-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
# DNS must already resolve go.flowqr.site to this server (A 201.18.202.128) or Caddy cannot obtain the certificate.
set -euo pipefail
CF=${CADDYFILE:-/home/deploy/GKP-Final-Build/Caddyfile}
BLOCK=${BLOCK:-/opt/flowqr/deploy/vps/Caddyfile.flowqr-go}
CTR=${CADDY_CONTAINER:-gkp-final-build-caddy-1}
WANT_SHA=${WANT_SHA:-22effe6fc2520675}   # first 16 hex of the reviewed block
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

[ -r "$CF" ] && [ -w "$CF" ] || { echo "cannot read and write $CF as $(id -un): run this as the file's owner (deploy) or root"; exit 1; }
[ -r "$BLOCK" ] || { echo "missing $BLOCK"; exit 1; }
got=$(sha256sum "$BLOCK" | cut -c1-16)
[ "$got" = "$WANT_SHA" ] || { echo "the block's checksum is $got, not the reviewed $WANT_SHA: refusing"; exit 1; }
docker inspect --type container "$CTR" --format '{{.State.Status}}' | grep -qx running || { echo "$CTR is not running"; exit 1; }
if grep -qE '^[[:space:]]*go\.flowqr\.site[[:space:]]*\{' "$CF"; then echo "go.flowqr.site is already in the Caddyfile: nothing to do"; exit 0; fi
grep -q 'go\.flowqr\.site' "$CF" && { echo "go.flowqr.site appears in the Caddyfile in another form: check by hand"; exit 1; }
grep -qE '^[[:space:]]*api\.flowqr\.site[[:space:]]*\{' "$CF" || { echo "the api.flowqr.site block is missing: this is not the expected Caddyfile, refusing"; exit 1; }
echo "Caddyfile: $(stat -c '%U:%G %a %s bytes' "$CF"); sites before: $(grep -cE '^[^[:space:]#].*\{[[:space:]]*$' "$CF")"
echo "Caddy before: id=$(docker inspect --type container "$CTR" --format '{{.Id}}' | cut -c1-12) started=$(docker inspect --type container "$CTR" --format '{{.State.StartedAt}}')"
[ "$DRY" = 1 ] && { echo "dry run: would back up, append $(wc -l < "$BLOCK") lines, validate and reload. Nothing changed."; exit 0; }

BK="$CF.bak-$(date +%Y%m%d%H%M%S)"
cp -p "$CF" "$BK"                                  # keeps owner, mode and timestamp
[ -n "$(tail -c1 "$CF")" ] && printf '\n' >> "$CF" # a missing final newline would glue the block onto the last line
{ printf '\n'; cat "$BLOCK"; } >> "$CF"            # append IN PLACE: the container bind-mounts this file, so replacing it would orphan the mount
echo "appended; backup: $BK"
if docker exec "$CTR" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  docker exec "$CTR" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  echo "reloaded gracefully. Caddy after: id=$(docker inspect --type container "$CTR" --format '{{.Id}}' | cut -c1-12) started=$(docker inspect --type container "$CTR" --format '{{.State.StartedAt}}') (must equal 'before')"
else
  cat "$BK" > "$CF"                                # restore IN PLACE
  echo "VALIDATION FAILED: the original Caddyfile is restored, Caddy was not reloaded"
  exit 2
fi
