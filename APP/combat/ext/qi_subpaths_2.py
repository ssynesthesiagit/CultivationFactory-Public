"""Alchemy's nonbreathing save and shared chosen cloud observers.

choose_zone_viewers may follow any native zone creation. It records a selected
observer roster on that exact zone; only automatic owners narrow it to allies.
No ambient source/name inference or mutable global state is used.
"""
import copy
from dataclasses import replace
from . import effect, hook

EXPLOSIVE_PILL = 'tianxia.subpath.qi.alchemical_cultivator.feature.explosive_pill'


@hook('compile_action')
def smoke_utility_aims(action, info):
    """Retain Smoke's legal utility placements in automatic decision menus.

    Smoke is not an empty damaging blast: it deliberately lays terrain, even
    where no enemy stands. Use the existing AI utility opt-in rather than
    replacing the action, changing candidate identities or relaxing another
    ability's recipient/knowledge restrictions.
    """
    if EXPLOSIVE_PILL not in info.get('owned_ids', ()):
        return None
    typed = (action.parameters or {}).get('typed') or {}
    if (typed.get('source') != EXPLOSIVE_PILL
            or typed.get('option_label') != 'Smoke Pill'):
        return None
    return action.model_copy(update={'parameters': {
        **action.parameters, 'ai_allow_empty_area': True}})


@effect('alchemical_venom_save')
def venom_save(ctx, row):
    from ..typed_executor import run_effects
    run_effects(replace(ctx, typed={**ctx.typed, 'alchemical_nonbreather_save': True}), row['effects'])


@hook('save')
def venom_nonbreather(ctx, subject, ability, named):
    from ..physiology import trait
    if ctx.typed.get('alchemical_nonbreather_save') and trait(subject, 'breath_dependent') is False:
        return {'modes': ['ADVANTAGE']}
    return None


def viewer_choices(ctx):
    from .. import zones
    from ..target_knowledge import located
    from ..targeting import line_of_effect
    from ..relations import relation
    from .needle import ask, checkpoint_id, CHOICE
    automatic = zones.uses_default_shape(ctx.engine, ctx.actor)
    pool = [s for s in ctx.engine.state.actors.values() if s.active and s is not ctx.actor
            and located(ctx.engine, ctx.actor, s) and line_of_effect(ctx.engine, ctx.actor, target=s)
            and (not automatic or relation(ctx.engine, ctx.actor, s) == 'ALLY')]
    allies = [s.entity_id for s in pool if relation(ctx.engine, ctx.actor, s) == 'ALLY']
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'cloud_viewers', ctx.source),
        ctx.actor, CHOICE+'cloud_viewers', [s.entity_id for s in pool],
        labels={s.entity_id:s.display_name for s in pool}, minimum=0, maximum=len(pool),
        allow_decline=True, preferred=allies, default_count=len(allies),
        prompt=f'{ctx.action.display_name}: choose creatures who can see through your smoke as Lightly Obscured for one minute while you maintain Concentration. You also gain this benefit.') if pool else []
    return [ctx.actor.entity_id, *picked]


@hook('before_target_reactions')
def choose_before_smoke(ctx):
    if any(r.get('type') == 'choose_zone_viewers' for r in ctx.typed.get('effects') or []):
        ctx.damage_cache['chosen_cloud_viewers'] = viewer_choices(ctx)


@effect('choose_zone_viewers')
def choose_viewers(ctx, row):
    from .. import zones
    zone = next((z for z in reversed(zones.typed_zones(ctx.engine))
                 if z.owner_id == ctx.actor.entity_id and z.source_definition_id == ctx.source), None)
    if zone is None:
        raise ValueError('Choose cloud observers requires a zone created by this activation')
    selected = ctx.damage_cache.get('chosen_cloud_viewers')
    if selected is None:
        raise ValueError('Choose cloud observers requires the pre-creation choice')
    profile = copy.deepcopy(zone.trigger_profile)
    profile['lightly_obscured_viewer_ids'] = list(selected)
    zone.trigger_profile = profile
    ctx.engine._append_event('ZONE_CREATED', ctx.source, actor_id=ctx.actor.entity_id,
                            payload={'zone':zone.model_dump(mode='json')})
