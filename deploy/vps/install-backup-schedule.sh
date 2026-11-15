#!/usr/bin/env bash
# Install the nightly FlowQR-ONLY database backup on the VPS. Run it once, as the `flowqr` user:   bash /opt/flowqr/deploy/vps/install-backup-schedule.sh
# It touches nothing outside /opt/flowqr and flowqr's own crontab: no clinic container, volume, database, backup job or cron entry is read or changed.
#
#   * creates /opt/flowqr/.backup.pass (random, mode 600) if missing. KEEP A COPY OFF THIS SERVER (password manager): without it no backup can be opened
#   * writes /opt/flowqr/run-backup.sh: runs deploy/backup.sh against the flowqr-production project only, and on ANY failure or a not-fully-safe result emails the support address
#     through the app's own SMTP (this server has no mail command), so a failed backup is never silent
#   * adds ONE cron line for the flowqr user (02:10 server time). Running this script again does not add a second one
#   * BACKUP_REMOTE (the OFF-SITE copy) goes in /opt/flowqr/.env.backup. Until it is set the backup is encrypted but only on this disk, and says so: status.json "offsite": false, the
#     Admin > Operations page shows a warning, and the nightly alert email is sent (exit status is non-zero by design)
# Prove restores with deploy/verify-restore.sh (weekly, and before every migration). Never test a restore over the live database.
set -euo pipefail
cd /opt/flowqr
[ "$(id -un)" = flowqr ] || { echo "run this as the flowqr user"; exit 1; }
[ -x deploy/backup.sh ] || chmod +x deploy/backup.sh
umask 077
[ -s .backup.pass ] || { openssl rand -base64 32 > .backup.pass; echo "created .backup.pass: COPY IT TO YOUR PASSWORD MANAGER NOW (cat /opt/flowqr/.backup.pass), then never paste it into a chat"; }
chmod 600 .backup.pass
[ -f .env.backup ] || printf '# BACKUP_REMOTE is the OFF-SITE destination. One of: user@host:/path (scp) | s3://bucket/prefix | rclone:remote:path | /mounted/dir\n# BACKUP_REMOTE=\nBACKUP_KEEP_DAYS=14\n' > .env.backup
chmod 600 .env.backup
cat > run-backup.sh <<'EOS'
#!/usr/bin/env bash
cd /opt/flowqr || exit 1
set -a; . ./.env.backup; set +a
export COMPOSE="docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml"
export BACKUP_DIR=/opt/flowqr/backups BACKUP_PASSPHRASE_FILE=/opt/flowqr/.backup.pass
OUT=$(./deploy/backup.sh 2>&1); rc=$?
echo "$(date -u +%FT%TZ) rc=$rc $OUT" | tail -n 6 >> backups/backup.log
if [ $rc -ne 0 ]; then
  SUBJ="FlowQR backup needs attention (exit $rc)"
  BODY="The nightly FlowQR database backup did not finish fully safely.\n\n$(echo "$OUT" | tail -n 8)\n\nCheck Admin > Operations or /opt/flowqr/backups/status.json."
  $COMPOSE exec -T -e SUBJ="$SUBJ" -e BODY="$BODY" api python -c "import os; from app.core.config import settings as s; from app.services.mailer import send_email; print('alert sent:', send_email(s.support_email, os.environ['SUBJ'], os.environ['BODY'].replace('\\\\n', '\n')))" </dev/null >> backups/backup.log 2>&1
fi
exit $rc
EOS
chmod 700 run-backup.sh
LINE='10 2 * * * /opt/flowqr/run-backup.sh'
{ crontab -l 2>/dev/null | grep -v -F '/opt/flowqr/run-backup.sh' || true; echo "$LINE"; } | crontab -   # '|| true': grep exits 1 on an empty crontab, which pipefail would turn into an abort
echo "installed. crontab for flowqr:"; crontab -l
echo "now: 1) save .backup.pass in your password manager  2) set BACKUP_REMOTE in /opt/flowqr/.env.backup  3) run /opt/flowqr/run-backup.sh once and check: cat /opt/flowqr/backups/status.json"
