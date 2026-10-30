"""Sound-qualified checks and live Ten-Thousand Echoes Field benefits.

Uses the public hazard check and action/zone hooks. Sound detection must be
named by the actual check; visual Hide is never silently treated as hearing.
Zone membership is queried live, so exiting or ending a Field removes its
benefits without deleting another caster's conditions. No owner, no change.
"""
from copy import deepcopy
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id

FIELD = 'TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD'
MUFFLE = 'TAL_SOUND_MUFFLE_FOOTFALL'
QUIET = 'condition:typed.sound_quiet_footfall'
CONFUSED = 'condition:typed.sound_echo_confusion'


@hook('compile_action')
def qualify_sound(action: Any, info: dict) -> Any:
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('source')
    if source not in (FIELD, MUFFLE):
        return None
    typed = deepcopy(typed)
    if source == MUFFLE:
        for row in typed.get('effects', []):
            if row.get('type') == 'choose_willing':
                row['effects'] = [{'type': 'sound_quiet_footfall', 'applies_to': 'target'}]
    else:
        typed['effects'] = [row for row in typed.get('effects', []) if row.get('type') == 'zone']
        for row in [*typed['effects'], typed.get('zone_spec') or {}]:
            for trigger in row.get('triggers', []):
                for save in trigger.get('effects', []):
                    if save.get('type') == 'save':
                        save['on_fail'] = [{'type': 'sound_echo_failure', 'applies_to': 'target'}]
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})


@effect('sound_quiet_footfall')
def quiet_footfall(ctx: Any, row: dict) -> None:
    if ctx.target is None:
        return
    from ..typed_executor import effect_expiry
    ctx.engine._apply_condition(ctx.target, QUIET, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.target, condition=True),
        data={'label': 'Muffle Footfall: Advantage on Stealth to avoid sound detection for 10 minutes'})


def fields(engine: Any, actor: Any, *, allied: bool) -> list:
    from .. import zones
    from ..spatial_areas import zone_contains
    from ..zone_sources import of
    from ..relations import relation, ENEMY, ALLY
    return [z for z in zones.typed_zones(engine)
            if (of(z) or {}).get('mechanic_id') == FIELD and zone_contains(engine, actor, z)
            and (owner := engine.state.actors.get(z.owner_id)) is not None and owner.active
            and relation(engine, owner, actor) == (ALLY if allied else ENEMY)]


@hook('ability_check_hazards')
def sound_check(engine: Any, actor: Any, ability: str, skill: str, hazards: tuple) -> str | None:
    if not {'sound_detection', 'hearing'}.intersection(hazards):
        return None
    if ability.upper() == 'DEX' and skill == 'Stealth':
        if any(c.condition_id == QUIET for c in actor.conditions.values()) or fields(engine, actor, allied=True):
            return 'ADVANTAGE'
    if ability.upper() == 'WIS' and skill == 'Perception' and fields(engine, actor, allied=False):
        return 'DISADVANTAGE'
    return None


@effect('sound_echo_failure')
def echo_failure(ctx: Any, row: dict) -> None:
    target = ctx.target
    if target is None:
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'echo_failure', ctx.source, target.entity_id),
        target, 'choice:needle.echo_failure', ['reaction', 'confusion'], name='Ten-Thousand Echoes Field',
        target_id=target.entity_id,
        labels={'reaction': 'Lose your Reaction until your next turn starts',
                'confusion': 'Spaces more than 30 feet away are lightly obscured to you until your next turn starts'},
        preferred=['reaction'],
        prompt=f'Ten-Thousand Echoes Field: {target.display_name} failed its start-of-turn Wisdom save. Choose Reaction loss or distant echo confusion until its next turn starts.')
    from .effect_durations import token
    expiry = token('start', target.entity_id, target.turns_started + 1)
    if chosen and chosen[0] == 'reaction':
        # Native condition dispatch owns Reaction suppression, immunity and
        # condition reactions; a raw receipt alone leaves the available flag set.
        from ..typed_executor import run_effects
        run_effects(ctx, [{'type': 'condition', 'condition': 'reaction_denied', 'applies_to': 'target',
                          'expires_on': expiry,
                          'condition_label': 'Ten-Thousand Echoes Field: this creature cannot take Reactions until the start of its next turn'}])
    elif chosen:
        ctx.engine._apply_condition(target, CONFUSED, ctx.source, ctx.actor.entity_id, expires_on=expiry,
            data={'label': 'Ten-Thousand Echoes Field: spaces beyond 30 feet are lightly obscured until your next turn starts'})


@hook('ability_check_hazard_mode')
def echo_visual_check(engine: Any, actor: Any, ability: str, skill: str, opponent: Any, hazards: tuple) -> str | None:
    if opponent is None or skill != 'Perception' or 'visual_concealment' not in hazards:
        return None
    if any(c.condition_id == CONFUSED for c in actor.conditions.values()) and engine._distance_actor_to_actor(actor, opponent) > 30:
        return 'DISADVANTAGE'
    return None


@hook('search_hazards')
def actual_search_sense(engine: Any, actor: Any, target: Any, source: str) -> list | None:
    """An actual native Search names its sensory method before drawing dice."""
    confused = any(c.condition_id == CONFUSED for c in actor.conditions.values())
    hostile_field = bool(fields(engine, actor, allied=False))
    if not confused and not hostile_field:
        return None
    from ..typed_executor import condition_rules
    rules = list(condition_rules(actor))
    options = []
    if not any(c.condition_id == 'condition:typed.blinded' for c in actor.conditions.values()):
        options.append('sight')
    if not any(row.get('cant_hear') for row in rules):
        options.append('hearing')
    selected = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'echo_search_sense', source, target.entity_id),
        actor, 'choice:needle.echo_search_sense', options, name='Ten-Thousand Echoes Field: Search',
        preferred=['sight'] if hostile_field else ['hearing'],
        labels={'sight': 'Search by sight: distant echo confusion may hinder this check',
                'hearing': 'Search by hearing: the hostile Echoes Field hinders this check'},
        prompt=f'Ten-Thousand Echoes Field: {actor.display_name} uses Search for a concealed creature. Choose sight or hearing for this Perception check; only the matching sensory penalty applies.')
    return [{'sight': 'visual_concealment', 'hearing': 'hearing'}[selected[0]]] if selected else []


@hook('choice_reactors')
def field_choosers(engine: Any) -> tuple:
    # Start-of-turn saves may resolve while another controller advances initiative.
    return tuple(a.entity_id for a in engine.state.actors.values() if fields(engine, a, allied=False))


@hook('resolution_final')
def echo_step(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    typed = (action.parameters or {}).get('typed') or {}
    # Casting the Field is itself a Sound talent; its zone is live here.
    if typed.get('sphere') != 'tianxia.sphere.sound' or not fields(engine, actor, allied=True):
        return
    stamp = f'{engine.state.round_number}:{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}'
    if actor.turn_flags.get('sound_echo_step') == stamp:
        return
    from .. import granted_movement
    paths = granted_movement.candidates(engine, actor, 5, intent, FIELD)
    picked = ask(engine, intent, checkpoint_id(engine, 'echo_step', action.source_definition_id, actor.entity_id),
        actor, 'choice:needle.echo_step', list(paths), name='Ten-Thousand Echoes Field', allow_decline=True,
        labels={k: f'Move to {c.destination.x},{c.destination.y} without opportunity attacks' for k, c in paths.items()},
        prompt=f'Ten-Thousand Echoes Field: after {actor.display_name} uses {action.display_name}, choose an optional 5-foot step without spending movement or provoking opportunity attacks.')
    if picked:
        actor.turn_flags['sound_echo_step'] = stamp
        engine._resolve_movement(actor, paths[picked[0]], intent, granted_ft=5,
            ignore_oa_from=tuple(engine.state.actors))
