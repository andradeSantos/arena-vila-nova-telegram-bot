"""Modulo de Memoria Preventiva e Auditoria de Erros (error-ledger.json)."""

from backend.app.memory.manager import MemoryManager, get_memory_manager

__all__ = ["MemoryManager", "get_memory_manager"]
