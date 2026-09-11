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

The stack defaults to `ghcr.io/itoms-hub/bearbiz:0.9.7` and can override it
with `BEARBIZ_IMAGE_TAG`. It uses explicit Docker volumes named
`bearbiz_postgres`, `bearbiz_media`, and `bearbiz_backups`, exposes `8002:8000`,
waits for the PostgreSQL healthcheck, runs migrations before Gunicorn, and
checks `/health/`. It does not use a build context, host bind paths, an
external env file, or the Docker socket.

## Portainer environment

Set these in the stack **Environment variables** table, or upload a private
`stack.env` through Portainer. Do not commit private values:

```text
SECRET_KEY=<long-random-secret>
POSTGRES_PASSWORD=<strong-unique-password>
ALLOWED_HOSTS=localhost,127.0.0.1,<host-or-proxy-name>
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<host-or-proxy-name>
DEBUG=0
POSTGRES_DB=bearbiz
POSTGRES_USER=bearbiz
BACKUP_OWNER_UID=1000
BACKUP_OWNER_GID=1000
BEARBIZ_IMAGE_TAG=0.9.7
GUNICORN_WORKERS=3
```

`POSTGRES_HOST=db`, `POSTGRES_PORT=5432`, and the container backup paths are
set by the compose file. Keep secrets and registry credentials in Portainer,
not Git.

## GHCR visibility and updates

A public GitHub repository does not automatically make its GHCR package public.
For unauthenticated pulls, set the package visibility to **Public** in GitHub
Packages. If the package is private, configure Portainer's `ghcr.io` registry
credentials using a read-only package token; never put the token in Compose or
`stack.env` committed to Git.

The checked-in workflow publishes with `GITHUB_TOKEN` and no application
secrets. Pushes to `main` publish `latest` and an immutable SHA tag. version
tags such as `v0.9.7` publish `0.9.7`, `0.9`, `0`, and a SHA tag. Prefer an
immutable version tag in Portainer; update `BEARBIZ_IMAGE_TAG` only after a
verified database-plus-media backup. Never use `down -v` during an update.

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
