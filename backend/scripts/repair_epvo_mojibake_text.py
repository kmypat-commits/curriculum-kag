"""Repair conservative UTF-8/CP1251 mojibake in EPVO text fields.

Only values whose characteristic marker score decreases after a valid
round-trip are changed. This never fabricates missing descriptions.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from sqlalchemy import create_engine, text


def repair(value: Any) -> str:
    value = " ".join(str(value or "").split()).strip()

    def score(s: str) -> int:
        return len(re.findall(r"[\u0420\u0421][\u0410-\u042f\u0401\u0430-\u044f\u0490-\u04ff]", s)) + sum(s.count(ch) for ch in ("\u2122", "\u00a4", "\u0403", "\u040e", "\u0402"))

    for _ in range(3):
        if score(value) < 2:
            break
        try:
            candidate = value.encode("cp1251").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if score(candidate) >= score(value):
            break
        value = candidate
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    normalized_updates = localization_updates = 0
    with engine.begin() as conn:
        rows = conn.execute(text("select id,content_json from epvo_disciplines_normalized where content_json::text like '%translation_provenance%'")).mappings().all()
        for row in rows:
            content = row["content_json"] if isinstance(row["content_json"], dict) else {}
            changed = False
            for lang in ("ru", "kk", "en"):
                key = f"description_{lang}"
                old = str(content.get(key) or "")
                new = repair(old)
                if new and new != old:
                    content[key] = new
                    changed = True
            if changed:
                conn.execute(text("update epvo_disciplines_normalized set content_json=cast(:v as jsonb) where id=:id"), {"v": json.dumps(content, ensure_ascii=False), "id": row["id"]})
                normalized_updates += 1
        rows = conn.execute(text("select id,title,description from course_localizations where source in ('machine_nllb_draft','encoding_repair_needs_review')")).mappings().all()
        for row in rows:
            title, description = repair(row["title"]), repair(row["description"])
            if title != (row["title"] or "") or description != (row["description"] or ""):
                conn.execute(text("update course_localizations set title=:t,description=:d,source='encoding_repair_needs_review',status='needs_review',updated_at=now() where id=:id"), {"t": title, "d": description, "id": row["id"]})
                localization_updates += 1
    result = {"normalized_updates": normalized_updates, "localization_updates": localization_updates}
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
