"""Remove only unrecoverable U+FFFD markers and mark affected records for review."""
from sqlalchemy import create_engine, text
import argparse

def main():
    p=argparse.ArgumentParser(); p.add_argument('--database-url',required=True); a=p.parse_args()
    e=create_engine(a.database_url, future=True)
    with e.begin() as c:
        n=c.execute(text("""
          update epvo_disciplines_normalized
             set title_ru=replace(title_ru,'�',''),
                 title_kk=replace(title_kk,'�',''),
                 title_en=replace(title_en,'�',''),
                 content_json=replace(content_json::text,'�','')::jsonb
           where title_ru like '%�%' or title_kk like '%�%' or title_en like '%�%' or content_json::text like '%�%'
        """)).rowcount
        l=c.execute(text("""
          update course_localizations
             set title=replace(title,'�',''), description=replace(description,'�',''),
                 status='needs_review', source='encoding_repair_needs_review', updated_at=now()
           where title like '%�%' or description like '%�%'
        """)).rowcount
    print({'normalized':n,'localizations':l})

if __name__=='__main__': main()
