"""Evidence-bound confirmations for optional professional-core blocks."""

import hashlib
import json
from datetime import datetime, timezone


_SOURCE_FIELDS = {"description", "topics", "learning_outcomes", "assessment_methods"}


def _hash(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalise(value):
    return " ".join(str(value or "").casefold().split())


def _source_text(course, field):
    value = getattr(course, field, None)
    if isinstance(value, list):
        return " ".join(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                        for item in value)
    return str(value or "")


def course_content_hash(course):
    return _hash({
        "course_id": course.course_id, "title": course.title,
        "domain": course.domain, "credits": course.credits,
        "language": course.language,
        **{field: getattr(course, field, None) for field in sorted(_SOURCE_FIELDS)},
    })


def block_content_hash(block):
    return _hash({key: block.get(key) for key in (
        "id", "title", "description", "lo_codes", "requirement",
        "min_courses", "min_credits",
    )})


def create_confirmation(block, course, *, source_field, excerpt, actor_user_id,
                        project_version_id, rationale):
    """Build a server-side attestation; caller supplies authenticated actor ID."""
    if int(course.id) not in block.get("accepted_course_ids", ()):
        raise ValueError("course_not_accepted_for_block")
    normalized_excerpt = _normalise(excerpt)
    if (source_field not in _SOURCE_FIELDS or not normalized_excerpt
            or normalized_excerpt not in _normalise(_source_text(course, source_field))):
        raise ValueError("source_excerpt_missing")
    if not str(rationale or "").strip():
        raise ValueError("confirmation_rationale_missing")
    if int(actor_user_id) <= 0 or int(project_version_id) <= 0:
        raise ValueError("invalid_confirmation_identity")
    content_hash = course_content_hash(course)
    return {
        "block_id": block["id"], "course_id": int(course.id),
        "source_reference": str(course.course_id),
        "source_revision": content_hash,
        "content_hash": content_hash,
        "block_hash": block_content_hash(block),
        "source_field": source_field, "source_excerpt": str(excerpt).strip(),
        "search_method": "manual_review", "status": "confirmed",
        "author_user_id": int(actor_user_id),
        "project_version_id": int(project_version_id),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "rationale": str(rationale).strip(),
    }


def verified_matches(blocks, confirmations, courses_by_id, *, project_version_id):
    """Recheck saved attestations against the current block and course revisions."""
    by_block = {block["id"]: block for block in blocks}
    matches = {}
    for record in confirmations:
        block = by_block.get(record.get("block_id"))
        course_id = record.get("course_id")
        course = courses_by_id.get(course_id)
        if not block or course is None or course_id not in block.get("accepted_course_ids", ()):
            continue
        if record.get("status") != "confirmed" or record.get("project_version_id") != project_version_id:
            continue
        if not record.get("author_user_id") or record.get("block_hash") != block_content_hash(block):
            continue
        if record.get("content_hash") != course_content_hash(course):
            continue
        if record.get("source_reference") != course.course_id:
            continue
        matches.setdefault(block["id"], set()).add(course_id)
    return matches
