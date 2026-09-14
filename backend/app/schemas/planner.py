from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlannerBuildRequest(BaseModel):
    """Stable request contract for plan generation.

    ``variants`` keeps accepting the legacy comma-separated string while new
    clients can send a typed list.
    """

    variants: str | list[str] | None = Field(default="A", description="A by default; B/C are optional comparison variants")


class SyllabusWeekRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    week: int = Field(ge=1, le=52)
    total_hours: int = Field(ge=0, le=168)
    lecture_hours: int = Field(default=0, ge=0, le=168)
    practical_hours: int = Field(default=0, ge=0, le=168)
    independent_hours: int = Field(default=0, ge=0, le=168)
    learning_outcome: str = Field(default="", max_length=2000)


class SyllabusContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(default="", max_length=500)
    code: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=10000)
    credits: int = Field(ge=1, le=60)
    weeks: int = Field(ge=10, le=20)
    hours_per_credit: int = Field(default=30, ge=1, le=60)
    contact_share: float = Field(default=0.5, ge=0.2, le=0.8)
    mode: str = Field(default="academic", pattern="^(academic|practical|project)$")
    thematic_plan: list[SyllabusWeekRow] = Field(min_length=1, max_length=52)
    learning_outcomes: list[str] = Field(default_factory=list, max_length=100)
    assessment_methods: list[str] = Field(default_factory=list, max_length=100)


class SyllabusDraftRequest(BaseModel):
    content: SyllabusContent


class SemesterInsightRequest(BaseModel):
    semester: int = Field(ge=1, le=20)
    variant: str = Field(default="A", pattern="^[ABCabc]$")
    language: str = Field(default="ru", pattern="^(ru|kk|en)$")


class BridgeReplacementCandidate(BaseModel):
    """Explicit payload for an expert-confirmed AI bridge replacement."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: int | None = Field(default=None, ge=1, le=3)
    title_ru: str = Field(min_length=4, max_length=240)
    title_kk: str | None = Field(default=None, max_length=240)
    title_en: str | None = Field(default=None, max_length=240)
    description_ru: str = Field(min_length=20, max_length=3000)
    description_kk: str | None = Field(default=None, max_length=3000)
    description_en: str | None = Field(default=None, max_length=3000)
    credits: int | None = Field(default=None, ge=1, le=60)
    target_los: list[str] = Field(default_factory=list, max_length=50)


class GenerateBridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_enrichment: bool = False


class LoAchievabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(default="ru", pattern="^(ru|kk|en)$")


class ApplyPriorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discipline_ids: list[int] = Field(default_factory=list, max_length=30)


class BridgeReplacementSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bridge_item_id: int = Field(ge=1)
    course_id: int = Field(ge=1)


class MatchFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_version_id: int = Field(ge=1)
    course_id: int = Field(ge=1)
    lo_id: int = Field(ge=1)
    verdict: str = Field(pattern="^(confirmed|weak|incorrect|corrected)$")
    corrected_score: float | None = Field(default=None, ge=0.0, le=1.0)
    comment: str | None = Field(default=None, max_length=5000)


class PlanFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int = Field(ge=1)
    feedback: str = Field(pattern="^(accepted|rejected|modified)$")
    details: dict | None = None


class PlannerBuildResponse(BaseModel):
    variants: dict
    active_variant: str | None = None
    publication_status: str = "complete"
    rejected_variants: list[dict] = Field(default_factory=list)
    drafts: list[dict] = Field(default_factory=list)
    goso_ruleset_version: str | None = None
    epvo_repository: dict = Field(default_factory=dict)
    change_report: dict = Field(default_factory=dict)
    descriptions: dict = Field(default_factory=dict)


class PlannerBuildQueuedResponse(BaseModel):
    state: str = "queued"
    job_id: str
    project_version_id: int
    status_url: str


class PlannerBuildStatusResponse(BaseModel):
    """Stable status envelope while retaining forward-compatible telemetry fields."""

    model_config = ConfigDict(extra="allow")

    state: str = "idle"
    stage: str = "idle"
    progress: int = Field(default=0, ge=0, le=100)
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    worker_id: str | None = None
    attempt_count: int | None = Field(default=None, ge=0)
    cancel_requested: int | None = Field(default=None, ge=0, le=1)
    error: str | None = None


class PlannerBuildCancelResponse(BaseModel):
    state: str
    cancelled: bool
    updated_at: datetime | None = None


class PlannerMetricPercentiles(BaseModel):
    # No samples is a valid operational state; do not turn it into a 500 via
    # response-model validation or misrepresent it as a measured zero.
    p50: float | None = None
    p95: float | None = None


class PlannerBuildPerformanceResponse(BaseModel):
    """Stable telemetry envelope for build latency and resource diagnostics."""

    model_config = ConfigDict(extra="allow")

    sample_size: int = 0
    duration_ms: PlannerMetricPercentiles = Field(default_factory=PlannerMetricPercentiles)
    sql_query_count: PlannerMetricPercentiles = Field(default_factory=PlannerMetricPercentiles)
    response_bytes: PlannerMetricPercentiles = Field(default_factory=PlannerMetricPercentiles)
    cache_hit_rate: float | None = None
    p95_budget_ms: int = 300_000
    p95_within_budget: bool | None = None
    recent: list[dict] = Field(default_factory=list)


class PlannerObservabilityResponse(BaseModel):
    """Aggregate, payload-free signals for staging dashboards and alerts."""

    build_states: dict[str, int] = Field(default_factory=dict)
    failed_or_timed_out: int = 0
    active_leases: int = 0
    telemetry_sample_size: int = 0
    duration_ms: PlannerMetricPercentiles = Field(default_factory=PlannerMetricPercentiles)
    p95_budget_ms: int = 300_000
    p95_within_budget: bool | None = None
