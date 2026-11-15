#!/usr/bin/env bash
# Enter the production SMTP settings ON THE SERVER, so the password never passes through chat or a terminal log.
#   bash /opt/flowqr/deploy/vps/set-smtp.sh            (edits /opt/flowqr/.env.production)
# It asks for host, port, user and password (typed hidden), saves a mode-600 backup of the file first, changes ONLY the SMTP_* lines, and never prints the password.
# The app's mailer uses STARTTLS on the given port (587 is the normal one). Port 465 (implicit TLS) is NOT supported: choose a provider/port that offers 587 or 2525.
set -euo pipefail
ENV=${1:-/opt/flowqr/.env.production}
[ -f "$ENV" ] || { echo "not found: $ENV"; exit 1; }
PY=""; for c in python3 python; do if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then PY=$c; break; fi; done
[ -n "$PY" ] || { echo "a working python is required"; exit 1; }
read -r -p "SMTP host (for example smtp.resend.com): " H
read -r -p "SMTP port [587]: " P; P=${P:-587}
read -r -p "SMTP username: " U
read -r -s -p "SMTP password or API key (typed hidden): " W; echo
read -r -p "From address [FlowQR <no-reply@flowqr.site>]: " F; F=${F:-FlowQR <no-reply@flowqr.site>}
[[ "$H" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "host looks wrong"; exit 1; }
[[ "$P" =~ ^[0-9]{2,5}$ ]] || { echo "port must be a number"; exit 1; }
[ "$P" != "465" ] || { echo "port 465 (implicit TLS) is not supported by this app; use 587 or 2525"; exit 1; }
[ -n "$U" ] && [ -n "$W" ] || { echo "username and password are required"; exit 1; }
case "$W$U$F" in *\'*|*\"*|*$'\n'*) echo "quotes and newlines are not allowed in these values"; exit 1;; esac
case "$H" in mailpit|localhost|127.*|smtp.example.*) echo "that is a local or placeholder host, not a real provider"; exit 1;; esac
BK="$ENV.bak-$(date +%Y%m%d%H%M%S)"; cp -p "$ENV" "$BK"; chmod 600 "$BK"
SMTP_H="$H" SMTP_P="$P" SMTP_U="$U" SMTP_W="$W" SMTP_F="$F" "$PY" - "$ENV" <<'PY'
import os, re, sys
path = sys.argv[1]
vals = {"SMTP_HOST": os.environ["SMTP_H"], "SMTP_PORT": os.environ["SMTP_P"], "SMTP_USER": os.environ["SMTP_U"], "SMTP_PASSWORD": os.environ["SMTP_W"],
        "SMTP_FROM": os.environ["SMTP_F"], "SMTP_STARTTLS": "true"}
lines, out, seen = open(path).read().split("\n"), [], set()
for l in lines:
    m = re.match(r"^([A-Z_]+)=", l)
    if m and m.group(1) in vals:
        out.append(f"{m.group(1)}='{vals[m.group(1)]}'")  # single quotes: Docker Compose does not expand $ inside them
        seen.add(m.group(1))
    else:
        out.append(l)
for k in vals:
    if k not in seen:
        out.append(f"{k}='{vals[k]}'")
open(path, "w").write("\n".join(out))
os.chmod(path, 0o600)
PY
echo "saved. file mode: $(stat -c %a "$ENV"). backup: $BK (mode $(stat -c %a "$BK"))"
echo "SMTP_HOST=$H  SMTP_PORT=$P  SMTP_USER=$U  SMTP_FROM=$F  SMTP_PASSWORD=<hidden, $(printf %s "$W" | wc -c) characters>"
unset W
