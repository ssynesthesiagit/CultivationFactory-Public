"""Smoke rider execution, using the owner's rules_text (riders lane 5).

Black-Lung Cloud adds a one-round choking trigger to the just-created veil.
Only hostile entry/start triggers its save, never
creation; its Poisoned/slow expires at the affected creature's next turn start.
Newly compiled choking rows request Advantage for creatures whose shared printed
physiology says they do not breathe. Legacy saved rows keep their previous modes.

Cinder Without Flame tests membership in the caster's own veil before the save
that prevents healing. Incense Calm targets oneself or an ally in one's own veil;
Censer Court offers an optional second target through the existing choice API
only while the caster is inside their Smoke Domain. A Smoke Domain counts as
smoke for these membership checks. No lock-file changes or actor substitutions.
"""

import copy
from dataclasses import replace
from typing import Any

from . import effect, hook
from .. import zones
from ..typed_executor import Context, run_effects

VEIL = 'SMOKE_BASE_SMOKE_VEIL'
DOMAIN = 'TAL_SMOKE_SMOKE_DOMAIN_COURT_OF_HIDDEN_WITNESSES'
CALM = 'TAL_SMOKE_INCENSE_CALM'
CENSER = 'TAL_SMOKE_CENSER_COURT_METHOD'
WITNESS = 'TAL_SMOKE_SOOT_MARKED_WITNESS'


def inside(engine: Any, actor: Any, owner_id: str, *, domain: bool = False) -> bool:
    sources = (DOMAIN,) if domain else (VEIL, DOMAIN)
    return any(z.owner_id == owner_id and any(s in z.source_definition_id for s in sources)
               and zones._inside(engine, actor, z) for z in zones.typed_zones(engine))


@effect('smoke_if_in_veil')
def in_veil(ctx: Context, eff: dict[str, Any]) -> None:
    if ctx.target is not None and inside(ctx.engine, ctx.target, ctx.actor.entity_id):
        run_effects(ctx, copy.deepcopy(eff.get('effects') or []))


@effect('smoke_choking')
def choking(ctx: Context, eff: dict[str, Any]) -> None:
    veil = ctx.damage_cache.get('smoke_moved_veil') or next((z for z in reversed(zones.typed_zones(ctx.engine))
                 if z.owner_id == ctx.actor.entity_id and z.source_definition_id == ctx.source), None)
    if veil is None:
        ctx.rider('Black-Lung Cloud needs the Smoke Veil area.')
        return
    until = ctx.actor.turns_started + 1
    triggers = copy.deepcopy(eff['triggers'])
    for trigger in triggers:
        trigger['effects'] = [{'type': 'smoke_choke_save', 'expires_owner_turn': until, 'effects': trigger['effects'], 'nonbreather_advantage': bool(eff.get('nonbreather_advantage'))}]
    updated = copy.deepcopy(veil.trigger_profile)
    updated['triggers'] = [*[t for t in updated.get('triggers', []) if t.get('id') != 'smoke_choking'], *triggers]
    updated['smoke_choking_until_owner_turn'] = until
    if eff.get('nonbreather_advantage'):
        updated['smoke_choking_v2'] = True
    veil.trigger_profile = updated
    # Existing placed-effect update protocol: complete zone snapshot replays under the same ID.
    ctx.engine._append_event('ZONE_CREATED', ctx.source, actor_id=ctx.actor.entity_id,
                            payload={'zone': veil.model_dump(mode='json')})


@effect('smoke_choke_save')
def choke_save(ctx: Context, eff: dict[str, Any]) -> None:
    if ctx.actor.turns_started < int(eff['expires_owner_turn']):
        inner = replace(ctx, typed={**ctx.typed, 'smoke_nonbreather_advantage': bool(eff.get('nonbreather_advantage'))})
        run_effects(inner, copy.deepcopy(eff.get('effects') or []))


@hook('save')
def nonbreather_save(ctx: Context, subject: Any, ability: str, named: Any) -> dict | None:
    from ..physiology import trait
    if ctx.typed.get('smoke_nonbreather_advantage') and trait(subject, 'breath_dependent') is False:
        return {'modes': ['ADVANTAGE']}
    return None


@hook('turn_start')
def actual_choking(engine: Any, actor: Any) -> None:
    nominal_choking(engine, actor, 'START_OF_TURN', nominal=False)


@hook('nominal_slot_boundary')
def nominal_choking(engine: Any, actor: Any, checkpoint: str, *, nominal: bool = True) -> None:
    """Retire only the added choking trigger; the underlying veil stays."""
    if checkpoint != 'START_OF_TURN':
        return
    from .effect_durations import custom_turn_due
    for zone in zones.typed_zones(engine):
        until = zone.trigger_profile.get('smoke_choking_until_owner_turn')
        if not nominal and not zone.trigger_profile.get('smoke_choking_v2'):
            continue
        if zone.owner_id != actor.entity_id or until is None or not custom_turn_due(
                actor, until, zone.per_turn_triggered, 'smoke_choking', nominal=nominal):
            continue
        profile = copy.deepcopy(zone.trigger_profile)
        profile.pop('smoke_choking_until_owner_turn', None)
        for trigger in profile.get('triggers', []):
            trigger['effects'] = [e for e in trigger.get('effects', []) if e.get('type') != 'smoke_choke_save']
        zone.trigger_profile = profile
        engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=actor.entity_id,
                             payload={'zone': zone.model_dump(mode='json')})


@effect('smoke_calm')
def calm(ctx: Context, eff: dict[str, Any]) -> None:
    target = ctx.target or ctx.actor
    targets = [target]
    if ctx.action.parameters.get('smoke_censer') and inside(ctx.engine, ctx.actor, ctx.actor.entity_id, domain=True):
        from .needle import ask, checkpoint_id

        options = [a.entity_id for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id
                   and a is not target and inside(ctx.engine, a, ctx.actor.entity_id)]
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'incense_calm', ctx.source), ctx.actor,
                     'choice:needle.incense_calm', options, minimum=0, maximum=1, allow_decline=True,
                     automatic=False, default='decline', target_id=target.entity_id,
                     name='Censer Court Method', feature_id=CENSER,
                     prompt=f'Censer Court Method: {ctx.actor.display_name} uses Incense Calm on {target.display_name}; choose an optional second target.',
                     labels={a.entity_id: a.display_name for a in ctx.engine.state.actors.values()})
        targets.extend(ctx.engine.state.actors[aid] for aid in chosen if aid in options)
    for subject in targets:
        if inside(ctx.engine, subject, ctx.actor.entity_id):
            run_effects(replace(ctx, target=subject, targets=[subject]), copy.deepcopy(eff.get('effects') or []))


@hook('compile_actions')
def censer_calm(info: dict[str, Any]) -> list[Any] | None:
    result = []
    for action in info['actions']:
        if ((action.parameters or {}).get('typed') or {}).get('source') == WITNESS:
            # The printed target is any marked creature. Keep the base ally
            # family and add the hostile family, sharing the same typed effect
            # and caster-owned payment/target gates; no duplicate execution.
            result.append(action.model_copy(update={
                'source_definition_id': action.source_definition_id + '#hostile',
                'target_kind': 'HOSTILE_ENTITY'}))
            continue
        if ((action.parameters or {}).get('typed') or {}).get('source') != CALM:
            continue
        result.append(action.model_copy(update={
            'source_definition_id': action.source_definition_id + '#ally', 'display_name': 'Incense Calm (ally)',
            'target_kind': 'ALLY_OR_SELF', 'range_ft': None}))
        if CENSER in info['owned_ids']:
            result.append(action.model_copy(update={
                'source_definition_id': action.source_definition_id + '#censer',
                'display_name': 'Incense Calm (Censer Court Method)', 'target_kind': 'ALLY_OR_SELF', 'range_ft': None,
                'parameters': {**action.parameters, 'smoke_censer': True}}))
    return result or None


@hook('candidate_allowed')
def calm_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('source') != CALM:
        return None
    if action.parameters.get('smoke_censer') and not inside(engine, actor, actor.entity_id, domain=True):
        return False
    subject = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else actor
    return subject is not None and subject.team_id == actor.team_id and inside(engine, subject, actor.entity_id)


@effect('smoke_move_choking')
def move_choking(ctx: Context, eff: dict[str, Any]) -> None:
    """Move the chosen nearest veil with the shared mover, then refresh choking."""
    from .tabik_dark import move_zone
    from .zone_mover import areas
    aim = ctx.intent.destination
    candidates = areas(ctx.engine, ctx.actor, VEIL)
    if aim is None or not candidates:
        return
    veil = min(candidates, key=lambda z: (ctx.engine.grid.distance_ft(z.center, aim), z.zone_id))
    move_zone(ctx, eff['move'])
    if veil.center == aim:
        ctx.damage_cache['smoke_moved_veil'] = veil
        choking(ctx, eff['choking'])


@hook('compile_actions')
def choking_move(info: dict[str, Any]) -> list[Any] | None:
    """Separate optional 1 CP movement button; an ordinary move spends no CP."""
    source = 'TAL_SMOKE_BLACK_LUNG_CLOUD'
    if source not in info['owned_ids'] or VEIL not in info['owned_ids']:
        return None
    from .zone_mover import mover_buttons
    record = info['mechanics'][source]
    row = copy.deepcopy(record['modifier']['effects'][0])
    if not row.get('nonbreather_advantage'):
        return None
    # Same public primary-CP binding as ordinary compiler actions. Other
    # creation augments never add their prices to this movement choice.
    from ..factory_compiler import RESOURCE_IDS
    costs = ((RESOURCE_IDS[info['primary']], int(record['modifier']['extra_cp'])),)
    base = next(a for a in mover_buttons(info) or [] if a.parameters.get('zone_move_technique') == VEIL)
    params = copy.deepcopy(base.parameters)
    move = params['typed']['effects'][0]
    params['typed']['effects'] = [{'type': 'smoke_move_choking', 'move': move, 'choking': row}]
    from ..decision_text import costs_text
    params['description'] = (
        f'Bonus Action and {costs_text(costs)}: move your Smoke Veil up to 10 feet '
        'and make it choking until your next turn starts. Hostile creatures make a '
        'Constitution saving throw on first entry each turn or when their turn starts. '
        'They are Poisoned on a failure or have their Speed reduced by 10 feet on a success; '
        "either result lasts until that creature's next turn starts. "
        'Creatures that do not breathe have Advantage on the save.')
    return [base.model_copy(update={'source_definition_id': base.source_definition_id + '#choking',
        'display_name': 'Smoke Veil: move and choke (1 CP)', 'costs': costs, 'parameters': params})]
