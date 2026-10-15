"""Ordered line damage: destroyed obstructions open the same activation's path.

The owning typed row supplies its save, damage and object multiplier. Native
geometry and object defenses retain authority; no walls are ignored or removed
by a query. Automatic harmful recipients default to enemies. An explicit
area.explicit_harmful_recipients includes allied creatures along the same
ordered line, using the existing native printed-recipient contract.
"""
from . import effect, hook


@hook('save_cover_reduction')
def piercing_cover(engine, target, ability, source_id, cover):
    action = engine.action_catalog.get(source_id)
    typed = ((action.parameters or {}).get('typed') or {}) if action is not None else {}
    return 2 if ability == 'DEX' and cover <= 5 and any(
        e.get('type') == 'piercing_area' and e.get('ignore_partial_cover')
        for e in typed.get('effects') or []) else None


@effect('piercing_area')
def piercing_area(ctx, row):
    from copy import deepcopy
    from .. import typed_executor as te
    from ..object_geometry import target_cells
    from ..space import position
    from ..target_knowledge import can_see
    from .objects import deal, area_reaches
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    from ..action_geometry import point
    origin=point(engine,actor)
    aim = ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    if aim is None or aim == origin:
        return
    area = ctx.typed.get('area') or {}
    if area.get('shape') != 'line':
        raise ValueError('piercing_area requires a line')
    save = deepcopy(row['effects'][0])
    damage = next(e for e in save['on_fail'] if e['type'] == 'damage')
    all_creatures=(ctx.typed.get('area') or {}).get('explicit_harmful_recipients') in ('other_creatures','every_creature')
    known = [t for t in ctx.targets if (all_creatures or t.team_id != actor.team_id) and can_see(engine, actor, t)]
    kinds = [str(k).upper() for k in damage.get('damage_types') or []]
    if len(kinds) > 1:
        # Only perceived recipients inform the automatic preference. The line
        # can later damage a hidden creature without disclosing its defenses
        # to the choice made before the shot.
        from ..typed_reactions import damage_factor
        preferred = max(kinds, key=lambda k: (sum(damage_factor(engine,t,k,ctx.source,actor.entity_id) for t in known), -kinds.index(k)))
        choice = ask(engine, ctx.intent, checkpoint_id(engine, 'piercing_area_type', actor.entity_id), actor,
            'choice:needle.piercing_area_type', kinds, preferred=[preferred],
            labels={k:k.title() for k in kinds}, name=ctx.action.display_name,
            prompt=f'{ctx.action.display_name}: choose the damage type for this shot.')
        selected = choice[0] if choice else preferred
        for e in save['on_fail'] + save['on_success']:
            if e.get('damage_types'):
                e['damage_types'] = [selected]
    ctx.damage_cache['_area_targets'] = known
    # "spreads" here asks only for the mathematical shape, never for around-
    # corner propagation. Each recipient's current line of effect is tested
    # below, after the nearer objects have actually taken damage.
    shape = {**area, 'spreads': True}
    entries = []
    for creature in engine.state.actors.values():
        if creature.active and creature.entity_id!=actor.entity_id and (all_creatures or creature.team_id != actor.team_id):
            cells = [position(p) for p in engine._actor_volume(creature) if te.in_area(engine, origin, aim, position(p), shape)]
            if cells:
                entries.append((min(engine.grid.distance_ft(origin, p) for p in cells), 1, creature.entity_id, creature))
    for obj in engine.state.objects.values():
        if not obj.destroyed and obj.current_hp is not None and obj.ac is not None:
            cells = [p for p in target_cells(engine, obj) if te.in_area(engine, origin, aim, p, shape)]
            if cells:
                entries.append((min(engine.grid.distance_ft(origin, p) for p in cells), 0, obj.object_id, obj))
    ctx.damage_cache['_ordered_objects'] = True
    for _, kind, _, target in sorted(entries, key=lambda e: e[:3]):
        if kind == 0:
            if not area_reaches(engine, origin, aim, target, area):
                continue
            amount, damage_type = te._damage_roll(ctx, damage)
            deal(engine, actor, target, [(amount, damage_type)], ctx.source,
                 multiplier=object_multiplier(row,target))
        elif target.active and any(te.in_area(engine, origin, aim, position(p), area) for p in engine._actor_volume(target)):
            # A singleton Context bounds recipient selection, not save scope.
            # Keep the row's explicit area recipient: defenses must see the
            # selecting area save even while delivery proceeds nearest first.
            sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
            te.run_effects(sub, [save])


def object_multiplier(row,obj):
    """Pure ordered-area multiplier with explicit physical categories.

    Unset double_object_kinds keeps legacy object_multiplier. An opted-in list
    uses native unattended/classification facts; names never establish kind.
    Consumers are Spirit Bow lines and the existing piercing-area sources.
    """
    kinds=row.get('double_object_kinds')
    if kinds is None:return int(row.get('object_multiplier') or 1)
    if not isinstance(kinds,list) or set(kinds)-{'unattended','temporary_barrier','vehicle','structure','formation_anchor'}:
        raise ValueError('double_object_kinds requires supported explicit object categories')
    c=obj.component or {};kind=str(obj.object_kind).lower()
    matches={'unattended':bool(obj.unattended),'temporary_barrier':bool(c.get('temporary_barrier')),
        'vehicle':kind in ('vehicle','cart','rowboat') or c.get('kind')=='vehicle',
        'structure':bool(c.get('structure')),'formation_anchor':bool(c.get('formation_anchor')) or kind=='formation_anchor'}
    return 2 if any(matches[k] for k in kinds) else 1
