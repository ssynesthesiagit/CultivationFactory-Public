"""Set Foundation's independent legal spaces and explicit safe designation.

Uses native exact zone cells, support, sight, choice checkpoints and replay.
The same existing Earth Response consumer handles willing ten-foot crossings.
"""
from copy import deepcopy
from . import hook, effect
from . import needle

SOURCE = 'EARTH_BASE_SET_FOUNDATION'
SAFE = 'earth_designated_safe'


def count(cl):
    return 2 + int(cl >= 5) + int(cl >= 11) + int(cl >= 17)


@hook('compile_action')
def spaces_action(action, info):
    parameters = action.parameters or {}
    typed = parameters.get('typed') or {}
    if typed.get('source') != SOURCE or SOURCE not in info['owned_ids']:
        return None
    typed = deepcopy(typed)
    typed['effects'] = [{'type': 'earth_foundation_spaces', 'spec': typed.pop('zone_spec', {})}]
    paths = (info['owner_sheet'].get('path_and_subpath') or {}).get('path_record_ids') or []
    typed['earth_body_contact'] = int('tianxia.path.body_refining' in paths)
    return action.model_copy(update={'target_kind': 'SELF', 'radius_ft': None,
        'parameters': {**parameters, 'typed': typed, 'inert': False}})


def legal_spaces(ctx):
    from ..gate2_runtime_models import Position
    from .surface_areas import supported_at
    from ..senses import perceives_cell
    from .. import targeting
    from .surface_contact import connected_contact
    engine, actor = ctx.engine, ctx.actor
    result = {}
    heights = {0, actor.position.z}
    heights.update(r.walk_ft // engine.grid.square_size_ft for r in engine.grid.roof_surfaces)
    for z in sorted(heights):
        for x in range(engine.grid.width):
            for y in range(engine.grid.height):
                p = Position(x=x, y=y, z=z)
                if (engine._distance_actor_to_cell(actor, p) > 60 or not supported_at(engine, p)
                        or not perceives_cell(engine, actor, p) or not targeting.line_of_effect(engine, actor, destination=p)):
                    continue
                from .physical_source_facts import projected
                if ctx.typed.get('earth_body_contact') and not projected(engine, actor.entity_id, SOURCE):
                    probe = actor.model_copy(update={'entity_id': 'probe:foundation', 'position': p, 'size_category': 'Medium', 'conditions': {}})
                    if not connected_contact(engine, actor, probe):
                        continue
                result[needle.cell_id(p)] = p
    return result


@effect('earth_foundation_spaces', harmful=False)
def create(ctx, row):
    from .. import zones
    cells = legal_spaces(ctx)
    anchors = {key: {'kind': 'fixed', 'x': p.x, 'y': p.y, 'z': p.z} for key,p in cells.items()}
    labels = {key: f'Ground Foundation at ({p.x}, {p.y}), {p.z * 5} feet high' for key,p in cells.items()}
    from .glass_surfaces import choices as actual_surfaces
    from .surface_identities import position as surface_position
    for identity, surface in actual_surfaces(ctx.engine,ctx.actor).items():
        if surface['kind'] == 'ground': continue
        if surface['kind'] == 'object':
            obj = ctx.engine.state.objects[surface['object_id']]
            if (obj.component or {}).get('material') not in ('stone','earth','clay','sand','crystal'):
                continue
        record = {'kind': 'actor' if surface['kind'] == 'body' else surface['kind'],
                  'actor_id': ctx.actor.entity_id, **{k:v for k,v in surface.items() if k in ('item_key','object_id')}}
        point = surface_position(ctx.engine,record)
        if point is None: continue
        key = identity + ':' + needle.cell_id(point)
        cells[key] = point; anchors[key] = record
        labels[key] = 'Foundation on ' + surface['label']
    from .. import target_knowledge
    known = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id != ctx.actor.team_id
             and target_knowledge.located(ctx.engine,ctx.actor,a)]
    preferred = sorted(cells, key=lambda k:(min((ctx.engine.grid.distance_ft(cells[k],a.position) for a in known),default=0),k))
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'foundation_spaces', ctx.source),
        ctx.actor, 'choice:needle.foundation_spaces', list(cells), minimum=0,
        maximum=min(count(int(ctx.numbers.get('cl') or 1)), len(cells)), allow_decline=True,
        preferred=preferred[:count(int(ctx.numbers.get('cl') or 1))], default='all',
        labels=labels,
        prompt='Set Foundation: choose up to your limit of visible legal five-foot ground, body or surface spaces within 60 feet. They may be separate. Body and item spaces follow their actual surface. An Action, no Cultivation Point cost, one minute, no Concentration.',
        name='Set Foundation')
    if not chosen:
        return
    spec = deepcopy(row.get('spec') or {})
    spec.update(cells=[cells[key] for key in chosen], name='Foundation Spaces', shape='special', size_ft=5,
                duration={'kind': 'minutes', 'amount': 1, 'concentration': False})
    spec.setdefault('move_through', {'min_ft': 10, 'inclusive': True, 'who': 'any',
        'effects': [{'type': 'earth_foundation_mark'}]})
    ctx.damage_cache['foundation_cell_anchors'] = [anchors[key] for key in chosen]
    zones.create(ctx, spec)


@hook('zone_created')
def designate(ctx, zone):
    if ctx.typed.get('source') != SOURCE:
        return None
    from .. import target_knowledge
    known = [a for a in ctx.engine.state.actors.values() if a.active
             and (a.entity_id == ctx.actor.entity_id or target_knowledge.located(ctx.engine, ctx.actor, a))]
    options = [a.entity_id for a in known]
    safe_preferred = [a.entity_id for a in known if a.team_id == ctx.actor.team_id]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'foundation_safe', ctx.source),
        ctx.actor, 'choice:needle.foundation_safe', options, minimum=0, maximum=max(1, len(options)), allow_decline=True,
        preferred=safe_preferred, automatic_options=safe_preferred, default='all',
        labels={a.entity_id: f'{a.display_name}: safe from your Foundation crossing mark' for a in known},
        prompt='Set Foundation: designate safe creatures for these spaces for one minute. Creatures you do not designate may gain your Burden Mark after willingly crossing ten feet in one turn. You may designate nobody.', name='Set Foundation')
    zone.trigger_profile[SAFE] = '|'.join(chosen)
    if 'foundation_cell_anchors' in ctx.damage_cache:
        zone.trigger_profile['cell_anchors'] = deepcopy(ctx.damage_cache['foundation_cell_anchors'])


def designated_safe(ctx, creature):
    """Public activation designation query used by earth_responses."""
    saved = ctx.damage_cache.get(SAFE)
    return creature.entity_id in saved.split('|') if isinstance(saved, str) else creature.team_id == ctx.actor.team_id


@hook('zone_trigger_context')
def restore(ctx, zone, creature, moment):
    if SAFE in zone.trigger_profile:
        ctx.damage_cache[SAFE] = zone.trigger_profile[SAFE]
