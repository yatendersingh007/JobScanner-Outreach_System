#!/usr/bin/env bash
# Run as root on the VM. Idempotent.
#
# No timer, ever (HARD RULE 2). This installs ONE long-running long-poll bot
# unit. Every run of the pipeline starts from a human's /scan command to that
# bot (or from the local CLI), never from a schedule.
set -euo pipefail

install -o root -g root -m 644 workflow-d-bot.service /etc/systemd/system/workflow-d-bot.service

# Never use `systemctl edit` for drop-ins: it can silently discard them
# (BRIEF 8). Write with tee, then verify with systemctl show. Restart=always
# and RestartSec=10 are already in the base unit file above; the drop-in here
# re-asserts them so a future hand-edit of the base file can't quietly drop
# the auto-restart behavior without systemctl show catching it.
mkdir -p /etc/systemd/system/workflow-d-bot.service.d
tee /etc/systemd/system/workflow-d-bot.service.d/override.conf >/dev/null <<'DROPIN'
[Service]
Restart=always
RestartSec=10
DROPIN

systemctl daemon-reload
systemctl enable --now workflow-d-bot.service

echo "--- verify (do not skip) ---"
systemctl show workflow-d-bot.service -p ActiveState -p SubState -p Restart -p RestartUSec
systemctl status workflow-d-bot.service --no-pager
# Expect: ActiveState=active, SubState=running, Restart=always, RestartUSec
# carrying the 10s drop-in. If the drop-in silently failed to apply (BRIEF 8's
# systemctl-edit landmine, guarded against here by using tee instead), Restart
# would show whatever the base unit file alone specifies — say so out loud
# rather than assuming the drop-in took.
