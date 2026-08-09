"""Planner API composition root.

The public route prefix remains ``/planner``.  Feature routers are split by
responsibility so changes to graph presentation, plan generation, course
replacement, coverage reporting, or syllabus authoring can evolve and be
tested independently.
"""

from fastapi import APIRouter

from app.api.planner_build import router as build_router
from app.api.planner_coverage import router as coverage_router
from app.api.planner_graph import router as graph_router
from app.api.planner_replacements import router as replacements_router
from app.api.planner_state import plan_build_status as _plan_build_status
from app.api.planner_state import set_build_status as _set_build_status
from app.api.planner_syllabus import router as syllabus_router


router = APIRouter()
router.include_router(graph_router)
router.include_router(syllabus_router)
router.include_router(build_router)
router.include_router(coverage_router)
router.include_router(replacements_router)


__all__ = ["router", "_plan_build_status", "_set_build_status"]
