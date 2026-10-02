"""Analytical adapters behind explicit contracts (WP10, R11).

``analytical`` is a self-contained, standard-library-only module: the same file runs
in-process (direct) and as the fresh contained worker per job (hosted), so direct and hosted
results can be compared byte for byte (AT16)."""
from . import analytical

__all__ = ["analytical"]
