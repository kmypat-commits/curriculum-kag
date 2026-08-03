"""Read-only check that the connected database is at the Alembic head.

This deliberately does not upgrade or mutate the database.  Deployments must
apply migrations explicitly; the acceptance gate only verifies that the
running database is not behind the checked-in migration graph.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    script = ScriptDirectory.from_config(config)
    expected = tuple(sorted(script.get_heads()))

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            current = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
    finally:
        engine.dispose()

    if current != expected:
        print(f"Alembic schema mismatch: current={current or 'none'} expected={expected or 'none'}", file=sys.stderr)
        return 1
    print(f"Alembic schema state: {current[0] if current else 'none'} (head)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
