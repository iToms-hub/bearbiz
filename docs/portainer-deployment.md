# Portainer CE deployment reference

This is the normal Community Edition flow for Bearbiz. The stack is
`compose.portainer.yml`; the development `compose.yml` is intentionally
unchanged and remains a source-mounted `runserver` workflow.

## Stack and image

Create a Portainer stack from the public repository:

- Repository: `https://github.com/iToms-hub/bearbiz.git`
- Reference: `refs/heads/main`
- Compose path: `compose.portainer.yml`
- Repository authentication: off; TLS verification: on

The stack uses the verified release image `ghcr.io/itoms-hub/bearbiz:1.1.7`.
It uses explicit Docker volumes named
`bearbiz_postgres`, `bearbiz_media`, and `bearbiz_backups`, exposes `8002:8000`,
waits for the PostgreSQL healthcheck, runs migrations before Gunicorn, and
checks `/health/`. It does not use a build context, host bind paths, an
external env file, or the Docker socket.

## Portainer environment

Set the four required rows in the stack **Environment variables** table, or
upload a private `stack.env` through Portainer. The remaining rows are optional
overrides with safe defaults. Do not commit private values:

```text
SECRET_KEY=<long-random-secret>
POSTGRES_PASSWORD=<strong-unique-password>
ALLOWED_HOSTS=localhost,127.0.0.1,<host-or-proxy-name>
CSRF_TRUSTED_ORIGINS=https://bearbiz.itoms.org,https://<host-or-proxy-name>
```

Optional overrides are `DEBUG=0`, `POSTGRES_DB=bearbiz`,
`POSTGRES_USER=bearbiz`, `BACKUP_OWNER_UID=1000`, `BACKUP_OWNER_GID=1000`,
and `GUNICORN_WORKERS=3`.

`POSTGRES_HOST=db`, `POSTGRES_PORT=5432`, and the container backup paths are
set by the compose file. `CSRF_TRUSTED_ORIGINS` must contain explicit full
origins (including `https://`), not bare hostnames. Keep secrets and registry
credentials in Portainer, not Git.

## GHCR visibility and updates

A public GitHub repository does not automatically make its GHCR package public.
For unauthenticated pulls, set the package visibility to **Public** in GitHub
Packages. If the package is private, configure Portainer's `ghcr.io` registry
credentials using a read-only package token; never put the token in Compose or
`stack.env` committed to Git.

The checked-in workflow publishes with `GITHUB_TOKEN` and no application
secrets. Pushes to `main` publish `latest` and an immutable SHA tag. version
version tags such as `v1.1.7` publish `1.1.7`, `1.0`, `1`, and a SHA tag. The compose
file pins the verified release tag. Never use `down -v` during an update.

The stack's `bearbiz_backups` volume is local to the deployment host and is not
an off-host backup. The stack also has no scheduler; run a verified backup
manually or configure an external host scheduler/export before relying on it.

## Verification

After deployment, confirm both services are healthy, then check:

```text
GET http://<host>:8002/health/
GET http://<host>:8002/
GET http://<host>:8002/admin/
```

The health response should be HTTP 200 and report the expected version. Confirm
uploads survive web recreation and retain all three named volumes across stack
updates.

## Preflight diagnostics and rollback

Run `scripts/portainer-preflight.sh` from a repository checkout with the same
environment values as the Portainer stack. The script reports independent gates
for Compose parsing, GHCR image pull, container startup, PostgreSQL readiness and
web migration, then the HTTP `/health/` check. It is non-destructive: it does not
run `down -v` or delete any named volume. On failure it prints the relevant
`docker compose ps` and `docker compose logs --tail=100 web db` command.

For rollback, verify the previous GHCR tag, intentionally edit the `image:`
reference in `compose.portainer.yml` to that tag, and redeploy. Retain the failed
release's containers and logs while investigating;
confirm the health endpoint and `bearbiz_postgres`, `bearbiz_media`, and
`bearbiz_backups` volumes after rollback.
