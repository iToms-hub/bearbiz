from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_portainer_stack_uses_portable_image_and_persistent_volumes() -> None:
    compose = (ROOT / "compose.portainer.yml").read_text()

    assert 'image: "ghcr.io/itoms-hub/bearbiz:9.9.9"' in compose
    assert "ghcr.io/itoms-hub/bearbiz:${" not in compose
    assert "build:" not in compose
    assert "- .:/app" not in compose
    assert "SECRET_KEY: \"${SECRET_KEY:?" in compose
    assert "bearbiz_media:/app/media" in compose
    assert "bearbiz_backups:/backups/bearbiz" in compose
    assert "/opt/bearbiz/" not in compose
    assert '"8002:8000"' in compose
    assert "ALLOWED_HOSTS: \"${ALLOWED_HOSTS:?" in compose
    assert "CSRF_TRUSTED_ORIGINS: \"${CSRF_TRUSTED_ORIGINS:?Set CSRF_TRUSTED_ORIGINS in the Portainer stack environment}\"" in compose
    assert "POSTGRES_PASSWORD: \"${POSTGRES_PASSWORD:?" in compose
    assert "env_file:" not in compose
    assert "BEARBIZ_ENV_FILE" not in compose
    assert "/opt/bearbiz.env" not in compose
    assert "POSTGRES_HOST: db" in compose
    assert "condition: service_healthy" in compose
    assert "migrate --noinput" in compose
    assert "gunicorn bearbiz.wsgi:application" in compose
    assert "restart: unless-stopped" in compose
    assert "/var/run/docker.sock" not in compose
    assert "bearbiz_postgres:" in compose
    assert "bearbiz_media:" in compose
    assert "bearbiz_backups:" in compose
    assert "name: bearbiz_postgres" in compose
    assert "name: bearbiz_media" in compose
    assert "name: bearbiz_backups" in compose
    assert "${ALLOWED_HOSTS}}" not in compose


def test_portainer_workflow_publishes_safe_ghcr_tags() -> None:
    workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text()

    assert "packages: write" in workflow
    assert "secrets.GITHUB_TOKEN" in workflow
    assert "type=semver" in workflow
    assert "type=sha" in workflow
    assert "type=raw,value=latest,enable={{is_default_branch}}" in workflow
    assert 'tags: ["v*"]' in workflow
    assert "Verify release tag metadata" in workflow
    assert "expected=\"ghcr.io/${GITHUB_REPOSITORY,,}:${RELEASE_TAG#v}\"" in workflow
    assert "password:" in workflow
    assert "SECRET_KEY" not in workflow


def test_portainer_instructions_use_ui_variables() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "UI" in readme
    assert "environment rows" in readme
    assert "Environment" in readme
    assert "variables" in readme
    for variable in (
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "ALLOWED_HOSTS",
        "CSRF_TRUSTED_ORIGINS",
        "DEBUG",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "BACKUP_OWNER_UID",
        "BACKUP_OWNER_GID",
    ):
        assert variable in readme

    reference = (ROOT / "docs/portainer-deployment.md").read_text()
    assert "ghcr.io/itoms-hub/bearbiz:9.9.9" in reference
    assert "stack.env" in reference
    assert "Packages" in reference
    assert "intentionally edit the `image:`" in reference

    preflight = ROOT / "scripts/portainer-preflight.sh"
    assert preflight.is_file()
    preflight_text = preflight.read_text()
    assert "config --quiet" in preflight_text
    assert "pull web db" in preflight_text
    assert "down -v" not in preflight_text


def test_docker_image_copies_runtime_files_not_source_mount() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    for directory in ("bearbiz", "apps", "templates", "static", "scripts"):
        assert f"COPY {directory} /app/{directory}" in dockerfile
    assert "mkdir -p /app/media/reports /app/staticfiles" in dockerfile
    assert "collectstatic --noinput" in dockerfile


def test_static_assets_are_packaged_for_gunicorn_production() -> None:
    settings = (ROOT / "bearbiz/settings.py").read_text()
    dependencies = (ROOT / "pyproject.toml").read_text()

    assert '"whitenoise>=6.9,<7.0"' in dependencies
    assert '"whitenoise.middleware.WhiteNoiseMiddleware"' in settings
    assert "STATIC_URL = \"/static/\"" in settings