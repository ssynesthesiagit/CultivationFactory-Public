"""Shared damage classification for typed saves and charm action gates.

Used by typed_executor's damaging_save tag, charm_rules' action query,
and dream_mirror's Reflection Cut failed-outcome eligibility query.
Damage in a save outcome includes a state applied by that outcome which deals
damage at the recipient's own turn start. Retaliation and other contingent
future triggers are not damage from the save itself and are not traversed.
This is a pure query; it neither applies effects nor changes stored state.
"""
from typing import Any


def has_damage(effects: Any) -> bool:
    """Whether these effects contain immediate or recipient-turn damage."""
    for row in effects or []:
        if not isinstance(row, dict):
            continue
        if row.get('type') in ('damage', 'extra_damage'):
            return True
        if row.get('type') == 'periodic_damage_state':
            # ash_talents stores these packets on the save's recipient and
            # delivers them at its turn start, just like own_turn_start below.
            packets = row.get('damage') or ([row] if row.get('dice') else [])
            if any(isinstance(packet, dict) and (packet.get('dice') or packet.get('flat'))
                   for packet in packets):
                return True
        if any(has_damage(row.get(key)) for key in (
                'on_fail', 'on_success', 'on_hit', 'on_miss', 'effects', 'own_turn_start')):
            return True
    return False
