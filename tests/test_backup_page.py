from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest
from django.urls import reverse

from apps.core import views


@pytest.mark.django_db
def test_backup_settings_page_is_one_page_and_shows_manual_controls(client, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    response = client.get(reverse("settings:backup"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Backup control center" in html
    assert "Run backup now" in html
    assert "Verify latest backup" in html
    assert "Not enabled" in html
    assert "Backup history" in html
    assert "Restore" in html


def test_backup_history_template_right_aligns_accessible_restore_action() -> None:
    template = Path("templates/settings/page.html").read_text()
    styles = Path("templates/base.html").read_text()

    assert '<tr><th>ID</th><th>Type</th><th>Timestamp</th><th>Size</th><th>Verification</th><th class="restore-actions">Restore</th></tr>' in template
    assert '<table class="backup-history-table"><colgroup>' in template
    assert '<col class="backup-col-timestamp"><col class="backup-col-size">' in template
    assert '<td class="restore-actions">{% if record.restore_available %}' in template
    assert 'class="restore-form"' in template
    assert '<select name="restore_mode" aria-label="Restore mode for {{ record.id }}">' in template
    assert '<option value="db-only">Database only</option>' in template
    assert '<option value="full">Database + media</option>' in template
    assert 'type="radio" name="restore_mode"' not in template
    assert 'class="restore-button" aria-label="Restore backup {{ record.id }}"' in template
    assert "gap: 0.35rem" in styles
    assert ".restore-actions { text-align: right; white-space: nowrap; }" in styles
    assert ".backup-history-table { table-layout: fixed; min-width: 68rem; }" in styles
    assert ".backup-history-table .backup-col-restore { width: 31%; }" in styles
    assert "flex-wrap: nowrap; gap: 0.35rem" in styles
    assert ".restore-form select" in styles
    assert '@media (max-width: 1100px)' in styles
    assert "justify-content: flex-end" in styles
    assert ".restore-button { background: #b42318" in styles


@pytest.mark.django_db
def test_backup_history_renders_mode_select_before_restore_button(client, monkeypatch) -> None:
    monkeypatch.setattr(views, "backup_snapshot", lambda: {
        "status": "healthy", "records": [{
            "id": "20260908T120000Z", "type": "full", "timestamp": "2026-09-08T12:00:00Z",
            "size_display": "1.2 KB", "verified": "verified", "restore_available": True,
            "full_restore_available": True,
        }], "latest": None, "count": 1, "storage_path": "/backups", "schedule": "nightly",
        "retention": "7", "last_attempted": "None recorded", "last_failed": "None recorded",
        "failure_reason": "",
    })

    response = client.get(reverse("settings:backup"))

    assert response.status_code == 200
    html = response.content.decode()
    select = '<select name="restore_mode" aria-label="Restore mode for 20260908T120000Z">'
    assert select in html
    assert '<option value="db-only">Database only</option>' in html
    assert '<option value="full">Database + media</option>' in html
    assert html.index(select) < html.index('class="restore-button"')


@pytest.mark.django_db
def test_verify_latest_without_restore_point_is_safe(client, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    response = client.post(reverse("settings:backup-action"), {"action": "verify"})

    assert response.status_code == 200
    assert b"No backup is available to verify" in response.content


@pytest.mark.django_db
def test_manual_backup_wires_direct_container_environment(client, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return CompletedProcess(command, 0, stdout="20260908T120000Z\n", stderr="")

    monkeypatch.setattr(views, "_backup_script", lambda: Path("/app/scripts/bearbiz-backup.sh"))
    monkeypatch.setattr(views.subprocess, "run", fake_run)

    response = client.post(reverse("settings:backup-action"), {"action": "run"})

    assert response.status_code == 200
    assert captured["command"] == ["/app/scripts/bearbiz-backup.sh", "backup"]


def test_compose_wires_shared_backup_mount_and_direct_postgres_mode() -> None:
    compose = Path(__file__).parents[1] / "compose.yml"
    text = compose.read_text()

    assert "BACKUP_EXECUTION_MODE: direct" in text
    assert "BACKUP_ROOT: /backups/bearbiz" in text
    assert "BACKUP_LOCK_FILE: /backups/bearbiz/backup.lock" in text
    assert "${BACKUP_ROOT:-/home/tome/backups/bearbiz}:/backups/bearbiz" in text
    assert "BACKUP_OWNER_UID: ${BACKUP_OWNER_UID:-1000}" in text
    assert "BACKUP_OWNER_GID: ${BACKUP_OWNER_GID:-1000}" in text


def test_web_image_pins_postgresql_backup_clients_to_database_major() -> None:
    dockerfile = Path(__file__).parents[1] / "Dockerfile"
    text = dockerfile.read_text()

    assert "postgresql-client-16" in text
    assert "postgresql-client\\n" not in text


@pytest.mark.django_db
def test_restore_selection_renders_confirmation_without_executing(client, monkeypatch) -> None:
    record = {
        "id": "20260908T120000Z", "timestamp": "2026-09-08T12:00:00Z",
        "verified": "verified", "size_display": "1.2 KB", "size": 1200,
    }
    monkeypatch.setattr(views, "_restore_record", lambda backup_id, mode: record)
    monkeypatch.setattr(views, "_backup_in_progress", lambda: False)
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")
    called = []
    monkeypatch.setattr(views.subprocess, "run", lambda *args, **kwargs: called.append(args))

    response = client.post(reverse("settings:backup-action"), {
        "action": "restore-select", "backup_id": record["id"], "restore_mode": "db-only",
    })

    assert response.status_code == 200
    assert b"Confirm restore" in response.content
    assert b"1.2 KB" in response.content
    assert called == []


@pytest.mark.django_db
def test_restore_confirmation_requires_matching_pending_selection(client, monkeypatch) -> None:
    monkeypatch.setattr(views, "_restore_record", lambda backup_id, mode: {"id": backup_id})
    monkeypatch.setattr(views, "_backup_in_progress", lambda: False)
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")
    called = []
    monkeypatch.setattr(views.subprocess, "run", lambda *args, **kwargs: called.append(args))

    response = client.post(reverse("settings:backup-action"), {
        "action": "restore-confirm", "backup_id": "20260908T120000Z", "restore_mode": "db-only",
    })

    assert response.status_code == 200
    assert b"confirmation expired" in response.content
    assert called == []


@pytest.mark.django_db
def test_restore_confirmation_executes_once_after_selection(client, monkeypatch) -> None:
    record = {"id": "20260908T120000Z", "timestamp": "2026-09-08T12:00:00Z", "verified": "verified", "size_display": "1 KB"}
    monkeypatch.setattr(views, "_restore_record", lambda backup_id, mode: record)
    monkeypatch.setattr(views, "_backup_in_progress", lambda: False)
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")
    from subprocess import CompletedProcess
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(views.subprocess, "run", fake_run)
    payload = {"backup_id": record["id"], "restore_mode": "db-only"}
    client.post(reverse("settings:backup-action"), {"action": "restore-select", **payload})
    response = client.post(reverse("settings:backup-action"), {"action": "restore-confirm", **payload})
    duplicate = client.post(reverse("settings:backup-action"), {"action": "restore-confirm", **payload})

    assert response.status_code == 200
    assert b"Restore completed" in response.content
    assert b"confirmation expired" in duplicate.content
    assert len(calls) == 1
