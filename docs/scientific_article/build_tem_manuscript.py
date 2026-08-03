from pathlib import Path
from docx import Document
from docx.shared import Mm, Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

OUT = Path(__file__).with_name("Curriculum_KAG_TEM_manuscript_draft.docx")

def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)

def set_cell_text(cell, text, bold=False):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(str(text))
    r.bold = bold
    r.font.name = 'Times New Roman'
    r.font.size = Pt(8.5)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

def add_heading(doc, text, level=1):
    p = doc.add_paragraph(style=f'Heading {level}')
    p.add_run(text)
    return p

def add_body(doc, text):
    p = doc.add_paragraph(style='Normal')
    p.add_run(text)
    return p

def add_bullet(doc, text):
    p = doc.add_paragraph(style='List Bullet')
    p.add_run(text)
    return p

doc = Document()
sec = doc.sections[0]
sec.page_width = Mm(210)
sec.page_height = Mm(297)
sec.top_margin = Mm(20)
sec.bottom_margin = Mm(20)
sec.left_margin = Mm(20)
sec.right_margin = Mm(18)

# TEM two-column layout.
sectPr = sec._sectPr
cols = sectPr.find(qn('w:cols'))
if cols is None:
    cols = OxmlElement('w:cols')
    sectPr.append(cols)
cols.set(qn('w:num'), '2')
cols.set(qn('w:space'), '283')  # 5 mm

styles = doc.styles
normal = styles['Normal']
normal.font.name = 'Times New Roman'
normal._element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
normal.font.size = Pt(9.5)
normal.paragraph_format.line_spacing = 1.0
normal.paragraph_format.space_after = Pt(3)
for name, size in [('Heading 1', 11), ('Heading 2', 10)]:
    st = styles[name]
    st.font.name = 'Times New Roman'
    st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
    st.font.size = Pt(size)
    st.font.bold = True
    st.paragraph_format.space_before = Pt(5)
    st.paragraph_format.space_after = Pt(2)

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
title.paragraph_format.space_after = Pt(5)
r = title.add_run('Curriculum-KAG: Expert-Grounded and Constraint-Aware Curriculum Synthesis from Learning Outcomes')
r.bold = True; r.font.name = 'Times New Roman'; r.font.size = Pt(14)

for line in [
    'Murat Kozhanov',
    'Abylkas Saginov Karaganda Technical University, Karaganda, Kazakhstan; Doctoral School of Applied Informatics and Applied Mathematics, Obuda University, Budapest, Hungary',
    'Corresponding author: m.kozhanov@ktu.edu.kz',
]:
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after = Pt(1)
    rr = p.add_run(line); rr.font.name = 'Times New Roman'; rr.font.size = Pt(9)

p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(5); p.paragraph_format.space_after = Pt(3)
rr = p.add_run('Abstract — '); rr.bold = True
p.add_run('Curriculum design must align courses with learning outcomes (LOs), prerequisites, credit regulations, and auditability. Curriculum-KAG combines the Kazakhstan EPVO repository, multilingual SBERT retrieval, expert-weighted course–LO evidence, a prerequisite graph, and constrained planning. The dataset contains 12,215 programmes, 408,638 raw course records, and 932,483 normalized expert links. On an independent 6,000-pair test set, fine-tuned SBERT achieved ROC-AUC 0.7647, PR-AUC 0.7673, and F1 0.7209, versus 0.7031, 0.6946, and 0.6886 for base SBERT. An experimental reranker improved Recall@10 from 0.6734 to 0.6857. The system remains human-supervised and rule-verified.')

p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(5)
rr = p.add_run('Keywords — '); rr.bold = True
p.add_run('curriculum design; learning outcomes; EPVO; SBERT; expert-in-the-loop')

add_heading(doc, '1. Introduction')
add_body(doc, 'Outcome-based curriculum design requires more than selecting a list of courses. Each intended learning outcome must be supported by teachable content, the sequence must respect prerequisite relations, and the resulting workload must satisfy institutional and regulatory constraints. Constructive alignment makes this relationship explicit, while accreditation frameworks require evidence that outcomes are assessed and improved continuously [1–3]. In practice, curriculum teams often work with heterogeneous programme descriptions, duplicated course titles, incomplete translations, and expert judgements stored in separate registry screens. This makes manual design slow and difficult to reproduce.')
add_body(doc, 'This study addresses the problem as constrained curriculum synthesis. The system is designed for a decision-support setting: a model proposes course–LO links and candidates, a deterministic planner assembles alternatives, and an expert confirms or rejects the result. The main contributions are: (i) a provenance-preserving EPVO data pipeline; (ii) a two-stage text model combining SBERT scoring and expert-weighted retrieval memory; (iii) a constrained planner with prerequisite, semester, credit, domain, and protected-component checks; and (iv) an auditable interface that exposes evidence instead of presenting an opaque recommendation.')

add_heading(doc, '2. Related Work')
add_body(doc, 'Sentence-BERT provides efficient sentence-level representations for semantic similarity [6,7], while dense retrieval and contrastive training improve candidate ranking [8,9]. Knowledge graphs are useful when entities, relations, and provenance must be inspected together [10]. Multi-objective evolutionary optimization is a valid research baseline for curriculum design, but an operational planner must also enforce hard constraints and produce a feasible plan after repair [11]. Human-in-the-loop machine learning is particularly appropriate when labels encode institutional judgement rather than an objective physical measurement [12]. Our system combines these ideas with a national programme registry and explicitly retains the origin of each score.')

add_heading(doc, '3. Data and Expert Provenance')
add_body(doc, 'The source is the public-facing Unified Higher Education Platform registry (EPVO) of Kazakhstan. The raw layer is preserved before normalization. It contains 12,215 programmes, 408,638 course records, and 124,521 raw learning outcomes. Repeated course–LO observations are aggregated only after preserving the original programme and expert-check context. The normalized repository contains 191,292 course entities and 932,483 course–LO links.')
add_body(doc, 'The expert signal is not a binary label invented by the model. During programme development, a university team first selected courses and programme outcomes. External reviewers subsequently inspected the course–LO pairs and marked the strength of achievement as low, medium, or high. In the extracted records, the principal numeric values are 0, 0.5, and 1; repeated observations are retained as votes. The training representation uses the mean of repeated votes for a pair, while rejected links are not treated as positive evidence. This distinction is essential: a semantic score estimates textual compatibility, whereas the EPVO score is evidence of prior expert judgement.')
add_body(doc, 'The storage layers are raw → normalized → approved → generation candidates. Every approved candidate retains source programmes, direction and group codes, language fields, expert votes, and a status. This prevents a convenient but untraceable “course pool” from being mistaken for verified curriculum evidence.')
add_body(doc, 'Normalization separates identity from presentation. A canonical course entity is keyed by a stable source identifier when available and by a conservative title-and-description fingerprint otherwise. Localized titles and descriptions are stored as language-specific fields rather than concatenated into a single text. Duplicate observations remain available for provenance analysis while generation works with one canonical candidate. The same principle is applied to outcomes: an outcome is linked to its programme and source record before cross-programme aggregation.')
add_body(doc, 'The split unit is the programme, not an individual course–LO row. A random row split would allow near-duplicate programme contexts and institutional wording to leak into the test set. The frozen experiment stores the source snapshot, split seed, model identifier, threshold-selection rule, and prediction file, so a later rerun can distinguish a changed model from a changed dataset.')

add_heading(doc, '4. Method')
add_heading(doc, '4.1 Course–LO scoring', 2)
add_body(doc, 'For course cᵢ and outcome oⱼ, the semantic encoder produces cosine similarity sᵢⱼ. A calibrated AI score is obtained by a monotone transform, pᵃⁱᵢⱼ = sigmoid((sᵢⱼ − τ)/T). A lexical/domain component bᵢⱼ is added and clipped: pᵏᵃᵍᵢⱼ = clip(pᵃⁱᵢⱼ + bᵢⱼ, 0, 1). The EPVO signal eᵢⱼ is the aggregated expert value. The final recommendation is a transparent combination rather than an unexplained replacement: qᵢⱼ = max(hᵢⱼ, 0.65hᵢⱼ + 0.35eᵢⱼ), where hᵢⱼ is the deterministic semantic/domain heuristic. The interface displays AI, EPVO, and final values separately.')
add_heading(doc, '4.2 Two-stage ranking', 2)
add_body(doc, 'The first stage retrieves candidates with multilingual SBERT. The second experimental stage builds a train-only memory of expert-supported course–LO evidence. Stronger judgements receive larger weights; zero-valued judgements are not positive evidence. The memory weight is selected on validation and frozen before test evaluation. This is a reranker candidate, not an enabled production feature.')
add_heading(doc, '4.3 Constrained planner', 2)
add_body(doc, 'The planner searches within the selected EPVO directions and education level. It first selects real courses with sufficient course–LO evidence, then applies protected national components when the Kazakhstan jurisdiction is selected. A candidate is admissible only if it satisfies the level guard, domain guard, LO threshold, credit range, and duplicate-course rules. The planner repairs semester assignments to respect prerequisite edges and workload. A plan is committed transactionally only after all requested variants pass validation. Bridge modules are permitted only when no adequate real course is available and are clearly marked for expert review.')
add_body(doc, 'For a plan P, the constraint vector includes total credits C(P), semester loads Lₛ(P), prerequisite violations Vₚ(P), uncovered outcomes U(P), domain quota violations Vᵈ(P), and protected-course violations Vᵍ(P). Feasibility is therefore: C(P) ∈ [Cₘᵢₙ, Cₘₐₓ], Lₛ(P) ∈ [Lₘᵢₙ, Lₘₐₓ], and Vₚ = U = Vᵈ = Vᵍ = 0. NSGA-II is retained as an experimental branch for Pareto exploration; it is not the default operational planner.')
add_body(doc, 'The repair stage is deliberately deterministic. If a semester is overloaded, the planner first moves a course to an admissible later semester while preserving all prerequisite predecessors. If a course becomes isolated from the selected EPVO domains, it is replaced by the highest-scoring admissible candidate from the same direction or group. If a protected component is involved, replacement is prohibited and the diagnostic is returned to the user. This order makes the planner reproducible and prevents a stochastic optimizer from silently trading away a regulatory requirement.')
add_body(doc, 'The planner records an explanation trace for every selected course: outcomes covered, AI score, EPVO evidence score, source direction and group, prerequisite predecessors, reason for the semester, and whether the course is protected or requires expert confirmation. A bridge module is not evidence of an existing EPVO course; it is an explicitly labelled proposal for a missing interdisciplinary unit.')

add_heading(doc, '5. Experimental Setup')
add_body(doc, 'All text-model splits are performed at programme level with seed 42, preventing the same programme context from appearing in train and test. The independent classification test contains 6,000 course–LO pairs. Ranking evaluation uses frozen programme-level splits. We report ROC-AUC, PR-AUC, F1, Recall@K, mean reciprocal rank (MRR), and normalized discounted cumulative gain (nDCG). The production path and experimental checkpoints are recorded separately. The control audit additionally checks credits, prerequisite order, domain scope, LO coverage, and protected Kazakhstan components.')
add_body(doc, 'For a ranked list, Recall@K is the fraction of relevant items appearing in the first K positions. MRR is the mean reciprocal position of the first relevant item. nDCG@K discounts relevant items that occur later and normalizes by the ideal ranking. These metrics answer different questions: recall asks whether a useful candidate was found, MRR asks how early the first useful candidate appears, and nDCG evaluates the quality of the whole top-K order.')
add_body(doc, 'The classification threshold is selected only on validation data and then frozen for test evaluation. Confidence intervals are estimated by resampling complete programmes rather than individual pairs, preserving within-programme dependence. The percentile interval over 2,000 bootstrap repetitions quantifies uncertainty for the computational benchmark; it does not turn a structural audit into a human efficacy study.')

add_heading(doc, '6. Results')
table = doc.add_table(rows=1, cols=5)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.style = 'Table Grid'
headers = ['Model / stage', 'ROC-AUC', 'PR-AUC', 'F1', 'Ranking result']
for c, h in zip(table.rows[0].cells, headers):
    set_cell_text(c, h, True); shade(c, 'D9EAF7')
rows = [
    ('Base multilingual SBERT', '0.7031', '0.6946', '0.6886', '—'),
    ('Fine-tuned SBERT 40k', '0.7666', '0.7681', '0.7188', '—'),
    ('Multi-positive SBERT', '—', '—', '—', 'R@10 0.6734; MRR 0.7866; nDCG 0.6629'),
    ('+ expert-weighted memory (experimental)', '—', '—', '—', 'R@10 0.6857; MRR 0.7975; nDCG 0.6789'),
]
for row in rows:
    cells = table.add_row().cells
    for c, value in zip(cells, row): set_cell_text(c, value)
add_body(doc, 'Fine-tuning improves ROC-AUC by 0.0635 and PR-AUC by 0.0735 over the base model on the independent classification set. The experimental expert-weighted memory adds 1.24 percentage points to Recall@10, 1.09 points to MRR, and 1.60 points to nDCG@10 over the comparable multi-positive baseline. These results support the value of expert provenance for ranking, but they do not justify silently enabling the reranker for production before a larger independent evaluation.')
add_body(doc, 'Fresh transactional audits of Kazakhstan and international control programmes produced feasible A/B/C plans with zero hard violations in the saved reports. For international programmes, Kazakhstan GOSO rules are intentionally not claimed; the system applies the international constraint profile. GNN and LSTM pilots did not outperform the SBERT path and remain separate research directions.')
add_body(doc, 'The independent CUDA rerun on the archived EPVO link dataset produced test ROC-AUC 0.7647 (95% CI 0.7378–0.7908), PR-AUC 0.7673 (0.7367–0.7957), F1 0.7209 (0.7032–0.7371), precision 0.6212 (0.6051–0.6378), and recall 0.8587 (0.8282–0.8846). The small difference from the historical passport point estimate is reported rather than averaged away. In the fresh transactional programme audit, six of seven cases were quality-eligible; the remaining case was retained as a diagnostic failure rather than removed. Mean EPVO provenance was 0.7821, reaching 1.0000 when regulatory components were excluded. These figures describe technical structural agreement and reproducibility, not a claim that every generated course is pedagogically approved.')

add_heading(doc, '7. Discussion and Limitations')
add_body(doc, 'The central result is methodological rather than a claim that a neural model can autonomously approve an educational programme. EPVO expert values improve the evidence layer, while deterministic constraints protect feasibility. This separation makes errors diagnosable: a low semantic score, a missing EPVO signal, a domain mismatch, and a prerequisite violation are different failure modes and are shown separately to the user.')
add_body(doc, 'The study has four limitations. First, registry data are heterogeneous and some descriptions require language review. Second, the reranker has so far been evaluated on a frozen split but not yet on a sufficiently large set of newly created programmes. Third, interface localization and legacy UI defects are engineering risks, not evidence of learning quality. Fourth, GNN/LSTM experiments were controlled pilots, not a full graph-temporal benchmark. The next validation must report confidence intervals and independent programmes before the experimental reranker is promoted.')

add_heading(doc, '8. Conclusion')
add_body(doc, 'Curriculum-KAG demonstrates a reproducible route from learning outcomes and EPVO evidence to a feasible, explainable curriculum plan. Its contribution is the integration of expert provenance, multilingual semantic retrieval, constrained scheduling, and human confirmation. The validated operational path is the constrained planner with repair and independent checks. SBERT supplies candidate relevance; expert-weighted ranking is a promising but experimental second stage. This architecture provides a practical basis for evidence-based continuous improvement without presenting automation as a replacement for academic governance.')

for heading, text in [
    ('Data availability', 'Raw EPVO records are not redistributed automatically. The repository contains normalization scripts, manifests, checksums, derived examples, and instructions for authorized data access.'),
    ('Code availability', 'Code, configuration, audit reports, and model metadata are versioned in the Curriculum-KAG repository. Large checkpoints are stored separately with SHA-256 identifiers.'),
    ('Ethics and conflicts', 'No student, medical, or performance data were used. The author declares no conflict of interest and no external funding.'),
    ('Generative AI disclosure', 'Generative AI assisted software development and language editing. The author verified algorithms, metrics, citations, and conclusions; AI did not approve curricula or serve as an author.'),
]:
    add_heading(doc, heading, 2); add_body(doc, text)

add_heading(doc, 'References')
refs = [
    '[1] Biggs, J. Enhancing teaching through constructive alignment. Higher Education 32 (1996), 347–364. doi:10.1007/BF00138871.',
    '[2] ABET. Criteria for Accrediting Computing Programs, 2025–2026.',
    '[3] Worldwide CDIO Initiative. CDIO Standards 3.0 (2022).',
    '[4] González, J.; Wagenaar, R. (eds.). Tuning Educational Structures in Europe (2003).',
    '[5] National Center for Higher Education Development. EPVO registry of educational programmes.',
    '[6] Devlin, J.; Chang, M.-W.; Lee, K.; Toutanova, K. BERT. NAACL-HLT (2019), 4171–4186.',
    '[7] Reimers, N.; Gurevych, I. Sentence-BERT. EMNLP-IJCNLP (2019), 3982–3992. doi:10.18653/v1/D19-1410.',
    '[8] Reimers, N.; Gurevych, I. Making Monolingual Sentence Embeddings Multilingual. EMNLP (2020), 4512–4525.',
    '[9] Karpukhin, V. et al. Dense Passage Retrieval. EMNLP (2020), 6769–6781.',
    '[10] Hogan, A. et al. Knowledge Graphs. ACM Computing Surveys 54(4) (2021), Article 71.',
    '[11] Deb, K. et al. A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II. IEEE TEC 6(2) (2002), 182–197.',
    '[12] Amershi, S. et al. Power to the People: The Role of Humans in Interactive Machine Learning. AI Magazine 35(4) (2014), 105–120.',
    '[13] Järvelin, K.; Kekäläinen, J. Cumulated Gain-based Evaluation of IR Techniques. ACM TOIS 20(4) (2002), 422–446.',
    '[14] Gebru, T. et al. Datasheets for Datasets. Communications of the ACM 64(12) (2021), 86–92.',
    '[15] Mitchell, M. et al. Model Cards for Model Reporting. FAT* (2019), 220–229.',
]
for ref in refs: add_body(doc, ref)

doc.core_properties.title = 'Curriculum-KAG: Expert-Grounded and Constraint-Aware Curriculum Synthesis from Learning Outcomes'
doc.core_properties.author = 'Murat Kozhanov'
doc.core_properties.subject = 'TEM Journal submission draft'
doc.core_properties.keywords = 'curriculum design, EPVO, SBERT, learning outcomes, expert evidence'
doc.save(OUT)
print(OUT)
