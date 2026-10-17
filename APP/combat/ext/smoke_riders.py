"""Smoke rider execution, using the owner's rules_text (riders lane 5).

Black-Lung Cloud adds a one-round choking trigger to the just-created veil.
Only hostile entry/start triggers its save, never
creation; its Poisoned/slow expires at the affected creature's next turn start.
The engine has no breathing physiology, so the nonbreather Advantage is retained
as a GM rider rather than inferred from Poison immunity or creature type.

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
    veil = next((z for z in reversed(zones.typed_zones(ctx.engine))
                 if z.owner_id == ctx.actor.entity_id and z.source_definition_id == ctx.source), None)
    if veil is None:
        ctx.rider('Black-Lung Cloud needs the Smoke Veil area.')
        return
    until = ctx.actor.turns_started + 1
    triggers = copy.deepcopy(eff['triggers'])
    for trigger in triggers:
        trigger['effects'] = [{'type': 'smoke_choke_save', 'expires_owner_turn': until, 'effects': trigger['effects']}]
    updated = copy.deepcopy(veil.trigger_profile)
    updated['triggers'] = [*updated.get('triggers', []), *triggers]
    updated['smoke_choking_until_owner_turn'] = until
    veil.trigger_profile = updated
    # Existing placed-effect update protocol: complete zone snapshot replays under the same ID.
    ctx.engine._append_event('ZONE_CREATED', ctx.source, actor_id=ctx.actor.entity_id,
                            payload={'zone': veil.model_dump(mode='json')})


@effect('smoke_choke_save')
def choke_save(ctx: Context, eff: dict[str, Any]) -> None:
    if ctx.actor.turns_started < int(eff['expires_owner_turn']):
        run_effects(ctx, copy.deepcopy(eff.get('effects') or []))


@hook('nominal_slot_boundary')
def nominal_choking(engine: Any, actor: Any, checkpoint: str) -> None:
    """Retire only the added choking trigger; the underlying veil stays."""
    if checkpoint != 'START_OF_TURN':
        return
    from .effect_durations import custom_turn_due
    for zone in zones.typed_zones(engine):
        until = zone.trigger_profile.get('smoke_choking_until_owner_turn')
        if zone.owner_id != actor.entity_id or until is None or not custom_turn_due(
                actor, until, zone.per_turn_triggered, 'smoke_choking', nominal=True):
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
