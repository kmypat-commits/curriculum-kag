"""Fill the six EPVO cards whose raw export has Russian-only descriptions.

The translations are explicitly machine drafts.  They are never marked as
expert-verified and remain ``needs_review`` until a subject expert confirms
them.  This keeps the catalogue complete without hiding provenance.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, text


DRAFTS = {
    24445: {
        "kk": "Пәнді оқу оқытудың тиімділігін арттыратын психологиялық әдістер мен жағдайлар туралы жүйеленген түсінік қалыптастырады. Білім алушылар психологиялық ағарту, оқу-тәрбие үдерісін болжау және іске асыру міндеттеріне қажетті әдістер мен тәсілдерді меңгереді.",
        "en": "The course develops a systematic understanding of psychological methods and conditions that improve learning effectiveness. Students acquire methods and techniques for psychological education, forecasting, and implementing educational processes.",
    },
    24546: {
        "kk": "Пәннің міндеті — психикалық сала бұзылыстарының психопатологиялық симптомдары мен синдромдарын жас ерекшеліктерін ескере отырып ажырата білу дағдысын қалыптастыру.",
        "en": "The course develops the ability to recognize psychopathological symptoms and syndromes of disorders of the mental sphere while considering age-related characteristics.",
    },
    24572: {
        "kk": "Пән ғылыми зерттеулерге қажетті логикалық және әдіснамалық білімдерді, ғылыми зерттеудегі логиканың рөлін және әдіснамалық талдау бағыттарын меңгертеді. Білім алушылар логикалық пайымдау рәсімдерін, логика заңдары мен қағидаттарын, дұрыс дәлелдеу және пікірталас жүргізу тәсілдерін қолдануды үйренеді.",
        "en": "The course develops the logical and methodological knowledge required for research, including the role of logic in research and approaches to methodological analysis. Students learn to apply logical reasoning procedures, laws and principles of logic, sound argumentation, criticism, and debate.",
    },
    24573: {
        "kk": "Арнайы курс психологиялық кеңес берудегі дағдыларды қалыптастыруға бағытталған. Білім алушылар тиімді психологиялық байланыс орнатуды, кеңес беру әдістері мен техникаларын қолдануды, араласу мақсаттарын анықтауға қажетті ақпаратты талдауды және жеке ерекшеліктерді ескеріп араласу бағдарламаларын әзірлеуді үйренеді.",
        "en": "The course focuses on developing counselling skills. Students learn to establish effective psychological contact, apply counselling methods and techniques, analyze information needed to define intervention goals, and design intervention programmes that account for clinical and individual psychological characteristics.",
    },
    24606: {
        "kk": "Білім алушылар әртүрлі аурулары бар адамдардың психологиялық ерекшеліктерін, психикалық бұзылыстарды диагностикалау әдістерін және пациент пен медицина қызметкері арасындағы қарым-қатынас психологиясын зерттейді. Олар психикалық жағдайды бағалауды, мінез-құлық пен психиканы талдауды және психокоррекциялық, психогигиеналық әрі психопрофилактикалық іс-шаралар жоспарын әзірлеуді үйренеді.",
        "en": "Students study the psychological characteristics of people with various diseases, methods for diagnosing mental disorders, and the psychology of patient–health-care-worker relationships. They learn to assess mental states, analyze behaviour and the psyche, and design psychocorrectional, psychohygienic, and psychopreventive plans.",
    },
    24627: {
        "kk": "Пән денсаулық сақтау ұйымдарында адам ресурстарын басқаруда қолданылатын психологиялық құралдар мен технологияларды зерттейді. Білім алушылар тұлғааралық және топаралық қарым-қатынас дағдыларын, сондай-ақ медициналық психология мен денсаулық сақтау саласындағы нормативтік-құқықтық актілерді қолдануды меңгереді.",
        "en": "The course examines psychological tools and technologies used to manage human resources in health-care organizations. Students develop interpersonal and intergroup communication skills and learn to apply regulatory legal acts in medical psychology and health care.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    engine = create_engine(args.database_url, future=True)
    updated = 0
    with engine.begin() as conn:
        for course_id, drafts in DRAFTS.items():
            row = conn.execute(
                text("SELECT content_json FROM epvo_disciplines_normalized WHERE approved_course_id=:id"),
                {"id": course_id},
            ).mappings().first()
            if not row:
                continue
            content = row["content_json"] if isinstance(row["content_json"], dict) else {}
            for language, value in drafts.items():
                content[f"description_{language}"] = value
                conn.execute(
                    text("UPDATE course_localizations SET description=:value, source='machine_translation_draft', status='needs_review', updated_at=now() WHERE course_id=:id AND language=:language"),
                    {"value": value, "id": course_id, "language": language},
                )
                updated += 1
            conn.execute(
                text("UPDATE epvo_disciplines_normalized SET content_json=CAST(:content AS jsonb) WHERE approved_course_id=:id"),
                {"content": json.dumps(content, ensure_ascii=False), "id": course_id},
            )
    print({"draft_fields_updated": updated, "courses": len(DRAFTS)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
