"""Server-owned model seats, outside the deterministic combat engine.

SeatRunner uses the table's legal menu and act/auto_step transport. No engine
method is replaced and fights without an explicit seat remain unchanged.
"""

from .runner import SeatRunner

__all__ = ["SeatRunner"]
