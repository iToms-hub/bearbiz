#!/usr/bin/env bash
# Non-destructive diagnostics for the image-based Portainer stack.
set -u

COMPOSE_FILE="${COMPOSE_FILE:-compose.portainer.yml}"
DOCKER=(docker)
if [ "${DOCKER_SUDO:-0}" = "1" ]; then
  DOCKER=(sudo docker)
fi
COMPOSE=("${DOCKER[@]}" compose -f "$COMPOSE_FILE")

fail() {
  printf 'FAIL [%s] %s\n' "$1" "$2" >&2
  printf '  Inspect with: %s ps && %s logs --tail=100 web db\n' "${COMPOSE[*]}" "${COMPOSE[*]}" >&2
  exit 1
}

printf 'PRECHECK [compose] validating %s\n' "$COMPOSE_FILE"
"${COMPOSE[@]}" config --quiet || fail compose "Compose interpolation or syntax failed"

printf 'PRECHECK [image] pulling release images\n'
"${COMPOSE[@]}" pull web db || fail image "Image pull failed; verify the pinned GHCR tag and registry access"

printf 'PRECHECK [startup] starting services without removing volumes\n'
"${COMPOSE[@]}" up -d || fail startup "Container startup failed"

printf 'PRECHECK [database] waiting for PostgreSQL and migrations\n'
for attempt in $(seq 1 30); do
  status=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}} {{.State}}' 2>/dev/null || true)
  printf '%s\n' "$status" | grep -q '^db healthy' && break
  [ "$attempt" -eq 30 ] && fail database "PostgreSQL did not become healthy"
  sleep 2
done

web_state=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}} {{.State}}' 2>/dev/null || true)
printf '%s\n' "$web_state" | grep -q '^web healthy' || {
  printf '%s\n' "$web_state" >&2
  fail migration "Web migration/startup did not reach a healthy state"
}

printf 'PRECHECK [healthcheck] HTTP health endpoint\n'
port="${WEB_PORT:-8002}"
curl --fail --silent --show-error "http://127.0.0.1:${port}/health/" || \
  fail healthcheck "GET /health/ failed on host port ${port}"
printf '\nPASS: Compose, image pull, startup, database migration, and HTTP healthcheck passed.\n'
