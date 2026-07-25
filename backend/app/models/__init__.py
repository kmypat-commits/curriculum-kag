"""ORM model registry.

Importing all model modules here ensures SQLAlchemy can resolve string-based
relationships (for example ``ProjectVersion.plans -> "Plan"``) no matter which
single model is imported first by a script, endpoint, or test.
"""

from app.models.user import User, Role  # noqa: F401
from app.models.course import Course, CourseChunk, CourseLocalization  # noqa: F401
from app.models.project import Project, ProjectVersion, LearningOutcome  # noqa: F401
from app.models.plan import Plan, PlanItem  # noqa: F401
from app.models.bridge_module import BridgeModule  # noqa: F401
from app.models.embedding import Embedding, MatchScore, MatchFeedback, GraphEdge  # noqa: F401
from app.models.audit import AuditEvent  # noqa: F401
from app.models.syllabus import SyllabusDraft  # noqa: F401
from app.models.epvo import (  # noqa: F401
    RawEpvoProgram, RawEpvoDiscipline, RawEpvoLearningOutcome, RawEpvoExpertCheck,
    EpvoDirection, EpvoGroup, EpvoDisciplineNormalized, EpvoDisciplineLoLink,
    EpvoPrerequisite,
)
