"""Read-only audit for mojibake in user-visible SQLite text fields."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "curriculum_kag.db"
FIELDS = {
    "projects": ("title", "goal"),
    "learning_outcomes": ("lo_text",),
    "courses": ("title", "description"),
    "bridge_modules": ("title", "description"),
}
SUSPICIOUS = ("Ð", "Ñ", "Â", "Ã", "�")


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    report: dict[str, object] = {"database": str(DB_PATH), "fields": {}}
    total = 0
    for table, columns in FIELDS.items():
        for column in columns:
            where = " OR ".join(f'{column} LIKE ?' for _ in SUSPICIOUS)
            params = tuple(f"%{marker}%" for marker in SUSPICIOUS)
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE {where}', params
            ).fetchone()[0]
            report["fields"][f"{table}.{column}"] = count
            total += count
    report["suspicious_values"] = total
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
