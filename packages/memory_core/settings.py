from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"


def load_dotenv_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and ((value[0] == value[-1]) and value[0] in {"'", '"'}):
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("PROJECT_DATABASE_URL", "sqlite+pysqlite:///./project_b.db"))
    prompt_version: str = field(default_factory=lambda: os.getenv("PROJECT_PROMPT_VERSION", "v1"))
    model_version: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_VERSION", "heuristic-v1"))
    model_provider: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_PROVIDER", "openai_compatible"))
    model_base_url: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_BASE_URL", "https://api.openai.com/v1"))
    model_api_key: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_API_KEY", ""))
    summary_model: str = field(default_factory=lambda: os.getenv("PROJECT_SUMMARY_MODEL", "gpt-5-nano"))
    verifier_model: str = field(default_factory=lambda: os.getenv("PROJECT_VERIFIER_MODEL", "gpt-5-nano"))
    model_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("PROJECT_MODEL_TIMEOUT_SECONDS", "30")))
    time_window_hours: int = field(default_factory=lambda: int(os.getenv("PROJECT_TIME_WINDOW_HOURS", "6")))
    cluster_similarity_threshold: float = field(
        default_factory=lambda: float(os.getenv("PROJECT_CLUSTER_SIMILARITY_THRESHOLD", "0.18"))
    )
    max_branches: int = field(default_factory=lambda: int(os.getenv("PROJECT_MAX_BRANCHES", "3")))
    default_token_budget: int = field(default_factory=lambda: int(os.getenv("PROJECT_DEFAULT_TOKEN_BUDGET", "180")))
    embedding_dimensions: int = field(default_factory=lambda: int(os.getenv("PROJECT_EMBEDDING_DIMENSIONS", "12")))
    summary_max_tokens: int = field(default_factory=lambda: int(os.getenv("PROJECT_SUMMARY_MAX_TOKENS", "18")))
    social_summary_max_tokens: int = field(default_factory=lambda: int(os.getenv("PROJECT_SOCIAL_SUMMARY_MAX_TOKENS", "24")))
    auto_create_schema: bool = field(default_factory=lambda: os.getenv("PROJECT_AUTO_CREATE_SCHEMA", "true").lower() == "true")
    ui_enabled: bool = field(default_factory=lambda: os.getenv("PROJECT_UI_ENABLED", "true").lower() == "true")


def load_settings() -> Settings:
    load_dotenv_file()
    return Settings()
