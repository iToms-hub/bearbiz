#!/usr/bin/env bash
# Bearbiz PostgreSQL/media backup and restore utility.
set -Eeuo pipefail
IFS=$'\n\t'

BACKUP_ROOT=${BACKUP_ROOT:-/home/tome/backups/bearbiz}
COMPOSE_FILE=${COMPOSE_FILE:-compose.yml}
DB_SERVICE=${DB_SERVICE:-db}
DB_NAME=${POSTGRES_DB:-bearbiz}
DB_USER=${POSTGRES_USER:-bearbiz}
MEDIA_ROOT=${MEDIA_ROOT:-media}
RETENTION_COUNT=${RETENTION_COUNT:-7}
DOCKER_SUDO=${DOCKER_SUDO:-0}
BACKUP_EXECUTION_MODE=${BACKUP_EXECUTION_MODE:-docker}
BACKUP_LOCK_FILE=${BACKUP_LOCK_FILE:-$BACKUP_ROOT/backup.lock}
BACKUP_LOCK_HELD=${BACKUP_LOCK_HELD:-0}
BACKUP_OWNER_UID=${BACKUP_OWNER_UID:-1000}
BACKUP_OWNER_GID=${BACKUP_OWNER_GID:-1000}
temp=''

usage() {
  cat <<'EOF'
Usage:
  scripts/bearbiz-backup.sh backup [--db-only] [--dry-run]
  scripts/bearbiz-backup.sh list
  scripts/bearbiz-backup.sh verify BACKUP_ID
  scripts/bearbiz-backup.sh normalize
  scripts/bearbiz-backup.sh prune [--keep N] [--dry-run]
  scripts/bearbiz-backup.sh restore BACKUP_ID [--db-only|--full] [--yes] [--dry-run]

Environment:
  BACKUP_ROOT      Backup directory (default: /home/tome/backups/bearbiz)
  COMPOSE_FILE     Compose file (default: compose.yml)
  DB_SERVICE       PostgreSQL service (default: db)
  MEDIA_ROOT       Media directory to archive (default: media)
  RETENTION_COUNT  Number of newest sets to retain (default: 7)
  DOCKER_SUDO      Use sudo -n for Docker (set to 1 when socket access needs it)
  BACKUP_EXECUTION_MODE  docker or direct (direct uses local PostgreSQL clients)
  BACKUP_LOCK_FILE Shared lock path for host and container invocations
  BACKUP_OWNER_UID  Owner UID for shared backup files (default: 1000)
  BACKUP_OWNER_GID  Owner GID for shared backup files (default: 1000)
EOF
}

log() { printf '[bearbiz-backup] %s\n' "$*" >&2; }
fatal() { log "ERROR: $*"; exit 1; }
cleanup_temp() { [[ -z "$temp" ]] || rm -rf -- "$temp"; }
cleanup_partial_sets() {
  [[ -d "$BACKUP_ROOT" ]] || return 0
  local path
  while IFS= read -r -d '' path; do
    rm -rf -- "$path"
  done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '.partial-*' -print0)
}

normalize_backup_permissions() {
  [[ "$BACKUP_OWNER_UID" =~ ^[0-9]+$ ]] || fatal 'BACKUP_OWNER_UID must be a numeric UID'
  [[ "$BACKUP_OWNER_GID" =~ ^[0-9]+$ ]] || fatal 'BACKUP_OWNER_GID must be a numeric GID'
  [[ -d "$BACKUP_ROOT" ]] || return 0
  if ((EUID == 0)); then
    chown -R -- "${BACKUP_OWNER_UID}:${BACKUP_OWNER_GID}" "$BACKUP_ROOT"
  fi
  chmod 0750 "$BACKUP_ROOT" 2>/dev/null || true
  find "$BACKUP_ROOT" -type d -exec chmod 0750 {} + 2>/dev/null || true
  find "$BACKUP_ROOT" -type f -exec chmod 0640 {} + 2>/dev/null || true
}

compose() {
  if [[ "$DOCKER_SUDO" == 1 ]]; then
    sudo -n docker compose -f "$COMPOSE_FILE" "$@"
  else
    docker compose -f "$COMPOSE_FILE" "$@"
  fi
}
require_command() {
  command -v "$1" >/dev/null 2>&1 || fatal "required command not found: $1"
  [[ "$DOCKER_SUDO" != 1 ]] || command -v sudo >/dev/null 2>&1 || fatal "required command not found: sudo"
}

acquire_lock() {
  [[ "$BACKUP_LOCK_HELD" == 1 ]] && return 0
  mkdir -p "$(dirname "$BACKUP_LOCK_FILE")"
  exec 9>"$BACKUP_LOCK_FILE"
  flock -n 9 || fatal 'backup already running; skipping overlapping invocation'
}

postgres_dump() {
  if [[ "$BACKUP_EXECUTION_MODE" == direct ]]; then
    PGHOST=${PGHOST:-$DB_SERVICE} PGPORT=${PGPORT:-5432} PGUSER=${PGUSER:-$DB_USER} \
      PGDATABASE=${PGDATABASE:-$DB_NAME} pg_dump -Fc
  else
    compose exec -T "$DB_SERVICE" pg_dump -Fc -U "$DB_USER" -d "$DB_NAME"
  fi
}

postgres_verify() {
  if [[ "$BACKUP_EXECUTION_MODE" == direct ]]; then
    pg_restore --list
  else
    compose exec -T "$DB_SERVICE" sh -c 'cat > /tmp/bearbiz-verify.dump && pg_restore --list /tmp/bearbiz-verify.dump; status=$?; rm -f /tmp/bearbiz-verify.dump; exit "$status"'
  fi
}

postgres_restore() {
  if [[ "$BACKUP_EXECUTION_MODE" == direct ]]; then
    PGHOST=${PGHOST:-$DB_SERVICE} PGPORT=${PGPORT:-5432} PGUSER=${PGUSER:-$DB_USER} \
      PGDATABASE=${PGDATABASE:-$DB_NAME} pg_restore --clean --if-exists --no-owner
  else
    compose exec -T "$DB_SERVICE" sh -c 'cat > /tmp/bearbiz-restore.dump && pg_restore --clean --if-exists --no-owner --dbname="$1" -U "$2" /tmp/bearbiz-restore.dump; status=$?; rm -f /tmp/bearbiz-restore.dump; exit "$status"' sh "$DB_NAME" "$DB_USER"
  fi
}

backup_id_valid() {
  [[ "$1" =~ ^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$ ]]
}

backup_dir() { printf '%s/%s\n' "$BACKUP_ROOT" "$1"; }

list_ids() {
  [[ -d "$BACKUP_ROOT" ]] || return 0
  local path id
  while IFS= read -r path; do
    id=${path##*/}
    backup_id_valid "$id" && printf '%s\n' "$id"
  done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -print | sort -r)
  return 0
}

verify_set() {
  local id=$1 dir dump archive
  backup_id_valid "$id" || fatal "invalid backup identifier: $id"
  dir=$(backup_dir "$id")
  [[ -d "$dir" ]] || fatal "backup set not found: $id"
  [[ -f "$dir/manifest.txt" && -f "$dir/SHA256SUMS" ]] || fatal "backup set is incomplete: $id"
  (cd "$dir" && sha256sum --check SHA256SUMS --status) || fatal "checksum verification failed: $id"
  dump=$dir/database.dump
  archive=$dir/media.tar.gz
  if [[ -f "$dump" ]]; then
    postgres_verify < "$dump" >/dev/null || fatal "PostgreSQL dump is unreadable: $id"
  fi
  if [[ -f "$archive" ]]; then
    tar -tzf "$archive" >/dev/null || fatal "media archive is unreadable: $id"
  fi
  log "verified $id"
}

create_backup() {
  local db_only=0 dry_run=0 arg id dir dump archive manifest suffix=0
  local -a checksum_files=(manifest.txt database.dump)
  while (($#)); do
    case "$1" in
      --db-only) db_only=1 ;;
      --dry-run) dry_run=1 ;;
      *) fatal "unknown backup option: $1" ;;
    esac
    shift
  done
  id=$(date -u +%Y%m%dT%H%M%SZ)
  dir=$(backup_dir "$id")
  while [[ -e "$dir" ]]; do
    suffix=$((suffix + 1))
    id="${id%%-*}-$suffix"
    dir=$(backup_dir "$id")
  done
  if ((dry_run)); then
    log "dry-run: would create $dir"
    return 0
  fi
  acquire_lock
  if [[ "$BACKUP_EXECUTION_MODE" == direct ]]; then require_command pg_dump; require_command pg_restore; else require_command docker; fi
  require_command sha256sum; require_command tar
  mkdir -p "$BACKUP_ROOT"
  normalize_backup_permissions
  cleanup_partial_sets
  temp=$(mktemp -d "$BACKUP_ROOT/.partial-${id}.XXXXXX")
  trap cleanup_temp EXIT
  dump=$temp/database.dump
  archive=$temp/media.tar.gz
  manifest=$temp/manifest.txt
  log "dumping PostgreSQL database from service $DB_SERVICE"
  postgres_dump > "$dump"
  if ((db_only == 0)); then
    if [[ -d "$MEDIA_ROOT" ]]; then
      tar -czf "$archive" -C "$(dirname "$MEDIA_ROOT")" "$(basename "$MEDIA_ROOT")"
    else
      log "media directory $MEDIA_ROOT does not exist; writing empty archive"
      tar -czf "$archive" -C "$temp" .
    fi
  fi
  {
    printf 'backup_id=%s\n' "$id"
    printf 'created_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'database_service=%s\n' "$DB_SERVICE"
    printf 'database_name=%s\n' "$DB_NAME"
    printf 'database_user=%s\n' "$DB_USER"
    printf 'media_root=%s\n' "$MEDIA_ROOT"
    printf 'mode=%s\n' "$([[ $db_only == 1 ]] && printf db-only || printf full)"
  } > "$manifest"
  ((db_only == 0)) && checksum_files+=(media.tar.gz)
  (cd "$temp" && sha256sum "${checksum_files[@]}" > SHA256SUMS)
  verify_set_from_dir "$temp"
  mv "$temp" "$dir"
  normalize_backup_permissions
  temp=''
  trap - EXIT
  log "backup created: $id"
  printf '%s\n' "$id"
}

verify_set_from_dir() {
  local dir=$1
  (cd "$dir" && sha256sum --check SHA256SUMS --status) || fatal "new backup checksum verification failed"
  postgres_verify < "$dir/database.dump" >/dev/null || fatal "new PostgreSQL dump is unreadable"
  [[ ! -f "$dir/media.tar.gz" ]] || tar -tzf "$dir/media.tar.gz" >/dev/null || fatal "new media archive is unreadable"
}

prune_sets() {
  local keep=$RETENTION_COUNT dry_run=0 id count=0
  while (($#)); do
    case "$1" in
      --keep) shift; [[ ${1:-} =~ ^[0-9]+$ ]] || fatal '--keep requires a non-negative integer'; keep=$1 ;;
      --dry-run) dry_run=1 ;;
      *) fatal "unknown prune option: $1" ;;
    esac
    shift
  done
  while IFS= read -r id; do
    count=$((count + 1))
    if ((count > keep)); then
      if ((dry_run)); then log "dry-run: would remove $id"; else rm -rf -- "$(backup_dir "$id")"; log "removed $id"; fi
    fi
  done < <(list_ids)
}

restore_set() {
  local id=$1 mode=full yes=0 dry_run=0 dir dump archive arg
  shift
  backup_id_valid "$id" || fatal "invalid backup identifier: $id"
  while (($#)); do
    case "$1" in
      --db-only) mode=db-only ;;
      --full) mode=full ;;
      --yes) yes=1 ;;
      --dry-run) dry_run=1 ;;
      *) fatal "unknown restore option: $1" ;;
    esac
    shift
  done
  dir=$(backup_dir "$id")
  [[ -d "$dir" ]] || fatal "backup set not found: $id"
  verify_set "$id"
  [[ -f "$dir/database.dump" ]] || fatal "backup has no database dump: $id"
  if [[ "$mode" == full && ! -f "$dir/media.tar.gz" ]]; then fatal "full restore requires media.tar.gz"; fi
  if ((dry_run)); then log "dry-run: would create a current-state safety backup, then restore $id ($mode)"; return 0; fi
  ((yes)) || fatal 'restore changes live data; re-run with --yes after reviewing the backup identifier'
  log "creating current-state safety backup before restore"
  create_backup
  log "restoring PostgreSQL database"
  if [[ "$BACKUP_EXECUTION_MODE" == direct ]]; then
    require_command pg_restore
  else
    require_command docker
  fi
  postgres_restore < "$dir/database.dump"
  if [[ "$mode" == full ]]; then
    log "restoring media directory"
    mkdir -p "$MEDIA_ROOT"
    tar -xzf "$dir/media.tar.gz" --strip-components=1 -C "$MEDIA_ROOT"
  fi
  log "restore complete: $id ($mode)"
}

main() {
  local command=${1:-}
  [[ -n "$command" ]] || { usage; exit 2; }
  shift
  case "$command" in
    backup) create_backup "$@" ;;
    list) (($# == 0)) || fatal 'list takes no options'; list_ids ;;
    verify) (($# == 1)) || fatal 'verify requires exactly one backup identifier'; verify_set "$1" ;;
    prune) prune_sets "$@" ;;
    normalize) (($# == 0)) || fatal 'normalize takes no options'; mkdir -p "$BACKUP_ROOT"; normalize_backup_permissions ;;
    restore) (($# >= 1)) || fatal 'restore requires an explicit backup identifier'; restore_set "$@" ;;
    -h|--help|help) usage ;;
    *) fatal "unknown command: $command" ;;
  esac
}

main "$@"
