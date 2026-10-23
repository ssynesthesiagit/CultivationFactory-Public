"""Explicit-kind Radiance clauses. Creature names never establish Unclean status.

Shared Scripture damage implementation for native and typed packets; radiance_dawnmark
handles the mark's duration and player-owned flare choice, not a second damage bonus.
"""
from . import hook
from .creature_kinds import is_unclean

PREFIX = 'tianxia.talent.radiance.'
WARD = PREFIX + 'dawn_ward'
SCRIPTURE = PREFIX + 'dawnmark_scripture'
SCRIPTURE_TURN_FLAG = '_round_dawnmark_scripture_unclean'


@hook('damage_reduction_bonus')
def dawn_ward_bonus(engine, owner, protected, attacker, row):
    if row.get('feature_id') == WARD and attacker is not None and is_unclean(attacker):
        return owner.proficiency_bonus
    return None


@hook('event', nested=True)
def scripture_damage(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    payload = kwargs.get('payload') or {}
    if int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0:
        return
    from ..alternative_payments import owned
    from ..typed_executor import bears_mark
    from ..gate2_runtime_models import DiceSpec
    from .placed import note
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None or not owned(engine, owner, SCRIPTURE):
        return
    turn = f'{engine.state.round_number}:{engine.state.current_actor_id}'
    key = SCRIPTURE_TURN_FLAG
    current = engine.state.actors[engine.state.current_actor_id]
    legacy = owner.turn_flags.get('radiance_scripture_damage_turn')
    if owner.turn_flags.get(key) == turn or legacy == [engine.state.round_number, current.entity_id, current.turns_started]:
        return
    for aid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(aid)
        if target is None or not is_unclean(target) or not bears_mark(target, owner.entity_id, 'Dawnmark'):
            continue
        owner.turn_flags[key] = turn  # before nested damage, so it cannot trigger itself
        roll = engine.roller.roll(DiceSpec(count=1, sides=8, modifier=0), actor_id=owner.entity_id,
                                  reason=f'DAMAGE:{kwargs.get("source_definition_id")}:Dawnmark Scripture')
        engine._record_roll(roll)
        engine._append_event('DAMAGE_ROLLED', SCRIPTURE, actor_id=owner.entity_id, target_ids=(aid,),
                            payload=roll.model_dump(mode='json'))
        note(engine, SCRIPTURE, owner, f'Dawnmark Scripture: {target.display_name} bears your Dawnmark and is Unclean; '
             f'add {roll.total} Radiant damage. This benefit has been used for this turn.')
        if target.active and target.current_hp > 0:
            engine._commit_damage(target, roll.total, 'RADIANT', SCRIPTURE, owner.entity_id,
                                  engine._active_intent, reaction_depth=0)
        break
