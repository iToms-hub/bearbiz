# Bearbiz

Bearbiz is a BI platform for weekly report uploads, PDF extraction, dashboards,
and printable/exportable sales reporting.

Current version: 0.9.5

## Prerequisites

- Docker Engine 24 or newer
- Docker Compose v2 (`docker compose`, not the obsolete `docker-compose` v1)
- Git, for checkout and upgrades
- At least 4 GB of available memory for PDF rendering and OCR

The application and PostgreSQL run in containers. A local Python installation
is only needed if you want to run the test suite or Django management commands
outside Docker; Python 3.12 or newer is required.

## Local installation with Docker Compose

From the repository root:

```bash
cp .env.example .env
# Edit .env: set a unique SECRET_KEY and a non-default database password.
docker compose up --build -d
```

The default development port is `http://localhost:8002`. Check the service
before opening the UI:

```bash
curl --fail http://localhost:8002/health/
# Expected shape: {"status":"ok","version":"0.9.5"}
```

Open `http://localhost:8002/admin/` for the admin site. The Compose web
command applies migrations before starting Django. To run migrations manually:

```bash
docker compose run --rm web python manage.py migrate
```

Start in the foreground when diagnosing startup:

```bash
docker compose up --build
```

Stop containers without deleting the database volume:

```bash
docker compose down
```

Do not use `docker compose down -v` unless you intentionally want to destroy
the PostgreSQL data volume. Uploaded files live under the bind-mounted `media/`
directory and must be backed up separately from source code.

## Environment setup

`.env.example` documents the supported settings. At minimum, production-like
deployments should set `SECRET_KEY`, `DEBUG=0`, `ALLOWED_HOSTS`,
`POSTGRES_DB`, `POSTGRES_USER`, and a strong `POSTGRES_PASSWORD`. Keep `.env`
and API keys out of Git; use the deployment secret store or host environment.
`WEB_PORT` changes the host port, and `BACKUP_ROOT` changes the host backup
mount (the default is `/home/tome/backups/bearbiz`).

## Production Docker notes

The checked-in Compose file is intended for local and small private
deployments. It bind-mounts the source tree, uses Django's development
server, supplies development defaults, and exposes PostgreSQL on the internal
Compose network. For production, use the published immutable GHCR image from a
tagged release, do not mount the source tree, set `DEBUG=0` and an explicit host list,
provide secrets externally, put a TLS-terminating reverse proxy in front of
the app, and run a production WSGI server such as Gunicorn instead of
`runserver`. Restrict the Docker socket and backup directory permissions, and
pin image/dependency versions as part of your deployment process.

Run `collectstatic` as part of an image or release step when serving static
assets from a separate web server. Apply migrations as a deliberate release
operation, with a verified database backup first; do not rely on a web
container restart to hide migration failures.

## Portainer Community Edition deployment

The CE stack is a portable image-based deployment. It pulls the pinned
`ghcr.io/itoms-hub/bearbiz:0.9.5` image by default; it does not build from a
checkout, use host bind paths, mount the Docker socket, or reference an
external `env_file`. The web container runs migrations before Gunicorn starts,
waits for PostgreSQL health, persists data in the explicitly named Docker
volumes `bearbiz_postgres`, `bearbiz_media`, and `bearbiz_backups`, and publishes
`8002:8000`.

### First deployment

In Portainer choose **Stacks → Add stack → Git repository**:

```text
Repository URL:       https://github.com/iToms-hub/bearbiz.git
Repository reference: refs/heads/main
Compose path:         compose.portainer.yml
```

The repository is public, so leave repository authentication off and TLS
verification on. In the stack editor's **Environment variables** table, add the
environment rows below, or upload a private `stack.env` file through Portainer;
set these values. Never commit the file or paste real secrets into Git:

```text
SECRET_KEY            <long-random-private-value>
POSTGRES_PASSWORD     <strong-private-password>
ALLOWED_HOSTS         localhost,127.0.0.1,<deployment-host>
DJANGO_ALLOWED_HOSTS  localhost,127.0.0.1,<deployment-host>
DEBUG                 0
POSTGRES_DB           bearbiz
POSTGRES_USER         bearbiz
BACKUP_OWNER_UID      1000
BACKUP_OWNER_GID      1000
BEARBIZ_IMAGE_TAG     0.9.5
GUNICORN_WORKERS      3
```

`BEARBIZ_IMAGE_TAG` is optional; omit it to use `0.9.5`. The stack sets
`POSTGRES_HOST=db` and the internal backup paths itself. Add any reverse-proxy
hostname to both allowed-host variables. Remove blank placeholder rows before
deploying.

GHCR package visibility is separate from GitHub repository visibility. The
image must be made **public** in the repository's Packages settings for an
unauthenticated Portainer/Docker pull. If the package remains private, configure
Portainer's registry credentials for `ghcr.io` with a read-only package token;
do not put that token in the compose file or Git. The workflow publishes on
`main` as `latest` plus an immutable SHA tag, and on version tags such as
`v0.9.6` as `0.9.6` (plus safe semver tags and SHA). Deploy a version tag for
repeatable releases; advance `BEARBIZ_IMAGE_TAG` only after verifying a backup
and the new image.

The named volumes survive stack updates. Never run `docker compose -f
compose.portainer.yml down -v` or delete a Portainer volume during a routine
upgrade. Before updating, verify a database-plus-media backup; redeploy, allow
migrations to finish, then verify container health and `GET /health/` at
`http://<deployment-host>:8002/`.

## What Bearbiz does

- Upload one fixed-structure report at a time
- Extract weekly PDF reports into structured storage
- Show per-report and combined dashboards, including performance views
- Export selected report data to printable PDF outputs
- Keep a shared core with per-report modules for future report types

## Repository layout

- `bearbiz/` — Django project configuration
- `apps/core/` — shared application pieces
- `apps/reports/` — report contracts, parsing modules, and registry
- `scripts/` — backup and backup-schedule utilities
- `tests/` — pytest and Django coverage

## Backups and restore

The repository includes `scripts/bearbiz-backup.sh`, a guarded backup tool for
the Compose PostgreSQL service and the local `media/` tree. It does not create
a schedule by default. Backup sets are timestamped directories under
`/home/tome/backups/bearbiz` by default; set `BACKUP_ROOT` to use another
location. Store that directory on durable storage outside the application host
when possible, and periodically test restoring it. A backup on the same disk
does not protect against disk failure, host loss, ransomware, or accidental
deletion.

From the repository root, while the Compose services are running:

```bash
# Full database + media backup (also verifies the dump and archive)
scripts/bearbiz-backup.sh backup

# Database only, list sets, or verify one set
scripts/bearbiz-backup.sh backup --db-only
scripts/bearbiz-backup.sh list
scripts/bearbiz-backup.sh verify 20260908T120000Z

# Preview retention pruning, then keep the newest five sets
scripts/bearbiz-backup.sh prune --keep 5 --dry-run
scripts/bearbiz-backup.sh prune --keep 5
```

For the Docker deployment, install the persistent host systemd user timer
(02:00 in America/Los_Angeles), or inspect/remove it safely:

```bash
scripts/bearbiz-backup-schedule.sh enable
scripts/bearbiz-backup-schedule.sh status
scripts/bearbiz-backup-schedule.sh disable
```

The scheduler runs the guarded full backup, prunes to the newest seven
verified sets, and uses a non-blocking `flock` lock to prevent overlap.
`status.json` and `backup.log` are written under `BACKUP_ROOT`; failures leave
the reason and timestamp visible to Settings → Backup. `BACKUP_ROOT` and
`RETENTION_COUNT` can be supplied when enabling the timer. Shared-mount files
are owned by `BACKUP_OWNER_UID:BACKUP_OWNER_GID` (both default to `1000`) and
use owner/group-only permissions; set those variables to match the host user
when deploying with a different UID/GID.

Restore requires an explicit identifier and `--yes`. Before any live database
restore it creates and verifies a new current-state safety backup. Use
`--dry-run` to inspect the operation without changing data. `--db-only`
restores only PostgreSQL; `--full` restores PostgreSQL and media files.

```bash
scripts/bearbiz-backup.sh restore 20260908T120000Z --db-only --dry-run
scripts/bearbiz-backup.sh restore 20260908T120000Z --db-only --yes
scripts/bearbiz-backup.sh restore 20260908T120000Z --full --yes
```

Useful overrides are `COMPOSE_FILE`, `DB_SERVICE`, `MEDIA_ROOT`, and the
PostgreSQL `POSTGRES_DB`/`POSTGRES_USER` environment variables. If the Docker
socket requires sudo, add `DOCKER_SUDO=1` to the command. The tool
writes `manifest.txt` and `SHA256SUMS` in every set, rejects malformed or
missing identifiers, cleans partial sets after failures, and never deletes the
live Docker volume.
