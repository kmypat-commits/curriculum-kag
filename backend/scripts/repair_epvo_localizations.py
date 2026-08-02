"""Recover missing/corrupt RU/KK/EN course text from the immutable EPVO layer.

The normalized table is the first source of truth; raw EPVO discipline payloads
are used only when a normalized field is empty or visibly damaged.  Existing
verified text is never replaced by a different value.  Recovered values are
marked ``verified_epvo`` so the UI can distinguish source evidence from manual
expert review.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict

from sqlalchemy import create_engine, text


LANGS = ("ru", "kk", "en")
BAD = ("\ufffd", "Ð", "Р", "С")


def clean(value):
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split()).strip()


def damaged(value):
    value = clean(value)
    if not value:
        return True
    if any(marker in value for marker in BAD):
        return True
    # A serialized PowerShell/Python mapping must never be shown as a title.
    return value.startswith("@{") or value.startswith("{'")


def key(value):
    return re.sub(r"\s+", " ", clean(value).casefold())


def raw_fields(payload):
    if not isinstance(payload, dict):
        return {}
    return {
        "ru": (payload.get("nameRu"), payload.get("briefinforu")),
        "kk": (payload.get("nameKz"), payload.get("briefinfo")),
        "en": (payload.get("nameEn"), payload.get("briefinfoen")),
    }


def better(old, candidate):
    candidate = clean(candidate)
    if damaged(candidate):
        return old
    if not old or damaged(old) or len(candidate) > len(old):
        return candidate
    return old


def sanitize_damaged(value):
    """Make a value displayable when every available source has U+FFFD.

    The original byte cannot be reconstructed honestly.  Removing only the
    replacement marker is preferable to exposing mojibake; the row remains
    ``needs_review`` in the audit report.
    """
    value = clean(value)
    return value.replace("\ufffd", "") if value else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    engine = create_engine(args.database_url, future=True)
    with engine.begin() as conn:
        # Only load rows that can actually be repaired; the full EPVO raw table
        # is hundreds of thousands of JSON records and must not be materialized.
        normalized = conn.execute(text("""
          SELECT id, approved_course_id, title_ru, title_kk, title_en,
                 source_keys, content_json
          FROM epvo_disciplines_normalized
          WHERE title_ru IS NULL OR title_kk IS NULL OR title_en IS NULL
             OR trim(title_ru) = '' OR trim(title_kk) = '' OR trim(title_en) = ''
             OR title_ru LIKE '%�%' OR title_kk LIKE '%�%' OR title_en LIKE '%�%'
             OR content_json::text LIKE '%�%'
             OR content_json::text NOT LIKE '%description_en%'
             OR content_json::text NOT LIKE '%description_kk%'
             OR trim(coalesce(content_json->>'description_en','')) = ''
             OR trim(coalesce(content_json->>'description_kk','')) = ''
             OR approved_course_id IN (
                 SELECT course_id FROM course_localizations
                 WHERE title LIKE '%�%' OR description LIKE '%�%'
             )
             OR approved_course_id IN (
                 SELECT n2.approved_course_id
                 FROM epvo_disciplines_normalized n2
                 JOIN course_localizations lru ON lru.course_id=n2.approved_course_id AND lru.language='ru'
                 JOIN course_localizations lkk ON lkk.course_id=n2.approved_course_id AND lkk.language='kk'
                 JOIN course_localizations len ON len.course_id=n2.approved_course_id AND len.language='en'
                 WHERE lru.title=lkk.title AND lru.title=len.title
                   AND (coalesce(n2.title_kk,'')<>coalesce(lru.title,'') OR coalesce(n2.title_en,'')<>coalesce(lru.title,''))
             )
        """)).mappings().all()
        source_ids = sorted({str(k) for row in normalized for k in (row["source_keys"] or [])})
        raw_by_key = {}
        raw_by_title = defaultdict(dict)
        if source_ids:
            raw_rows = conn.execute(text("""
              SELECT source_key, payload_json FROM raw_epvo_disciplines
              WHERE source_key = ANY(:keys)
            """), {"keys": source_ids}).mappings()
            for raw in raw_rows:
                payload = raw_fields(raw["payload_json"])
                raw_by_key[str(raw["source_key"])] = payload
                title = key(payload.get("ru", (None,))[0])
                if title:
                    bucket = raw_by_title[title]
                    for lang in LANGS:
                        title_value, description = payload[lang]
                        bucket[lang] = (better(bucket.get(lang, ("", ""))[0], title_value),
                                        better(bucket.get(lang, ("", ""))[1], description))

        # Title fallback is limited to the set of affected Russian titles.
        ru_titles = sorted({key(row["title_ru"]) for row in normalized if key(row["title_ru"])})
        if ru_titles:
            raw_rows = conn.execute(text("""
              SELECT payload_json FROM raw_epvo_disciplines
              WHERE lower(payload_json->>'nameRu') = ANY(:titles)
            """), {"titles": ru_titles}).mappings()
            for raw in raw_rows:
                payload = raw_fields(raw["payload_json"])
                title = key(payload.get("ru", (None,))[0])
                bucket = raw_by_title[title]
                for lang in LANGS:
                    title_value, description = payload[lang]
                    bucket[lang] = (better(bucket.get(lang, ("", ""))[0], title_value),
                                    better(bucket.get(lang, ("", ""))[1], description))

        changed_norm = 0
        changed_loc = 0
        for row in normalized:
            sources = [raw_by_key.get(str(source_key), {}) for source_key in (row.source_keys or [])]
            fallback = raw_by_title.get(key(row.title_ru), {})
            values = {}
            for lang in LANGS:
                title = clean(getattr(row, f"title_{lang}", None))
                content = row.content_json if isinstance(row.content_json, dict) else {}
                description = clean(content.get(f"description_{lang}"))
                for source in sources:
                    title = better(title, source.get(lang, (None, None))[0])
                    description = better(description, source.get(lang, (None, None))[1])
                fb_title, fb_desc = fallback.get(lang, ("", ""))
                title = better(title, fb_title)
                description = better(description, fb_desc)
                if damaged(description):
                    description = sanitize_damaged(description)
                if not description:
                    raw_description = content.get(f"description_{lang}")
                    for source in sources:
                        raw_description = raw_description or source.get(lang, (None, None))[1]
                    description = sanitize_damaged(raw_description)
                values[lang] = (title, description)
                old_title = row[f"title_{lang}"]
                if damaged(old_title) or not clean(old_title):
                    if title:
                        conn.execute(text(f"UPDATE epvo_disciplines_normalized SET title_{lang}=:value WHERE id=:id"), {"value": title, "id": row["id"]})
                        changed_norm += 1
                if damaged(content.get(f"description_{lang}")) or not description:
                    if description:
                        content[f"description_{lang}"] = description
                        conn.execute(text("UPDATE epvo_disciplines_normalized SET content_json=CAST(:content AS jsonb) WHERE id=:id"), {"content": json.dumps(content, ensure_ascii=False), "id": row["id"]})
                        changed_norm += 1

            course_id = row["approved_course_id"]
            if not course_id:
                continue
            current = conn.execute(text("SELECT id, language, title, description, status FROM course_localizations WHERE course_id=:id"), {"id": course_id}).mappings().all()
            locs = {item["language"]: item for item in current}
            ru_title = (locs.get("ru") or {}).get("title")
            ru_description = (locs.get("ru") or {}).get("description")
            for lang in LANGS:
                title, description = values[lang]
                if not title:
                    continue
                loc = locs.get(lang)
                if loc is None:
                    conn.execute(text("""INSERT INTO course_localizations(course_id, language, title, description, source, status, created_at, updated_at)
                      VALUES (:course_id,:language,:title,:description,'epvo_raw_recovery','verified_epvo',now(),now())"""),
                                 {"course_id": course_id, "language": lang, "title": title, "description": description or None})
                    changed_loc += 1
                    continue
                same_as_ru = lang != "ru" and clean(loc["title"]) == clean(ru_title)
                if damaged(loc["title"]) or not clean(loc["title"]) or (same_as_ru and clean(title) != clean(ru_title)):
                    conn.execute(text("UPDATE course_localizations SET title=:title, source='epvo_raw_recovery', updated_at=now() WHERE id=:id"), {"title": title, "id": loc["id"]})
                    changed_loc += 1
                same_description_as_ru = lang != "ru" and clean(loc["description"]) == clean(ru_description)
                if description and (damaged(loc["description"]) or not clean(loc["description"]) or (same_description_as_ru and clean(description) != clean(ru_description))):
                    conn.execute(text("UPDATE course_localizations SET description=:description, source='epvo_raw_recovery', updated_at=now() WHERE id=:id"), {"description": description, "id": loc["id"]})
                    changed_loc += 1
                    if "\ufffd" in str(loc["description"] or ""):
                        conn.execute(text("UPDATE course_localizations SET status='needs_review' WHERE id=:id"), {"id": loc["id"]})
                if loc["status"] not in {"verified", "verified_epvo", "machine_reviewed"}:
                    conn.execute(text("UPDATE course_localizations SET status='verified_epvo', source='epvo_raw_recovery', updated_at=now() WHERE id=:id"), {"id": loc["id"]})
        print({"normalized_field_updates": changed_norm, "localization_updates": changed_loc,
               "normalized_rows": len(normalized), "raw_rows": len(raw_by_key)})


if __name__ == "__main__":
    main()
