from __future__ import annotations

from packages.memory_core.bootstrap import get_memory_service
from packages.memory_core.services import MemoryService


def get_service() -> MemoryService:
    return get_memory_service()

