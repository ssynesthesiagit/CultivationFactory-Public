"""Lightweight in-process Tianxia combat content and projection support.

Gate 1 intentionally contains no combat resolution engine.
"""

from .gate1 import Gate1BuildResult, build_gate1
from .version import COMBAT_MODULE_VERSION, ENGINE_API_VERSION, PROJECTION_COMPILER_VERSION

__all__ = [
    "COMBAT_MODULE_VERSION",
    "ENGINE_API_VERSION",
    "PROJECTION_COMPILER_VERSION",
    "Gate1BuildResult",
    "build_gate1",
]
