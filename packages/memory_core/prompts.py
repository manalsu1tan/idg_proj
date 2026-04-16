from __future__ import annotations

"""Prompt loading utilities
Reads prompt templates for model components"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "configs" / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()
