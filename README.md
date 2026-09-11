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
Compose network. For production, build an immutable image from a tagged
release, do not mount the source tree, set `DEBUG=0` and an explicit host list,
provide secrets externally, put a TLS-terminating reverse proxy in front of
the app, and run a production WSGI server such as Gunicorn instead of
`runserver`. Restrict the Docker socket and backup directory permissions, and
pin image/dependency versions as part of your deployment process.

Run `collectstatic` as part of an image or release step when serving static
assets from a separate web server. Apply migrations as a deliberate release
operation, with a verified database backup first; do not rely on a web
container restart to hide migration failures.

## Portainer Community Edition deployment

Portainer CE repository deployments do not persist or apply the **Environment
variables** rows in the stack editor. Do not put deployment values there. The
tracked `compose.portainer.yml` reads one env file from the Docker host instead,
with the default absolute path `/opt/bearbiz.env` (not a path inside a
container). This also prevents Compose from trying to interpolate required
values such as `ALLOWED_HOSTS` before the container starts.

On the Docker LXC, create the file without putting its contents in Git:

```bash
sudo install -o root -g root -m 600 /dev/null /opt/bearbiz.env
sudoedit /opt/bearbiz.env
sudo chmod 600 /opt/bearbiz.env
```

The file must contain these entries (use real private values on the host):

```text
SECRET_KEY=replace-with-a-long-random-value
POSTGRES_PASSWORD=replace-with-a-strong-password
ALLOWED_HOSTS=localhost,127.0.0.1,LXC_HOST_IP
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,LXC_HOST_IP
DEBUG=0
POSTGRES_DB=bearbiz
POSTGRES_USER=bearbiz
BACKUP_OWNER_UID=1000
BACKUP_OWNER_GID=1000
```

`POSTGRES_HOST` is deliberately set to the internal Compose service name `db`
by the stack. The stack also uses stable Docker-host paths
`/opt/bearbiz/media` and `/opt/bearbiz/backups`, and always publishes
`8002:8000`. The checked-in default is intentionally `/opt/bearbiz.env`; if a
different absolute host path is required, change `BEARBIZ_ENV_FILE` in the
repository deployment configuration before deploying. The stack editor's UI
environment rows are not a substitute for this host file.

In Portainer choose **Stacks → Add stack → Git repository** and fill in:

```text
Repository URL:       your Bearbiz Git repository URL
Repository reference: main (or the release tag to deploy)
Compose path:         compose.portainer.yml
```

Leave the stack **Environment variables** table empty. On an LXC host, these
paths are on the Docker host. If the host is reached through an LXC or
reverse-proxy address, replace `LXC_HOST_IP` in the env file with the real
address and configure the reverse-proxy upstream accordingly.

Before first deploy, create and permission the persistent directories on the
Docker host. Match ownership to the container application user as appropriate:

```bash
sudo mkdir -p /opt/bearbiz/media /opt/bearbiz/backups
sudo chown -R 1000:1000 /opt/bearbiz/media /opt/bearbiz/backups
```

The PostgreSQL named volume `bearbiz_postgres`, the media bind mount, and the
backup bind mount are persistent. Keep them when updating the repository; never
run `docker compose -f compose.portainer.yml down -v` during an upgrade. Deploy
a new tag, verify the backup, then let the web container apply migrations before
checking `/health/`. Copy backups to separate durable storage and test restores.

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
