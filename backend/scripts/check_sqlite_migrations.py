"""Apply the complete Alembic chain to a clean temporary SQLite database."""

from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    # Windows may release SQLite's file handle a moment after the migration
    # subprocess exits; cleanup must not turn a successful smoke into a flaky
    # failure.
    with tempfile.TemporaryDirectory(
        prefix="curriculum-kag-migration-", ignore_cleanup_errors=True
    ) as directory:
        database = Path(directory) / "migration.db"
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        with sqlite3.connect(database) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            if "cli_token_version" not in columns:
                raise RuntimeError("SQLite migration did not create users.cli_token_version")
        print("SQLite migration smoke passed: clean database reached Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
