"""Persistent, source-aware cache for expensive plan build stages.

The cache is stored in audit_events, so it needs no schema migration and remains
valid after a backend restart.  A hit is accepted only when both the input
fingerprint and the expected output rows are present.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.course import Course, CourseChunk
from app.models.embedding import Embedding, MatchFeedback, MatchScore
from app.models.epvo import (
    EpvoDisciplineLoLink, EpvoDisciplineNormalized, RawEpvoDiscipline,
    RawEpvoExpertCheck, RawEpvoLearningOutcome, RawEpvoProgram,
)
from app.models.project import ProjectVersion


EPVO_CACHE_VERSION = "epvo-approval-v2-scoped"
SCORING_CACHE_VERSION = "course-lo-scoring-v1"
EPVO_CACHE_ACTION = "cache_epvo_repository"
SCORING_CACHE_ACTION = "cache_course_lo_matches"


def _digest(rows: Any) -> str:
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        )
        hasher.update(b"\n")
    return hasher.hexdigest()


def _scope_pairs(version: ProjectVersion) -> list[tuple[str, str]]:
    constraints = version.project.constraints_json or {}
    pairs = [(str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or ""))]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))
    return [(group, direction) for group, direction in pairs if group or direction]


def _content_digest(db: Session, model, column_name: str | None) -> str:
    """Return a deterministic content digest when the table has a source key.

    ``max(id)`` and row counts only detect appended/deleted records.  EPVO
    imports can also repair a payload in place.  Raw records carry a checksum
    and normalized records carry a dedup fingerprint, so PostgreSQL can hash
    the ordered values without loading hundreds of thousands of rows into the
    Python process.  SQLite keeps a cheap min/max fallback for local tests.
    """
    if not column_name:
        return ""
    column = getattr(model, column_name, None)
    if column is None:
        return ""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        table_name = model.__tablename__.replace('"', '""')
        column_name_sql = column.name.replace('"', '""')
        value = db.execute(text(
            f"SELECT md5(string_agg(\"{column_name_sql}\", ',' ORDER BY \"id\")) "
            f"FROM \"{table_name}\""
        )).scalar()
        return str(value or "")
    minimum, maximum = db.query(func.min(column), func.max(column)).one()
    return f"{minimum or ''}:{maximum or ''}"


def _table_stamp(db: Session, model) -> list[Any]:
    """Source stamp that also detects in-place updates and deletes.

    ``max(id)`` alone only detects appended rows.  EPVO normalization and
    localization repairs can update existing records without changing their
    ids, so include row count and ``updated_at`` when the table provides it.
    """
    latest_id = db.query(func.max(model.id)).scalar() or 0
    row_count = db.query(func.count(model.id)).scalar() or 0
    updated_column = getattr(model, "updated_at", None)
    latest_update = db.query(func.max(updated_column)).scalar() if updated_column is not None else None
    content_column = (
        "checksum" if getattr(model, "checksum", None) is not None
        else "dedup_fingerprint" if getattr(model, "dedup_fingerprint", None) is not None
        else None
    )
    return [
        model.__tablename__,
        int(row_count),
        int(latest_id),
        str(latest_update or ""),
        content_column or "",
        _content_digest(db, model, content_column),
    ]


def _approved_scope_stamp(version: ProjectVersion, db: Session) -> list[Any]:
    """Track approvals relevant to this programme, not every EPVO direction."""
    pairs = _scope_pairs(version)
    codes = sorted({
        code
        for group, direction in pairs
        for code in (group, direction)
        if code
    })
    query = db.query(
        func.count(EpvoDisciplineNormalized.id),
        func.max(EpvoDisciplineNormalized.id),
    ).filter(EpvoDisciplineNormalized.approved_course_id.isnot(None))
    if codes:
        conditions = [
            cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{code}"%')
            for code in codes
        ] + [
            cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{code}"%')
            for code in codes
        ]
        query = query.filter(or_(*conditions))
    approved = query.one()
    return [
        "approved_scope",
        codes,
        int(approved[0] or 0),
        int(approved[1] or 0),
        "",
    ]


def epvo_input_signature(version: ProjectVersion, db: Session) -> str:
    constraints = version.project.constraints_json or {}
    keys = (
        "education_level", "program_type", "instruction_language",
        "group_code", "direction_code", "secondary_group_code", "secondary_direction_code",
    )
    rows = [
        ["cache_version", EPVO_CACHE_VERSION],
        ["constraints", {key: constraints.get(key) for key in keys}],
        _table_stamp(db, RawEpvoProgram),
        _table_stamp(db, RawEpvoDiscipline),
        _table_stamp(db, RawEpvoLearningOutcome),
        _table_stamp(db, RawEpvoExpertCheck),
        _table_stamp(db, EpvoDisciplineNormalized),
        _table_stamp(db, EpvoDisciplineLoLink),
        _approved_scope_stamp(version, db),
    ]
    return _digest(rows)


def scoring_input_signature(version: ProjectVersion, db: Session) -> str:
    constraints = version.project.constraints_json or {}
    rows: list[Any] = [
        ["cache_version", SCORING_CACHE_VERSION],
        ["epvo_signature", epvo_input_signature(version, db)],
        ["project", version.project.domain1, version.project.domain2, constraints.get("education_level")],
        _table_stamp(db, Course),
        _table_stamp(db, CourseChunk),
        _table_stamp(db, Embedding),
    ]
    rows.extend([
        "lo", lo.id, lo.lo_code, lo.lo_text, lo.taxonomy_level, lo.weight, lo.order_index,
    ] for lo in sorted(version.learning_outcomes, key=lambda item: item.id))
    feedback = db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == version.id
    ).order_by(MatchFeedback.id).all()
    rows.extend([
        "feedback", item.id, item.course_id, item.lo_id, item.verdict,
        item.corrected_score, item.comment, item.model_snapshot_json,
    ] for item in feedback)
    return _digest(rows)


def cache_hit(db: Session, version: ProjectVersion, action: str, signature: str) -> bool:
    event = db.query(AuditEvent).filter(
        AuditEvent.action == action,
        AuditEvent.entity_type == "project_version",
        AuditEvent.entity_id == version.id,
    ).order_by(AuditEvent.id.desc()).first()
    if not event or (event.details_json or {}).get("signature") != signature:
        return False
    if action == EPVO_CACHE_ACTION:
        approved = db.query(func.count(EpvoDisciplineNormalized.approved_course_id)).scalar() or 0
        return int(approved) > 0
    lo_ids = [lo.id for lo in version.learning_outcomes]
    if not lo_ids:
        return False
    covered_los = db.query(func.count(func.distinct(MatchScore.lo_id))).filter(
        MatchScore.project_version_id == version.id,
        MatchScore.lo_id.in_(lo_ids),
    ).scalar() or 0
    return int(covered_los) == len(lo_ids)


def remember_cache(
    db: Session,
    version: ProjectVersion,
    action: str,
    signature: str,
    user_id: int | None,
    details: dict | None = None,
) -> None:
    payload = {"signature": signature, "cache_version": (
        EPVO_CACHE_VERSION if action == EPVO_CACHE_ACTION else SCORING_CACHE_VERSION
    )}
    payload.update(details or {})
    db.add(AuditEvent(
        user_id=user_id,
        action=action,
        entity_type="project_version",
        entity_id=version.id,
        details_json=payload,
    ))
