"""
Bi-Sync Persistence Strategy
============================

Encodes how a user-visible edit should persist back to source.

This keeps drag, property edits, reload, and export on the same contract:
1. exact_source: update the existing source-backed AST node directly
2. safe_patch: inject a stable post-creation patch after the source anchor
3. no_persist: allow no source write because there is no reliable target
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PersistenceStrategy:
    """Persistence policy for one pending edit."""

    mode: str
    reason: str = ""
    source_key: Optional[str] = None

    @property
    def exact_source(self) -> bool:
        return self.mode == "exact_source"

    @property
    def safe_patch(self) -> bool:
        return self.mode == "safe_patch"

    @property
    def no_persist(self) -> bool:
        return self.mode == "no_persist"
