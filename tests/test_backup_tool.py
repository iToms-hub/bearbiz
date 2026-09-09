from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "bearbiz-backup.sh"


def run_tool(*args: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=cwd,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


def fake_docker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
case \" $* \" in
  *\ pg_dump\ *) printf 'fake postgres custom dump\\n' ;;
  *\ pg_restore\ *) cat >/dev/null ;;
  *) exit 2 ;;
esac
"""
    )
    path.chmod(0o755)


def failing_docker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
case \" $* \" in
  *\ pg_dump\ *) printf 'fake postgres custom dump\\n' ;;
  *\ pg_restore\ *) cat >/dev/null; exit 1 ;;
  *) exit 2 ;;
esac
"""
    )
    path.chmod(0o755)


def fake_postgres_clients(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
case "$(basename "$0") $*" in
  *pg_dump*) printf 'fake direct postgres custom dump\\n' ;;
  *pg_restore*) cat >/dev/null ;;
  *) exit 2 ;;
esac
"""
    )
    path.chmod(0o755)


def test_full_backup_writes_manifest_checksums_and_archive(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    media = tmp_path / "media"
    media.mkdir()
    (media / "report.pdf").write_bytes(b"report")
    backup_root = tmp_path / "backups"

    result = run_tool(
        "backup",
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "BACKUP_ROOT": str(backup_root),
            "MEDIA_ROOT": str(media),
            "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        },
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    backup_id = result.stdout.strip()
    backup = backup_root / backup_id
    assert (backup / "database.dump").is_file()
    assert (backup / "media.tar.gz").is_file()
    assert (backup / "manifest.txt").read_text().endswith("mode=full\n")
    assert "database.dump" in (backup / "SHA256SUMS").read_text()

    verified = run_tool(
        "verify",
        backup_id,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "BACKUP_ROOT": str(backup_root),
            "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        },
        cwd=tmp_path,
    )
    assert verified.returncode == 0, verified.stderr


def test_db_only_backup_and_restore_confirmation_guard(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "MEDIA_ROOT": str(tmp_path / "missing-media"),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
    }

    result = run_tool("backup", "--db-only", env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    backup_id = result.stdout.strip()
    backup = backup_root / backup_id
    assert not (backup / "media.tar.gz").exists()
    assert "mode=db-only" in (backup / "manifest.txt").read_text()

    restore = run_tool("restore", backup_id, "--db-only", env=env, cwd=tmp_path)
    assert restore.returncode != 0
    assert "--yes" in restore.stderr


def test_dry_run_does_not_create_backup(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    result = run_tool(
        "backup",
        "--dry-run",
        env={"BACKUP_ROOT": str(backup_root), "PATH": f"{bin_dir}:/bin"},
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert not backup_root.exists()

    invalid = run_tool(
        "backup",
        "--dry-run",
        "--not-an-option",
        env={"BACKUP_ROOT": str(backup_root), "PATH": f"{bin_dir}:/bin"},
        cwd=tmp_path,
    )
    assert invalid.returncode != 0
    assert "unknown backup option" in invalid.stderr


def test_failed_backup_removes_stale_and_new_partial_sets(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    failing_docker(bin_dir / "docker")
    backup_root = tmp_path / "backups"
    stale = backup_root / ".partial-old-interrupted"
    stale.mkdir(parents=True)
    (stale / "database.dump").write_text("stale")

    result = run_tool(
        "backup",
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "BACKUP_ROOT": str(backup_root),
            "MEDIA_ROOT": str(tmp_path / "missing-media"),
            "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        },
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert list(backup_root.glob(".partial-*")) == []


def test_direct_mode_uses_postgres_clients_without_docker(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_postgres_clients(bin_dir / "pg_dump")
    fake_postgres_clients(bin_dir / "pg_restore")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "BACKUP_EXECUTION_MODE": "direct",
        "PGHOST": "db",
        "PGPORT": "5432",
        "PGPASSWORD": "bearbiz",
        "MEDIA_ROOT": str(tmp_path / "missing-media"),
    }

    result = run_tool("backup", "--db-only", env=env, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    backup_id = result.stdout.strip()
    assert (backup_root / backup_id / "database.dump").read_text() == "fake direct postgres custom dump\n"


def test_backup_normalizes_shared_mount_ownership_and_permissions(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_postgres_clients(bin_dir / "pg_dump")
    fake_postgres_clients(bin_dir / "pg_restore")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "BACKUP_EXECUTION_MODE": "direct",
        "BACKUP_OWNER_UID": str(os.getuid()),
        "BACKUP_OWNER_GID": str(os.getgid()),
    }

    result = run_tool("backup", "--db-only", env=env, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    backup = backup_root / result.stdout.strip()
    assert backup.stat().st_uid == os.getuid()
    assert (backup / "database.dump").stat().st_uid == os.getuid()
    assert backup.stat().st_mode & 0o777 == 0o750
    assert (backup / "database.dump").stat().st_mode & 0o777 == 0o640
