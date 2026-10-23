"""Shared current Exhaustion provenance for qi_homefire_recovery,
forged_exhaustion and journey continuation.

Balances describe levels still held, never historical exposure events. Ordinary
unsourced levels remain unknown and cannot satisfy a cause-specific cure.
"""
import json


def causes(conditions, total):
    """Read current per-level causes, padding old/unsourced levels as unknown."""
    found = []
    for c in conditions:
        if c.condition_id == 'condition:typed.exhaustion':
            found = list(c.data.get('causes') or [])
            break
    return (found + ['unknown'] * max(0, total - len(found)))[:total]


def resized(before, total, source='unknown'):
    """An ordinary cure consumes oldest levels; an increase records its source."""
    if total < len(before):
        return before[len(before) - total:] if total else []
    return before + [source] * (total - len(before))


def journey_causes(actor):
    """Snapshot levels plus only the outstanding native travel delta.

    A journey's scalar is the current total. Its encounter snapshot holds the
    last combat's total; travel exposure only increments the scalar. Once a
    cause-specific cure updates both, an old exposure can never be reused.
    """
    from ..gate2_runtime_models import ConditionInstance
    snapshot = actor.get('encounter_snapshot') or {}
    conditions = [ConditionInstance.model_validate(json.loads(raw))
                  for raw in snapshot.get('conditions', {}).values()]
    old = next((int(c.data.get('level', 0)) for c in conditions
                if c.condition_id == 'condition:typed.exhaustion'), 0)
    held = causes(conditions, old)
    return resized(held, actor['exhaustion'], 'travel')
