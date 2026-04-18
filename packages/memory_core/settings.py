from __future__ import annotations

"""Runtime config loader
Parses env vars defaults and routing policy files"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"
QUERY_ROUTING_POLICY_PATH = ROOT_DIR / "configs" / "policies" / "query_routing_policy.json"


def load_dotenv_file(path: Path = ENV_PATH) -> None:
    """Load env values from .env style file
    Preserves existing process env and only sets missing keys"""
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


def _default_query_routing_policy() -> dict[str, Any]:
    """Return fallback routing policy when file is missing"""
    return {
        "feature_triggers": {
            "temporal_cue": [
                "latest",
                "updated",
                "changed",
                "revision",
                "current",
                "now",
                "ship",
                "launch",
                "when",
                "actually",
            ],
            "conflict_cue": [
                "conflict",
                "argument",
                "fight",
                "tension",
                "issue",
                "problem",
                "clash",
                "with whom",
                "who was involved",
            ],
            "composition_cue": [
                "based on what i know",
                "given their",
                "preferences and dislikes",
                "and dislikes",
                "using what i already know",
                "communicate",
                "communication",
                "talk",
                "message",
                "preference",
                "prefer",
                "dislike",
                "avoid",
                "what am i bringing for",
                "what did i say i'd bring for",
                "which item",
                "commit",
                "bringing",
            ],
            "negation_cue": [
                "not",
                "never",
                "don't",
                "didn't",
                "did not",
                "do not",
                "agree to bring",
                "agreed to bring",
                "pack",
            ],
            "entity_ambiguity_cue": [
                "alias",
                "pronoun",
                "he",
                "she",
                "they",
                "him",
                "her",
                "different person",
                "same name",
                "who exactly",
                "which person",
                "whom",
                "describe",
                "identity",
                "role",
                "presenting",
                "facilitation",
            ],
        },
        "feature_norms": {
            "temporal_cue": 3.0,
            "conflict_cue": 2.0,
            "composition_cue": 3.0,
            "negation_cue": 2.0,
            "entity_ambiguity_cue": 3.0,
        },
        "feature_weights": {
            "temporal_cue": 1.0,
            "conflict_cue": 1.0,
            "composition_cue": 1.0,
            "negation_cue": 1.0,
            "entity_ambiguity_cue": 1.0,
        },
        "strategy_thresholds": {
            "flat_top1_max": 0.32,
            "revision_leaf_min": 0.45,
            "coverage_min": 0.45,
            "hierarchy_expand_min": 0.48,
            "multi_branch_min": 0.65,
            "feature_active_min": 0.34,
        },
        "resolver_thresholds": {
            "low_confidence_margin": 0.08,
            "disambiguation_close_margin": 0.08,
            "competing_person_score_ratio": 0.55,
            "competing_person_score_gap": 0.25,
            "competing_person_window": 8,
            "expansion_branch_target": 2,
        },
        "supplemental_weights": {
            "coverage_bonus_per_key": 0.06,
            "required_bonus_per_key": 0.12,
            "communication_bonus": 0.10,
            "polarity_bonus": 0.10,
            "disambiguation_bonus": 0.10,
            "entity_aligned_bonus": 0.03,
        },
        "supplemental_thresholds": {
            "base_utility_threshold": 0.08,
            "missing_required_relax": 0.02,
            "communication_gap_relax": 0.02,
            "polarity_relax": 0.02,
            "disambiguation_relax": 0.03,
            "low_confidence_relax": 0.01,
            "temporal_only_penalty": 0.04,
            "min_utility_threshold": 0.04,
            "max_utility_threshold": 0.14,
        },
    }


def load_query_routing_policy(path: Path = QUERY_ROUTING_POLICY_PATH) -> dict[str, Any]:
    """Load routing policy json with fallback defaults"""
    if not path.exists():
        return _default_query_routing_policy()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _default_query_routing_policy()
    if not isinstance(payload, dict):
        return _default_query_routing_policy()
    baseline = _default_query_routing_policy()
    merged = dict(baseline)
    for key in (
        "feature_triggers",
        "feature_norms",
        "feature_weights",
        "strategy_thresholds",
        "resolver_thresholds",
        "supplemental_weights",
        "supplemental_thresholds",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            merged[key] = value
    return merged


@dataclass(frozen=True)
class Settings:
    """Runtime settings container
    Central source for db model prompt and policy config values"""

    database_url: str = field(default_factory=lambda: os.getenv("PROJECT_DATABASE_URL", "sqlite+pysqlite:///./project_b.db"))
    database_fallback_url: str = field(
        default_factory=lambda: os.getenv("PROJECT_DATABASE_FALLBACK_URL", "sqlite+pysqlite:///./project_b.db")
    )
    database_fallback_on_unavailable: bool = field(
        default_factory=lambda: os.getenv("PROJECT_DATABASE_FALLBACK_ON_UNAVAILABLE", "true").lower() == "true"
    )
    prompt_version: str = field(default_factory=lambda: os.getenv("PROJECT_PROMPT_VERSION", "v1"))
    model_version: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_VERSION", "heuristic-v1"))
    model_provider: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_PROVIDER", "openai_compatible"))
    model_base_url: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_BASE_URL", "https://api.openai.com/v1"))
    model_api_key: str = field(default_factory=lambda: os.getenv("PROJECT_MODEL_API_KEY", ""))
    summary_model: str = field(default_factory=lambda: os.getenv("PROJECT_SUMMARY_MODEL", "gpt-5-nano"))
    answer_model: str = field(default_factory=lambda: os.getenv("PROJECT_ANSWER_MODEL", "gpt-5-nano"))
    verifier_model: str = field(default_factory=lambda: os.getenv("PROJECT_VERIFIER_MODEL", "gpt-5-nano"))
    model_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("PROJECT_MODEL_TIMEOUT_SECONDS", "30")))
    model_max_retries: int = field(default_factory=lambda: int(os.getenv("PROJECT_MODEL_MAX_RETRIES", "3")))
    model_retry_backoff_seconds: float = field(
        default_factory=lambda: float(os.getenv("PROJECT_MODEL_RETRY_BACKOFF_SECONDS", "1.5"))
    )
    time_window_hours: int = field(default_factory=lambda: int(os.getenv("PROJECT_TIME_WINDOW_HOURS", "6")))
    cluster_similarity_threshold: float = field(
        default_factory=lambda: float(os.getenv("PROJECT_CLUSTER_SIMILARITY_THRESHOLD", "0.18"))
    )
    max_branches: int = field(default_factory=lambda: int(os.getenv("PROJECT_MAX_BRANCHES", "3")))
    default_token_budget: int = field(default_factory=lambda: int(os.getenv("PROJECT_DEFAULT_TOKEN_BUDGET", "180")))
    embedding_dimensions: int = field(default_factory=lambda: int(os.getenv("PROJECT_EMBEDDING_DIMENSIONS", "12")))
    summary_max_tokens: int = field(default_factory=lambda: int(os.getenv("PROJECT_SUMMARY_MAX_TOKENS", "18")))
    social_summary_max_tokens: int = field(default_factory=lambda: int(os.getenv("PROJECT_SOCIAL_SUMMARY_MAX_TOKENS", "24")))
    query_routing_policy_path: str = field(
        default_factory=lambda: os.getenv("PROJECT_QUERY_ROUTING_POLICY_PATH", str(QUERY_ROUTING_POLICY_PATH))
    )
    query_routing_policy: dict[str, Any] = field(
        default_factory=lambda: load_query_routing_policy(
            Path(os.getenv("PROJECT_QUERY_ROUTING_POLICY_PATH", str(QUERY_ROUTING_POLICY_PATH)))
        )
    )
    auto_create_schema: bool = field(default_factory=lambda: os.getenv("PROJECT_AUTO_CREATE_SCHEMA", "true").lower() == "true")
    ui_enabled: bool = field(default_factory=lambda: os.getenv("PROJECT_UI_ENABLED", "true").lower() == "true")


def load_settings() -> Settings:
    """Load and materialize Settings from env and policy file inputs
    Used by service bootstrap API and eval entrypoints"""
    load_dotenv_file()
    return Settings()
