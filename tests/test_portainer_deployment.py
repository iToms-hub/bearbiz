from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_portainer_stack_builds_immutable_runtime_and_persists_host_data() -> None:
    compose = (ROOT / "compose.portainer.yml").read_text()

    assert "context: ." in compose
    assert "- .:/app" not in compose
    assert "${MEDIA_ROOT:-/opt/bearbiz/media}:/app/media" in compose
    assert "${BACKUP_ROOT:-/opt/bearbiz/backups}:/backups/bearbiz" in compose
    assert '"${WEB_PORT:-8002}:8000"' in compose
    assert "POSTGRES_HOST: db" in compose
    assert "condition: service_healthy" in compose
    assert "migrate --noinput" in compose
    assert "restart: unless-stopped" in compose
    assert "/var/run/docker.sock" not in compose


def test_docker_image_copies_runtime_files_not_source_mount() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    for directory in ("bearbiz", "apps", "templates", "static", "scripts"):
        assert f"COPY {directory} /app/{directory}" in dockerfile
    assert "mkdir -p /app/media/reports /app/staticfiles" in dockerfile