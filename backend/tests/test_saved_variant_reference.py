"""Saved alternatives remain diversity references across separate requests."""
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.plan import PlanItem
import app.api.planner_build as build


def test_saved_b_reference_uses_latest_b_and_ignores_null_courses():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all([
                PlanItem(plan_id=11, course_id=3, semester=1, credits=5),
                PlanItem(plan_id=12, course_id=7, semester=1, credits=5),
                PlanItem(plan_id=12, course_id=8, semester=2, credits=5),
                PlanItem(plan_id=12, course_id=None, semester=2, credits=5),
                PlanItem(plan_id=13, course_id=9, semester=1, credits=5),
            ])
            db.flush()
            plans = [SimpleNamespace(id=11, variant_type='B'),
                     SimpleNamespace(id=12, variant_type='B'),
                     SimpleNamespace(id=13, variant_type='A')]
            assert hasattr(build, '_saved_variant_course_ids')
            assert build._saved_variant_course_ids(db, plans, 'B') == frozenset({7, 8})
            assert build._saved_variant_course_ids(db, plans, 'C') == frozenset()
    finally:
        engine.dispose()
