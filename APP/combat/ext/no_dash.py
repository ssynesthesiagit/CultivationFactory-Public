"""Clinging Seal's "cannot benefit from the Dash action" (fight audit 2026-09-29: it was a stand-in 'guarding' tag that
did nothing). The no_dash condition (combat/rules/typed_conditions.json) takes the Dash action off what the fighter is
offered; a typed Dash (movement equal to its Speed) is blocked in typed_executor.block_movement.

Thick Darkness ("Creatures inside ... cannot take the Dash or Disengage actions", auto-lane5): an area's ``inside`` row
(combat/zones.py sync_inside) puts the rules no_dash and no_disengage on every creature standing in it, and this hook
takes both actions off their menu the same way."""

from __future__ import annotations

from typing import Any

from . import hook

_BARRED = {"system:combat.dash": "no_dash", "system:combat.disengage": "no_disengage"}


@hook("candidate_allowed")
def no_dash(engine: Any, actor: Any, candidate: Any, action: Any) -> bool:
    rule_name = _BARRED.get(candidate.source_definition_id)
    if rule_name is None:
        return True
    from ..typed_executor import condition_rules

    return not any(rule.get(rule_name) for rule in condition_rules(actor))
