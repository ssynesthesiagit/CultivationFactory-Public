"""Astral Projection's source-owned action restrictions, dismissal and damage ending.

The printed Spirit Awakening CL7 rule permits perception, communication and
astral travel, not physical combat. The single-position engine cannot yet model
the unconscious body, tether, spiritual visibility or material-crossing route;
those remain explicit GM requirements pending the two-position lock seam.
"""
from typing import Any
from . import effect, hook, note

SOURCE = 'tianxia.path.spirit_awakening.feature.astral_projection'
INVISIBLE = 'condition:typed.invisible'
DISMISS = 'astral_projection_dismiss'
PERCEPTION = {f'tianxia.path.spirit_awakening.feature.{name}'
              for name in ('spiritual_sense', 'read_the_spirit', 'soul_gaze')}
SYSTEM_SETUP = 'system:combat.fight_setup'
# "Use your normal AC ... saving throws, and defenses" permits defenses of
# the projected creature itself, never a reaction that changes another creature.
SELF_DEFENSE_BLOCKS = {'hit_ac', 'save_rescue', 'damage_soak'}
SELF_DEFENSE_EFFECTS = {'ac_bonus', 'save_bonus', 'damage_reduction', 'resistance'}
SELF_DEFENSE_TRIGGERS = {'attacked', 'hit', 'missed', 'damaged', 'save'}


@hook('prefight_ai_allowed')
def prefight_ai_allowed(action: Any) -> bool | None:
    """Projection is for travel and perception; the player may still choose it."""
    if ((action.parameters or {}).get('typed') or {}).get('source') == SOURCE:
        return False
    return None


def projected_instances(engine: Any, actor: Any) -> list[Any]:
    """Recognize both new and saved projection invisibility by actual source ownership."""
    out = []
    for condition in actor.conditions.values():
        action = engine.action_catalog.get(condition.source_definition_id)
        source = ((action.parameters or {}).get('typed') or {}).get('source') if action else condition.source_definition_id
        if condition.condition_id == INVISIBLE and source == SOURCE and condition.source_actor_id == actor.entity_id:
            out.append(condition)
    return out


def end_projection(engine: Any, actor: Any, reason: str) -> None:
    for condition in projected_instances(engine, actor):
        actor.conditions.pop(condition.instance_id)
        engine._append_event('CONDITION_REMOVED', condition.source_definition_id, actor_id=actor.entity_id,
            target_ids=(actor.entity_id,), payload={'condition_id': INVISIBLE, 'instance_id': condition.instance_id})
    note(engine, SOURCE, actor, f'Astral Projection ends for {actor.display_name}: {reason}.')


@hook('compile_actions')
def dismissal(info: dict[str, Any]) -> list[Any] | None:
    if SOURCE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{DISMISS}",
        display_name='Dismiss Astral Projection (no action or resource cost)', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': DISMISS, 'effects': [{'type': DISMISS,
                             'evidence': 'Dismiss your projection without an action; return to your body.'}], 'numbers': info['numbers'],
                             'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0})]


@effect(DISMISS)
def dismiss(ctx: Any, effect: dict[str, Any]) -> None:
    if projected_instances(ctx.engine, ctx.actor):
        end_projection(ctx.engine, ctx.actor, 'you dismissed your spirit back to your body')


@hook('candidate_allowed')
def allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((action.parameters or {}).get('typed') or {}) if action else {}
    dismissing = any(e.get('type') == DISMISS for e in typed.get('effects') or [])
    active = bool(projected_instances(engine, actor))
    if dismissing:
        return active
    if not active:
        return None
    kind = str(getattr(candidate.kind, 'value', candidate.kind))
    if kind in ('MOVE', 'END_TURN', 'HOLD_POSITION', 'DECLINE_REACTION'):
        return None
    # Initiative setup is an ACTION-shaped bookkeeping choice. Its system source
    # marker, rather than its presentation label, distinguishes it from an action.
    if candidate.source_definition_id == SYSTEM_SETUP:
        return None
    if kind == 'REACTION':
        return None if _permitted_reaction(typed, getattr(action, 'target_kind', None)) else False
    return None if typed.get('source') in PERCEPTION else False


def _permitted_reaction(row: dict[str, Any], target_kind: str | None = None) -> bool:
    """Conservative allow-list of the printed normal defenses of one's spirit.

    Compiled reaction rows are dictionaries; actions pass their typed dictionary.
    Unknown blocks/effects and every nested non-defense remain refused by default.
    """
    if target_kind not in (None, 'SELF') or row.get('target_kind') not in (None, 'SELF'):
        return False
    if row.get('attack') or row.get('hostile') or row.get('kind') not in (None, *SELF_DEFENSE_TRIGGERS):
        return False
    effects = row.get('effects') or []
    if row.get('block') not in SELF_DEFENSE_BLOCKS and not (
            row.get('block') in (None, 'generic') and effects):
        return False
    if any(not isinstance(e, dict) or 'type' not in e for e in effects):
        return False
    pending = list(effects)
    while pending:
        effect_row = pending.pop()
        if isinstance(effect_row, list):
            pending.extend(effect_row)
            continue
        if not isinstance(effect_row, dict):
            continue
        if 'type' in effect_row:
            if effect_row['type'] not in SELF_DEFENSE_EFFECTS:
                return False
            if effect_row.get('hostile') or effect_row.get('applies_to') not in (None, 'self'):
                return False
        # Inspect all containers, including future effect-tree branches. A new
        # physical effect cannot become permitted just by nesting it differently.
        for value in effect_row.values():
            if isinstance(value, (dict, list)):
                pending.append(value)
    return True


@hook('reaction_allowed')
def physical_reactions(engine: Any, reactor: Any, other: Any) -> bool | None:
    # This hook has no row argument. Let the row-aware gate decide whether the
    # particular reaction is an attack or hostile/physical effect.
    return None


@hook('opportunity_allowed')
def physical_opportunity_attacks(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if projected_instances(engine, reactor) else None


@hook('row_allowed')
def physical_reaction_rows(engine: Any, reactor: Any, row: dict[str, Any]) -> bool | None:
    if not projected_instances(engine, reactor):
        return None
    return None if _permitted_reaction(row) else False


@hook('event', nested=True)
def damage_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    # Delayed damage can be committed inside turn/event hooks (Fate Deferred).
    # Use bounded nested delivery so the printed ending rule covers it too.
    if event_type != 'DAMAGE_COMMITTED' or int((kwargs.get('payload') or {}).get('reduced_to') or 0) <= 0:
        return
    for aid in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(aid)
        if actor and projected_instances(engine, actor):
            end_projection(engine, actor, 'you took damage')
