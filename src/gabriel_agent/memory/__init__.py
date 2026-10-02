"""Memory as a provenance service (WP09): versioned observations, as-of retrieval, scoped claims,
outcome labels that count each matured outcome once, and durable compaction."""
from .service import MemoryService, Frontier, source_key

__all__ = ["MemoryService", "Frontier", "source_key"]
