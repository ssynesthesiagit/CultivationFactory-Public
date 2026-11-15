"""Prison Warden's prison statistics and post-escape teleport prohibition."""
from typing import Any
from . import hook
from .ability_source import compiled_feature_rows, mechanic_of, mechanic_at

WARDEN = 'insight.prison-warden'
BLOCK = 'chains_prison_warden'
STOP = 'condition:typed.chains_warden_escape'
PRISONS = frozenset('tianxia.talent.chains.' + name for name in
    ('shackling_chain', 'chain_prison', 'chain_the_door', 'prison_of_nine_gates'))


@hook('compile_block')
def compile_warden(block: str, spec: dict, row: dict, numbers: dict) -> list[dict] | None:
    return [{**row, 'block': BLOCK}] if block == BLOCK else None


@hook('bound_object_bonuses')
def prison_statistics(ctx: Any, spec: dict) -> dict | None:
    if mechanic_of(ctx.action) not in PRISONS or not compiled_feature_rows(ctx.engine, ctx.actor.entity_id, WARDEN):
        return None
    return {'ac': 2, 'hp': 5 * int(ctx.actor.proficiency_bonus)}


@hook('hold_escaped')
def stop_escape_teleport(engine: Any, record: dict) -> None:
    holder = engine.state.actors.get(record.get('holder'))
    if holder is None:
        return
    from .effect_durations import token
    for held in record.get('holds') or []:
        source = mechanic_at(engine, held.get('source', ''))
        if not (source.startswith('tianxia.talent.chains.') or source.startswith('TAL_CHAINS_')):
            continue
        owner = engine.state.actors.get(held.get('owner'))
        if owner is not None and (owner.summon or {}).get('source', '').startswith('tianxia.talent.chains.'):
            owner = engine.state.actors.get(owner.summon.get('owner'))
        if owner is None or not compiled_feature_rows(engine, owner.entity_id, WARDEN):
            continue
        engine._apply_condition(holder, STOP, WARDEN, owner.entity_id,
            expires_on=token('start', holder.entity_id, int(holder.turns_started) + 1),
            data={'label': 'Prison Warden: you cannot teleport until your next turn starts'})
        break


@hook('teleport_gate')
def no_escape_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    return False if any(c.condition_id == STOP for c in ctx.actor.conditions.values()) else None
