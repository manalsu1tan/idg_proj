from __future__ import annotations

"""Service bootstrap helpers
Creates singleton memory service for app entrypoints"""

from functools import lru_cache

from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings


@lru_cache(maxsize=1)
def get_memory_service() -> MemoryService:
    return MemoryService(load_settings())
