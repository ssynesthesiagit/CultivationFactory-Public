"""Shared opt-in query for healing plug-ins with historical commit paths.

bodya_body_refining, goruden and fate_riders retain their original preparation,
receipt and reaction semantics unless a provider explicitly opts this recipient
into ordinary healing preparation. blood_court_healing supplies the current
sealed-zone policy. No match-wide migration or saved state is introduced.
"""
from . import CheckpointError, run_checkpoint


def ordinary_preparation(engine, subject):
    """Pure recipient policy query, independent of bonuses or remaining allowance."""
    replies = run_checkpoint("healing_preparation_policy", engine, subject)
    if any(type(reply) is not bool for reply in replies):
        raise CheckpointError("healing_preparation_policy must return bool or None")
    return any(replies)
