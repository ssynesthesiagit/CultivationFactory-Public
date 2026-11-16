"""Owned mode-removal consumers and shared compatibility query for rider C15.

Piercing Senses removes only Invisible, Blinded and obscuration Disadvantage
within 30 feet; it grants no sight or knowledge. Discern Tells removes Advantage
on attacks against its owner by a creature that owner has Analyzed. Neither
adds Disadvantage or removes unrelated causes of Disadvantage.

The shared removed helper delegates to the native strict query. No condition
masking or typed strike-mode workaround is registered here. Conditional higher
authority exceptions, such as Storm Without Direction's, belong to their own
qualified providers; an unconditional ADVANTAGE token removes every source.
"""
from . import hook

BLOCK = 'attack_mode_removal'


def removed(engine, attacker, target, ranged=None):
    """Shared C15 import preserved; native collection owns validation/timing."""
    from ..attack_modes import removed as native_removed
    return native_removed(engine, attacker, target, ranged)


@hook('compile_block')
def compile_removal(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, **{key: value for key, value in spec.items() if key not in {'why', 'resource'}},
                 'keeps_compiling': True}]


@hook('attack_mode_removed')
def owned_removals(engine, attacker, target, ranged):
    from .eye_common import analyzed_by
    tokens = []
    for owner, defensive in ((attacker, False), (target, True)):
        for row in getattr(engine, 'typed_passive_rows', {}).get(owner.entity_id, ()):
            if row.get('block') != BLOCK or row.get('held_back'):
                continue
            if bool(row.get('defensive')) != defensive:
                continue
            if row.get('ranged') is not None and (ranged is None or bool(row['ranged']) != ranged):
                continue
            if row.get('range_ft') is not None and engine._distance_actor_to_actor(attacker, target) > row['range_ft']:
                continue
            if row.get('analyzed_by_owner') and not analyzed_by(attacker, owner.entity_id):
                continue
            tokens.extend(row.get('remove') or ())
    return tokens or None


@hook('attack_mode_removed')
def area_rows(engine, attacker, target, ranged):
    """Owned zone metadata removes modes only inside that zone's real volume."""
    from .. import zones
    tokens = []
    for zone in zones.typed_zones(engine):
        if not zone.active or not zones._inside(engine, attacker, zone):
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action else {}
        rule = next((row[BLOCK] for row in typed.get('effects') or ()
                     if row.get('type') == 'zone' and isinstance(row.get(BLOCK), dict)), None)
        if not rule or (rule.get('ranged') is not None and rule['ranged'] != ranged):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if rule.get('who') == 'hostile' and (owner is None or owner.team_id == attacker.team_id):
            continue
        tokens.extend(rule.get('remove') or ())
    return tokens or None
