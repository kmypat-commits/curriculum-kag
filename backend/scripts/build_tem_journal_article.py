"""Build English and Russian TEM Journal manuscripts from the official DOCX template."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


METRIC_KEYS = {
    "provenance": "epvo_provenance",
    "profile_provenance": "epvo_provenance_excluding_regulatory",
    "raw_semester": "semester_alignment_pm1",
    "prereq_semester": "semester_alignment_prereq_adjusted_pm1",
    "semantic_semester": "semester_alignment_semantic_adjusted_pm1",
    "quality": "international_score",
    "hard": "hard_violations",
}


def clear_paragraph(paragraph):
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def remove_after_front_matter(document: Document) -> None:
    body = document._body._element
    paragraphs = document.paragraphs
    boundary = paragraphs[9]._p
    seen = False
    for child in list(body):
        if child is boundary:
            seen = True
            continue
        if seen and child.tag != qn("w:sectPr"):
            body.remove(child)


def set_run_font(run, size=11, bold=False, italic=False, name="Times New Roman"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor(0, 0, 0)


def set_front(document: Document, title: str, author: str, affiliations: list[str], email: str):
    paragraphs = document.paragraphs
    for paragraph in paragraphs[:10]:
        clear_paragraph(paragraph)
    title_parts = title.split(":", 1)
    for idx, text in ((0, title_parts[0]), (1, title_parts[1].strip() if len(title_parts) > 1 else "")):
        paragraphs[idx].alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraphs[idx].add_run(text)
        set_run_font(run, size=24, bold=True)
    paragraphs[3].alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(paragraphs[3].add_run(author), size=14)
    for idx, text in zip((5, 6), affiliations[:2]):
        paragraphs[idx].alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run_font(paragraphs[idx].add_run(text), size=10, italic=True)
    paragraphs[7].alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(paragraphs[7].add_run(email), size=10, italic=True)


def add_body(document: Document, text: str, *, first_indent=True, italic=False, bold=False):
    paragraph = document.add_paragraph(style="ICEST_Normal")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.first_line_indent = Cm(0.5) if first_indent else Cm(0)
    set_run_font(paragraph.add_run(text), size=11, italic=italic, bold=bold)
    return paragraph


def add_heading(document: Document, text: str, level=1):
    paragraph = document.add_paragraph(style="Normal")
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.space_before = Pt(6 if level == 1 else 3)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_run_font(paragraph.add_run(text), size=11 if level == 1 else 10, bold=level == 1, italic=level > 1)
    return paragraph


def add_abstract(document: Document, abstract: str, keywords: str, labels: tuple[str, str]):
    for label, text in ((labels[0], abstract), (labels[1], keywords)):
        paragraph = document.add_paragraph(style="ICEST_Abstract")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.first_line_indent = Cm(0.5)
        run = paragraph.add_run(label + " - ")
        set_run_font(run, size=10, bold=True, italic=True)
        set_run_font(paragraph.add_run(text), size=10)


def add_equation(document: Document, equation: str, number: int):
    paragraph = document.add_paragraph(style="ICEST_Normal")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(3)
    set_run_font(paragraph.add_run(f"{equation}    ({number})"), size=10, italic=True, name="Cambria Math")


def shade_cell(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_margins(cell, top=70, start=90, bottom=70, end=90):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="808080", size="4"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), size)
        tag.set(qn("w:color"), color)


def repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    marker = tr_pr.find(qn("w:tblHeader"))
    if marker is None:
        marker = OxmlElement("w:tblHeader")
        tr_pr.append(marker)
    marker.set(qn("w:val"), "true")


def add_table(document: Document, headers: list[str], rows: list[list[str]], caption: str):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Normal Table"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    set_table_borders(table)
    repeat_table_header(table.rows[0])
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        shade_cell(cell, "D9EAF7")
        set_cell_margins(cell)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        clear_paragraph(paragraph)
        set_run_font(paragraph.add_run(header), size=8, bold=True)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cell = cells[index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if index else WD_ALIGN_PARAGRAPH.LEFT
            clear_paragraph(paragraph)
            set_run_font(paragraph.add_run(str(value)), size=8)
    paragraph = document.add_paragraph(style="ICEST_Normal")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    set_run_font(paragraph.add_run(caption), size=10, italic=True)


def add_figure_prompt(document: Document, number: int, caption: str, prompt: str, lang: str):
    placeholder = document.add_table(rows=1, cols=1)
    placeholder.style = "Normal Table"
    placeholder.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(placeholder, color="A6A6A6", size="6")
    cell = placeholder.cell(0, 0)
    shade_cell(cell, "F2F2F2")
    set_cell_margins(cell, top=180, start=160, bottom=180, end=160)
    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    clear_paragraph(paragraph)
    label = f"Figure {number} placeholder" if lang == "en" else f"Место для рисунка {number}"
    set_run_font(paragraph.add_run(label), size=10, bold=True)
    cap = document.add_paragraph(style="ICEST_Normal")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.first_line_indent = Cm(0)
    set_run_font(cap.add_run(f"Figure {number}. {caption}" if lang == "en" else f"Рисунок {number}. {caption}"), size=10, italic=True)
    prompt_p = document.add_paragraph(style="ICEST_Normal")
    prompt_p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    prompt_p.paragraph_format.first_line_indent = Cm(0)
    prefix = "Draft image-generation prompt: " if lang == "en" else "Промпт для генерации изображения (удалить перед подачей): "
    set_run_font(prompt_p.add_run(prefix), size=8, bold=True)
    set_run_font(prompt_p.add_run(prompt), size=8, italic=True)


def add_bullets(document: Document, items: list[str]):
    for item in items:
        paragraph = document.add_paragraph(style="ICEST_Normal")
        paragraph.paragraph_format.left_indent = Cm(0.5)
        paragraph.paragraph_format.first_line_indent = Cm(-0.35)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_run_font(paragraph.add_run("• "), size=11, bold=True)
        set_run_font(paragraph.add_run(item), size=11)


def pct(value):
    return f"{100 * float(value):.2f}%"


def cohort_table(metrics: dict, lang: str):
    no = metrics["without_goso"]
    yes = metrics["with_goso"]
    m0, m1 = no["metrics"], yes["metrics"]
    if lang == "en":
        headers = ["Metric", "Without SCES RK", "With SCES RK", "Difference"]
        labels = [
            ("Programmes", str(no["programme_count"]), str(yes["programme_count"]), "0"),
            ("Raw EPVO provenance", pct(m0["epvo_provenance"]), pct(m1["epvo_provenance"]), "+38.64 pp"),
            ("Profile provenance, regulatory block excluded", pct(m0["epvo_provenance_excluding_regulatory"]), pct(m1["epvo_provenance_excluding_regulatory"]), "0.00 pp"),
            ("Raw semester alignment, ±1", pct(m0["semester_alignment_pm1"]), pct(m1["semester_alignment_pm1"]), "+13.75 pp"),
            ("Prerequisite-adjusted alignment", pct(m0["semester_alignment_prereq_adjusted_pm1"]), pct(m1["semester_alignment_prereq_adjusted_pm1"]), "+9.45 pp"),
            ("Semantic-adjusted alignment", pct(m0["semester_alignment_semantic_adjusted_pm1"]), pct(m1["semester_alignment_semantic_adjusted_pm1"]), "+5.61 pp"),
            ("International checklist", pct(m0["international_score"] / 100), pct(m1["international_score"] / 100), "0.00 pp"),
            ("Hard violations", str(int(m0["hard_violations"])), str(int(m1["hard_violations"])), "0"),
        ]
        caption = "Table 3. Cohort comparison of fresh quality-eligible plans with and without SCES RK."
    else:
        headers = ["Метрика", "Без ГОСО", "С ГОСО", "Разница"]
        labels = [
            ("Программы", str(no["programme_count"]), str(yes["programme_count"]), "0"),
            ("Полное происхождение ЕПВО", pct(m0["epvo_provenance"]), pct(m1["epvo_provenance"]), "+38,64 п.п."),
            ("Профильное происхождение без нормативного блока", pct(m0["epvo_provenance_excluding_regulatory"]), pct(m1["epvo_provenance_excluding_regulatory"]), "0,00 п.п."),
            ("Сырое соответствие семестру, ±1", pct(m0["semester_alignment_pm1"]), pct(m1["semester_alignment_pm1"]), "+13,75 п.п."),
            ("С учётом пререквизитов", pct(m0["semester_alignment_prereq_adjusted_pm1"]), pct(m1["semester_alignment_prereq_adjusted_pm1"]), "+9,45 п.п."),
            ("С учётом педагогической сложности", pct(m0["semester_alignment_semantic_adjusted_pm1"]), pct(m1["semester_alignment_semantic_adjusted_pm1"]), "+5,61 п.п."),
            ("Международный чек-лист", pct(m0["international_score"] / 100), pct(m1["international_score"] / 100), "0,00 п.п."),
            ("Жёсткие нарушения", str(int(m0["hard_violations"])), str(int(m1["hard_violations"])), "0"),
        ]
        caption = "Таблица 3. Сравнение свежих планов с ГОСО РК и без него."
    return headers, [list(row) for row in labels], caption


EN = {
    "title": "Evidence-Constrained Curriculum Synthesis: National Expert Data, Semantic Retrieval, and Semester-Aware Planning",
    "abstract": (
        "This study presents Curriculum-KAG, a decision-support system that converts programme goals and learning outcomes into verifiable curricula. "
        "It combines a national expert corpus, multilingual semantic retrieval, course-prerequisite graphs, regulatory rules, and constrained semester scheduling. "
        "On an independent test set, the fine-tuned model achieved ROC-AUC 0.7666. Fresh plans without the Kazakhstan regulatory core reached 86.84% semantic-adjusted semester alignment, compared with 81.23% under the regulatory constraint, while both cohorts retained 100% profile provenance and zero hard violations."
    ),
    "keywords": "curriculum design, learning outcomes, semantic retrieval, expert knowledge, constrained optimization",
    "sections": [
        ("1. Introduction", [
            "Educational programmes must connect intended learning outcomes to courses, assessment, prerequisites, credit volumes, and a feasible sequence of semesters. This requirement follows constructive alignment and outcome-based education: the curriculum is valid only when each declared outcome is supported by observable learning activities and assessment evidence [1], [2]. In practice, programme teams must also satisfy education-level rules, domain quotas, national standards, and institutional constraints. These conditions make curriculum design a constrained evidence-integration problem rather than a free text-generation task.",
            "Curriculum-KAG addresses this problem by retrieving real courses from the national Registry of Educational Programs of Kazakhstan, predicting course-to-learning-outcome links, transferring historical expert evidence, constructing a prerequisite graph, and synthesising one or three curriculum alternatives. A deterministic verifier checks credits, semester loads, prerequisite direction, education level, domain relevance, regulatory components, and real learning-outcome coverage before a plan can become active. The system therefore supports academic decision-making without assigning final authority to artificial intelligence.",
            "The research question is whether a hybrid architecture can transform noisy multilingual registry data and probabilistic model scores into complete curricula whose structural invariants are machine-verifiable and whose individual choices remain understandable to an expert. The principal contribution is the integration of four forms of evidence: multilingual text semantics, longitudinal external expert judgements, graph structure, and formal programme constraints."
        ]),
        ("1.1. Research Hypotheses and Contributions", [
            "The study examines four hypotheses. H1 states that the longitudinal EPVO corpus contains a learnable signal that separates supported and unsupported course-LO pairs. H2 states that programme-scoped expert memory improves the ordering of candidates beyond semantic similarity alone. H3 states that a constrained planner can convert probabilistic links into exact-credit plans without hard violations. H4 states that regulatory and international modes require separate denominators because protected statutory components are not ordinary professional repository courses.",
            "The first contribution is a reproducible national dataset pipeline in which raw records, normalized entities, approved courses, and generation candidates are separated. The second is a two-stage recommendation architecture: a semantic classifier retrieves plausible links and an expert-memory reranker reorders the shortlist using historical evidence. The third is a graph-aware planner that treats credits, levels, domains, prerequisites, and statutory blocks as constraints rather than after-the-fact warnings.",
            "The fourth contribution is an explanation and feedback protocol. Every course can be traced to its source and linked outcomes; model evidence and expert evidence remain distinguishable; uncertain bridge modules are visible; and expert decisions are versioned. The fifth contribution is an independent validation layer that evaluates the stored plan after generation instead of trusting an internal optimisation score.",
            "Unlike a system that asks a language model to write a plausible list of course names, Curriculum-KAG operates over a bounded approved repository and preserves whole-course credits. Generative AI is used only in explicitly marked assistance functions. The core curriculum remains reproducible when external APIs are unavailable, a requirement for institutional use and scientific replication."
        ]),
        ("2. Related Work", [
            "Sentence-BERT maps sentences to a shared vector space and enables efficient semantic retrieval [3]. Multilingual sentence representations are particularly important for the Kazakhstan context because course titles and descriptions appear in Kazakh, Russian, and English. BM25 complements dense retrieval by preserving exact technical expressions that may be diluted in a sentence embedding [4]. Knowledge-augmented generation extends retrieval by attaching structured entities, provenance, and rules to retrieved text [5].",
            "Curriculum construction also resembles multi-objective optimisation. Coverage, relevance, diversity, and interdisciplinarity must be maximised while credit deviation, duplication, prerequisite violations, and domain imbalance are minimised. NSGA-II provides a useful experimental Pareto-search branch [6], but the operational path in this study is a deterministic constrained planner with repair heuristics. This distinction improves reproducibility: the same input can be regenerated and independently verified, while evolutionary search remains available for controlled comparison.",
            "Graph neural networks and recurrent architectures can represent curricular dependencies, but higher complexity is not automatically beneficial. Controlled GNN and LSTM pilots did not outperform the semantic baseline on the available frozen splits. The production pipeline therefore retains SBERT-based retrieval and uses graph reasoning for prerequisite closure and verification rather than promoting an unconfirmed neural architecture [7]-[9]."
        ]),
        ("3. Data and Provenance", [
            "The source corpus was collected from the public Registry of Educational Programs within the Unified Higher Education Platform. The registry reflects a two-stage academic process. First, university departments formulate a programme and map courses to learning outcomes. Second, external experts review these mappings and assign low, medium, or high achievability. The recovered numerical values 0, 0.5, and 1 therefore represent expert relationship strength rather than neural-model confidence.",
            "The data pipeline preserves four layers: immutable raw EPVO records; normalized and deduplicated programmes, courses, outcomes, directions, and expert links; an approved multilingual course repository; and project-scoped generation candidates. This separation prevents raw imports from contaminating active curricula and makes every selected course traceable to its source. The operational PostgreSQL/pgvector repository stores three-language titles and descriptions, embeddings, prerequisite edges, model scores, expert feedback, and versioned plans.",
            "Programme-level train, validation, and test splits were used to reduce contextual leakage. All cards originating from one educational programme remain in the same split. Model thresholds and mixture weights are selected on validation data and then frozen before test evaluation. Dataset and model reports retain the seed, configuration, checksums, and split identifiers."
        ]),
        ("4. Method", [
            "For course c_i and learning outcome o_j, the multilingual encoder g_theta produces L2-normalised vectors. Their semantic similarity is the cosine of the angle between the vectors. A lexical score is added to protect exact professional terminology. The hybrid retrieval score is defined by Equation (1), where alpha is selected on validation data.",
            "Historical expert evidence is transferred conservatively. An EPVO score is used only when the source learning outcome and the new outcome share sufficient semantic or lexical content. Several expert votes are aggregated without collapsing medium and high relations into a single binary label. AI and EPVO scores are displayed separately because they answer different questions: the former is a model prediction for a new pair; the latter is evidence from previously reviewed programmes.",
            "A course is admitted only if it belongs to the selected education level and programme scope, supports at least one learning outcome, satisfies the domain guard, and can participate in a feasible prerequisite closure. Real EPVO courses are preferred. A bridge module is created only when no sufficiently supported real course closes an outcome or an exact credit gap, and it is visibly marked for expert confirmation.",
            "The planner assigns courses to semesters using the typical EPVO semester, prerequisite depth, semantic complexity, and semester capacity. Reranking is constrained: moving a course closer to its historical semester is allowed only if both source and destination loads remain inside the permitted interval and all prerequisite edges still point forward. This prevents a superficially better similarity score from producing an impossible plan."
        ]),
        ("4.1. Auditable Admission and Domain Evidence", [
            "Candidate admission is stricter than nearest-neighbour retrieval. Let I_level, I_scope, I_LO, and I_context denote binary checks for education level, EPVO direction or group, minimum learning-outcome evidence, and absence of a foreign professional context. A candidate can enter the optimisation pool only when their product equals one. This rule blocks, for example, a master's robotics course from entering a bachelor's programme and prevents a generic occurrence of the word digital from legitimising an unrelated professional discipline.",
            "Deduplication is performed before domain accounting. Several source cards may normalize to one canonical course while retaining evidence from different programmes. Domain evidence is therefore aggregated over every source record rather than inherited from the last database row. Exact programme-group evidence has priority over direction-level evidence, while a course supported by both selected domains can contribute to an interdisciplinary quota. The approach prevents database ordering from changing curriculum composition.",
            "A selected course must support at least one programme learning outcome. The final relationship is accepted through a two-threshold rule: strong model evidence can establish a new link, whereas sufficiently similar historical EPVO evidence can confirm it. Weak signals remain visible but do not satisfy the real-course coverage invariant. Protected SCES RK components receive dedicated system learning outcomes so that they appear in the OBE matrix without pretending to be professional EPVO evidence."
        ]),
        ("4.2. Exact Credits, Bridge Control, and Regulatory Closure", [
            "Credit fitting treats a real course as an atomic unit. Its original credit value cannot be silently reduced or split to close a semester gap. After the protected SCES RK block is inserted, the remaining professional-credit target is solved as an exact-fit selection problem over admissible course credits. Dynamic programming retains the best evidence-bearing combination for every reachable credit sum and selects the exact remainder before considering a synthetic filler.",
            "Bridge modules have two legitimate roles: they may represent genuinely new content at the intersection of fields, or they may close a learning-outcome gap for which the repository has no sufficiently supported real course. A generic component placeholder is never treated as a discipline. The replacement service retrieves three real alternatives, exposes title, description, credits, level, AI evidence, EPVO evidence, and prerequisites, and stores the expert's selection for the next transactional generation.",
            "Regulatory closure is conditional on programme mode and level. International programmes do not receive Kazakhstan-specific mandatory courses. A programme created under SCES RK receives only the applicable bachelor's, master's, or doctoral components, including practice, research work, and final attestation with their prescribed credits. These elements are protected from suspicious-course replacement and from diversity mutations across A/B/C."
        ]),
        ("4.3. Knowledge Graph, Semester Repair, and A/B/C Transactions", [
            "The curriculum graph contains course nodes, learning-outcome nodes, prerequisite edges, postrequisite relations, domain membership, and semester assignments. Explicit repository prerequisites are combined with conservative inferred edges based on foundation and advanced terminology. The graph is required to be acyclic after repair. For every edge c_a -> c_b, the verifier requires semester(c_a) < semester(c_b), except for separately classified concurrent regulatory activities.",
            "Semester repair uses bounded whole-course moves and swaps. It first addresses hard prerequisite or load violations, then improves pedagogical ordering and historical semester proximity. Moving a late advanced clinical, cybersecurity, research, or systems course into the first foundation term is prohibited by semantic floors. Introductory and foundation courses receive upper bounds so that one anomalous historical record cannot push them to the final year.",
            "Alternative generation varies ranking weights and candidate choices while preserving a common regulatory core. Pairwise fingerprints and Jaccard similarity ensure that A, B, and C are genuinely distinct. All requested alternatives are generated and verified before one atomic commit. This protects old active plans and makes a generation failure recoverable. Users can activate any successful alternative and retain the other versions for comparison."
        ]),
        ("4.4. Formal Objective and Independent Verifier", [
            "Let x_i indicate inclusion of course c_i and z_is its assignment to semester s. The planner maximises a weighted objective containing probabilistic LO coverage, domain relevance, expert evidence, diversity, and historical-semester agreement. Penalties represent duplicate content, credit deviation, quota deficits, bridge count, and prerequisite complexity. The weights define variants A, B, and C but do not relax hard constraints.",
            "The main constraints require each selected course to appear in exactly one semester, the total credits to equal the programme target within the declared tolerance, each semester to remain within its load interval, and every prerequisite to precede its dependent course. Domain credits must meet project quotas, and each professional LO must have at least one admitted real course unless an explicitly reviewed bridge is retained. Education-level and SCES RK guards are Boolean admission constraints.",
            "The verifier recomputes these properties from the persisted plan. Feasibility V(P) equals one only when the credit, load, prerequisite, level, duplicate, domain, LO-evidence, and regulatory predicates all equal one. This independent calculation prevents an optimisation routine from declaring success using stale intermediate state. International-quality indicators are reported alongside V(P) but cannot override a failed hard predicate.",
            "Coverage is probabilistic rather than a simple course count. If several moderately supported courses address one outcome, their combined evidence increases while remaining bounded by one. This avoids reporting 300% coverage and prevents a single weak course from automatically producing a full score. The interface also shows the contributing courses so that an expert can inspect whether statistical aggregation matches academic judgement."
        ]),
        ("5. Experimental Design", [
            "Evaluation separates pair classification, retrieval ranking, and complete-plan validity. ROC-AUC, PR-AUC, and F1 evaluate course-to-outcome classification. Recall@K measures the fraction of expert-relevant courses recovered in the first K positions, MRR rewards the position of the first relevant course, and nDCG@K evaluates the full graded ordering. At plan level, the verifier checks exact credits, semester load, prerequisites, education level, duplicate titles, domain quotas, real learning-outcome evidence, and protected regulatory components.",
            "The fresh cohort comparison uses six quality-eligible programmes: projects 13, 15, and 16 without SCES RK, and projects 19, 136, and 137 with protected SCES RK components. Project 135 is a predefined negative stress test and is excluded before aggregation. Cohorts are equal in size, all reported plans are freshly generated, and the same validator and tolerance of ±1 semester are used. This is a structural validation, not a blinded accreditation study.",
            "SCES RK is the State Compulsory Standard of Education of the Republic of Kazakhstan. Depending on education level, it introduces a protected core of mandatory general education, practice, research work, and final attestation. These components cannot be replaced merely to increase semantic similarity. Consequently, raw EPVO provenance and semester flexibility are expected to be lower in the regulated cohort; profile-only metrics must therefore be reported separately."
        ]),
        ("6. Results", [
            "The base multilingual SBERT achieved ROC-AUC 0.7031, PR-AUC 0.6946, and F1 0.6886. Fine-tuning on 40,000 EPVO pairs improved these values to 0.7666, 0.7681, and 0.7188. A cached 12k candidate reached 0.7748, 0.7746, and 0.7268 but remains an experimental candidate rather than silently replacing the validated operational baseline. A separate ranking-loss model achieved Recall@10 0.7071, MRR 0.7815, and nDCG@10 0.6923 on its frozen benchmark.",
            "A second controlled retrieval experiment combined SBERT with global and programme-scoped expert memory. On its independent clean-v2 split, Recall@10 increased from 0.5348 to 0.5657, Recall@20 from 0.7476 to 0.7580, MRR from 0.2898 to 0.3740, and nDCG@10 from 0.3163 to 0.3735. The same result was preserved when the memory limit increased from 64 to 128 candidates, providing an initial robustness check. The production model was not changed by this experiment.",
            "The cohort comparison shows that plans without SCES RK achieved 86.84% semantic-adjusted semester alignment, whereas regulated plans achieved 81.23%. The 5.61 percentage-point difference is attributed to lower scheduling freedom: the regulated cohort contains 35 protected components across three plans. The raw semester gap is larger, 13.75 points, but falls to 5.61 points after prerequisite and pedagogical adjustments. Both cohorts achieved 100% profile provenance after excluding the regulatory block, a 100% international checklist score, and zero hard violations.",
            "Fresh aggregation across all six eligible programmes produced raw semester agreement of 76.82%, prerequisite-adjusted agreement of 80.42%, and semantic-adjusted agreement of 84.03%. The constrained feasibility indicator is retained as a separate diagnostic and does not replace these historical-agreement metrics. On control project 137 it reached 100%, meaning that every remaining disagreement could not be repaired by a direct move without violating the 27-33-credit envelope; it does not mean that every historical semester was reproduced exactly."
        ]),
        ("6.1. End-to-End Control Programmes and Ablation Evidence", [
            "Control programmes cover conventional and interdisciplinary bachelor's designs, a master's programme, and a doctoral programme. Fresh generation produced exact totals of 240, 120, and 180 credits at the corresponding levels. The stored plans passed prerequisite, level, duplicate, credit-integrity, foreign-context, and regulatory checks. The international checklist reported 100% for all six quality-eligible programmes, while the predefined negative control remained outside the cohort rather than being used to inflate the mean.",
            "Ablation observations identify which safeguards cause the improvement. In the Digital Forensics Investigator case, the education-level guard removed courses from inappropriate levels, final LO repair established real coverage for every professional outcome, and the contextual guard removed unrelated courses hidden behind generic digital terminology. In IT-medicine, the real-course-first residual rule selected an admissible EPVO course before a generic credit filler and eliminated unnecessary bridges.",
            "The D094 doctoral control demonstrates exact fitting after a large regulatory block. The planner retained the protected research, practice, and attestation components and selected an exact professional remainder from real courses. Earlier bridge-heavy variants were replaced by evidence-bearing EPVO courses while maintaining 180 total credits and zero hard violations. This case is important because raw provenance alone would understate quality: most credits are intentionally regulatory.",
            "The A/B/C mechanism was also tested for diversity. Alternatives share mandatory components but differ in professional composition and ranking priorities. Transactional fingerprints prevent accidental publication of identical variants. When only one plan is requested, the system avoids the cost of building unused alternatives; A/B/C can later be completed from the same frozen project constraints."
        ]),
        ("6.2. Efficiency, Failure Handling, and Explainability", [
            "Repeated preprocessing was a major source of latency. Cache signatures now incorporate relevant data and configuration, so unchanged EPVO normalization and course-to-outcome scoring can be reused. In a controlled repeated build, the EPVO stage decreased from 28.45 to 0.15 seconds and the scoring stage from 175.38 to 0.16 seconds; full generation decreased from 320.5 to 138.3 seconds because the remaining time represented actual A/B/C synthesis and verification.",
            "External AI services are optional assistants for proposing programme goals, learning outcomes, achievability explanations, and bridge titles. Structured response contracts validate language, item count, score ranges, and domain relevance. Provider failure activates a deterministic fallback and never bypasses the curriculum verifier. Long operations expose progress rather than leaving the interface in an indefinite loading state.",
            "The explanation layer distinguishes final relationship strength, AI prediction, and EPVO evidence. A statement such as AI 76% and EPVO 21% means that two independent signals support the same course-LO pair; the numbers are not percentages of the programme and are not added. The interface also lists preceding and subsequent courses from the active plan, making the graph useful for curriculum review rather than merely decorative."
        ]),
        ("6.3. Registry Comparison and International Quality", [
            "A generated interdisciplinary programme is not expected to copy one historical programme. For each EPVO reference programme, the system calculates shared courses, Jaccard overlap, generated-plan containment, and reference recall. Low overlap with any single source can coexist with high provenance when the new programme intentionally combines validated components from several directions. The comparison screen therefore displays several neighbours and missing or distinctive elements instead of presenting one analogue as ground truth.",
            "The international checklist operationalises OBE, ABET-style continuous improvement, CDIO integration, and Tuning competence principles. It checks outcome coverage, credit and semester consistency, prerequisite integrity, domain relevance, interdisciplinary integration, assessment-method availability, and evidence of expert participation. The score is diagnostic: every component remains expandable and actionable, and a 100% software checklist is not described as international accreditation.",
            "The cohort results illustrate this distinction. Both groups obtained a 100% checklist score because their plans passed the implemented criteria. The semantic semester values remained below 100% because historical agreement is a separate external comparison. Maintaining both results prevents the system from hiding a semester discrepancy behind a broad quality score and gives the programme team a concrete target for manual or algorithmic refinement.",
            "The knowledge graph provides an additional visual audit. For a selected alternative, nodes are arranged by semester, prerequisite edges are directed, and the interface explains what the student is expected to acquire after each term. Course cards list prerequisites and postrequisites from the active plan. A future empirical study can compare these generated progression statements with student assessment data."
        ]),
        ("7. Discussion", [
            "The results show why regulatory and professional metrics must not be conflated. Raw provenance in the SCES RK cohort is 61.36% because protected practices, research work, and attestation are regulatory objects rather than ordinary EPVO courses. After excluding these expected objects, profile provenance is 100% in both cohorts. Reporting only the raw percentage would incorrectly portray statutory compliance as retrieval failure.",
            "The semester comparison has the same interpretation. Unregulated programmes can move courses more freely toward historical EPVO positions, so they exceed the regulated cohort. Nevertheless, the regulated plans remain feasible, have no hard violations, and preserve all profile-course provenance. Curriculum-KAG therefore provides a strong initial plan rather than a final legal or accreditation decision.",
            "In a preliminary expert demonstration, specialists from Abylkas Saginov Karaganda Technical University and the Academy of Public Administration under the President of the Republic of Kazakhstan assessed the resulting programmes positively, particularly their traceability, explainability, and protection of regulatory components. They recommended limited manual refinement of disputed links and syllabus-level details before formal approval. This assessment supports the human-in-the-loop design: automation prepares a coherent evidence package, while the academic expert retains authority.",
            "The practical value lies in reducing repetitive work. A programme team can define the field, education level, goals, and learning outcomes; obtain scoped course candidates; inspect why each course was selected; compare alternatives; review prerequisite and postrequisite chains; and correct uncertain links. Expert actions are stored as future learning data, enabling continuous improvement without hiding human responsibility."
        ]),
        ("8. System Implementation and Reproducibility", [
            "The implemented system uses a FastAPI backend, a React interface, PostgreSQL as the primary transactional database, and pgvector for semantic indexing. Course, learning-outcome, prerequisite, expert-evidence, and plan-version entities are stored separately. This avoids embedding essential provenance in generated prose and permits the verifier to reproduce every decision directly from structured records. SQLite is retained only as a lightweight local fallback; experiments and the reported fresh generations use the PostgreSQL path.",
            "Generation is transactional. The planner constructs the requested alternative or the complete A/B/C set in memory, applies repair procedures, verifies each result, and commits only when the requested set satisfies the invariants. If a provider timeout, an impossible credit remainder, or a validation error occurs, the transaction is rolled back and the previous active plan remains unchanged. This property is important for academic information systems because a partial generation must never overwrite a previously approved curriculum.",
            "The planning process is divided into observable stages: scope selection, EPVO candidate retrieval, course-to-outcome scoring, regulatory closure, prerequisite closure, credit fitting, semester allocation, repair, and independent validation. The interface reports stage progress, prevents duplicate launches, and permits generation of either one plan or three alternatives. If one plan was initially requested, the remaining alternatives can be generated later without recreating the project definition.",
            "Course explanations expose the final relationship strength, the AI prediction, the transferred EPVO expert score, source direction and programme group, prerequisite role, and semester rationale. These numbers are not added as if they were parts of one percentage. They are separate evidence channels combined by an explicit policy. The expert may confirm a link, mark it as weak or incorrect, propose a correction, or exclude a course from the next regeneration. This feedback is versioned and can become supervised data in a later model cycle.",
            "The multilingual layer stores title and description records independently for Russian, Kazakh, and English, together with a source status. Verified source translations are distinguished from generated drafts requiring review. Interface labels, cycle names, errors, exports, and course explanations use the selected language with deterministic fallback. This design prevents a translated interface from silently displaying a course in a different language and preserves the origin of each text.",
            "Reproducibility artefacts include the frozen split, seed 42, dataset counts, model and configuration identifiers, metric JSON files, plan fingerprints, and automated regression tests. The current local suite covers semantic deduplication, education-level guards, regulatory protection, prerequisite order, credit tolerance, course uniqueness, multilingual integrity, and safe fallback when an external AI provider is unavailable. The same validator is called by the interface and by offline experiments, reducing divergence between a scientific benchmark and the operational application."
        ]),
        ("9. Validity and Academic Use", [
            "Internal validation establishes software and structural validity: generated plans satisfy declared formal constraints, model experiments use programme-disjoint splits, and reported cohort metrics can be recomputed from saved artefacts. Content validity is supported by the longitudinal EPVO corpus and by the separation of AI prediction from historical expert evidence. Construct validity is strengthened by reporting classification, ranking, provenance, semester alignment, and whole-plan feasibility as different measurements rather than compressing them into one opaque score.",
            "The cohort result should be interpreted at its observed scale. Three regulated and three unregulated programmes are sufficient for a controlled engineering comparison but not for a population-level claim about every field in Kazakhstan. The study therefore reports programme identifiers, a predefined negative control, and the exact cohort rule. Future evaluation can add a temporal holdout, blind review with a common rubric, inter-rater agreement, discipline-level error analysis, and prospective measurement of learning outcomes after programme implementation.",
            "For practical deployment, the system acts as a co-designer. It can prepare an initial programme structure, reveal missing outcome coverage, identify inconsistent prerequisites, compare the design with programmes in the Registry, and produce an auditable evidence package. The responsible academic body still approves the programme goal, learning outcomes, course contents, assessment strategy, staff and infrastructure requirements, and compliance with the current legal edition of SCES RK.",
            "The distinction between a bridge module and a real EPVO course is preserved throughout the lifecycle. A bridge represents a justified curriculum hypothesis at the intersection of fields. It becomes an ordinary approved course only after an expert selects or edits its title, description, credits, outcomes, prerequisites, and assessment approach. This workflow allows genuinely new interdisciplinary content without presenting synthetic modules as historical registry evidence.",
            "The next research stage will optimise semester ranking directly under credit and prerequisite constraints. Candidate moves will be evaluated globally rather than as isolated swaps, while the raw historical metric remains unchanged for comparability. Retrieval experiments will test programme-dependent hard negatives and listwise expert-strength objectives. A new model will be promoted only if it improves Recall, MRR, and nDCG on an independent split and preserves whole-plan invariants on fresh generation."
        ]),
        ("9.1. Research Roadmap", [
            "The first planned extension is a larger blind expert evaluation. Reviewers from several disciplinary groups will receive generated and reference fragments without knowing their origin and will score relevance, semester appropriateness, prerequisite coherence, and readiness for adoption. Inter-rater agreement and confidence intervals will complement the existing qualitative demonstration.",
            "The second extension is temporal validation. Programmes registered before a cut-off will form training memory, whereas later programmes will be held out. This will test whether the method predicts future academic choices rather than recalling contemporary duplicates. Direction-transfer experiments will measure performance in data-poor fields and determine when a bridge is preferable to a weak cross-domain match.",
            "The third extension is learning-to-rank with graded expert strength. Direct regression to 0, 0.5, and 1 did not improve retrieval in the pilot, so future work will use pairwise or listwise ordering within one programme. Hard negatives will be selected from the same level and nearby direction, making them semantically plausible but academically incorrect and therefore more informative than random negatives.",
            "Finally, the curriculum graph can support syllabus generation, weekly topic allocation, assessment mapping, and longitudinal programme monitoring. These functions should inherit the same provenance and verifier principles. A generated syllabus will be treated as a draft linked to credits and LOs, while measured student achievement and expert revisions will close the continuous-improvement loop."
        ]),
        ("10. Conclusion", [
            "Curriculum-KAG demonstrates that national expert memory, multilingual semantic retrieval, graph constraints, and deterministic repair can be combined into a reproducible curriculum-synthesis workflow. The system produced feasible plans in both regulated and international modes, retained 100% profile provenance, and achieved zero hard violations in the reported cohorts. The measured 86.84% versus 81.23% semantic-adjusted semester alignment clarifies the effect of the protected SCES RK core. The remaining manual refinement is intentionally exposed through explanations and expert feedback rather than concealed by an aggregate score."
        ]),
    ],
}


RU = {
    "title": "Доказательный синтез учебных планов: экспертные данные, семантический поиск и ограниченное распределение по семестрам",
    "abstract": (
        "Представлена система Curriculum-KAG, преобразующая цели и результаты обучения в проверяемые учебные планы. "
        "Метод объединяет экспертную базу ЕПВО, многоязычный семантический поиск, граф пререквизитов, нормативные правила и constrained-распределение по семестрам. "
        "Без ГОСО семантически скорректированное соответствие семестру составило 86,84%, с ГОСО - 81,23%; обе группы сохранили 100% профильного происхождения дисциплин из ЕПВО и ноль жёстких нарушений."
    ),
    "keywords": "образовательная программа, результаты обучения, ЕПВО, семантический поиск, constrained-оптимизация",
    "sections": [
        ("1. Введение", [
            "Образовательная программа должна связывать заявленные результаты обучения с дисциплинами, оцениванием, пререквизитами, кредитами и последовательностью семестров. Эта логика соответствует конструктивному согласованию и outcome-based education: результат обучения считается достижимым только при наличии содержательных и проверяемых учебных единиц [1], [2]. На практике разработчик одновременно учитывает уровень образования, предметную область, нормативные требования и допустимую нагрузку.",
            "Curriculum-KAG решает задачу как управляемый синтез на основе доказательств. Система извлекает реальные дисциплины из национального Реестра образовательных программ ЕПВО, прогнозирует связи дисциплина-результат обучения, переносит историческое экспертное подтверждение, формирует граф пререквизитов и строит один или три варианта учебного плана. До активации независимый verifier проверяет кредиты, семестры, уровень образования, предметную релевантность, нормативные компоненты и покрытие результатов обучения реальными дисциплинами.",
            "Исследовательский вопрос состоит в том, может ли гибридная архитектура преобразовать шумные многоязычные данные и вероятностные оценки в полный план с формально проверяемыми инвариантами. Новизна заключается в совместном использовании четырёх источников: семантики текста, накопленных внешних экспертных оценок, структуры графа и жёстких ограничений программы."
        ]),
        ("1.1. Гипотезы и научный вклад", [
            "Проверяются четыре гипотезы. H1: многолетний корпус ЕПВО содержит обучаемый сигнал для различения подтверждённых и неподтверждённых связей дисциплина-РО. H2: scoped-память экспертов улучшает порядок кандидатов по сравнению с одной семантикой. H3: constrained-планировщик преобразует вероятностные связи в точный кредитный план без жёстких нарушений. H4: нормативный и международный режимы требуют разных знаменателей из-за защищённых компонентов.",
            "Первый вклад - воспроизводимый национальный конвейер данных с разделением raw, normalized, approved repository и generation candidates. Второй - двухэтапная рекомендация: семантический классификатор получает кандидатов, а экспертная память меняет их порядок. Третий - graph-aware планировщик, для которого кредиты, уровни, направления, пререквизиты и ГОСО являются ограничениями, а не предупреждениями после генерации.",
            "Четвёртый вклад - протокол объяснения и обратной связи. Каждая дисциплина прослеживается до источника и РО; прогноз модели отделён от экспертного доказательства; bridge видим; решение эксперта версионируется. Пятый вклад - независимый verifier сохранённого плана, который не доверяет внутреннему score оптимизатора.",
            "В отличие от запроса языковой модели на правдоподобный список названий, Curriculum-KAG работает в ограниченном утверждённом репозитории и сохраняет целые кредиты. Генеративный ИИ включается только в явно маркированные вспомогательные функции. Основной план воспроизводится и без внешнего API."
        ]),
        ("2. Связанные исследования", [
            "Sentence-BERT формирует векторные представления предложений и обеспечивает быстрый семантический поиск [3]. Для Казахстана особенно важна многоязычность, поскольку карточки дисциплин представлены на казахском, русском и английском языках. BM25 сохраняет точные профессиональные термины [4], а Knowledge-Augmented Generation дополняет поиск сущностями, происхождением и правилами [5].",
            "Проектирование плана является многокритериальной задачей: требуется максимизировать покрытие, релевантность и междисциплинарность при минимизации дублирования и нарушений. NSGA-II используется как экспериментальная Pareto-ветка [6]. Рабочий путь системы - детерминированный constrained-планировщик с repair-эвристиками, что обеспечивает повторяемость результата и независимую проверку.",
            "Контролируемые эксперименты GNN и LSTM не превзошли SBERT на зафиксированных выборках. Поэтому графовые правила применяются для замыкания пререквизитов и верификации, а усложнение нейронной архитектуры не внедряется без подтверждённого выигрыша [7]-[9]."
        ]),
        ("3. Данные и происхождение", [
            "Корпус получен из публичного Реестра образовательных программ ЕПВО. Данные отражают двухэтапную экспертизу. Сначала кафедра разрабатывает программу и связывает дисциплины с результатами обучения. Затем внешние эксперты оценивают достижимость связей как низкую, среднюю или высокую. Восстановленные значения 0, 0,5 и 1 являются силой экспертной связи, а не уверенностью нейронной модели.",
            "Конвейер разделён на четыре слоя: неизменяемые raw-данные; нормализованные и дедуплицированные программы, дисциплины, результаты и экспертные связи; утверждённый многоязычный репозиторий; кандидаты конкретного проекта. PostgreSQL/pgvector хранит три языковые версии, embeddings, пререквизиты, модельные оценки, обратную связь и версии планов.",
            "Разбиение train/validation/test выполнено на уровне программ: карточки одной университетской программы не попадают одновременно в обучение и тест. Пороги и веса выбираются на validation и фиксируются до теста. Для воспроизводимости сохраняются seed, конфигурация, контрольные суммы и идентификаторы split."
        ]),
        ("4. Метод", [
            "Для дисциплины c_i и результата обучения o_j многоязычный encoder g_theta формирует нормализованные векторы. Семантическая близость рассчитывается как косинус, а лексический сигнал сохраняет точные профессиональные термины. Итог поиска определяется формулой (1), где alpha выбирается по validation.",
            "Экспертный сигнал ЕПВО переносится консервативно: он используется только при достаточном совпадении исходного и нового результата обучения. Несколько экспертных голосов агрегируются без сведения средней и высокой связи к одной бинарной метке. В интерфейсе AI-score и EPVO-score показаны раздельно.",
            "Дисциплина допускается в план, если соответствует уровню и выбранному направлению, подтверждает хотя бы один результат обучения, проходит domain guard и допускает замыкание пререквизитов. Реальные дисциплины ЕПВО имеют приоритет. Bridge-модуль создаётся только при отсутствии сильной реальной замены и явно маркируется для экспертного решения.",
            "Распределение по семестрам учитывает типичный семестр ЕПВО, глубину пререквизитов, сложность и вместимость. Constrained-reranking переносит дисциплину ближе к историческому семестру лишь тогда, когда исходный и целевой семестры остаются в диапазоне нагрузки, а все стрелки пререквизитов направлены вперёд."
        ]),
        ("4.1. Аудируемый допуск и доменные доказательства", [
            "Допуск кандидата строже обычного nearest-neighbour поиска. Обозначим I_level, I_scope, I_LO и I_context бинарные проверки уровня образования, направления или группы ЕПВО, минимального доказательства РО и отсутствия чужого профессионального контекста. Дисциплина входит в пул оптимизации только при произведении индикаторов, равном единице. Поэтому магистерский курс робототехники не попадает в бакалавриат, а слово «цифровой» не легализует нерелевантную дисциплину.",
            "Дедупликация выполняется до учёта предметных областей. Несколько исходных карточек могут образовать одну каноническую дисциплину, сохранив доказательства разных программ. Доменные оценки агрегируются по всем источникам, а не берутся из последней строки базы. Точное совпадение группы ОП имеет приоритет над направлением; дисциплина с доказательствами обеих областей учитывается как междисциплинарная.",
            "Каждая выбранная дисциплина должна поддерживать хотя бы один РО программы. Двухпороговое правило допускает сильное новое доказательство модели или подтверждение достаточно похожей исторической связью ЕПВО. Слабые сигналы видимы эксперту, но не закрывают инвариант реального покрытия. Для защищённых компонентов ГОСО создаются отдельные системные РО без выдачи их за профильные данные ЕПВО."
        ]),
        ("4.2. Точные кредиты, bridge-контроль и нормативное замыкание", [
            "Реальная дисциплина является атомарной кредитной единицей: её кредиты нельзя незаметно уменьшить или разделить. После вставки защищённого блока ГОСО профильный остаток решается как exact-fit задача. Динамическое программирование сохраняет лучший набор доказательных дисциплин для каждой достижимой суммы и выбирает точный остаток до создания синтетического заполнителя.",
            "Bridge-модуль допустим как действительно новое содержание на стыке областей либо как закрытие РО, для которого нет сильной реальной дисциплины. Пустой «компонент по выбору» не считается дисциплиной. Сервис замены показывает три реальных варианта, их описание, кредиты, уровень, AI/EPVO evidence и пререквизиты; выбор эксперта сохраняется для следующей генерации.",
            "Нормативное замыкание зависит от режима и уровня. Международная программа не получает казахстанские обязательные дисциплины. Режим ГОСО добавляет только применимые компоненты бакалавриата, магистратуры или докторантуры, включая практики, НИР и итоговую аттестацию с заданными кредитами. Они защищены от удаления и случайной мутации между A/B/C."
        ]),
        ("4.3. Граф знаний, semester-repair и транзакция A/B/C", [
            "Граф содержит дисциплины, РО, пререквизиты, постреквизиты, предметные области и семестры. Явные связи репозитория дополняются осторожно выведенными зависимостями «основа - продвинутый курс». После repair граф обязан быть ацикличным. Для каждого ребра c_a -> c_b verifier требует semester(c_a) < semester(c_b), кроме отдельно классифицированных параллельных нормативных активностей.",
            "Semester-repair использует ограниченные переносы и обмены целых дисциплин. Сначала устраняются жёсткие нарушения, затем улучшается педагогический порядок и историческая близость. Продвинутый клинический, кибербезопасностный или исследовательский курс не переносится в первый фундаментальный семестр. Вводные дисциплины получают верхнюю границу, чтобы единичная аномальная карточка ЕПВО не отправляла их в выпускной год.",
            "A/B/C различаются весами ranking и выбором кандидатов при общем нормативном ядре. Fingerprint и pairwise Jaccard проверяют реальное различие. Все запрошенные варианты строятся и проверяются до единого atomic commit. При ошибке старые активные планы сохраняются, а пользователь может активировать любой успешный вариант."
        ]),
        ("4.4. Формальная целевая функция и независимый verifier", [
            "Пусть x_i показывает включение дисциплины c_i, а z_is - назначение в семестр s. Планировщик максимизирует взвешенную функцию вероятностного покрытия РО, доменной релевантности, экспертного доказательства, разнообразия и исторической близости семестра. Штрафуются дубли, кредитное отклонение, дефицит квот, число bridge и сложность графа. Разные веса формируют A/B/C, но не ослабляют жёсткие ограничения.",
            "Ограничения требуют назначения каждой выбранной дисциплины ровно в один семестр, соблюдения итоговых кредитов и допустимой нагрузки, предшествования каждого пререквизита, выполнения квот областей и реального доказательства каждого профессионального РО. Level guard и ГОСО являются булевыми условиями допуска.",
            "Verifier пересчитывает свойства из сохранённого плана. Feasibility V(P)=1 только при одновременном выполнении предикатов кредитов, нагрузки, пререквизитов, уровня, отсутствия дубликатов, квот, LO-evidence и ГОСО. Это не позволяет оптимизатору объявить успех по устаревшему промежуточному состоянию. Международный score не может перекрыть провал жёсткого условия.",
            "Покрытие РО вероятностное, а не простая сумма дисциплин. Несколько средних доказательств усиливают результат, оставаясь в диапазоне до единицы. Поэтому система не показывает 300% покрытия и не считает одну слабую связь полноценным достижением. Интерфейс раскрывает дисциплины-источники для академической проверки."
        ]),
        ("5. Дизайн эксперимента", [
            "Классификация связи оценивается ROC-AUC, PR-AUC и F1. Retrieval оценивается Recall@K, MRR и nDCG@K. На уровне полного плана проверяются точные кредиты, нагрузка, пререквизиты, уровень образования, дубликаты, квоты областей, реальное покрытие РО и защищённые нормативные компоненты.",
            "Для сравнения отобраны шесть quality-eligible программ: проекты 13, 15 и 16 без ГОСО; проекты 19, 136 и 137 с защищёнными компонентами ГОСО. Проект 135 является заранее заданным отрицательным stress-test и исключён до агрегации. В обеих группах по три программы, используется один validator и допуск ±1 семестр.",
            "ГОСО - государственный общеобязательный стандарт образования Республики Казахстан. Он задаёт защищённое нормативное ядро: обязательные компоненты, практики, научно-исследовательскую работу и итоговую аттестацию в зависимости от уровня образования. Их нельзя заменить только ради роста семантического процента. Поэтому полное происхождение ЕПВО и свобода перемещения по семестрам ожидаемо ниже, а профильные метрики показываются отдельно."
        ]),
        ("6. Результаты", [
            "Исходная multilingual SBERT получила ROC-AUC 0,7031, PR-AUC 0,6946 и F1 0,6886. Дообучение на 40 000 парах ЕПВО повысило результаты до 0,7666, 0,7681 и 0,7188. Cached-кандидат 12k достиг 0,7748, 0,7746 и 0,7268, но сохранён как экспериментальный кандидат. Модель ranking-loss получила Recall@10 0,7071, MRR 0,7815 и nDCG@10 0,6923.",
            "Комбинация SBERT с глобальной и scoped-памятью экспертов на independent clean-v2 split повысила Recall@10 с 0,5348 до 0,5657, Recall@20 с 0,7476 до 0,7580, MRR с 0,2898 до 0,3740 и nDCG@10 с 0,3163 до 0,3735. Результат сохранился при расширении памяти с 64 до 128 кандидатов. Рабочая production-модель этим экспериментом не заменялась.",
            "Без ГОСО семантически скорректированное соответствие семестру достигло 86,84%, с ГОСО - 81,23%. Разница 5,61 процентного пункта связана с меньшей свободой планирования: в трёх программах ГОСО присутствуют 35 защищённых компонентов. Сырая разница равна 13,75 пункта, но уменьшается после учёта пререквизитов и педагогической сложности. Обе группы получили 100% профильного происхождения из ЕПВО, 100% международного чек-листа и ноль жёстких нарушений.",
            "По всем шести пригодным программам сырое соответствие семестру составило 76,82%, с учётом пререквизитов - 80,42%, с учётом семантических границ - 84,03%. Constrained-feasibility сохраняется отдельной диагностикой. На проекте 137 она составила 100%: оставшиеся прямые переносы нарушали бы диапазон 27-33 кредита. Это не означает буквальное совпадение каждого исторического семестра."
        ]),
        ("6.1. Сквозные контрольные программы и ablation", [
            "Контроль включает обычные и междисциплинарные программы бакалавриата, магистратуру и докторантуру. Свежая генерация дала точные объёмы 240, 120 и 180 кредитов. Планы прошли проверки пререквизитов, уровня, дубликатов, целостности кредитов, чужого контекста и ГОСО. Международный чек-лист равен 100% для шести quality-eligible программ; заранее заданный отрицательный контроль не включён в среднее.",
            "Ablation показывает вклад защитных механизмов. В программе «Киберследователь» level guard удалил дисциплины чужого уровня, финальный LO-repair обеспечил реальное покрытие профессиональных РО, context guard убрал нерелевантные курсы со случайным цифровым термином. В IT-медицине real-course-first правило выбрало допустимую дисциплину ЕПВО вместо общего заполнителя и сократило bridge.",
            "Докторская программа D094 демонстрирует exact-fit после крупного нормативного блока. Планировщик сохранил практики, НИР и аттестацию, затем набрал точный профильный остаток реальными дисциплинами. Bridge-heavy варианты были заменены доказательными курсами при 180 кредитах и нуле жёстких нарушений. Сырая provenance здесь ожидаемо ниже из-за нормативных кредитов.",
            "Проверено и разнообразие A/B/C. Обязательные компоненты совпадают, но профильный состав и ranking-приоритеты различаются. Транзакционные fingerprints запрещают публикацию одинаковых альтернатив. При выборе одной программы система не тратит время на две неиспользуемые, но позволяет достроить их позднее из тех же ограничений проекта."
        ]),
        ("6.2. Производительность, отказоустойчивость и объяснимость", [
            "Повторная предобработка была главным источником задержки. Подпись кэша учитывает данные и конфигурацию, поэтому неизменившиеся этапы ЕПВО и scoring переиспользуются. В повторном контрольном запуске этап ЕПВО сократился с 28,45 до 0,15 секунды, scoring - со 175,38 до 0,16 секунды, а полная A/B/C генерация - с 320,5 до 138,3 секунды. Оставшееся время относится к реальному синтезу и verifier.",
            "Внешние AI API используются только для предложений целей, РО, объяснений достижимости и названий bridge. Типизированный контракт проверяет язык, число элементов, диапазон оценок и предметную релевантность. При сбое включается детерминированный fallback, который не обходит verifier. Длительные операции показывают этапы прогресса и блокируют повторный запуск.",
            "Объяснение разделяет итоговую силу связи, прогноз ИИ и доказательство ЕПВО. AI 76% и EPVO 21% означают два независимых сигнала для одной пары, а не доли программы и не числа для сложения. Интерфейс дополнительно показывает предшествующие и последующие дисциплины активного плана, превращая граф в инструмент экспертизы."
        ]),
        ("6.3. Сравнение с Реестром и международное качество", [
            "Новая междисциплинарная программа не обязана копировать один исторический план. Для каждой программы ЕПВО рассчитываются общие дисциплины, Jaccard, containment и recall эталона. Низкое совпадение с одной программой совместимо с высокой provenance, если новый план объединяет подтверждённые элементы нескольких направлений. Экран сравнения показывает несколько аналогов, отсутствующие и уникальные элементы.",
            "Международный чек-лист операционализирует OBE, ABET-style continuous improvement, CDIO и Tuning. Проверяются РО, кредиты, семестры, пререквизиты, предметная релевантность, междисциплинарность, методы оценивания и участие эксперта. Score является диагностикой: 100% программной проверки не называется международной аккредитацией.",
            "Обе когорты получили 100% чек-листа, поскольку прошли реализованные критерии. Семестровое соответствие осталось ниже 100%, так как это отдельное внешнее сравнение. Раздельные результаты не позволяют скрыть проблему семестра общим score и дают ясную цель для ручной или алгоритмической коррекции.",
            "Граф знаний обеспечивает визуальный аудит: узлы расположены по семестрам, стрелки пререквизитов направлены вперёд, а интерфейс объясняет ожидаемый итог каждого семестра. Карточка показывает пре- и постреквизиты активного плана. В будущем эти выводы можно сопоставить с фактическими оценками студентов."
        ]),
        ("7. Обсуждение", [
            "Результаты показывают, почему нормативные и профильные показатели нельзя смешивать. В группе ГОСО полное происхождение ЕПВО равно 61,36%, поскольку практики, исследовательская работа и аттестация являются нормативными объектами, а не обычными карточками дисциплин ЕПВО. После их корректного исключения профильное происхождение равно 100% в обеих группах.",
            "У программ без ГОСО больше свободы для приближения к историческим семестрам, поэтому их процент выше. При этом планы ГОСО остаются выполнимыми, не содержат жёстких нарушений и сохраняют профильные дисциплины ЕПВО. Система формирует сильный исходный вариант, но не заменяет юридическое утверждение и аккредитацию.",
            "В ходе предварительной экспертной демонстрации специалисты Карагандинского технического университета имени Абылкаса Сагинова и Академии государственного управления при Президенте Республики Казахстан высоко оценили связность, объяснимость и защиту нормативных компонентов. Перед формальным утверждением рекомендована небольшая ручная докрутка спорных связей и деталей силлабусов. Это соответствует human-in-the-loop архитектуре.",
            "Практическая ценность состоит в сокращении рутинной работы. Разработчик задаёт идею, направление, уровень, цели и результаты; получает релевантные дисциплины, причины выбора, альтернативы, граф пререквизитов и отчёт о качестве. Экспертные подтверждения сохраняются как данные для дальнейшего улучшения."
        ]),
        ("8. Реализация и воспроизводимость", [
            "Система реализована на FastAPI и React; основной транзакционной базой является PostgreSQL, а pgvector используется для семантического индекса. Дисциплины, результаты обучения, пререквизиты, экспертные доказательства и версии планов хранятся раздельно. Поэтому происхождение не растворяется в сгенерированном тексте, а verifier может повторно получить каждое решение из структурированных записей. SQLite сохраняется только как облегчённый локальный fallback; эксперименты и свежая генерация статьи выполнены в PostgreSQL-режиме.",
            "Генерация транзакционна. Планировщик формирует выбранный вариант или полный набор A/B/C в памяти, применяет repair-процедуры, проверяет каждый результат и фиксирует данные только после прохождения инвариантов. При таймауте провайдера, невозможном кредитном остатке или ошибке проверки транзакция откатывается, а предыдущий активный план сохраняется. Частичный результат не может заменить ранее утверждённую версию.",
            "Процесс разделён на наблюдаемые этапы: выбор scope, получение кандидатов ЕПВО, оценка дисциплина-РО, нормативное замыкание, замыкание пререквизитов, подбор точной суммы кредитов, распределение по семестрам, repair и независимая проверка. Интерфейс показывает прогресс и блокирует повторный запуск. Пользователь может создать один вариант либо сразу A/B/C, а недостающие альтернативы построить позднее.",
            "Объяснение дисциплины показывает итоговую силу связи, прогноз ИИ, перенесённую оценку экспертов ЕПВО, направление и группу ОП, роль в графе и причину семестра. Эти проценты не складываются: они являются отдельными каналами доказательств. Эксперт может подтвердить связь, отметить её как слабую или неверную, исправить или исключить дисциплину из следующей генерации. Решение версионируется и может стать обучающим примером.",
            "Многоязычный слой отдельно хранит названия и описания на русском, казахском и английском языках вместе со статусом источника. Проверенные переводы отделены от черновиков, требующих просмотра. Подписи интерфейса, циклы, ошибки, экспорт и объяснения выбираются по текущему языку с детерминированным fallback. Это предотвращает незаметное смешение языков.",
            "Артефакты воспроизводимости включают frozen split, seed 42, статистику набора, идентификаторы модели и конфигурации, JSON с метриками, fingerprints планов и автоматические regression-тесты. Тесты покрывают дедупликацию, level guard, защиту ГОСО, порядок пререквизитов, допуск кредитов, уникальность дисциплин, целостность трёх языков и безопасный fallback при недоступности внешнего AI API. Один validator используется в интерфейсе и экспериментах."
        ]),
        ("9. Валидность и академическое применение", [
            "Внутренняя проверка подтверждает программную и структурную валидность: планы соблюдают формальные ограничения, модельные эксперименты используют program-disjoint split, а когортные метрики пересчитываются из сохранённых файлов. Содержательная валидность поддерживается многолетним корпусом ЕПВО и разделением прогноза ИИ и исторического экспертного сигнала. Разные аспекты - классификация, ranking, provenance, семестр и выполнимость - не сворачиваются в один непрозрачный балл.",
            "Сравнение интерпретируется в наблюдаемом масштабе. Три программы с ГОСО и три без ГОСО позволяют провести контролируемую инженерную проверку, но не являются заявлением обо всех направлениях Казахстана. Поэтому сохранены идентификаторы проектов, отрицательный контроль и правило формирования когорт. Следующий этап может включать temporal holdout, слепую экспертизу по общей рубрике, inter-rater agreement и перспективное измерение фактических результатов студентов.",
            "В эксплуатации система выступает академическим соавтором решения: готовит структуру, показывает пробелы РО, находит конфликты пререквизитов, сравнивает с Реестром и формирует аудируемый пакет доказательств. Ответственный коллегиальный орган утверждает цель, РО, содержание, методы оценивания, кадровые и инфраструктурные требования и соответствие актуальной редакции ГОСО.",
            "Bridge-модуль не смешивается с реальной дисциплиной ЕПВО. Он является обоснованной гипотезой на стыке областей и становится утверждённой дисциплиной только после выбора или редактирования названия, описания, кредитов, РО, пререквизитов и оценивания экспертом. Так система поддерживает новую междисциплинарность, не выдавая синтетический модуль за исторический факт.",
            "Следующий исследовательский этап будет оптимизировать semester ranking непосредственно под ограничениями кредитов и графа. Переносы оцениваются глобально, а сырая историческая метрика сохраняется для сопоставимости. Retrieval-эксперименты проверят программно-зависимые hard negatives и listwise-цель с экспертной силой. Новая модель будет внедрена только при росте Recall, MRR и nDCG на независимом split и сохранении инвариантов свежей генерации."
        ]),
        ("9.1. Исследовательская дорожная карта", [
            "Первое расширение - более крупная слепая экспертиза. Специалисты нескольких направлений получат фрагменты сгенерированных и реальных планов без указания источника и оценят релевантность, семестр, пререквизиты и готовность к применению. Inter-rater agreement и доверительные интервалы дополнят качественную демонстрацию.",
            "Второе расширение - temporal validation. Программы до даты отсечения формируют память, более поздние остаются в holdout. Это проверит прогноз будущих академических решений, а не запоминание современных дублей. Domain-transfer покажет поведение в малых направлениях и границу выбора bridge вместо слабого междоменного кандидата.",
            "Третье расширение - learning-to-rank с градуированной экспертной силой. Прямая регрессия к 0, 0,5 и 1 не улучшила retrieval в пилоте, поэтому будут проверены pairwise/listwise цели внутри программы. Hard negatives выбираются из того же уровня и близкого направления: они семантически правдоподобны, но академически неверны.",
            "Наконец, граф поддержит генерацию силлабусов, недельных тем, assessment mapping и мониторинг программы. Эти функции наследуют provenance и verifier. Силлабус остаётся draft, связанным с кредитами и РО, а фактическое достижение студентов и экспертные исправления замыкают continuous-improvement цикл."
        ]),
        ("10. Заключение", [
            "Curriculum-KAG показывает, что национальная экспертная память, многоязычный поиск, графовые ограничения и детерминированные repair-эвристики могут быть объединены в воспроизводимый конвейер. Получены выполнимые планы в нормативном и международном режимах, 100% профильного происхождения и ноль жёстких нарушений. Разница 86,84% против 81,23% объясняет влияние защищённого ядра ГОСО, а необходимость небольшой ручной докрутки остаётся видимой в интерфейсе экспертной обратной связи."
        ]),
    ],
}


DATA_ROWS_EN = [
    ["Educational programmes", "12,215"],
    ["Raw course records", "408,638"],
    ["Raw learning outcomes", "124,521"],
    ["Normalized courses", "191,292"],
    ["Normalized expert links", "932,483"],
    ["Pairs with numerical expert labels", "800,793"],
    ["Approved operational courses", "21,525"],
]
DATA_ROWS_RU = [
    ["Образовательные программы", "12 215"],
    ["Исходные записи дисциплин", "408 638"],
    ["Исходные результаты обучения", "124 521"],
    ["Нормализованные дисциплины", "191 292"],
    ["Нормализованные экспертные связи", "932 483"],
    ["Пары с числовой экспертной оценкой", "800 793"],
    ["Утверждённые рабочие дисциплины", "21 525"],
]

MODEL_ROWS = [
    ["Base multilingual SBERT", "0.7031", "0.6946", "0.6886", "-"],
    ["Fine-tuned SBERT 40k", "0.7666", "0.7681", "0.7188", "operational"],
    ["Cached candidate 12k", "0.7748", "0.7746", "0.7268", "experimental"],
]

REFERENCES = [
    "[1] Biggs, J. (1996). Enhancing teaching through constructive alignment. Higher Education, 32, 347-364.",
    "[2] Harden, R. M. (2007). Outcome-based education: the future is today. Medical Teacher, 29(7), 625-629.",
    "[3] Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. EMNLP-IJCNLP, 3982-3992.",
    "[4] Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in Information Retrieval, 3(4), 333-389.",
    "[5] Lewis, P., et al. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. Advances in Neural Information Processing Systems, 33, 9459-9474.",
    "[6] Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). A fast and elitist multiobjective genetic algorithm: NSGA-II. IEEE Transactions on Evolutionary Computation, 6(2), 182-197.",
    "[7] Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. ICLR.",
    "[8] Hamilton, W. L., Ying, R., & Leskovec, J. (2017). Inductive representation learning on large graphs. NeurIPS, 1024-1034.",
    "[9] Hochreiter, S., & Schmidhuber, J. (1997). Long short-term memory. Neural Computation, 9(8), 1735-1780.",
    "[10] Gebru, T., et al. (2021). Datasheets for datasets. Communications of the ACM, 64(12), 86-92.",
    "[11] Mitchell, M., et al. (2019). Model cards for model reporting. FAT* 2019, 220-229.",
    "[12] Unified Higher Education Platform of the Republic of Kazakhstan. Registry of Educational Programs. https://epvo.kz/#/register/education_program",
    "[13] Ministry of Science and Higher Education of the Republic of Kazakhstan. State Compulsory Standards of Higher and Postgraduate Education, revision dated May 4, 2026.",
    "[14] ABET. (2025). Criteria for Accrediting Computing Programs.",
    "[15] Crawley, E. F., Malmqvist, J., Östlund, S., Brodeur, D. R., & Edström, K. (2014). Rethinking Engineering Education: The CDIO Approach. Springer.",
    "[16] González, J., & Wagenaar, R. (Eds.). (2003). Tuning Educational Structures in Europe. University of Deusto.",
]


FIGURES = {
    1: (
        "End-to-end evidence-constrained architecture.",
        "Create a publication-grade vector diagram, white background, two-column-journal readable. Show Programme Goal and Learning Outcomes -> Scoped EPVO Repository -> multilingual SBERT plus BM25 -> EPVO expert-memory reranker -> course-prerequisite knowledge graph -> deterministic constrained planner -> independent verifier -> expert confirmation. Mark PostgreSQL/pgvector as the provenance store. Use navy, teal, green, and amber; no robots, no neon, no fictional metrics; editable SVG and 300-dpi PNG.",
        "Сквозная доказательная архитектура.",
        "Создай строгую векторную схему для научного журнала на белом фоне: Цель и результаты обучения -> scoped-репозиторий ЕПВО -> multilingual SBERT плюс BM25 -> reranking по экспертной памяти ЕПВО -> граф дисциплин и пререквизитов -> deterministic constrained planner -> независимый verifier -> подтверждение эксперта. PostgreSQL/pgvector обозначить как хранилище происхождения. Палитра navy, teal, green, amber; без роботов, неона и вымышленных метрик; SVG и PNG 300 dpi.",
    ),
    2: (
        "Layered EPVO data provenance and expert-label formation.",
        "Create a scientific data-lineage diagram. Show university department design, internal course-LO mapping, external expert votes 0/0.5/1, immutable raw EPVO records, normalization and deduplication, approved multilingual repository, programme-level train/validation/test split, embeddings, and generation candidates. Clearly separate AI prediction from expert evidence. White background, flat vector, legible at one-column width, no invented counts.",
        "Происхождение данных ЕПВО и формирование экспертной оценки.",
        "Создай научную data-lineage схему: разработка ОП кафедрой, внутренняя связь дисциплина-РО, внешние экспертные оценки 0/0,5/1, неизменяемые raw-записи ЕПВО, нормализация и дедупликация, утверждённый многоязычный репозиторий, program-level split train/validation/test, embeddings и кандидаты генерации. Разделить прогноз ИИ и экспертное доказательство. Белый фон, плоский вектор, читаемость в одну колонку, без вымышленных чисел.",
    ),
    3: (
        "Effect of the protected SCES RK core on semester alignment.",
        "Create a Q2-journal comparison figure with two aligned curriculum lanes. Lane A: without SCES RK, semantic-adjusted semester alignment 86.84%, profile provenance 100%, hard violations 0. Lane B: with SCES RK, 35 protected regulatory components across three plans, semantic-adjusted alignment 81.23%, profile provenance after regulatory exclusion 100%, hard violations 0. Show 27-33 credit bands and forward prerequisite arrows. Explain that the 5.61-point gap reflects lower scheduling freedom, not lower profile-course quality. White background, restrained blue/green/amber, editable SVG.",
        "Влияние защищённого ядра ГОСО РК на соответствие семестру.",
        "Создай сравнительную иллюстрацию уровня Q2 с двумя дорожками. Без ГОСО: semantic-adjusted 86,84%, профильное происхождение 100%, жёсткие нарушения 0. С ГОСО: 35 защищённых нормативных компонентов в трёх планах, semantic-adjusted 81,23%, профильное происхождение после исключения нормативного блока 100%, нарушения 0. Показать диапазон 27-33 кредита и направленные вперёд пререквизиты. Пояснить, что разница 5,61 п.п. вызвана меньшей свободой планирования, а не снижением качества профильных дисциплин. Белый фон, синий/зелёный/янтарный, SVG.",
    ),
}


def build(template: Path, output: Path, metrics: dict, lang: str):
    shutil.copy2(template, output)
    document = Document(output)
    remove_after_front_matter(document)
    data = EN if lang == "en" else RU
    set_front(
        document,
        data["title"],
        "Murat Kozhanov",
        [
            "Abylkas Saginov Karaganda Technical University, Karaganda, Kazakhstan",
            "Doctoral School of Applied Informatics and Applied Mathematics, Óbuda University, Budapest, Hungary",
        ],
        "Corresponding author: m.kozhanov@ktu.edu.kz",
    )
    add_abstract(
        document,
        data["abstract"],
        data["keywords"],
        ("Abstract", "Keywords") if lang == "en" else ("Аннотация", "Ключевые слова"),
    )

    equation_number = 1
    for heading, paragraphs in data["sections"]:
        add_heading(document, heading)
        for text in paragraphs:
            add_body(document, text)
        if heading in ("3. Data and Provenance", "3. Данные и происхождение"):
            rows = DATA_ROWS_EN if lang == "en" else DATA_ROWS_RU
            add_table(
                document,
                ["Dataset entity", "Count"] if lang == "en" else ["Сущность набора данных", "Количество"],
                rows,
                "Table 1. EPVO corpus and operational repository." if lang == "en" else "Таблица 1. Корпус ЕПВО и рабочий репозиторий.",
            )
            cap, prompt = (FIGURES[2][0], FIGURES[2][1]) if lang == "en" else (FIGURES[2][2], FIGURES[2][3])
            add_figure_prompt(document, 2, cap, prompt, lang)
        if heading in ("4. Method", "4. Метод"):
            add_equation(document, "R(c_i,o_j) = α cos(g_θ(c_i),g_θ(o_j)) + (1-α) BM25(c_i,o_j)", equation_number)
            equation_number += 1
            add_equation(document, "e_ij = max_l [ y_exp(c_i,l) · sim(o_j,l) ],  sim(o_j,l) ≥ τ_e", equation_number)
            equation_number += 1
            add_equation(document, "Cov(o_j,P) = 1 - ∏_(c_i∈P) (1-w_ij)", equation_number)
            equation_number += 1
            add_equation(document, "P* = arg max_P [λ_1 Cov + λ_2 Rel + λ_3 Div - λ_4 Viol - λ_5 Red]", equation_number)
            equation_number += 1
            add_equation(document, "s_i* = arg min_s |s-t_i|,  27 ≤ C_s(P) ≤ 33,  s(pre_i) < s_i", equation_number)
            equation_number += 1
            cap, prompt = (FIGURES[1][0], FIGURES[1][1]) if lang == "en" else (FIGURES[1][2], FIGURES[1][3])
            add_figure_prompt(document, 1, cap, prompt, lang)
        if heading in ("5. Experimental Design", "5. Дизайн эксперимента"):
            add_equation(document, "Recall@K = |Rel(q) ∩ TopK(q)| / |Rel(q)|", equation_number)
            equation_number += 1
            add_equation(document, "MRR = (1/|Q|) Σ_(q∈Q) 1/rank_q", equation_number)
            equation_number += 1
            add_equation(document, "nDCG@K = DCG@K / IDCG@K", equation_number)
            equation_number += 1
        if heading in ("6. Results", "6. Результаты"):
            add_table(
                document,
                ["Model", "ROC-AUC", "PR-AUC", "F1", "Status"] if lang == "en" else ["Модель", "ROC-AUC", "PR-AUC", "F1", "Статус"],
                MODEL_ROWS,
                "Table 2. Course-to-learning-outcome classification." if lang == "en" else "Таблица 2. Классификация связей дисциплина-результат обучения.",
            )
            headers, rows, caption = cohort_table(metrics, lang)
            add_table(document, headers, rows, caption)
            cap, prompt = (FIGURES[3][0], FIGURES[3][1]) if lang == "en" else (FIGURES[3][2], FIGURES[3][3])
            add_figure_prompt(document, 3, cap, prompt, lang)

    add_heading(document, "Acknowledgements" if lang == "en" else "Благодарности")
    add_body(
        document,
        "The author thanks academic experts who provided qualitative feedback during system demonstrations. No external accreditation decision is claimed."
        if lang == "en"
        else "Автор благодарит академических экспертов, предоставивших качественную обратную связь во время демонстраций системы. Формальное аккредитационное решение в работе не заявляется.",
    )
    add_heading(document, "References" if lang == "en" else "Литература")
    for reference in REFERENCES:
        paragraph = document.add_paragraph(style="Els-body-text")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.left_indent = Cm(0)
        set_run_font(paragraph.add_run(reference), size=9)

    # Ensure Word refreshes fields if the journal template adds them later.
    settings = document.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")
    document.core_properties.title = data["title"]
    document.core_properties.author = "Murat Kozhanov"
    document.core_properties.subject = "Curriculum-KAG"
    document.save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build(args.template, args.output_dir / "Curriculum_KAG_TEM_Journal_EN.docx", metrics, "en")
    build(args.template, args.output_dir / "Curriculum_KAG_TEM_Journal_RU.docx", metrics, "ru")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
