"""Public reaction eligibility for Air guards and future sight-based reactions.

Uses the shared equipment sight query, native/typed condition rules and
unmaking's public attacker-specific prohibition query. A free use
waives spending/availability of the Reaction, but never a reaction prohibition.
"""
from typing import Any


def eligible(engine: Any, actor: Any, subject: Any, *, attacker: Any = None, free: bool = False) -> bool:
    """Check sight of the protected subject and permission against the attacker.

    Omitted attacker retains subject-independent checks for future consumers.
    ``free`` waives only Reaction availability, never any prohibition.
    """
    from ..typed_executor import condition_rules
    from ..unmaking import reactions_denied_against
    from .equipment_armor import can_see
    from .needle import incapacitated

    held = {c.condition_id for c in actor.conditions.values()}
    self_visible = actor.entity_id == subject.entity_id and not held.intersection({
        "condition:typed.blinded", "condition:core.blinded", "condition:typed.invisible", "condition:core.invisible"})
    return bool(actor.active and not incapacitated(actor)
                and (free or actor.reaction_available)
                and "condition:core.reaction_denied" not in held
                and not any(bool((c.data or {}).get("reaction_denied")) for c in actor.conditions.values())
                and not any(row.get("no_reactions") for row in condition_rules(actor))
                and not reactions_denied_against(actor, attacker)
                and (self_visible or can_see(engine, actor, subject)))
