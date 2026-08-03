"""Audit EPVO multilingual fields and their course-localization projection."""
from __future__ import annotations

import argparse
import json
from sqlalchemy import create_engine, text


def scalar(conn, query):
    return int(conn.execute(text(query)).scalar() or 0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    e = create_engine(a.database_url, future=True)
    with e.connect() as c:
        report = {
            "normalized": scalar(c, "select count(*) from epvo_disciplines_normalized"),
            "normalized_missing_title": {
                lang: scalar(c, f"select count(*) from epvo_disciplines_normalized where title_{lang} is null or length(btrim(title_{lang}))=0")
                for lang in ("ru", "kk", "en")
            },
            "normalized_missing_description": {
                lang: scalar(c, f"select count(*) from epvo_disciplines_normalized where content_json->>'description_{lang}' is null or length(btrim(content_json->>'description_{lang}'))=0")
                for lang in ("ru", "kk", "en")
            },
            "localization_missing": {
                lang: scalar(c, f"select count(*) from courses x left join course_localizations l on l.course_id=x.id and l.language='{lang}' where l.id is null or l.title is null or length(btrim(l.title))=0")
                for lang in ("ru", "kk", "en")
            },
            "localization_missing_description": {
                lang: scalar(c, f"select count(*) from courses x left join course_localizations l on l.course_id=x.id and l.language='{lang}' where l.id is null or l.description is null or length(btrim(l.description))=0")
                for lang in ("ru", "kk", "en")
            },
            "directions": {
                "total": scalar(c, "select count(*) from epvo_directions"),
                "missing_ru": scalar(c, "select count(*) from epvo_directions where title_ru is null or length(btrim(title_ru))=0"),
                "missing_kk": scalar(c, "select count(*) from epvo_directions where title_kk is null or length(btrim(title_kk))=0"),
                "missing_en": scalar(c, "select count(*) from epvo_directions where title_en is null or length(btrim(title_en))=0"),
            },
            "groups": {
                "total": scalar(c, "select count(*) from epvo_groups"),
                "missing_ru": scalar(c, "select count(*) from epvo_groups where title_ru is null or length(btrim(title_ru))=0"),
                "missing_kk": scalar(c, "select count(*) from epvo_groups where title_kk is null or length(btrim(title_kk))=0"),
                "missing_en": scalar(c, "select count(*) from epvo_groups where title_en is null or length(btrim(title_en))=0"),
            },
            "projection_mismatch": {
                lang: scalar(c, f"""
                    select count(*) from epvo_disciplines_normalized n
                    join course_localizations l on l.course_id=n.approved_course_id and l.language='{lang}'
                    where length(btrim(coalesce(n.title_{lang},'')))>0
                      and length(btrim(coalesce(l.title,'')))>0
                      and btrim(n.title_{lang}) <> btrim(l.title)
                """) for lang in ("ru", "kk", "en")
            },
            "mojibake": {
                "normalized_replacement_characters": scalar(c, "select count(*) from epvo_disciplines_normalized where content_json::text like '%�%' or title_ru like '%�%' or title_kk like '%�%' or title_en like '%�%'") ,
                "localization_replacement_characters": scalar(c, "select count(*) from course_localizations where title like '%�%' or description like '%�%'") ,
                "normalized_question_mark_runs": scalar(c, "select count(*) from epvo_disciplines_normalized where content_json::text ~ '\\?{3,}' or title_ru ~ '\\?{3,}' or title_kk ~ '\\?{3,}' or title_en ~ '\\?{3,}'"),
                "localization_question_mark_runs": scalar(c, "select count(*) from course_localizations where title ~ '\\?{3,}' or description ~ '\\?{3,}'"),
                "course_question_mark_runs": scalar(c, "select count(*) from courses where title ~ '\\?{3,}' or description ~ '\\?{3,}'"),
                "chunk_question_mark_runs": scalar(c, "select count(*) from course_chunks where chunk_text ~ '\\?{3,}'"),
            },
        }
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
