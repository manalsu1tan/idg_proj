from __future__ import annotations

"""API dependency wiring
Provides request scoped service accessors"""

from packages.memory_core.bootstrap import get_memory_service
from packages.memory_core.services import MemoryService


def get_service() -> MemoryService:
    """Resolve shared memory service for request handlers"""
    return get_memory_service()
