from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    # Plan generation and expert review sessions can legitimately last hours.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    
    # Embedding Model
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    EMBEDDING_DIMENSION: int = 768
    ENABLE_SBERT: bool = False
    SBERT_DEVICE: str = "auto"
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
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
