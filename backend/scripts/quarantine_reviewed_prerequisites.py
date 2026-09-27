"""Reversible, explicitly reviewed correction; never a blanket legacy cleanup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from sqlalchemy import text

REVIEWED = ((517, 724), (517, 787), (5029, 8142), (5029, 8183))
REASON = ("Reviewed legacy inference crosses unrelated subjects: professional "
          "language -> GIS/programming/Android/Fourier. No explicit EPVO "
          "prerequisite records; source descriptions do not establish these edges.")


def change_edges(connection, edges, *, restore):
    edges = tuple(edges)
    counts = [connection.execute(text(
        "SELECT COUNT(*) FROM course_prerequisites WHERE course_id=:c AND prerequisite_id=:p"
    ), {"c": c, "p": p}).scalar_one() for c, p in edges]
    if not restore and any(count != 1 for count in counts):
        raise ValueError("Reviewed edge set changed; refusing partial correction")
    changed = 0
    for (c, p), count in zip(edges, counts):
        if restore:
            if count:
                continue
            connection.execute(text(
                "INSERT INTO course_prerequisites (course_id,prerequisite_id) VALUES (:c,:p)"
            ), {"c": c, "p": p})
        else:
            connection.execute(text(
                "DELETE FROM course_prerequisites WHERE course_id=:c AND prerequisite_id=:p"
            ), {"c": c, "p": p})
        changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.apply and args.restore:
        parser.error("Choose apply or restore")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import engine
    with engine.begin() as connection:
        # Prevent snapshot/apply drift; table is small and operation bounded.
        connection.execute(text("LOCK TABLE course_prerequisites IN EXCLUSIVE MODE"))
        if args.restore:
            payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
            encoded = json.dumps(payload["all_edges"], separators=(",", ":")).encode()
            if hashlib.sha256(encoded).hexdigest() != payload["edges_sha256"]:
                raise ValueError("Snapshot checksum mismatch")
            if tuple(map(tuple, payload["reviewed_edges"])) != REVIEWED:
                raise ValueError("Snapshot is not this reviewed migration")
            changed = change_edges(connection, REVIEWED, restore=True)
            print(json.dumps({"restored": changed}))
            return
        rows = connection.execute(text(
            "SELECT course_id,prerequisite_id FROM course_prerequisites ORDER BY course_id,prerequisite_id"
        )).all()
        all_edges = [list(row) for row in rows]
        if not all(all_edges.count(list(edge)) == 1 for edge in REVIEWED):
            raise ValueError("Reviewed edges absent or duplicated")
        # Explicit source relations must never be automatically quarantined.
        explicit_count = connection.execute(text("SELECT COUNT(*) FROM epvo_prerequisites")).scalar_one()
        if explicit_count:
            raise ValueError("Explicit source relations exist; require individual source review")
        courses = connection.execute(text(
            "SELECT id,course_id,title FROM courses WHERE id IN (517,724,787,5029,8142,8183) ORDER BY id"
        )).mappings().all()
        payload = {"reason": REASON, "reviewed_edges": REVIEWED,
                   "all_edges": all_edges, "courses": [dict(row) for row in courses],
                   "explicit_epvo_prerequisites": explicit_count,
                   "edges_sha256": hashlib.sha256(json.dumps(
                       all_edges, separators=(",", ":")).encode()).hexdigest()}
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        with args.snapshot.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        changed = change_edges(connection, REVIEWED, restore=False) if args.apply else 0
        after = connection.execute(text("SELECT COUNT(*) FROM course_prerequisites")).scalar_one()
        if after != len(rows) - changed:
            raise ValueError("Unexpected edge count delta")
        print(json.dumps({"snapshot": str(args.snapshot), "before": len(rows),
                          "quarantined": changed, "after": after}))


if __name__ == "__main__":
    main()
