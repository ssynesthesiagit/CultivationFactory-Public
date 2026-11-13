"""Explicit, ephemeral provenance for a confirmed attack's damage packet."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AttackDamage:
    source_id: str
    attacker_id: str
    target_id: str
    attack_index: int
    roll_id: str
    natural_result: int
    total: int
    critical: bool
    kind: str = 'other'
    component: str = 'primary'
    critical_cancelled: bool = False


def packet_metadata(engine, source_id, attack, label=None):
    """Journal contract shared by all flat/rolled, attached/independent packets.

    hit_roll_id is the existing confirmed hit's roll_id, or None. damage_label
    names this packet, not the enclosing action; neither field changes delivery.
    """
    from .history_text import history_name
    action = engine.action_catalog.get(source_id)
    display = label or (action.display_name if action is not None else source_id)
    return {"hit_roll_id": attack.roll_id if attack is not None else None,
            "damage_label": history_name(display, {})}
