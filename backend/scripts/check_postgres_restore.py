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
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"Required PostgreSQL utility is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-2000:]
        raise SystemExit(f"PostgreSQL utility failed ({command[0]}): {detail}") from exc


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url or not database_url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL for restore verification")
    source = make_url(database_url)
    if not source.database or not source.host:
        raise SystemExit("DATABASE_URL must include a database and host")
    if not shutil.which("pg_dump") or not shutil.which("pg_restore"):
        raise SystemExit("pg_dump and pg_restore are required for restore verification")

    token = uuid.uuid4().hex[:10]
    restore_db = f"{source.database}_restore_{token}"
    libpq_source = source.set(drivername="postgresql")
    admin_url = libpq_source.set(database="postgres")
    restore_url = source.set(database=restore_db)
    restore_libpq_url = libpq_source.set(database=restore_db)
    dump_path = Path(tempfile.gettempdir()) / f"curriculum-kag-{token}.dump"
    admin = None
    try:
        _run([
            "pg_dump", "--format=custom", "--no-owner", "--no-acl",
            "--file", str(dump_path), database_url,
        ])
        admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{restore_db}"')
        _run([
            "pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
            "--dbname", restore_libpq_url.render_as_string(hide_password=False),
            str(dump_path),
        ])
        engine = create_engine(restore_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                versions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
                if not versions:
                    raise SystemExit("Restored database has no Alembic version row")
        finally:
            engine.dispose()
        print(f"PostgreSQL restore round-trip passed: {restore_db} ({len(versions)} Alembic row(s))")
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
        dump_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
