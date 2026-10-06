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


def failing_final_media_move(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
if [[ "${FAIL_FINAL_MOVE:-0}" == 1 && "$*" == *".media-restore."* ]]; then
  exit 23
fi
exec /bin/mv \"$@\"
"""
    )
    path.chmod(0o755)



def fail_first_restore_then_recover(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
case \" $* \" in
  *\ pg_dump\ *) printf 'fake postgres custom dump\\n' ;;
  *\ pg_restore\ *--list*) cat >/dev/null ;;
  *\ pg_restore\ *)
    count_file=\"${FAKE_COUNT:?}\"
    count=0
    [[ -f \"$count_file\" ]] && count=$(<\"$count_file\")
    count=$((count + 1)); printf '%s' \"$count\" >\"$count_file\"
    cat >/dev/null
    ((count == 1)) && exit 7
    ;;
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


def strict_restore_postgres_clients(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s %s\\n' "$(basename "$0")" "$*" >> "${FAKE_LOG:?}"
case "$(basename "$0") $*" in
  *pg_dump*) printf 'fake direct postgres custom dump\\n' ;;
  *pg_restore*--list*) cat >/dev/null ;;
  *pg_restore*--no-owner*--exit-on-error*--dbname=*) cat >/dev/null ;;
  *pg_restore*--clean*) printf 'pg_restore must not use --clean\\n' >&2; exit 2 ;;
  *pg_restore*) printf 'pg_restore requires safe restore flags\\n' >&2; exit 2 ;;
  *psql*--no-psqlrc*--set=ON_ERROR_STOP=1*--dbname=*--command=*) : ;;
  *psql*) printf 'psql requires fail-fast schema reset flags\\n' >&2; exit 2 ;;
  *) exit 2 ;;
esac
"""
    )
    path.chmod(0o755)


def strict_compose_client(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "${FAKE_LOG:?}"
case "$*" in
  *pg_dump*) printf 'fake compose postgres custom dump\\n' ;;
  *pg_restore*) cat >/dev/null ;;
  *psql*--no-psqlrc*--set=ON_ERROR_STOP=1*--dbname=*) : ;;
  *) printf 'unsupported compose command: %s\\n' "$*" >&2; exit 2 ;;
esac
"""
    )
    path.chmod(0o755)


def assert_safe_restore_calls(calls: list[str], reset_prefix: str = "psql ") -> None:
    reset_index = next(index for index, call in enumerate(calls) if reset_prefix in call)
    restore_index = next(
        index for index, call in enumerate(calls)
        if "pg_restore " in call and "--list" not in call
    )
    assert reset_index < restore_index
    assert "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" in calls[reset_index]
    assert "--clean" not in calls[restore_index]
    assert "--exit-on-error" in calls[restore_index]


def test_compose_restore_resets_public_schema_before_pg_restore(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    strict_compose_client(bin_dir / "docker")
    backup_root = tmp_path / "backups"
    media = tmp_path / "media"
    media.mkdir()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        "FAKE_LOG": str(tmp_path / "compose.log"),
        "MEDIA_ROOT": str(media),
    }

    backup = run_tool("backup", "--db-only", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr
    restored = run_tool("restore", backup.stdout.strip(), "--db-only", "--yes", env=env, cwd=tmp_path)
    assert restored.returncode == 0, restored.stderr

    calls = (tmp_path / "compose.log").read_text().splitlines()
    assert_safe_restore_calls(calls)


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


def test_direct_restore_passes_database_target_while_reading_dump_from_stdin(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    strict_restore_postgres_clients(bin_dir / "pg_dump")
    strict_restore_postgres_clients(bin_dir / "pg_restore")
    strict_restore_postgres_clients(bin_dir / "psql")
    backup_root = tmp_path / "backups"
    media = tmp_path / "media"
    media.mkdir()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "BACKUP_EXECUTION_MODE": "direct",
        "PGHOST": "db",
        "PGPORT": "5432",
        "PGUSER": "bearbiz",
        "PGPASSWORD": "bearbiz",
        "PGDATABASE": "target_database",
        "FAKE_LOG": str(tmp_path / "postgres.log"),
        "MEDIA_ROOT": str(media),
    }

    backup = run_tool("backup", "--db-only", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr

    restored = run_tool("restore", backup.stdout.strip(), "--db-only", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode == 0, restored.stderr
    restore_calls = (tmp_path / "postgres.log").read_text().splitlines()
    assert_safe_restore_calls(restore_calls)







def test_failed_database_restore_restores_safety_dump_and_keeps_original_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fail_first_restore_then_recover(bin_dir / "docker")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        "FAKE_COUNT": str(tmp_path / "restore-count"),
        "MEDIA_ROOT": str(tmp_path / "media"),
    }
    backup = run_tool("backup", "--db-only", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr

    restored = run_tool("restore", backup.stdout.strip(), "--db-only", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode == 7
    assert (tmp_path / "restore-count").read_text() == "2"


def test_full_restore_replaces_media_from_normal_backup_archive(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    media = tmp_path / "media"
    media.mkdir()
    (media / "old.txt").write_text("old")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "MEDIA_ROOT": str(media),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
    }

    backup = run_tool("backup", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr
    (media / "old.txt").unlink()
    (media / "restored.txt").write_text("restored")

    restored = run_tool("restore", backup.stdout.strip(), "--full", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode == 0, restored.stderr
    assert (media / "old.txt").read_text() == "old"
    assert not (media / "restored.txt").exists()


def test_full_restore_preserves_original_media_when_final_replacement_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    failing_final_media_move(bin_dir / "mv")
    media = tmp_path / "media"
    media.mkdir()
    (media / "original.txt").write_text("original")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "MEDIA_ROOT": str(media),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
        "FAIL_FINAL_MOVE": "1",
    }

    backup = run_tool("backup", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr
    (media / "original.txt").unlink()
    (media / "current.txt").write_text("current")

    restored = run_tool("restore", backup.stdout.strip(), "--full", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode == 23
    assert (media / "current.txt").read_text() == "current"
    assert not (media / "original.txt").exists()
    assert not list(tmp_path.glob(".media-restore-backup.*"))


def test_full_restore_creates_missing_media_root_parent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    media = tmp_path / "missing" / "nested" / "media"
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "MEDIA_ROOT": str(media),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
    }

    source_media = tmp_path / "source-media"
    source_media.mkdir()
    (source_media / "restored.txt").write_text("restored")
    backup = run_tool("backup", env={**env, "MEDIA_ROOT": str(source_media)}, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr
    restored = run_tool("restore", backup.stdout.strip(), "--full", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode == 0, restored.stderr
    assert media.is_dir()


def test_full_restore_rejects_symlink_media_archive_without_touching_destination(tmp_path: Path) -> None:
    import tarfile

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker(bin_dir / "docker")
    media = tmp_path / "media"
    media.mkdir()
    (media / "original.txt").write_text("original")
    backup_root = tmp_path / "backups"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(backup_root),
        "MEDIA_ROOT": str(media),
        "COMPOSE_FILE": str(tmp_path / "compose.yml"),
    }
    backup = run_tool("backup", env=env, cwd=tmp_path)
    assert backup.returncode == 0, backup.stderr
    backup_dir = backup_root / backup.stdout.strip()
    archive = backup_dir / "media.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("media/escape")
        info.type = tarfile.SYMTYPE
        info.linkname = str(tmp_path / "outside")
        tar.addfile(info)
    subprocess.run(
        "sha256sum manifest.txt database.dump media.tar.gz > SHA256SUMS",
        shell=True,
        cwd=backup_dir,
        check=True,
    )

    restored = run_tool("restore", backup.stdout.strip(), "--full", "--yes", env=env, cwd=tmp_path)

    assert restored.returncode != 0
    assert (media / "original.txt").read_text() == "original"
    assert not (tmp_path / "outside").exists()


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
