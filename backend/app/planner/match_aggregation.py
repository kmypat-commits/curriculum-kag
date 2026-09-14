"""Preparation of match evidence used by variant selection."""

from typing import Dict, Iterable


def semantic_evidence_score(match) -> float:
    """Return the non-inflated semantic evidence for one course--LO link.

    ``MatchScore.score`` is a *ranking* score: in AI mode it includes a
    calibrated confidence curve and lexical boosts.  It is useful to rank
    candidates, but treating it as direct evidence made a broad in-scope
    course look like a perfect programme match.  Admission and publication
    need the underlying semantic similarity instead.  Older/manual rows do
    not have that field, so keep their stored score as the compatible source
    of evidence.
    """
    evidence = getattr(match, "evidence_json", None) or {}
    if evidence.get("semantic_score") is not None:
        return float(evidence.get("semantic_score") or 0.0)
    return float(getattr(match, "score", 0.0) or 0.0)


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
            "professional_lo_codes": set(), "lo_scores": {}, "max": 0.0, "semantic_max": 0.0,
            "evidence_sum": 0.0, "evidence_max": 0.0, "expert": 0.0,
        })
        data["sum"] += match.score * weights.get(match.lo_id, 1.0)
        data["los"].add(match.lo_id)
        if lo_codes_by_id.get(match.lo_id):
            data["lo_codes"].add(lo_codes_by_id[match.lo_id])
        expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective_value = max(float(match.score or 0.0), expert_value)
        semantic_value = semantic_evidence_score(match)
        lo_code = str(lo_codes_by_id.get(match.lo_id) or "")
        if lo_code:
            data["lo_scores"][lo_code] = max(float(data["lo_scores"].get(lo_code) or 0.0), effective_value)
        # Use semantic/expert evidence for admission.  ``effective_value``
        # remains the retrieval/ranking score above, so candidate ordering is
        # unchanged; only a course's right to fill a professional LO is
        # protected from a generic heuristic boost.
        admission_value = max(semantic_value, expert_value)
        data["evidence_sum"] += admission_value * weights.get(match.lo_id, 1.0)
        data["evidence_max"] = max(data["evidence_max"], admission_value)
        if lo_code and admission_value >= 0.4:
            data["credible_lo_codes"].add(lo_code)
            if not lo_code.startswith("LO-GOSO-"):
                data["professional_lo_codes"].add(lo_code)
        data["expert"] = max(data["expert"], expert_value)
        data["max"] = max(data["max"], effective_value)
        data["semantic_max"] = max(data["semantic_max"], semantic_value)
    return weights, lo_codes_by_id, aggregates
