#!/usr/bin/env bash
# Install and run the persistent host scheduler for Bearbiz backups.
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
BACKUP_TOOL=${BACKUP_TOOL:-$SCRIPT_DIR/bearbiz-backup.sh}
BACKUP_ROOT=${BACKUP_ROOT:-$HOME/backups/bearbiz}
STATUS_FILE=${BACKUP_STATUS_FILE:-$BACKUP_ROOT/status.json}
LOG_FILE=${BACKUP_LOG_FILE:-$BACKUP_ROOT/backup.log}
LOCK_FILE=${BACKUP_LOCK_FILE:-$BACKUP_ROOT/backup.lock}
BACKUP_OWNER_UID=${BACKUP_OWNER_UID:-1000}
BACKUP_OWNER_GID=${BACKUP_OWNER_GID:-1000}
UNIT_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
SERVICE_NAME=bearbiz-backup.service
TIMER_NAME=bearbiz-backup.timer

log() { printf '[bearbiz-scheduler] %s\n' "$*" | tee -a "$LOG_FILE" >&2; }
fatal() { log "ERROR: $*"; exit 1; }

normalize_backup_permissions() {
  [[ "$BACKUP_OWNER_UID" =~ ^[0-9]+$ && "$BACKUP_OWNER_GID" =~ ^[0-9]+$ ]] || fatal 'backup owner UID/GID must be numeric'
  [[ -d "$BACKUP_ROOT" ]] || return 0
  if ((EUID == 0)); then chown -R -- "${BACKUP_OWNER_UID}:${BACKUP_OWNER_GID}" "$BACKUP_ROOT"; fi
  chmod 0750 "$BACKUP_ROOT" 2>/dev/null || true
  find "$BACKUP_ROOT" -type d -exec chmod 0750 {} + 2>/dev/null || true
  find "$BACKUP_ROOT" -type f -exec chmod 0640 {} + 2>/dev/null || true
}

write_status() {
  local state=$1 message=${2:-} backup_id=${3:-} now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$BACKUP_ROOT"
  STATUS_FILE="$STATUS_FILE" STATE="$state" MESSAGE="$message" BACKUP_ID="$backup_id" NOW="$now" python3 - <<'PY'
import json, os
from pathlib import Path
path = Path(os.environ['STATUS_FILE'])
old = {}
if path.is_file():
    try: old = json.loads(path.read_text())
    except (OSError, ValueError): pass
state = os.environ['STATE']
if state == 'enabled': old['enabled'] = True
elif state == 'disabled': old['enabled'] = False
old.update({'schedule': '02:00 America/Los_Angeles', 'state': state, 'last_attempted': os.environ['NOW']})
if state == 'success':
    old.update({'last_successful': os.environ['NOW'], 'last_backup_id': os.environ['BACKUP_ID'], 'failure_reason': ''})
elif state == 'failed':
    old['last_failed'] = os.environ['NOW']
    old['failure_reason'] = os.environ['MESSAGE']
path.write_text(json.dumps(old, indent=2, sort_keys=True) + '\n')
PY
  normalize_backup_permissions
}

run_backup() {
  mkdir -p "$BACKUP_ROOT"
  normalize_backup_permissions
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then log 'backup already running; skipping overlapping invocation'; exit 75; fi
  write_status running
  local output id detail rc=0
  output=$(BACKUP_ROOT="$BACKUP_ROOT" BACKUP_LOCK_FILE="$LOCK_FILE" BACKUP_LOCK_HELD=1 RETENTION_COUNT="${RETENTION_COUNT:-7}" BACKUP_OWNER_UID="$BACKUP_OWNER_UID" BACKUP_OWNER_GID="$BACKUP_OWNER_GID" "$BACKUP_TOOL" backup 2>>"$LOG_FILE") || rc=$?
  if ((rc == 0)); then
    id=$(printf '%s\n' "$output" | tail -n 1)
    BACKUP_ROOT="$BACKUP_ROOT" BACKUP_OWNER_UID="$BACKUP_OWNER_UID" BACKUP_OWNER_GID="$BACKUP_OWNER_GID" "$BACKUP_TOOL" prune --keep "${RETENTION_COUNT:-7}" >>"$LOG_FILE" 2>&1 || rc=$?
  fi
  if ((rc == 0)); then
    write_status success '' "$id"
    log "backup succeeded: $id"
  else
    detail=$(tail -n 1 "$LOG_FILE" 2>/dev/null || printf 'backup command failed')
    write_status failed "$detail"
    log "backup failed: $detail"
    normalize_backup_permissions
    return 1
  fi
  normalize_backup_permissions
}

install_units() {
  command -v systemctl >/dev/null || fatal 'required command not found: systemctl'
  mkdir -p "$UNIT_DIR"
  cat >"$UNIT_DIR/$SERVICE_NAME" <<EOF
[Unit]
Description=Bearbiz full database and media backup
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$REPO_ROOT
Environment=BACKUP_ROOT=$BACKUP_ROOT
Environment=RETENTION_COUNT=${RETENTION_COUNT:-7}
Environment=BACKUP_OWNER_UID=$BACKUP_OWNER_UID
Environment=BACKUP_OWNER_GID=$BACKUP_OWNER_GID
Environment=COMPOSE_FILE=$REPO_ROOT/compose.yml
Environment=DOCKER_SUDO=${DOCKER_SUDO:-0}
ExecStart=$SCRIPT_DIR/bearbiz-backup-schedule.sh run
EOF
  cat >"$UNIT_DIR/$TIMER_NAME" <<EOF
[Unit]
Description=Nightly Bearbiz backup timer

[Timer]
OnCalendar=*-*-* 02:00:00 America/Los_Angeles
Persistent=true
Unit=$SERVICE_NAME

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$TIMER_NAME"
  mkdir -p "$BACKUP_ROOT"
  write_status enabled
  log "enabled nightly backup timer at 02:00 America/Los_Angeles"
}

disable_units() {
  systemctl --user disable --now "$TIMER_NAME" 2>/dev/null || true
  rm -f "$UNIT_DIR/$TIMER_NAME" "$UNIT_DIR/$SERVICE_NAME"
  systemctl --user daemon-reload
  mkdir -p "$BACKUP_ROOT"
  write_status disabled
  log 'disabled nightly backup timer'
}

status_units() {
  local state=disabled
  if systemctl --user is-enabled --quiet "$TIMER_NAME" 2>/dev/null; then state=enabled; fi
  printf 'scheduler=%s\n' "$state"
  printf 'schedule=02:00 America/Los_Angeles\n'
  systemctl --user list-timers "$TIMER_NAME" --no-legend 2>/dev/null || true
  [[ -f "$STATUS_FILE" ]] && cat "$STATUS_FILE"
}

usage() { printf 'Usage: %s enable|disable|status|run\n' "$0"; }
case "${1:-}" in
  enable) install_units ;;
  disable) disable_units ;;
  status) status_units ;;
  run) run_backup ;;
  *) usage; exit 2 ;;
esac
