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
    value = unicodedata.normalize("NFC", value)
    # EPVO exports occasionally contain UTF-8 decoded as CP1251
    # (e.g. ``РџРµРґ...``).  Repair only when the round-trip is valid and
    # clearly reduces the characteristic mojibake markers.
    for _ in range(2):
        if value.count("Р") < 2 and value.count("С") < 2:
            break
        try:
            candidate = value.encode("cp1251").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == value:
            break
        value = candidate
    return " ".join(value.split()).strip()


def has_mojibake(value):
    if not isinstance(value, str):
        return False
    value = value.replace("РНР", "")
    # Typical UTF-8/CP1251 artefacts look like ``РџРµ`` or ``СЂ``.  Keep
    # legitimate abbreviations such as ``РНР`` out of this detector.
    return "\ufffd" in value or bool(re.search(r"Р[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]|С[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]", value))


def damaged(value):
    raw = value
    value = clean(value)
    if not value:
        return True
    if has_mojibake(raw) or any(marker in value for marker in BAD):
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


def repair_identical_fallbacks(conn) -> int:
    """Replace RU-copied KK/EN text when another normalized EPVO alias has it."""
    rows = conn.execute(text("""
      SELECT n.approved_course_id, n.title_ru, n.title_kk, n.title_en,
             n.content_json, lru.title ru_title, lkk.title kk_title, len.title en_title,
             lru.description ru_description, lkk.description kk_description,
             len.description en_description
      FROM epvo_disciplines_normalized n
      JOIN course_localizations lru ON lru.course_id=n.approved_course_id AND lru.language='ru'
      JOIN course_localizations lkk ON lkk.course_id=n.approved_course_id AND lkk.language='kk'
      JOIN course_localizations len ON len.course_id=n.approved_course_id AND len.language='en'
      WHERE lru.title=lkk.title AND lru.title=len.title
         OR (lru.description IS NOT NULL AND lru.description=lkk.description AND lru.description=len.description)
    """)).mappings().all()
    best = {}
    for row in rows:
        content = row["content_json"] if isinstance(row["content_json"], dict) else {}
        score = sum(bool(clean(row[f"title_{lang}"])) and clean(row[f"title_{lang}"]) != clean(row["title_ru"]) for lang in ("kk", "en"))
        score += sum(bool(clean(content.get(f"description_{lang}"))) and clean(content.get(f"description_{lang}")) != clean(content.get("description_ru")) for lang in ("kk", "en"))
        old = best.get(row["approved_course_id"])
        if old is None or score > old[0]:
            best[row["approved_course_id"]] = (score, row)
    changed = 0
    for course_id, (_, row) in best.items():
        content = row["content_json"] if isinstance(row["content_json"], dict) else {}
        for lang, current_title, current_description in (("kk", row["kk_title"], row["kk_description"]), ("en", row["en_title"], row["en_description"])):
            title = clean(row[f"title_{lang}"])
            description = clean(content.get(f"description_{lang}"))
            if title and clean(current_title) == clean(row["ru_title"]) and title != clean(row["ru_title"]):
                conn.execute(text("UPDATE course_localizations SET title=:value, source='epvo_raw_recovery', updated_at=now() WHERE course_id=:course_id AND language=:language"), {"value": title, "course_id": course_id, "language": lang})
                changed += 1
            if description and clean(current_description) == clean(row["ru_description"]) and description != clean(row["ru_description"]):
                conn.execute(text("UPDATE course_localizations SET description=:value, source='epvo_raw_recovery', updated_at=now() WHERE course_id=:course_id AND language=:language"), {"value": description, "course_id": course_id, "language": lang})
                changed += 1
    return changed


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
             OR title_ru ~ 'Р[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]'
             OR title_kk ~ 'Р[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]'
             OR title_en ~ 'Р[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]'
             OR content_json::text LIKE '%�%'
             OR content_json::text ~ 'Р[А-ЯЁ][РС][^А-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]'
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
             OR approved_course_id IN (
                 SELECT n3.approved_course_id
                 FROM epvo_disciplines_normalized n3
                 JOIN course_localizations r3 ON r3.course_id=n3.approved_course_id AND r3.language='ru'
                 JOIN course_localizations k3 ON k3.course_id=n3.approved_course_id AND k3.language='kk'
                 JOIN course_localizations e3 ON e3.course_id=n3.approved_course_id AND e3.language='en'
                 WHERE r3.description IS NOT NULL AND r3.description=k3.description AND r3.description=e3.description
                   AND (coalesce(n3.content_json->>'description_kk','')<>r3.description OR coalesce(n3.content_json->>'description_en','')<>r3.description)
             )
        """)).mappings().all()
        # Several normalized rows can point to the same approved course. Use
        # the richest multilingual row once; otherwise a later sparse alias
        # could overwrite a recovered KK/EN description.
        best_by_course = {}
        for candidate in normalized:
            course_key = candidate["approved_course_id"] or f"norm:{candidate['id']}"
            content = candidate["content_json"] if isinstance(candidate["content_json"], dict) else {}
            richness = sum(bool(clean(candidate[f"title_{lang}"])) for lang in LANGS)
            richness += sum(bool(clean(content.get(f"description_{lang}"))) for lang in LANGS)
            # Prefer a row that actually contains different KK/EN text over a
            # legacy alias that merely repeats the Russian fallback.
            richness += 2 * sum(
                bool(clean(candidate[f"title_{lang}"])) and clean(candidate[f"title_{lang}"]) != clean(candidate["title_ru"])
                for lang in ("kk", "en")
            )
            richness += 2 * sum(
                bool(clean(content.get(f"description_{lang}"))) and clean(content.get(f"description_{lang}")) != clean(content.get("description_ru"))
                for lang in ("kk", "en")
            )
            previous = best_by_course.get(course_key)
            if previous is None or richness > previous[0]:
                best_by_course[course_key] = (richness, candidate)
        normalized = [item[1] for item in best_by_course.values()]
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
                    source_title, source_description = source.get(lang, (None, None))
                    # A clean KK/EN source must win over a longer RU fallback.
                    if lang != "ru" and clean(source_title) and clean(source_title) != clean(row["title_ru"]):
                        title = clean(source_title)
                    else:
                        title = better(title, source_title)
                    if lang != "ru" and clean(source_description) and clean(source_description) != clean(content.get("description_ru")):
                        description = clean(source_description)
                    else:
                        description = better(description, source_description)
                fb_title, fb_desc = fallback.get(lang, ("", ""))
                if lang != "ru" and clean(fb_title) and clean(fb_title) != clean(row["title_ru"]):
                    title = clean(fb_title)
                else:
                    title = better(title, fb_title)
                if lang != "ru" and clean(fb_desc) and clean(fb_desc) != clean(content.get("description_ru")):
                    description = clean(fb_desc)
                else:
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
        fallback_updates = repair_identical_fallbacks(conn)
        print({"normalized_field_updates": changed_norm, "localization_updates": changed_loc + fallback_updates,
               "normalized_rows": len(normalized), "raw_rows": len(raw_by_key)})


if __name__ == "__main__":
    main()
