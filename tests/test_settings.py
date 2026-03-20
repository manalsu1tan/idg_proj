from __future__ import annotations

import os
from pathlib import Path

from packages.memory_core.settings import Settings, load_dotenv_file


def test_load_dotenv_file_sets_missing_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PROJECT_B_MODEL_API_KEY=test-key\nPROJECT_B_MODEL_PROVIDER=openai_compatible\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PROJECT_B_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PROJECT_B_MODEL_PROVIDER", raising=False)
    load_dotenv_file(env_file)
    assert os.environ["PROJECT_B_MODEL_API_KEY"] == "test-key"
    assert os.environ["PROJECT_B_MODEL_PROVIDER"] == "openai_compatible"


def test_load_dotenv_file_does_not_override_existing_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PROJECT_B_MODEL_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_B_MODEL_PROVIDER", "openai_compatible")
    load_dotenv_file(env_file)
    assert os.environ["PROJECT_B_MODEL_PROVIDER"] == "openai_compatible"


def test_settings_reads_environment_at_instantiation(monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_B_MODEL_API_KEY", "test-key")
    settings = Settings()
    assert settings.model_api_key == "test-key"
