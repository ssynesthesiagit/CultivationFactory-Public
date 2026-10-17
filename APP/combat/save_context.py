"""Ephemeral save geometry and bonus proposals used by native and typed saves."""
from copy import deepcopy


def spatial_context(ctx):
    """Freeze the actual typed origin, never an unrelated active intent's aim."""
    from .action_geometry import point, record_for
    area = deepcopy(ctx.typed.get('area') or {})
    aim = ctx.damage_cache.get('_checkpoint_aim')
    secondary = ctx.save_geometry
    origin = None
    kind = 'unknown'
    cells = []
    if secondary is not None:
        # A secondary route has its own origin; never fall back to the caster.
        ids = secondary.get('origin_ids') or []
        for who in ids:
            actor = ctx.engine.state.actors.get(who)
            if actor is not None:
                cells.extend(ctx.engine._actor_volume(actor))
        if len(ids) == 1 and ids[0] in ctx.engine.state.actors:
            origin = ctx.engine.state.actors[ids[0]].position
            kind = 'actor'
        elif cells:
            kind = 'actors'
        area = deepcopy(secondary.get('area') or {})
    elif area.get('size_ft'):
        origin = point(ctx.engine, ctx.actor) if area.get('shape') in ('line', 'cone') else (aim or point(ctx.engine, ctx.actor))
        kind = 'point'
        cells = [(origin.x, origin.y, origin.z)]
    else:
        origin = point(ctx.engine, ctx.actor)
        kind = 'point' if record_for(ctx.engine, ctx.actor, ctx.source) else 'actor'
        cells = [(origin.x, origin.y, origin.z)] if kind == 'point' else list(ctx.engine._actor_volume(ctx.actor))
    return {'effect_origin': origin.model_dump(mode='json') if origin else None,
            'effect_origin_kind': kind, 'effect_origin_cells': [list(cell) for cell in sorted(set(cells))],
            'area': area or None, 'save_geometry': deepcopy(secondary)}


def bonus_details(engine, target, ability, dc, source_id, intent):
    """Validate one pure proposal per provider; its amount and event metadata agree."""
    from . import ext
    total, contributions = 0, {}
    for proposal in ext.run_strict('save_bonus_details', engine, target, ability, dc, source_id, intent):
        if (not isinstance(proposal, dict) or set(proposal) != {'bonus', 'contributions'}
                or type(proposal['bonus']) is not int or not isinstance(proposal['contributions'], dict)):
            raise ValueError('save_bonus_details requires integer bonus and named integer contributions')
        parts = proposal['contributions']
        if any(not isinstance(key, str) or not key or type(value) is not int for key, value in parts.items()) or sum(parts.values()) != proposal['bonus']:
            raise ValueError('save_bonus_details contributions must sum to the proposed bonus')
        total += proposal['bonus']
        for key, value in parts.items():
            contributions[key] = contributions.get(key, 0) + value
    return total, {key: value for key, value in sorted(contributions.items()) if value}
