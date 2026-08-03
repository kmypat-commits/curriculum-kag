"""Fill the three genuinely empty EPVO descriptions as reviewable drafts."""
from sqlalchemy import create_engine, text

DRAFTS = {
    (20568, "kk"): "Болжамды модельдерді әзірлеу тәсілдері, бастапқы деректерді талдау және өзара байланыстардың детерминирленген заңдылықтарын анықтау қарастырылады. Білім алушылар болжамды модельдерді құру, бағалау және ғылыми зерттеулерде қолдану әдістерін меңгереді.",
    (20646, "en"): "Detection of computer attacks, firewall technologies, virtual private networks, and secure data-processing technologies are considered. Students learn modern technologies for organizing and conducting scientific research.",
    (20656, "en"): "The course provides fundamental knowledge of the history, morphology and aesthetics of typefaces, introduces the plasticity and basic laws of form development, and develops the ability to apply these principles in design work.",
}

def main() -> None:
    import os
    url = os.environ["DATABASE_URL"]
    e = create_engine(url, future=True)
    changed = 0
    with e.begin() as c:
        for (course_id, language), value in DRAFTS.items():
            result = c.execute(text("""
                update course_localizations
                   set description=:description,
                       source='machine_translation_draft',
                       status='needs_review',
                       updated_at=now()
                 where course_id=:course_id and language=:language
                   and (description is null or length(btrim(description))=0)
            """), {"description": value, "course_id": course_id, "language": language})
            changed += result.rowcount
    print({"updated": changed, "drafts": len(DRAFTS)})

if __name__ == "__main__":
    main()
