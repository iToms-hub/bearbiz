from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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
    assert "No backup has been created yet." in html
    assert "Backup history" in html
    assert "Restore" in html


def test_named_volume_backup_snapshot_warns_about_local_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("BACKUP_STORAGE_MODE", "named-volume")

    snapshot = views.backup_snapshot()

    assert snapshot["schedule"] == "Not configured - run manually."
    warning = str(snapshot["storage_warning"])
    assert "not an off-host" not in warning
    assert "off-host" in warning


def test_backup_snapshot_distinguishes_failed_attempt_from_fresh_install(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "backups"
    root.mkdir()
    (root / "status.json").write_text('{"state":"failed","failure_reason":"pg_dump failed"}')
    monkeypatch.setenv("BACKUP_ROOT", str(root))

    snapshot = views.backup_snapshot()

    assert snapshot["status_message"] == "The latest backup attempt failed."


def test_backup_history_template_right_aligns_accessible_restore_action() -> None:
    template = Path("templates/settings/page.html").read_text()
    styles = Path("templates/base.html").read_text()

    assert '<tr><th>ID</th><th>Type</th><th>Timestamp</th><th>Size</th><th>Verification</th><th class="restore-actions">Actions</th></tr>' in template
    assert '<table class="backup-history-table"><colgroup>' in template
    assert '<col class="backup-col-timestamp"><col class="backup-col-size">' in template
    assert '<td class="restore-actions">{% if record.restore_available %}' in template
    assert 'class="restore-form"' in template
    assert '<select name="restore_mode" aria-label="Restore mode for {{ record.id }}">' in template
    assert '<option value="db-only">Database only</option>' in template
    assert '<option value="full">Database + media</option>' in template
    assert 'type="radio" name="restore_mode"' not in template
    assert 'class="restore-button" aria-label="Restore backup {{ record.id }}"' in template
    assert 'value="delete-select"' in template
    assert 'aria-label="Delete backup {{ record.id }}"' in template
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
def test_complete_backup_download_contains_database_media_manifest_and_checksums(client, tmp_path: Path, monkeypatch) -> None:
    backup_root = tmp_path / "backups"
    backup_dir = backup_root / "20260908T120000Z"
    backup_dir.mkdir(parents=True)
    for name, content in {
        "manifest.txt": b"backup_id=20260908T120000Z\nmode=full\n",
        "database.dump": b"database",
        "media.tar.gz": b"media",
        "SHA256SUMS": b"checksums",
    }.items():
        (backup_dir / name).write_bytes(content)
    monkeypatch.setenv("BACKUP_ROOT", str(backup_root))
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")

    response = client.get(reverse("settings:backup-download"))

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
        assert set(bundle.namelist()) == {"manifest.txt", "database.dump", "media.tar.gz", "SHA256SUMS"}


@pytest.mark.django_db
def test_uploaded_complete_backup_is_verified_and_requires_restore_confirmation(client, tmp_path: Path, monkeypatch) -> None:
    backup_id = "20260908T120000Z"
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("manifest.txt", f"backup_id={backup_id}\nmode=full\n")
        bundle.writestr("database.dump", b"database")
        bundle.writestr("media.tar.gz", b"media")
        bundle.writestr("SHA256SUMS", b"checksums")
    record = {"id": backup_id, "timestamp": "2026-09-08T12:00:00Z", "verified": "verified", "size_display": "1 KB", "full_restore_available": True}
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")
    monkeypatch.setattr(views, "backup_snapshot", lambda: {"records": [record], "latest": record, "latest_full": record, "count": 1, "storage_path": "/backups", "schedule": "manual", "retention": "7", "last_attempted": "None", "last_failed": "None", "failure_reason": "", "status": "healthy", "status_message": "A verified backup is available."})
    monkeypatch.setattr(views.subprocess, "run", lambda *args, **kwargs: CompletedProcess(args[0], 0, stdout="", stderr=""))

    response = client.post(reverse("settings:backup-action"), {
        "action": "upload",
        "backup_zip": SimpleUploadedFile("bearbiz.zip", payload.getvalue(), content_type="application/zip"),
    })

    assert response.status_code == 200
    assert b"Confirm restore" in response.content
    assert client.session["backup_restore"] == {"id": backup_id, "mode": "full"}


@pytest.mark.django_db
@pytest.mark.parametrize("session_state", ["missing", "stale"])
def test_uploaded_backup_confirmation_uses_signed_handoff_when_session_is_unavailable_or_stale(
    client, tmp_path: Path, monkeypatch, session_state: str
) -> None:
    backup_id = "20260908T120000Z"
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("manifest.txt", f"backup_id={backup_id}\nmode=full\n")
        bundle.writestr("database.dump", b"database")
        bundle.writestr("media.tar.gz", b"media")
        bundle.writestr("SHA256SUMS", b"checksums")
    record = {"id": backup_id, "timestamp": "2026-09-08T12:00:00Z", "verified": "verified", "size_display": "1 KB", "full_restore_available": True}
    monkeypatch.setenv("BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(views, "_verification_state", lambda path: "verified")
    monkeypatch.setattr(views, "backup_snapshot", lambda: {"records": [record], "latest": record, "latest_full": record, "count": 1, "storage_path": "/backups", "schedule": "manual", "retention": "7", "last_attempted": "None", "last_failed": "None", "failure_reason": "", "status": "healthy", "status_message": "A verified backup is available."})
    monkeypatch.setattr(views, "_restore_record", lambda selected_id, mode: record if selected_id == backup_id and mode == "full" else None)
    from subprocess import CompletedProcess
    calls = []
    monkeypatch.setattr(views.subprocess, "run", lambda command, **kwargs: (calls.append(command) or CompletedProcess(command, 0, stdout="", stderr="")))

    upload = client.post(reverse("settings:backup-action"), {
        "action": "upload",
        "backup_zip": SimpleUploadedFile("bearbiz.zip", payload.getvalue(), content_type="application/zip"),
    })
    html = upload.content.decode()
    token_match = re.search(r'name="restore_token" value="([^"]+)"', html)
    assert token_match
    token = token_match.group(1)
    session = client.session
    if session_state == "missing":
        session.pop("backup_restore", None)
    else:
        session["backup_restore"] = {"id": "20260907T120000Z", "mode": "db-only"}
    session.save()

    response = client.post(reverse("settings:backup-action"), {
        "action": "restore-confirm", "backup_id": backup_id, "restore_mode": "full", "restore_token": token,
    })

    assert b"Restore completed" in response.content
    assert len(calls) == 2


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
    selection = client.post(reverse("settings:backup-action"), {"action": "restore-select", **payload})
    token_match = re.search(r'name="restore_token" value="([^"]+)"', selection.content.decode())
    assert token_match
    response = client.post(reverse("settings:backup-action"), {"action": "restore-confirm", **payload, "restore_token": token_match.group(1)})
    duplicate = client.post(reverse("settings:backup-action"), {"action": "restore-confirm", **payload, "restore_token": token_match.group(1)})

    assert response.status_code == 200
    assert b"Restore completed" in response.content
    assert b"confirmation expired" in duplicate.content
    assert len(calls) == 1


@pytest.mark.django_db
def test_restore_failure_surfaces_all_actionable_stderr(client, monkeypatch) -> None:
    record = {"id": "20260908T120000Z", "timestamp": "2026-09-08T12:00:00Z", "verified": "verified", "size_display": "1 KB"}
    monkeypatch.setattr(views, "_restore_record", lambda backup_id, mode: record)
    monkeypatch.setattr(views, "_backup_in_progress", lambda: False)
    monkeypatch.setattr(views.subprocess, "run", lambda command, **kwargs: CompletedProcess(
        command, 1, stdout="", stderr="pg_restore: error: relation \"facts\" does not exist\npg_restore: warning: errors ignored on restore: 12\n"
    ))
    selection = client.post(reverse("settings:backup-action"), {"action": "restore-select", "backup_id": record["id"], "restore_mode": "db-only"})
    token = re.search(r'name="restore_token" value="([^"]+)"', selection.content.decode()).group(1)

    response = client.post(reverse("settings:backup-action"), {
        "action": "restore-confirm", "backup_id": record["id"], "restore_mode": "db-only", "restore_token": token,
    })

    body = response.content.decode()
    assert "relation &quot;facts&quot; does not exist" in body
    assert "errors ignored on restore: 12" in body


@pytest.mark.django_db
def test_delete_requires_two_steps_and_removes_only_selected_backup(client, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "backups"
    selected = root / "20260908T120000Z"
    other = root / "20260908T130000Z"
    selected.mkdir(parents=True)
    other.mkdir(parents=True)
    (root / "safety-backup").mkdir()
    monkeypatch.setenv("BACKUP_ROOT", str(root))
    monkeypatch.setattr(views, "_backup_in_progress", lambda: False)

    selection = client.post(reverse("settings:backup-action"), {"action": "delete-select", "backup_id": selected.name})
    assert selection.status_code == 200
    assert selected.exists()
    token = re.search(r'name="delete_token" value="([^"]+)"', selection.content.decode()).group(1)

    first = client.post(reverse("settings:backup-action"), {"action": "delete-confirm", "backup_id": selected.name})
    assert b"Delete confirmation expired" in first.content
    assert selected.exists()

    deleted = client.post(reverse("settings:backup-action"), {
        "action": "delete-confirm", "backup_id": selected.name, "delete_token": token,
    })
    assert b"Backup 20260908T120000Z deleted" in deleted.content
    assert not selected.exists()
    assert other.exists()
    assert (root / "safety-backup").exists()

    duplicate = client.post(reverse("settings:backup-action"), {
        "action": "delete-confirm", "backup_id": selected.name, "delete_token": token,
    })
    assert b"Delete confirmation expired" in duplicate.content or b"unavailable" in duplicate.content


@pytest.mark.django_db
def test_delete_refuses_while_backup_is_in_progress(client, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "backups"
    target = root / "20260908T120000Z"
    target.mkdir(parents=True)
    monkeypatch.setenv("BACKUP_ROOT", str(root))
    monkeypatch.setattr(views, "_backup_in_progress", lambda: True)

    response = client.post(reverse("settings:backup-action"), {"action": "delete-select", "backup_id": target.name})

    assert b"already running" in response.content
    assert target.exists()
