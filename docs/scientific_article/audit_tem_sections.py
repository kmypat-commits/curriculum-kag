"""Check that the generated manuscript retains the official TEM page geometry."""
from pathlib import Path
from docx import Document

path = Path(__file__).with_name("Curriculum_KAG_TEM_manuscript_official_template.docx")
doc = Document(path)
assert len(doc.sections) == 2, f"expected 2 sections, got {len(doc.sections)}"
for section in doc.sections:
    assert round(section.page_width.inches, 2) == 8.27
    assert round(section.page_height.inches, 2) == 11.69
first, second = doc.sections
assert round(first.left_margin.inches, 2) == 0.79
assert round(first.right_margin.inches, 2) == 0.71
assert round(second.left_margin.inches, 2) == 0.79
assert round(second.right_margin.inches, 2) == 0.71
print("PASS: A4 geometry and official TEM margins preserved; sections=2")
