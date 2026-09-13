"""Verify a PostgreSQL dump/restore round-trip in an isolated database.

The CI PostgreSQL service is deliberately used as the source.  The script
creates a temporary sibling database, restores a custom-format dump into it,
checks the Alembic version table, and drops the sibling database in ``finally``.
It never runs against the production database and never mutates source rows.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _run(command: list[str]) -> None:
    timeout_seconds = max(60, int(os.getenv("RESTORE_COMMAND_TIMEOUT_SECONDS", "900")))
    safe_command = " ".join(
        "<redacted>" if any(token in part.lower() for token in ("password", "postgresql://", "postgresql+")) else part
        for part in command
    )
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Required PostgreSQL utility is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-2000:]
        raise SystemExit(f"PostgreSQL utility failed ({command[0]}): {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-1000:]
        raise SystemExit(
            f"PostgreSQL utility timed out after {timeout_seconds}s ({safe_command}); "
            f"partial_output={detail}"
        ) from exc


def _run_restore_stream(command: list[str], dump_path: Path) -> None:
    """Restore a host dump through stdin, avoiding Docker file-sharing/cp."""
    timeout_seconds = max(60, int(os.getenv("RESTORE_COMMAND_TIMEOUT_SECONDS", "900")))
    process = None
    try:
        with dump_path.open("rb") as stream:
            process = subprocess.Popen(
                command,
                stdin=stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        if process.returncode:
            detail = (stderr or stdout or b"").decode("utf-8", errors="replace")[-2000:]
            raise SystemExit(f"PostgreSQL restore failed ({command[0]}): {detail}")
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            process.kill()
            process.communicate()
        raise SystemExit(
            f"PostgreSQL restore stream timed out after {timeout_seconds}s"
        ) from exc


def _docker_cli() -> str | None:
    """Find Docker CLI for Windows hosts where PostgreSQL tools are not on PATH."""
    configured = os.getenv("DOCKER_CLI")
    candidates = [configured] if configured else []
    candidates.extend(["docker", r"C:\Users\User\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if shutil.which(candidate) or Path(candidate).exists():
                return candidate
        except OSError:
            continue
    return None


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, help="Existing custom-format dump to restore")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url or not database_url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL for restore verification")
    source = make_url(database_url)
    if not source.database or not source.host:
        raise SystemExit("DATABASE_URL must include a database and host")
    use_container_tools = not (shutil.which("pg_dump") and shutil.which("pg_restore"))
    docker = _docker_cli() if use_container_tools else None
    container = os.getenv("POSTGRES_CONTAINER", "curriculum-kag-postgres-shadow")
    if use_container_tools and not docker:
        raise SystemExit("pg_dump/pg_restore are absent and Docker CLI was not found")

    token = uuid.uuid4().hex[:10]
    restore_db = f"{source.database}_restore_{token}"
    libpq_source = source.set(drivername="postgresql")
    admin_url = libpq_source.set(database="postgres")
    restore_url = source.set(database=restore_db)
    restore_libpq_url = libpq_source.set(database=restore_db)
    dump_path = args.dump.resolve() if args.dump else Path(tempfile.gettempdir()) / f"curriculum-kag-{token}.dump"
    if args.dump and not dump_path.is_file():
        raise SystemExit(f"Backup dump does not exist: {dump_path}")
    container_dump_path = f"/tmp/curriculum-kag-{token}.dump"
    container_source = libpq_source.set(host="localhost", port=5432)
    container_source_url = container_source.render_as_string(hide_password=False)
    admin = None
    try:
        if use_container_tools and args.dump:
            # A large dump on a secondary Windows drive can block Docker's
            # file-sharing layer indefinitely.  Stream it directly to the
            # container's pg_restore instead of using docker cp.
            pass
        elif use_container_tools:
            _run([docker, "exec", container, "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                  "--file", container_dump_path, container_source_url])
        else:
            _run(["pg_dump", "--format=custom", "--no-owner", "--no-acl",
                  "--file", str(dump_path), database_url])
        admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{restore_db}"')
        if use_container_tools and args.dump:
            container_restore_url = restore_libpq_url.set(host="localhost", port=5432)
            _run_restore_stream(
                [docker, "exec", "-i", container, "pg_restore", "--exit-on-error",
                 "--no-owner", "--no-acl", "--dbname",
                 container_restore_url.render_as_string(hide_password=False)],
                dump_path,
            )
        elif use_container_tools:
            container_restore_url = restore_libpq_url.set(host="localhost", port=5432)
            _run([docker, "exec", container, "pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
                  "--dbname", container_restore_url.render_as_string(hide_password=False), container_dump_path])
        else:
            _run(["pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
                  "--dbname", restore_libpq_url.render_as_string(hide_password=False), str(dump_path)])
        engine = create_engine(restore_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                tables = {
                    row[0]
                    for row in connection.execute(text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public'"
                    ))
                }
                required_tables = {"users", "courses", "projects", "project_versions"}
                missing = sorted(required_tables - tables)
                if missing:
                    raise SystemExit("Restored database is missing required tables: " + ", ".join(missing))
                versions = []
                if "alembic_version" in tables:
                    versions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
        finally:
            engine.dispose()
        print(f"PostgreSQL restore round-trip passed: {restore_db} ({len(tables)} public tables; {len(versions)} Alembic row(s))")
        return 0
    finally:
        if admin is not None:
            try:
                with admin.cursor() as cursor:
                    cursor.execute(f'REVOKE CONNECT ON DATABASE "{restore_db}" FROM PUBLIC')
                    cursor.execute(f'ALTER DATABASE "{restore_db}" CONNECTION LIMIT 0')
                    cursor.execute(f'DROP DATABASE IF EXISTS "{restore_db}" WITH (FORCE)')
            finally:
                admin.close()
        if use_container_tools and docker:
            try:
                _run([docker, "exec", container, "rm", "-f", container_dump_path])
            except SystemExit:
                pass
        if not args.dump:
            dump_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
