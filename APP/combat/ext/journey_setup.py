"""Generic journey-to-combat condition binding.

Consumers: CombatService.journey_start_combat and native match_initialize. Explicit
integer/string journey_setup snapshots preserve encounter health, life state and
permanent conditions in genesis and cold replay. Turn-bound conditions, modifiers
and altered maximum HP cannot safely cross encounter clocks: resume
requires explicit GM adjudication that those effects have ended. An active
Concentration crosses only when its owning plug-in answers the documented
journey_continued_concentration hook with "carry" and persists its own live
state (Harvest Cultivator's fields and Seeds). A condition marked
``journey_transient`` in its data is bookkeeping its owner rebuilds for the next
encounter (the hidden concentration deadline) and is not carried or rejected.
The terminal
fight remains immutable, and the journey retains the full pre-resolution record.
No snapshot means no edits or events. Travel effects
are deliberately absent from this transfer: they end at combat entry.
"""
from . import hook
import json


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
    # A source-owned active Concentration may cross a short encounter break when
    # its owning plug-in answers the documented journey_continued_concentration
    # hook with "carry" and persists its own live state. With no subscriber (or
    # one that answers None) an active Concentration still requires the explicit
    # GM checkpoint, exactly as before.
    concentration_carried = actor.concentration is None
    if actor.concentration is not None:
        from . import run_strict
        replies = run_strict('journey_continued_concentration', actor.concentration)
        for reply in replies:
            if reply != 'carry':
                raise ValueError('journey_continued_concentration must return None or "carry"')
        concentration_carried = bool(replies)
    require(not actor.modifiers and not actor.maximum_hp_adjustments
            and actor.transformed_size_category is None and concentration_carried,
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
        if condition.data.get('journey_transient'):
            # Presentation/bookkeeping state an owning plug-in rebuilds for the
            # next encounter (combat/ext/concentration_duration's hidden deadline).
            # It is not a printed effect and must not force a GM checkpoint.
            continue
        row = condition.model_dump(mode='json', exclude_none=True)
        require(condition.expires_on in (None, 'UNTIL_REMOVED') and condition.expires_turn_count is None
                and supported(row),
                'This creature has a timed or unsupported condition. A GM may confirm timed effects have ended '
                'and give a reason when resuming the journey; this does not heal or recover resources.')
        conditions[key] = json.dumps(row, sort_keys=True)
    from .life_state import encounter_death_saves
    return {'current_hp': actor.current_hp, 'maximum_hp': actor.maximum_hp,
            'temporary_hp': actor.temporary_hp, 'active': int(actor.active),
            'life_state': actor.life_state or '', 'conditions': conditions,
            'death_saves': encounter_death_saves(actor)}


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
            # Keep new encounter's sourced setup conditions as well as the
            # survivor's persistent conditions; do not erase other providers.
            actor.conditions.update({key: ConditionInstance.model_validate(json.loads(row))
                                     for key, row in encounter['conditions'].items()})
            if not actor.active or actor.life_state in ('DYING', 'STABLE'):
                actor.action_available = actor.bonus_action_available = actor.reaction_available = False
                actor.movement_remaining_ft = 0
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
