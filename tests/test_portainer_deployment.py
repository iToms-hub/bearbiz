from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_portainer_stack_builds_immutable_runtime_and_persists_host_data() -> None:
    compose = (ROOT / "compose.portainer.yml").read_text()

    assert "context: ." in compose
    assert "- .:/app" not in compose
    assert "${BEARBIZ_ENV_FILE:-/opt/bearbiz.env}" in compose
    assert "/opt/bearbiz/media:/app/media" in compose
    assert "/opt/bearbiz/backups:/backups/bearbiz" in compose
    assert '"8002:8000"' in compose
    assert "SECRET_KEY: ${" not in compose
    assert "ALLOWED_HOSTS: ${" not in compose
    assert "POSTGRES_PASSWORD: ${" not in compose
    assert "env_file:" in compose
    assert "POSTGRES_HOST: db" in compose
    assert "condition: service_healthy" in compose
    assert "migrate --noinput" in compose
    assert "restart: unless-stopped" in compose
    assert "/var/run/docker.sock" not in compose


def test_portainer_instructions_use_host_env_file_not_ui_variables() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "/opt/bearbiz.env" in readme
    assert "chmod 600 /opt/bearbiz.env" in readme
    assert "UI" in readme
    assert "environment rows" in readme
    assert "BEARBIZ_ENV_FILE" in readme
    for variable in (
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "ALLOWED_HOSTS",
        "DJANGO_ALLOWED_HOSTS",
        "DEBUG",
        "POSTGRES_DB",
        "POSTGRES_USER",
    ):
        assert variable in readme


def test_docker_image_copies_runtime_files_not_source_mount() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    for directory in ("bearbiz", "apps", "templates", "static", "scripts"):
        assert f"COPY {directory} /app/{directory}" in dockerfile
    assert "mkdir -p /app/media/reports /app/staticfiles" in dockerfile