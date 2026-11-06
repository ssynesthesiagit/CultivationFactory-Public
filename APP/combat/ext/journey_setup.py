"""Generic journey-to-combat condition binding.

Consumers: CombatService.journey_start_combat and native match_initialize. Explicit
integer/string journey_setup snapshots preserve encounter health, life state and
permanent conditions in genesis and cold replay. Turn-bound conditions, modifiers,
concentration and altered maximum HP cannot safely cross encounter clocks: resume
requires explicit GM adjudication that those effects have ended. The terminal
fight remains immutable, and the journey retains the full pre-resolution record.
No snapshot means no edits or events. Travel effects
are deliberately absent from this transfer: they end at combat entry.
"""
from . import hook
import json

from ..effect_endings import SHORT_REST_EXPIRY


def encounter_incapacitated(snapshot):
    """Pure saved-health/condition check shared by journey resume and commands.

    Missing snapshots are inert. Clearing a separate travel flag cannot recover
    zero HP or remove a permanent condition from an encounter snapshot.
    """
    if snapshot is None:
        return False
    from ..gate2_runtime_models import ConditionInstance
    return snapshot['current_hp'] <= 0 or any(
        ConditionInstance.model_validate(json.loads(row)).condition_id in (
            'incapacitated', 'stunned', 'unconscious', 'paralyzed', 'petrified')
        for row in snapshot['conditions'].values())


@hook('journey_short_rest')
def end_rest_scoped_conditions(session, aid):
    """Rest the saved encounter through its engine, never by editing condition rows.

    The terminal fight remains immutable. Its fresh engine is overlaid with the
    journey's latest survivor snapshots (including previous rests); the journey
    atomically saves the new snapshots and the actual combat events/rolls.
    Replaying the journey loads that same immutable fight and runs the same rest.
    """
    from ..journey import require

    actors = session.state['actors']
    owner = actors[aid]
    if not owner.get('encounter_snapshot'):
        return None
    match_id = owner.get('encounter_match_id') or session.state.get('match_id')
    require(match_id and session.encounter_loader is not None,
            'The saved encounter is needed to finish this short rest.')
    engine = session.encounter_loader(match_id)
    survivors = {}
    for actor_id, saved in actors.items():
        snapshot = saved.get('encounter_snapshot')
        if snapshot is None or actor_id not in engine.state.actors:
            continue
        creature = engine.state.actors[actor_id]
        # Only transferable state survived the encounter checkpoint. Do not
        # reintroduce effects explicitly ended there by the GM.
        creature.modifiers.clear()
        creature.concentration = None
        creature.transformed_size_category = None
        creature.maximum_hp = snapshot['maximum_hp']
        creature.maximum_hp_base = None
        creature.maximum_hp_adjustments.clear()
        restore_encounter(creature, snapshot, merge_conditions=False)
        creature.resources = dict(saved['resources'])
        creature.position = creature.position.model_validate(saved['position'])
        survivors[actor_id] = creature

    event_start, roll_start = len(engine.events), len(engine.rolls)
    engine.short_rest(aid)
    # Validate every subscriber consequence before changing the journey snapshot.
    snapshots = {actor_id: encounter_snapshot(creature) for actor_id, creature in survivors.items()}
    for actor_id, snapshot in snapshots.items():
        saved = actors[actor_id]
        was_incapacitated = encounter_incapacitated(saved['encounter_snapshot'])
        saved['encounter_snapshot'] = snapshot
        saved['resources'] = {key: int(value) for key, value in survivors[actor_id].resources.items()}
        saved['incapacitated'] = int(encounter_incapacitated(snapshot)
                                     or (saved['incapacitated'] and not was_incapacitated))
    session.emit('ENCOUNTER_SHORT_REST', aid, match_id=match_id,
                 combat_events=[event.model_dump_json() for event in engine.events[event_start:]],
                 combat_rolls=[roll.model_dump_json() for roll in engine.rolls[roll_start:]],
                 text=f"{owner['name']} finishes resting; their short-rest effects end.")
    return None

def encounter_snapshot(actor, *, effects_ended=False):
    """General CombatService continuation seam; reject unsupported timed state.

    Stored leaves are integers/strings. Conditions are JSON strings validated
    here, then reconstructed with their runtime model before the first turn.
    """
    from ..journey import require
    if effects_ended:
        from ..concentration import HELD
        # This is an explicit GM checkpoint, never inferred expiry or an AI
        # decision. Keep permanent conditions, wounds, temp HP and life state.
        # Returning to the unmodified maximum cannot grant current HP.
        actor = actor.model_copy(deep=True)
        actor.modifiers.clear()
        actor.concentration = None
        actor.transformed_size_category = None
        base = actor.maximum_hp_base if actor.maximum_hp_base is not None else actor.maximum_hp
        actor.current_hp = min(actor.current_hp, base)
        actor.maximum_hp = base
        actor.maximum_hp_base = None
        actor.maximum_hp_adjustments.clear()
        actor.conditions = {key: c for key, c in actor.conditions.items()
                            if c.expires_on in (None, 'UNTIL_REMOVED') and c.expires_turn_count is None
                            and c.condition_id != HELD}
    require(not actor.modifiers and actor.concentration is None
            and not actor.maximum_hp_adjustments and actor.transformed_size_category is None,
            'This creature has encounter effects that cannot continue yet. A GM may confirm they have ended '
            'and give a reason when resuming the journey; this does not heal or recover resources.')
    conditions = {}
    def supported(value):
        if value is None or type(value) in (str, int):
            return True
        if isinstance(value, dict):
            return all(type(k) is str and supported(v) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return all(supported(v) for v in value)
        return False
    for key, condition in actor.conditions.items():
        row = condition.model_dump(mode='json', exclude_none=True)
        require(condition.expires_on in (None, 'UNTIL_REMOVED', SHORT_REST_EXPIRY) and condition.expires_turn_count is None
                and supported(row),
                'This creature has a timed or unsupported condition. A GM may confirm timed effects have ended '
                'and give a reason when resuming the journey; this does not heal or recover resources.')
        conditions[key] = json.dumps(row, sort_keys=True)
    from .life_state import encounter_death_saves
    return {'current_hp': actor.current_hp, 'maximum_hp': actor.maximum_hp,
            'temporary_hp': actor.temporary_hp, 'active': int(actor.active),
            'life_state': actor.life_state or '', 'conditions': conditions,
            'death_saves': encounter_death_saves(actor)}


def restore_encounter(actor, encounter, *, merge_conditions=True):
    """Restore the same saved survivor for combat entry and an out-of-combat rest.

    Entry keeps new encounter setup conditions; a rest replaces the old fight's
    conditions with the journey's current snapshot, so already ended effects do
    not return on a later rest.
    """
    from ..gate2_runtime_models import ConditionInstance
    from ..journey import require
    require(actor.maximum_hp == encounter['maximum_hp'],
            'This creature’s maximum HP changed; resolve its encounter snapshot before continuing.')
    actor.current_hp = encounter['current_hp']
    actor.temporary_hp = encounter['temporary_hp']
    actor.active = bool(encounter['active'])
    actor.life_state = encounter['life_state'] or None
    if 'death_saves' in encounter:
        from .life_state import restore_encounter_death_saves
        restore_encounter_death_saves(actor, encounter['death_saves'])
    conditions = {key: ConditionInstance.model_validate(json.loads(row))
                  for key, row in encounter['conditions'].items()}
    if merge_conditions:
        actor.conditions.update(conditions)
    else:
        actor.conditions = conditions
    if not actor.active or actor.life_state in ('DYING', 'STABLE'):
        actor.action_available = actor.bonus_action_available = actor.reaction_available = False
        actor.movement_remaining_ft = 0


@hook('match_initialize')
def setup(engine):
    initialized = False
    for bundle in engine.typed_bundle_documents:
        snapshot = bundle.get('journey_setup')
        if snapshot is None:
            continue
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue  # preliminary/replay constructors may use another roster
        initialized = True
        encounter = snapshot.get('encounter_snapshot')
        if encounter is not None:
            restore_encounter(actor, encounter)
        if snapshot.get('incapacitated') and not (actor.current_hp <= 0 or any(
                c.condition_id in ('incapacitated', 'stunned', 'unconscious', 'paralyzed', 'petrified')
                for c in actor.conditions.values())):
            engine._apply_condition(actor, 'incapacitated', 'journey:condition_snapshot', actor.entity_id,
                                    expires_on='UNTIL_REMOVED', data={'label': 'Incapacitated before combat'})
        if snapshot.get('exhaustion'):
            from .forged_exhaustion import add, level
            delta = int(snapshot['exhaustion']) - level(actor)
            if delta > 0:
                add(engine, actor, delta, 'journey:condition_snapshot')
    # The persistence constructor uses Gate2 genesis before controller upgrade;
    # snapshots require its first-turn subscribers to observe restored state.
    return True if initialized else None
