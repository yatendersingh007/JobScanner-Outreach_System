#!/usr/bin/env bash
# Run as root on the VM. Idempotent.
set -euo pipefail

install -o root -g root -m 644 workflow-d.service /etc/systemd/system/workflow-d.service
install -o root -g root -m 644 workflow-d.timer   /etc/systemd/system/workflow-d.timer

# Never use `systemctl edit` for drop-ins: it can silently discard them
# (BRIEF 8). Write with tee, then verify with systemctl show.
mkdir -p /etc/systemd/system/workflow-d-bot.service.d
tee /etc/systemd/system/workflow-d-bot.service.d/override.conf >/dev/null <<'DROPIN'
[Service]
Restart=always
RestartSec=10
DROPIN

systemctl daemon-reload
systemctl enable --now workflow-d.timer

echo "--- verify (do not skip) ---"
systemctl show workflow-d.timer -p TimersCalendar -p Persistent -p NextElapseUSecRealtime
systemctl list-timers workflow-d.timer --all
# Expect: OnCalendar carrying America/New_York, Persistent=yes, next elapse at
# 09:00 Eastern. If Timezone= is ignored the systemd build is too old for it:
# fall back to a UTC OnCalendar plus a DST check in daily_run, and say so out
# loud rather than shipping a timer that drifts an hour twice a year.
