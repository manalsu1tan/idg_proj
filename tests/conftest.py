from __future__ import annotations

import os

import pytest

from packages.memory_core.services import MemoryService
from packages.memory_core.settings import Settings


@pytest.fixture()
def memory_service(tmp_path) -> MemoryService:
    db_path = tmp_path / "project_b.sqlite3"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        prompt_version="test-v1",
        model_version="test-heuristic",
        model_provider="mock",
        time_window_hours=12,
        cluster_similarity_threshold=0.12,
        max_branches=3,
        default_token_budget=120,
    )
    return MemoryService(settings)
