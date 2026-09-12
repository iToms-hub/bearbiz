from __future__ import annotations

import json
import os
import re
import fcntl
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings as django_settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .ai import fetch_available_model_names as fetch_ai_model_suggestions, probe_ai_endpoint
from .forms import AIIntegrationSettingsForm, FiscalYearSettingsForm
from .models import AIIntegrationSettings, FiscalYearSettings
from .navigation import settings_tabs, shell_context


def coming_soon(request: HttpRequest, feature: str) -> HttpResponse:
    """Render a clear placeholder for navigation sections not yet implemented."""
    context = shell_context(
        section=feature.lower().replace(" ", "-"),
        page_title=feature,
        eyebrow=feature,
        subtitle=f"{feature} is planned for a future Bearbiz release.",
        coming_soon_feature=feature,
    )
    return render(request, "coming_soon.html", context)


def settings_page(request: HttpRequest, slug: str = "theme") -> HttpResponse:
    if slug == "general":
        slug = "theme"
    if slug not in {"theme", "fiscal", "ai", "backup"}:
        raise Http404("Unknown settings section.")

    fiscal_settings = FiscalYearSettings.current()
    ai_settings = AIIntegrationSettings.current()
    tabs = settings_tabs(slug)

    if slug == "backup":
        context = shell_context(
            section="settings", page_title="Settings",
            subtitle="Manage backup health, verification, retention, and restore-point history.",
            top_tabs=tabs, fiscal_settings=fiscal_settings, ai_settings=ai_settings,
            section_slug=slug, backup=backup_snapshot(),
        )
        return render(request, "settings/page.html", context)

    if slug == "fiscal":
        if request.method == "POST":
            form = FiscalYearSettingsForm(request.POST, instance=fiscal_settings)
            if form.is_valid():
                form.save()
                return redirect("settings:fiscal")
        else:
            form = FiscalYearSettingsForm(instance=fiscal_settings)

        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="Configure calendar and integration settings for Bearbiz.",
            top_tabs=tabs,
            form=form,
            settings=fiscal_settings,
            ai_settings=ai_settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    if slug == "ai":
        available_models = fetch_ai_model_suggestions(ai_settings)
        probe_result = None
        if request.method == "POST":
            form = AIIntegrationSettingsForm(request.POST, instance=ai_settings, available_models=available_models)
            action = request.POST.get("action", "save")
            if form.is_valid():
                if action == "test":
                    ai_settings = form.save()
                    probe_result = probe_ai_endpoint(ai_settings)
                    available_models = probe_result.models or available_models
                    form = AIIntegrationSettingsForm(
                        instance=ai_settings,
                        available_models=available_models,
                    )
                else:
                    form.save()
                    return redirect("settings:ai")
        else:
            form = AIIntegrationSettingsForm(instance=ai_settings, available_models=available_models)

        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="AI integration and assistant settings land here next.",
            top_tabs=tabs,
            form=form,
            settings=ai_settings,
            fiscal_settings=fiscal_settings,
            available_models=available_models,
            probe_result=probe_result,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    if slug == "theme":
        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="Customize Bearbiz colors and light/dark mode behavior.",
            top_tabs=tabs,
            fiscal_settings=fiscal_settings,
            ai_settings=ai_settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    context = shell_context(
        section="settings",
        page_title="Settings",
        subtitle="General Bearbiz configuration and owners/users will live here.",
        top_tabs=tabs,
        fiscal_settings=fiscal_settings,
        ai_settings=ai_settings,
        section_slug=slug,
    )
    return render(request, "settings/page.html", context)


@require_POST
def ai_connection_test(request: HttpRequest) -> JsonResponse:
    payload = _request_json(request)
    result = probe_ai_endpoint(payload or None)
    status = 200 if result.ok else 400
    return JsonResponse(
        {
            "ok": result.ok,
            "provider": result.provider,
            "model": result.models[0] if result.models else "",
            "model_suggestions": list(result.models),
            "payload": result.payload,
            "error": result.error,
        },
        status=status,
    )


@require_POST
def backup_action(request: HttpRequest) -> HttpResponse:
    action = request.POST.get("action")
    if action == "restore-select":
        return _restore_selection(request)
    if action == "restore-cancel":
        request.session.pop("backup_restore", None)
        return _backup_page(request)
    if action == "restore-confirm":
        return _restore_confirm(request)
    if action not in {"run", "verify"}:
        raise Http404("Unknown backup action.")
    args = ["backup"] if action == "run" else ["verify"]
    snapshot = backup_snapshot()
    if action == "verify":
        if not snapshot["latest"]:
            return _backup_page(request, "No backup is available to verify.", False)
        args.append(snapshot["latest"]["id"])
    try:
        result = subprocess.run(
            [str(_backup_script()), *args], cwd=django_settings.BASE_DIR,
            env=os.environ.copy(), capture_output=True, text=True, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _backup_page(request, f"Backup {action} failed: {exc}", False)
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[-1] if lines else "unknown error"
        return _backup_page(request, f"Backup {action} failed: {detail}", False)
    message = "Backup completed successfully." if action == "run" else "Latest backup verified successfully."
    return _backup_page(request, message, True)


def _restore_selection(request: HttpRequest) -> HttpResponse:
    backup_id = request.POST.get("backup_id", "")
    mode = request.POST.get("restore_mode", "db-only")
    if _backup_in_progress():
        return _backup_page(request, "A backup or restore is already running. Try again when it finishes.", False)
    if _restore_record(backup_id, mode) is None:
        return _backup_page(request, "That restore point is unavailable, incomplete, or not verified.", False)
    request.session["backup_restore"] = {"id": backup_id, "mode": mode}
    return _backup_page(request)


def _restore_confirm(request: HttpRequest) -> HttpResponse:
    pending = request.session.pop("backup_restore", None)
    backup_id = request.POST.get("backup_id", "")
    mode = request.POST.get("restore_mode", "")
    if not isinstance(pending, dict) or pending.get("id") != backup_id or pending.get("mode") != mode:
        return _backup_page(request, "Restore confirmation expired or did not match the selected backup.", False)
    if _backup_in_progress():
        return _backup_page(request, "A backup or restore is already running. Try again when it finishes.", False)
    if _restore_record(backup_id, mode) is None:
        return _backup_page(request, "That restore point is unavailable, incomplete, or not verified.", False)
    args = ["restore", backup_id, "--db-only" if mode == "db-only" else "--full", "--yes"]
    try:
        result = subprocess.run(
            [str(_backup_script()), *args], cwd=django_settings.BASE_DIR,
            env=os.environ.copy(), capture_output=True, text=True, timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _backup_page(request, f"Restore failed safely: {exc}", False)
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[-1] if lines else "unknown error"
        return _backup_page(request, f"Restore failed safely: {detail}", False)
    return _backup_page(request, f"Restore completed for {backup_id} ({mode}).", True)


def _backup_page(request: HttpRequest, message: str = "", ok: bool = False) -> HttpResponse:
    pending = request.session.get("backup_restore") if hasattr(request, "session") else None
    confirmation = None
    if isinstance(pending, dict):
        confirmation = _restore_record(str(pending.get("id", "")), str(pending.get("mode", "db-only")))
    context = shell_context(
        section="settings", page_title="Settings",
        subtitle="Manage backup health, verification, retention, and restore-point history.",
        top_tabs=settings_tabs("backup"), section_slug="backup", backup=backup_snapshot(),
        backup_message=message, backup_message_ok=ok, backup_confirmation=confirmation,
    )
    return render(request, "settings/page.html", context)


def _backup_script() -> Path:
    return Path(django_settings.BASE_DIR) / "scripts" / "bearbiz-backup.sh"


def backup_snapshot() -> dict[str, object]:
    root = Path(os.environ.get("BACKUP_ROOT", str(Path.home() / "backups" / "bearbiz")))
    records = []
    if root.is_dir():
        paths = sorted((p for p in root.iterdir() if p.is_dir() and _backup_id(p.name)), reverse=True)
        for path in paths:
            manifest = _read_manifest(path / "manifest.txt")
            timestamp = manifest.get("created_at_utc", "")
            records.append({
                "id": path.name, "type": manifest.get("mode", "full"), "timestamp": timestamp,
                "size": _directory_size(path), "database_size": _file_size(path / "database.dump"),
                "media_size": _file_size(path / "media.tar.gz"), "verified": _verification_state(path),
                "created": _parse_time(timestamp),
            })
            records[-1]["size_display"] = _format_bytes(records[-1]["size"])
            records[-1]["database_size_display"] = _format_bytes(records[-1]["database_size"])
            records[-1]["media_size_display"] = _format_bytes(records[-1]["media_size"])
            records[-1]["restore_available"] = _restore_record_from_path(path, records[-1], "db-only") is not None
            records[-1]["full_restore_available"] = _restore_record_from_path(path, records[-1], "full") is not None
    records.sort(key=lambda item: item["created"], reverse=True)
    latest = records[0] if records else None
    status = _read_backup_status(root / "status.json")
    schedule = status.get("schedule") or os.environ.get("BACKUP_SCHEDULE") or "Not configured - run manually."
    if status.get("state") == "failed":
        status_message = "The latest backup attempt failed."
    elif latest:
        status_message = "A verified backup is available."
    else:
        status_message = "No backup has been created yet."
    storage_warning = ""
    if os.environ.get("BACKUP_STORAGE_MODE") == "named-volume":
        storage_warning = "Named-volume backups remain on this deployment host; copy them off-host for disaster recovery."
    return {
        "status": "healthy" if latest and latest["verified"] == "verified" and status.get("state") != "failed" else "warning",
        "records": records, "latest": latest, "count": len(records),
        "last_attempted": status.get("last_attempted") or (latest["timestamp"] if latest else "None recorded"),
        "last_failed": status.get("last_failed", "None recorded"), "failure_reason": status.get("failure_reason", ""),
        "storage_path": str(root), "schedule": schedule, "storage_warning": storage_warning,
        "status_message": status_message,
        "retention": os.environ.get("RETENTION_COUNT", "7"),
    }


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(max(value, 0))
    unit = units[-1]
    for unit in units:
        if amount < 1000 or unit == units[-1]:
            break
        amount /= 1000
    return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"


def _restore_record(backup_id: str, mode: str) -> dict[str, object] | None:
    if not _backup_id(backup_id) or mode not in {"db-only", "full"}:
        return None
    root = Path(os.environ.get("BACKUP_ROOT", str(Path.home() / "backups" / "bearbiz")))
    record = next((item for item in backup_snapshot()["records"] if item["id"] == backup_id), None)
    return _restore_record_from_path(root / backup_id, record, mode) if isinstance(record, dict) else None


def _restore_record_from_path(path: Path, record: dict[str, object] | None, mode: str) -> dict[str, object] | None:
    if not record or record.get("verified") != "verified" or not (path / "manifest.txt").is_file():
        return None
    if not (path / "database.dump").is_file() or (mode == "full" and not (path / "media.tar.gz").is_file()):
        return None
    return record


def _backup_in_progress() -> bool:
    root = Path(os.environ.get("BACKUP_ROOT", str(Path.home() / "backups" / "bearbiz")))
    lock_path = Path(os.environ.get("BACKUP_LOCK_FILE", str(root / "backup.lock")))
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except (BlockingIOError, OSError):
        return True
    return False


def _read_backup_status(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _backup_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8}T\d{6}Z(?:-\d+)?", value))


def _read_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return dict(line.split("=", 1) for line in path.read_text(errors="replace").splitlines() if "=" in line)


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _verification_state(path: Path) -> str:
    if not (path / "SHA256SUMS").is_file():
        return "not verified"
    try:
        subprocess.run(["sha256sum", "--check", "SHA256SUMS", "--status"], cwd=path, check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "verified"


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


@require_GET
def ai_model_suggestions(request: HttpRequest) -> JsonResponse:
    try:
        suggestions = _fetch_model_suggestions(request.GET or None)
    except Exception as exc:
        return JsonResponse({"ok": False, "models": [], "error": str(exc)}, status=400)

    return JsonResponse({"ok": True, "models": list(suggestions)})


def _fetch_model_suggestions(source: object | None = None) -> tuple[str, ...]:
    try:
        suggestions = fetch_ai_model_suggestions(source)
    except TypeError:
        suggestions = fetch_ai_model_suggestions()
    return tuple(suggestions)


def _request_json(request: HttpRequest) -> dict[str, object]:
    try:
        import json

        if not request.body:
            return {}
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
