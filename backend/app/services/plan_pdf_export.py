"""Methodist-facing PDF export for a published curriculum plan."""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


_FONT_NAMES = ("CurriculumPDF", "CurriculumPDF-Bold")


_SELECTION_METHOD_REASONS = {
    "epvo_priority": "Приоритетная дисциплина выбранного профиля ЕПВО.",
    "epvo_priority_replacement": "Приоритетная дисциплина ЕПВО заменила менее релевантную равнокредитную позицию.",
    "domain_quota_reserve": "Сохранена для выполнения заявленной доли предметной области.",
    "final_domain_quota_repair": "Добавлена при финальной проверке доли предметной области.",
    "final_domain_quota_group_repair": "Добавлена при финальной проверке группы образовательных программ.",
    "real_epvo_credit_top_up": "Добавлена как реальная дисциплина ЕПВО для закрытия объёма программы.",
    "final_real_credit_fill": "Добавлена как реальная дисциплина для закрытия кредитного объёма.",
    "credit_gap_real_course": "Добавлена как реальная дисциплина для закрытия кредитного дефицита.",
    "epvo_lo_gap_repair": "Добавлена для закрытия непокрытого результата обучения реальной дисциплиной.",
    "expert_confirmed_course_replacement": "Добавлена по подтверждённой экспертной замене.",
}


def _register_fonts() -> tuple[str, str]:
    """Register a Cyrillic-capable font, failing clearly if the runtime lacks one."""
    if all(name in pdfmetrics.getRegisteredFontNames() for name in _FONT_NAMES):
        return _FONT_NAMES
    candidates = [
        (os.environ.get("CURRICULUM_PDF_FONT_REGULAR"), os.environ.get("CURRICULUM_PDF_FONT_BOLD")),
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if regular and bold and Path(regular).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont(_FONT_NAMES[0], regular))
            pdfmetrics.registerFont(TTFont(_FONT_NAMES[1], bold))
            return _FONT_NAMES
    raise RuntimeError("PDF export requires a Cyrillic TrueType font. Configure CURRICULUM_PDF_FONT_REGULAR and CURRICULUM_PDF_FONT_BOLD.")


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _selection_reason(item, plan) -> str:
    if item.bridge_module_id:
        return "Bridge-модуль: закрывает структурный, междисциплинарный или кредитный пробел; требует экспертной проверки содержания."
    snapshot = ((plan.metrics_json or {}).get("selection_evidence_snapshot") or {}).get("courses") or {}
    evidence = snapshot.get(str(item.course_id)) or {}
    method_reason = _SELECTION_METHOD_REASONS.get(str(evidence.get("selection_method") or ""))
    top = (evidence.get("top_lo_matches") or [{}])[0]
    if top.get("lo_code"):
        lo_reason = f"Связь с {top['lo_code']}: {round(float(top.get('effective_score') or 0) * 100)}%. Снимок на момент публикации плана."
        return f"{method_reason} {lo_reason}" if method_reason else lo_reason
    if method_reason:
        return method_reason
    return "Включена для структуры, кредитного баланса или доменной целостности; проверьте связь с LO."


def build_methodist_prompt(project_version, plan, items, courses_by_id, bridges_by_id) -> str:
    """Create a transparent hand-off prompt without claiming normative approval."""
    project = project_version.project
    constraints = project.constraints_json or {}
    outcomes = "\n".join(
        f"{lo.lo_code}: {lo.lo_text}" for lo in project_version.learning_outcomes
    )
    return "\n".join([
        "Вы выступаете как методист и предметный эксперт. Проведите критическую доработку проекта ОП.",
        "Не утверждайте нормативное соответствие без проверки актуальных требований конкретного вуза и страны.",
        f"Название: {project.title}",
        f"Цель: {project.goal}",
        f"Уровень: {constraints.get('education_level', '')}; язык: {constraints.get('instruction_language', '')}; объём: {constraints.get('total_credits', '')} кредитов / {constraints.get('total_semesters', '')} семестров.",
        "Результаты обучения:", outcomes,
        "Текущая траектория, кредиты по семестрам и автоматические основания выбора приведены в таблицах этого PDF. Используйте их как исходные данные, а не восстанавливайте список дисциплин по памяти.",
        "Проверьте: (1) покрытие каждого LO реальными дисциплинами и заданиями; (2) недостающие и нерелевантные темы; (3) логику пререквизитов и сложности по семестрам; (4) реализуемость практик, оценивания и ресурсов; (5) конкретные замены без выдумывания источников. Верните таблицу замечаний с приоритетом и обоснованием.",
    ])


def build_plan_pdf(*, project_version, plan, items, courses_by_id, bridges_by_id, localizations, language: str) -> BytesIO:
    """Build a compact, printable PDF for review; no audit logs or credentials are included."""
    regular, bold = _register_fonts()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("curriculum-title", parent=styles["Title"], fontName=bold, fontSize=18, leading=22, textColor=colors.HexColor("#123B5D"))
    heading = ParagraphStyle("curriculum-heading", parent=styles["Heading2"], fontName=bold, fontSize=12, leading=16, textColor=colors.HexColor("#123B5D"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("curriculum-body", parent=styles["BodyText"], fontName=regular, fontSize=9, leading=13, spaceAfter=5)
    small = ParagraphStyle("curriculum-small", parent=body, fontSize=7.6, leading=10)
    center = ParagraphStyle("curriculum-center", parent=body, alignment=TA_CENTER, textColor=colors.HexColor("#52606D"))
    output = BytesIO()

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(18 * mm, 12 * mm, "Curriculum-KAG · черновой методический пакет")
        canvas.drawRightString(192 * mm, 12 * mm, f"Стр. {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm, title=str(project_version.project.title or "Учебный план"),
    )
    project = project_version.project
    constraints = project.constraints_json or {}
    verification = (plan.metrics_json or {}).get("verification") or {}
    target_credits = verification.get("target_credits", constraints.get("total_credits", "—"))
    total_credits = verification.get("total_credits", "—")
    maximum_credits = verification.get("maximum_total_credits")
    credit_volume = f"{total_credits} / {target_credits}"
    if maximum_credits is not None:
        credit_volume += f" (допустимо до {maximum_credits})"
    story = [
        _paragraph("ПРОЕКТ ОБРАЗОВАТЕЛЬНОЙ ПРОГРАММЫ", center),
        _paragraph(project.title or "Учебный план", title),
        _paragraph(
            f"Вариант {plan.variant_type} · версия {project_version.version_number} · "
            f"{constraints.get('total_credits', '—')} кредитов · {constraints.get('total_semesters', '—')} семестров",
            body,
        ),
        _paragraph("Статус: рабочая основа для методической доработки и академического рассмотрения. Это не автоматическое нормативное утверждение программы.", body),
        _paragraph("Цель программы", heading),
        _paragraph(project.goal or "Не указана", body),
        _paragraph("Результаты обучения", heading),
    ]
    for lo in sorted(project_version.learning_outcomes, key=lambda value: (value.order_index or 0, value.id)):
        story.append(Paragraph(
            f"<b>{escape(str(lo.lo_code or 'LO'))}</b> — {escape(str(lo.lo_text or ''))}", body
        ))
    story.extend([
        _paragraph("Итог автоматических проверок", heading),
        Table([
            [_paragraph("Проверка", small), _paragraph("Значение", small)],
            [_paragraph("Статус", small), _paragraph("Пройдена" if verification.get("feasible") else "Требует доработки", small)],
            [_paragraph("Жёсткие нарушения", small), _paragraph(str(verification.get("hard_violation_count", "—")), small)],
            [_paragraph("Покрытие LO", small), _paragraph(str(verification.get("min_lo_coverage", "—")), small)],
            [_paragraph("Объём кредитов", small), _paragraph(credit_volume, small)],
        ], colWidths=[65 * mm, 105 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6F0F7")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
        _paragraph("Учебный план и основания выбора", heading),
    ])
    by_semester = {}
    for item in items:
        by_semester.setdefault(int(item.semester), []).append(item)
    for semester, semester_items in sorted(by_semester.items()):
        rows = [[_paragraph("Дисциплина", small), _paragraph("Кр.", small), _paragraph("Основание выбора", small)]]
        for item in sorted(semester_items, key=lambda value: value.id):
            source = courses_by_id.get(item.course_id) if item.course_id else bridges_by_id.get(item.bridge_module_id)
            if item.course_id:
                translations = (localizations.get(item.course_id) or {}).get("title_translations") or {}
                course_title = translations.get(language) or translations.get("ru") or getattr(source, "title", "Дисциплина")
            else:
                course_title = getattr(source, "title", "Bridge-модуль") + " [bridge]"
            rows.append([_paragraph(course_title, small), _paragraph(str(item.credits), small), _paragraph(_selection_reason(item, plan), small)])
        table = Table(rows, colWidths=[75 * mm, 12 * mm, 83 * mm], repeatRows=1, style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6F0F7")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(KeepTogether([_paragraph(f"Семестр {semester}", heading), table, Spacer(1, 4)]))
    story.extend([
        PageBreak(),
        _paragraph("Prompt для внешней LLM / экспертной доработки", heading),
        _paragraph("Загружайте этот пакет вместе с prompt. Не передавайте персональные данные студентов, пароли и закрытые материалы.", body),
        # A prompt can legitimately exceed one page.  It must be a normal
        # flowable, not a one-cell table, otherwise ReportLab cannot split it
        # and rejects an otherwise valid long curriculum package.
        _paragraph(build_methodist_prompt(project_version, plan, items, courses_by_id, bridges_by_id), small),
    ])
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
