#!/usr/bin/env bash
# READ-ONLY audit of the shared VPS, to run BEFORE anything is deployed (docs/PRODUCTION_INFRASTRUCTURE_AUDIT.md is written from its output). It changes nothing:
# no docker start/stop/rm/prune, no file writes outside stdout, no firewall or SSH changes. Run as a user that can read docker:  bash audit.sh | tee flowqr-vps-audit.txt
set -u
h() { printf '\n===== %s =====\n' "$*"; }
h "host"; date -u; hostnamectl 2>/dev/null | head -8 || uname -a; uptime
h "memory and swap"; free -h
h "disk"; df -hT -x tmpfs -x devtmpfs -x overlay 2>/dev/null; echo; docker system df 2>/dev/null
h "cpu"; nproc; lscpu 2>/dev/null | grep -E "Model name|^CPU\(s\)"
h "listening ports (who owns 80, 443 and the ports FlowQR wants: 18000)"; ss -tlnp 2>/dev/null | awk 'NR==1 || /LISTEN/'
h "docker version"; docker version --format 'client {{.Client.Version}} / server {{.Server.Version}}' 2>&1; docker compose version 2>&1
h "containers (all)"; docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1
h "compose projects"; docker compose ls -a 2>&1
h "compose labels per container (project, working dir, config files)"; docker ps -a --format '{{.Names}}' | while read -r n; do printf '%s | %s | %s\n' "$n" "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$n")" "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$n")"; done
h "networks"; docker network ls 2>&1
h "volumes"; docker volume ls 2>&1
h "images (names and sizes only)"; docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' 2>&1 | head -40
h "per-container memory and cpu right now"; docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>&1
h "caddy: how it runs"; (systemctl is-active caddy 2>/dev/null && systemctl status caddy --no-pager 2>/dev/null | head -8) ; docker ps -a --filter "ancestor=caddy" --format '{{.Names}} {{.Image}} {{.Ports}}' 2>&1; docker ps -a --format '{{.Names}} {{.Image}}' | grep -i caddy
h "caddy: configuration files (paths only, then the SITE ADDRESSES in them; no secrets are printed)"; for f in /etc/caddy/Caddyfile /opt/*/Caddyfile /srv/*/Caddyfile; do [ -f "$f" ] && { echo "--- $f"; grep -nE '^[^#[:space:]{}][^{]*\{|^\s*(import|reverse_proxy)\b' "$f" | head -40; }; done
h "dns for the three names (what the world sees)"; for d in flowqr.site www.flowqr.site api.flowqr.site; do printf '%s -> ' "$d"; getent hosts "$d" | awk '{print $1}' | tr '\n' ' '; echo; done
h "existing backups (locations and newest files only)"; ls -dt /opt/*/backups /var/backups /root/backups /home/*/backups 2>/dev/null | head; for d in /opt/*/backups /var/backups /root/backups; do [ -d "$d" ] && { echo "--- $d"; ls -lt "$d" 2>/dev/null | head -5; }; done
h "firewall (status only)"; (ufw status verbose 2>/dev/null || echo "ufw not active or not installed"); iptables -S 2>/dev/null | head -20
h "ssh daemon (read only)"; grep -E '^(PermitRootLogin|PasswordAuthentication|Port) ' /etc/ssh/sshd_config 2>/dev/null
h "time sync"; timedatectl 2>/dev/null | grep -E "System clock|NTP"
h "/opt contents (names only)"; ls -la /opt 2>/dev/null
echo; echo "AUDIT COMPLETE (read-only)"
