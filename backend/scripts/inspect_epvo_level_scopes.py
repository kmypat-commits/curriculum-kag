"""Compact EPVO direction/group counts by education level prefix."""

from __future__ import annotations

import argparse
import json
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="curriculum_kag.db")
    parser.add_argument("--prefix", default="8D")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        directions = connection.execute(
            "SELECT code, title_ru, education_level FROM epvo_directions "
            "WHERE upper(code) LIKE upper(?) ORDER BY code LIMIT ?",
            (f"{args.prefix}%", args.limit),
        ).fetchall()
        groups = connection.execute(
            "SELECT g.code, g.title_ru, g.direction_code FROM epvo_groups g "
            "JOIN epvo_directions d ON d.code = g.direction_code "
            "WHERE upper(d.code) LIKE upper(?) ORDER BY g.code LIMIT ?",
            (f"{args.prefix}%", args.limit),
        ).fetchall()
    finally:
        connection.close()
    print(json.dumps({
        "prefix": args.prefix,
        "directions": directions,
        "groups": groups,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
