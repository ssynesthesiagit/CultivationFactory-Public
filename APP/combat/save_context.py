"""Ephemeral save geometry and bonus proposals used by native and typed saves."""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class DamageSave:
    """The resolved save selecting this recipient's damage, never fight state.

    Shared by the typed executor and damage-response plug-ins such as Equipment.
    It can support any defense limited by save ability, outcome or area delivery.
    Unknown/legacy damage has no proposal; enclosing action geometry is not proof.
    """
    source_id: str
    actor_id: str
    target_id: str
    ability: str
    failed: bool
    area: bool
    action_name: str


_DAMAGE_SAVE = ContextVar("typed_damage_save", default=None)


@contextmanager
def damage_scope(ctx, subject):
    """Publish only this delivery's save; restore the parent on error or pause."""
    origin = ctx.origin_save or {}
    proposal = None
    if ctx.failed_save is not None and origin.get("ability"):
        from .ext import damage_delivery
        delivery = damage_delivery.frame(ctx.engine)
        actual_area = (delivery["identity"] == ctx.damage_source
                       and delivery["hazard"] == damage_delivery.AREA)
        proposal = DamageSave(ctx.damage_source, ctx.actor.entity_id, subject.entity_id,
                              str(origin["ability"]).upper(), bool(ctx.failed_save),
                              ctx.save_area is True or actual_area, ctx.action.display_name)
    token = _DAMAGE_SAVE.set((ctx.engine, proposal, ctx.save_damage_responses))
    try:
        yield
    finally:
        _DAMAGE_SAVE.reset(token)


def damage_save(engine, target_id, source_id, source_actor_id):
    """Pure exact-packet query; unrelated nested damage cannot borrow a save."""
    frame = _DAMAGE_SAVE.get()
    if frame is None or frame[0] is not engine:
        return None
    proposal = frame[1]
    if proposal is not None and (proposal.target_id, proposal.source_id, proposal.actor_id) == (
            target_id, source_id, source_actor_id):
        return proposal
    return None


def damage_response_state(engine, proposal, source_id):
    """A consumer's local budget/decline for this single recipient/save outcome.

    Shared across its split damage rows, never across recipients or saves.
    Equipment uses it to spend and roll once, and to carry only unused reduction.
    The caller owns the namespaced contents; no state survives the action.
    """
    frame = _DAMAGE_SAVE.get()
    if frame is None or frame[0] is not engine or frame[1] is not proposal:
        raise ValueError("No matching damage-save scope")
    return frame[2].setdefault(source_id, {})


def area_origin_records(ctx):
    """Validate optional source-owned multi-origin save geometry.

    None records mean the creature's physical origin. Other records must still
    be authorized by the action's existing public effect_origins provider.
    Legacy origin_ids/range_ft geometry is untouched.
    """
    geometry = ctx.save_geometry or {}
    if 'origin_records' not in geometry:
        return None
    from .action_geometry import origins
    records = geometry['origin_records']
    if not isinstance(records, list) or not records:
        raise ValueError('Area save geometry requires at least one origin record')
    legal = origins(ctx.engine, ctx.actor, ctx.action)
    # An origin destroyed or otherwise withdrawn during a reaction no longer
    # delivers this packet. Retain any other still-legal selected origin.
    return [record for record in records if record is None or record in legal]


def area_target_check(ctx, subject):
    """Recheck one recipient against every still-authorized selected origin."""
    from .action_geometry import activate
    from .typed_executor import area_targets
    records = area_origin_records(ctx)
    if records is None:
        return False
    aim = ctx.damage_cache.get('_checkpoint_aim')
    area = ctx.save_geometry.get('area') or ctx.typed.get('area') or {}
    for record in records:
        with activate(ctx.engine, ctx.actor, ctx.action.source_definition_id, record):
            if subject in area_targets(ctx.engine, ctx.actor, aim, area, typed=ctx.typed):
                return True
    return False


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
        records = area_origin_records(ctx)
        if records is not None:
            from .action_geometry import activate, volume
            for record in records:
                with activate(ctx.engine, ctx.actor, ctx.action.source_definition_id, record):
                    cells.extend(volume(ctx.engine, ctx.actor))
            kind = 'points' if cells else 'unknown'
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
        for key, value in parts.items():
            contributions[key] = max(contributions.get(key, 0), value) if key == 'cover' else contributions.get(key, 0) + value
    total = sum(contributions.values())
    # A source-bound bypass can remove an already supplied cover contribution.
    # It never invents spatial cover or alters unrelated save bonuses.
    cover = contributions.get('cover', 0)
    if cover > 0:
        replies = ext.run_strict('save_cover_reduction', engine, target, ability, source_id, cover)
        if any(type(value) is not int or value < 0 for value in replies):
            raise ValueError('save_cover_reduction requires nonnegative integer levels')
        if replies:
            levels = [0, 2, 5, 99]
            level = next((i for i, amount in enumerate(levels) if cover <= amount), 3)
            remaining = levels[max(0, level - sum(replies))]
            removed = max(0, cover - remaining)
            total -= removed
            contributions['cover'] = cover - removed
    return total, {key: value for key, value in sorted(contributions.items()) if value}
