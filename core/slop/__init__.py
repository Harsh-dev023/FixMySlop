"""Deterministic slop detection: UI slop, code slop, security, phantom dependencies."""
from core.slop.engine import SlopEngine, slop_score, grade, at_or_above
from core.slop.rule import RULES

__all__ = ["SlopEngine", "RULES", "slop_score", "grade", "at_or_above"]
