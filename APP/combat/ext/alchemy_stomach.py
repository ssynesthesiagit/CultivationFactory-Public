"""Furnace-Tyrant's Stomach: own-product reduction and other-source resistance.

Decorates its existing hash-gated Poison defense row, never another creature's
catalog. A packet must name the same owner and a retained Alchemy action to
receive the additional PB reduction. The existing resistance is still read
by native packet defenses. The save benefit asks whether another effective
Poison Resistance exists, excluding this Insight's own defense contribution.
"""
from typing import Any

from . import hook

STOMACH = 'insight.furnace-tyrant-s-stomach'


@hook('compile_passives')
def annotate(passives: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    if STOMACH not in (info.get('owned_ids') or ()):
        return passives
    return [{**row, 'alchemy_stomach': 1, 'pb': int(info['numbers']['pb']),
             'player_outcome': 'Resistance to Poison; own Alchemy Poison damage is reduced by your '
                               'Proficiency Bonus; another Poison Resistance grants Advantage against Poisoned'}
            if row.get('feature_id') == STOMACH and row.get('kind') == 'resistance' else row
            for row in passives]


def owned(engine: Any, actor: Any) -> dict[str, Any] | None:
    return next((row for row in engine.typed_passive_rows.get(actor.entity_id, ())
                 if row.get('feature_id') == STOMACH and row.get('alchemy_stomach') == 1), None)


@hook('final_damage')
def own_poison(engine: Any, target: Any, amount: int, kind: str, source_id: str,
               source_actor_id: str, intent: Any) -> dict[str, Any] | None:
    row = owned(engine, target)
    if not row or kind.upper() != 'POISON' or source_actor_id != target.entity_id:
        return None
    action = engine.action_catalog.get(source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    from .alchemy_riders import alchemy_source
    source = str(typed.get('option_of') or typed.get('source') or '').split('#')[0]
    if not alchemy_source(source):
        return None
    return {'reduction': min(amount, int(row['pb']))}


@hook('save_mode')
def other_resistance(engine: Any, subject: Any, ability: str, dc: int,
                     source_id: str, context: dict[str, Any]) -> str | None:
    if not owned(engine, subject) or 'poisoned' not in {str(v).lower() for v in context.get('named') or ()}:
        return None
    from ..typed_reactions import resistance_profile
    if resistance_profile(engine, subject, 'POISON', {}, excluded_feature_ids=(STOMACH,))['ordinary']:
        return 'ADVANTAGE'
