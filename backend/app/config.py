from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List
from urllib.parse import urlparse


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)
    # Database
    DATABASE_URL: str
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    # Plan generation and expert review sessions can legitimately last hours.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    # Local HTTP needs a non-Secure cookie; every HTTPS deployment must set
    # this to true in its environment instead of changing application code.
    AUTH_COOKIE_SECURE: bool = False
    # CLI bearer tokens are intentionally shorter-lived than browser sessions.
    CLI_TOKEN_EXPIRE_MINUTES: int = 60
    
    # Embedding Model
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    EMBEDDING_DIMENSION: int = 768
    ENABLE_SBERT: bool = False
    SBERT_DEVICE: str = "auto"
    # Larger inference batches reduce Python/transformer call overhead while
    # the upper bound keeps local CPU/RAM usage predictable on staging hosts.
    SBERT_BATCH_SIZE: int = Field(default=64, ge=1, le=128)
    EPVO_AI_ENABLED: bool = False
    EPVO_AI_THRESHOLD: float = 0.3449310730397701
    EPVO_AI_TEMPERATURE: float = 0.08
    EPVO_RANKER_ENABLED: bool = False
    EPVO_RANKER_MODEL_NAME: str = "models/epvo-sbert-mined-triplets-6k"
    EPVO_RANKER_DEVICE: str = "cpu"
    # Frozen A/B decision 2026-07-17: validation selected weight 0.0.
    # A non-zero value is experimental and must be justified by a new report.
    EPVO_RANKER_WEIGHT: float = 0.0

    # Public research identity. Legacy EPVO_* setting names remain supported
    # internally for backward compatibility and source-provenance tracing.
    EXPERT_EVIDENCE_REPOSITORY_NAME: str = "Curriculum Expert Evidence Repository"
    EXPERT_EVIDENCE_REPOSITORY_SLUG: str = "ceer"
    
    # LLM Configuration
    LLM_PROVIDER: str = "openai"  # openai, anthropic, local
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gpt-4"
    LLM_BASE_URL: str = ""  # For local models
    # External AI assistance must never block deterministic plan construction
    # indefinitely. A timeout returns a documented local fallback instead.
    LLM_TIMEOUT_SECONDS: float = 15.0
    # Optional typed LLM orchestration. Disabled by default so the production
    # environment does not need an additional dependency.
    PYDANTIC_AI_ENABLED: bool = False
    PYDANTIC_AI_MODEL_NAME: str = ""
    # Keep optional LLM orchestration bounded and deterministic by default.
    # A provider retry is allowed only when explicitly configured.
    PYDANTIC_AI_RETRIES: int = 0
    
    # KAG Configuration
    SIMILARITY_THRESHOLD: float = 0.82
    COVERAGE_THRESHOLD: float = 0.60
    MAX_BRIDGE_MODULES: int = 5
    TOP_K_RETRIEVAL: int = 20
    # Profiled production defaults. NSGA-II ranking is O(G * P^2); the old
    # 200x100 settings spent minutes ranking near-identical curricula. 36x50
    # retained 100/100 quality and distinct A/B/C on the 240-credit control
    # programme while reducing the complete dry-run to 22.91 seconds.
    # Keep interactive plan generation bounded.  The previous 36x50 search
    # evaluated every candidate thousands of times and could occupy the only
    # API worker for 20+ minutes.  18x20 preserves evolutionary diversity while
    # keeping a new programme responsive; users can still rerun after review.
    NSGA2_POPULATION: int = 18
    NSGA2_GENERATIONS: int = 20
    NSGA2_CROSSOVER_PROBABILITY: float = 0.9
    NSGA2_MUTATION_PROBABILITY: float = 0.1
    
    # Localization
    DEFAULT_LANGUAGE: str = "ru"
    # The UI uses the ISO 639-1 code `kk`; `kz` remains accepted as a
    # backwards-compatible request alias in EPVO endpoints.
    SUPPORTED_LANGUAGES: List[str] = ["ru", "kk", "en"]
    # PostgreSQL CourseLocalization/EPVO rows are authoritative. Enable the
    # JSON fallback only for a deliberate legacy-data recovery run.
    LEGACY_TRANSLATIONS_FALLBACK: bool = False
    
    # Application
    APP_NAME: str = "Curriculum-KAG Generator"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ALLOWED_HOSTS: List[str] = ["localhost", "127.0.0.1", "testserver"]
    # Keep browser origins explicit in production; the local defaults support
    # the Vite development server without allowing arbitrary credentials.
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5173",
    ]
    APP_ENV: str = "local"
    DOMAIN: str = ""
    DOCS_ENABLED: bool = False
    # Repository inspection/branch UI is a local development convenience,
    # never an implicit production capability.
    GIT_UI_ENABLED: bool = True
    # The worker heartbeat runs every lease/3.  Variant B/C may legitimately
    # spend several minutes in strict quality verification; a three-minute
    # lease falsely timed out live workers. Ten minutes still bounds recovery
    # well below the independent one-hour absolute build deadline.
    BUILD_LEASE_SECONDS: int = 600
    # Absolute job limit is deliberately independent from the renewable
    # worker lease. A heartbeat may prove liveness, never grant infinite time.
    BUILD_DEADLINE_SECONDS: int = 3600
    MAX_REQUEST_BYTES: int = 2 * 1024 * 1024
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10
    # A methodologist may reasonably retry after correcting inputs, build A,
    # and explicitly compare alternatives in one review session. Three
    # submissions made a healthy local session hit a 429 before any build was
    # running. Eight still bounds expensive work to a small per-client rate.
    RATE_LIMIT_BUILD_PER_TEN_MINUTES: int = 8
    RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES: int = 10
    # Local/test remains process-local; production Compose explicitly opts
    # into the PostgreSQL bucket after Alembic has created its table.
    RATE_LIMIT_BACKEND: str = "memory"
    ASYNC_BUILDS: bool = False
    # When enabled, API requests enqueue durable jobs and a separate worker
    # service consumes them.  Keep the one-shot process mode as the explicit
    # local fallback for environments without a worker service.
    PERSISTENT_PLANNER_WORKER: bool = False
    WEB_CONCURRENCY: int = 1
    # Build telemetry is diagnostic data, not the permanent audit record.
    # Cleanup is explicit and dry-run by default.
    AUDIT_TELEMETRY_RETENTION_DAYS: int = 365
    # Operational SLO for interactive planner builds. The API exposes the
    # comparison; an external monitor can alert without parsing logs.
    PLANNER_P95_BUDGET_MS: int = 300_000
    
def validate_production_settings(settings: Settings) -> None:
    if settings.APP_ENV.lower() != "production":
        return
    database_url = urlparse(str(settings.DATABASE_URL or ""))
    if database_url.scheme not in {"postgresql", "postgresql+psycopg2", "postgresql+asyncpg"} or not database_url.hostname:
        raise RuntimeError("DATABASE_URL must point to a PostgreSQL host in production")
    if len(settings.SECRET_KEY) < 32 or settings.SECRET_KEY.lower().startswith(("change", "secret", "dev")):
        raise RuntimeError("SECRET_KEY must be a generated secret of at least 32 characters in production")
    if not settings.AUTH_COOKIE_SECURE:
        raise RuntimeError("AUTH_COOKIE_SECURE=true is required in production")
    if settings.DOCS_ENABLED:
        raise RuntimeError("DOCS_ENABLED must be false in production unless protected at the edge")
    if settings.GIT_UI_ENABLED:
        raise RuntimeError("GIT_UI_ENABLED must be false in production")
    if settings.MAX_REQUEST_BYTES <= 0:
        raise RuntimeError("MAX_REQUEST_BYTES must be positive in production")
    if settings.PLANNER_P95_BUDGET_MS <= 0:
        raise RuntimeError("PLANNER_P95_BUDGET_MS must be positive in production")
    if settings.BUILD_LEASE_SECONDS <= 0 or settings.BUILD_DEADLINE_SECONDS <= 0:
        raise RuntimeError("BUILD_LEASE_SECONDS and BUILD_DEADLINE_SECONDS must be positive in production")
    if settings.CLI_TOKEN_EXPIRE_MINUTES <= 0 or settings.CLI_TOKEN_EXPIRE_MINUTES > 240:
        raise RuntimeError("CLI_TOKEN_EXPIRE_MINUTES must be between 1 and 240 in production")
    if any(
        limit <= 0
        for limit in (
            settings.RATE_LIMIT_LOGIN_PER_MINUTE,
            settings.RATE_LIMIT_BUILD_PER_TEN_MINUTES,
            settings.RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES,
        )
    ):
        raise RuntimeError("Production rate limits must be positive")
    if settings.WEB_CONCURRENCY <= 0:
        raise RuntimeError("WEB_CONCURRENCY must be positive in production")
    if settings.WEB_CONCURRENCY > 1:
        if settings.RATE_LIMIT_BACKEND.lower() not in {"postgres", "postgresql"}:
            raise RuntimeError("WEB_CONCURRENCY>1 requires RATE_LIMIT_BACKEND=postgres")
    hosts = [str(host).strip().lower() for host in (settings.ALLOWED_HOSTS or [])]
    if not hosts or "*" in hosts or any("://" in host or not host for host in hosts):
        raise RuntimeError("ALLOWED_HOSTS must list explicit production hostnames, not URLs or wildcards")
    origins = [str(origin).strip() for origin in (settings.CORS_ORIGINS or [])]
    if not origins or "*" in origins or any(urlparse(origin).scheme not in {"http", "https"} or not urlparse(origin).netloc for origin in origins):
        raise RuntimeError("CORS_ORIGINS must list explicit http(s) origins")
    domain = str(settings.DOMAIN or "").strip().lower()
    if not domain:
        raise RuntimeError("DOMAIN is required in production")
    if domain not in hosts:
        raise RuntimeError("DOMAIN must be present in ALLOWED_HOSTS")
    origin_urls = [urlparse(origin) for origin in origins]
    if any(
        url.scheme != "https"
        or url.hostname in {"localhost", "127.0.0.1", "::1"}
        for url in origin_urls
    ):
        raise RuntimeError("Production CORS_ORIGINS must use HTTPS and cannot target localhost")


settings = Settings()
validate_production_settings(settings)
