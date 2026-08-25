"""Small regression checks for leakage-safe listwise sampling policies."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_graded_listwise_sampling_preserves_expert_strengths_and_negatives():
    from scripts.finetune_epvo_sbert_multipositive_ranker import build_groups

    programme = {
        "program_id": "sampling-test",
        "split": "train",
        "courses": [
            {"id": "c1", "title": {"ru": "Анализ данных"}, "description": {"ru": "модели"}},
            {"id": "c2", "title": {"ru": "Анализ данных"}, "description": {"ru": "практика"}},
            {"id": "c3", "title": {"ru": "Анализ данных"}, "description": {"ru": "другой модуль"}},
        ],
        "outcomes": [{"id": "lo1", "text": {"ru": "Анализировать данные"}}],
        "positive_edges": [["c1", "lo1"], ["c2", "lo1"]],
        "expert_edges": [
            {"course_id": "c1", "lo_id": "lo1", "score": 0.5},
            {"course_id": "c2", "lo_id": "lo1", "score": 1.0},
        ],
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "programmes.jsonl"
        path.write_text(json.dumps(programme, ensure_ascii=False) + "\n", encoding="utf-8")
        groups, stats = build_groups(path, 10, 3, 8, 42, "ru", 0.5, "lexical", "graded")

    assert stats["selected_groups"] == 1
    assert groups[0]["positive_count"] == 2
    assert sorted(groups[0]["positive_weights"]) == [0.5, 1.0]
    assert len(groups[0]["documents"]) == 3
