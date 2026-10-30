"""Ordinary immediate-step eligibility shared by Storm-Heart and Black-Claw.

Extra movement cannot override effective Speed (including immobilizing typed
conditions). Call before replacing the actor's ordinary movement budget.
"""
from typing import Any


def immediate_step_budget(engine: Any, actor: Any, distance_ft: int) -> int:
    """Return the step allowance capped by effective Speed, or zero if immobile."""
    return min(max(0, distance_ft), engine._effective_speed(actor))
