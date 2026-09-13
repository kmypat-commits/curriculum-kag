"""Preparation of match evidence used by variant selection."""

from typing import Dict, Iterable


def aggregate_match_scores(db, match_model, project_version_id: int, learning_outcomes: Iterable):
    outcomes = list(learning_outcomes)
    weights = {lo.id: lo.weight or 1.0 for lo in outcomes}
    lo_codes_by_id = {lo.id: lo.lo_code for lo in outcomes}
    aggregates: Dict[int, Dict] = {}
    rows = db.query(match_model).filter(
        match_model.project_version_id == project_version_id
    ).order_by(match_model.course_id.asc(), match_model.lo_id.asc()).all()
    for match in rows:
        data = aggregates.setdefault(match.course_id, {
            "sum": 0.0, "los": set(), "lo_codes": set(), "credible_lo_codes": set(),
            "professional_lo_codes": set(), "lo_scores": {}, "max": 0.0, "expert": 0.0,
        })
        data["sum"] += match.score * weights.get(match.lo_id, 1.0)
        data["los"].add(match.lo_id)
        if lo_codes_by_id.get(match.lo_id):
            data["lo_codes"].add(lo_codes_by_id[match.lo_id])
        expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective_value = max(float(match.score or 0.0), expert_value)
        lo_code = str(lo_codes_by_id.get(match.lo_id) or "")
        if lo_code:
            data["lo_scores"][lo_code] = max(float(data["lo_scores"].get(lo_code) or 0.0), effective_value)
        if lo_code and effective_value >= 0.4:
            data["credible_lo_codes"].add(lo_code)
            if not lo_code.startswith("LO-GOSO-"):
                data["professional_lo_codes"].add(lo_code)
        data["expert"] = max(data["expert"], expert_value)
        data["max"] = max(data["max"], effective_value)
    return weights, lo_codes_by_id, aggregates
