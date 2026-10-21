"""Calamity Banner's native CL3 projection prerequisite.

One source owner, one object, no phantom creature or independent initiative.
Ownership comes only from validated native source admissions. Existing compiler,
cell candidate, typed effect, OBJECT_UPDATED and round expiry contracts carry
the entire activation; later Banner combat clauses are deliberately unclaimed.
"""
from . import effect, hook

PARENT = 'tianxia.subpath.qi.calamity_banner_cultivator'
RAISE = PARENT + '.feature.raise_the_calamity_banner'
PATH = 'tianxia.path.qi_cultivation'
KEY = 'calamity_banner'


def admission(sheet):
    return next((r for r in sheet.get('combat_acquisitions', [])
                 if r.get('feature_id') == RAISE), None)


@hook('compile_passives')
def ownership(rows, info):
    if RAISE not in info['owned_ids'] or not admission(info['owner_sheet']):
        return None
    qi = next(r['attainment'] for r in info['owner_sheet']['path_and_subpath']['paths']
              if r['path_id'] == PATH)
    return [*rows, {'block': KEY, 'feature_id': RAISE,
                    'source_cl': min(qi, int(info['numbers']['cl']))}]


@hook('compile_action')
def projection_action(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != RAISE:
        return None
    # Seal the actual Qi attainment rather than a multiclass character's CL.
    qi = next((r.get('attainment', 0) for r in
               (info['owner_sheet'].get('path_and_subpath') or {}).get('paths', [])
               if r.get('path_id') == PATH), 0)
    numbers = {**typed.get('numbers', {}), 'cl': min(qi, int(info['numbers']['cl']))}
    return action.model_copy(update={'target_kind': 'CELL', 'range_ft': 30, 'radius_ft': 0,
        'display_name': 'Raise the Calamity Banner — Bonus Action, 1 Qi, 1 hour',
        'parameters': {**action.parameters, 'banner_projection': 1, 'any_cell': True,
                       'ai_allow_empty_area': True,
                       'typed': {**typed, 'numbers': numbers, 'duration': {'kind': 'instant'},
                                 'effects': [{'type': 'calamity_banner_projection'}], 'riders': []}}})


def owned(engine, actor):
    return any(r.get('block') == KEY and r.get('feature_id') == RAISE and r['source_cl'] >= 3
               for r in engine.typed_passive_rows.get(actor.entity_id, []))


def banners(engine, owner):
    return [o for o in engine.state.objects.values() if o.owner_id == owner.entity_id
            and (o.component or {}).get(KEY) and not o.destroyed]


def legal_position(engine, actor, point):
    if point is None or not engine.grid.in_bounds((point.x, point.y)):
        return False
    if engine.grid.distance_ft(actor.position, point) > 30:
        return False
    from ..spatial_areas import actor_positions
    from ..object_geometry import target_cells
    if any(a.active and point in actor_positions(engine, a) for a in engine.state.actors.values()):
        return False
    if any(not o.destroyed and point in target_cells(engine, o) for o in engine.state.objects.values()):
        return False
    return engine.grid.placement_legal(point)


@hook('candidate_allowed')
def projection_allowed(engine, actor, candidate, action):
    if action is None or not action.parameters.get('banner_projection'):
        return None
    return (action.owner_id == actor.entity_id and owned(engine, actor)
            and not banners(engine, actor) and legal_position(engine, actor, candidate.destination))


@effect('calamity_banner_projection', harmful=False)
def project(ctx, row):
    from ..gate2_runtime_models import RuntimeObjectState
    from .effect_durations import round_token
    engine, actor = ctx.engine, ctx.actor
    if not owned(engine, actor) or banners(engine, actor) or not legal_position(engine, actor, ctx.intent.destination):
        raise ValueError('Choose one unoccupied point within 30 feet for your Calamity Banner.')
    cl, pb = int(ctx.numbers['cl']), int(ctx.numbers['pb'])
    obj = RuntimeObjectState(object_id=f'object:calamity_banner:{actor.entity_id}:{engine.state.event_sequence + 1}',
        object_kind='CALAMITY_BANNER', position=ctx.intent.destination, owner_id=actor.entity_id,
        unattended=True, flammable=False, ac=12 + pb, current_hp=4 * cl, maximum_hp=4 * cl,
        damage_immunities=('POISON', 'PSYCHIC'), destroyed=False, height_ft=5,
        component={'name': 'Calamity Banner', 'size': 'medium', 'kind': 'cultivation_asset',
                   'source': RAISE, 'source_cl': cl, 'blocks': False,
                   KEY: {'projected': 1, 'expires_on': round_token(engine, 600),
                         'noncultivated_resistance': ['BLUDGEONING', 'PIERCING', 'SLASHING'],
                         'save_bonus': pb + int(ctx.numbers.get('key_mod', 0)),
                         'fly_speed_ft': 20, 'hover': 1, 'no_independent_actions': 1,
                         'condition_immunities': ['charmed', 'frightened', 'poisoned', 'prone']}})
    engine._update_object(obj, RAISE, actor.entity_id)


@hook('event')
def expire_projection(engine, event_type, kwargs):
    if event_type not in ('TURN_STARTED', 'TURN_ENDED'):
        return
    from .effect_durations import due
    for obj in list(engine.state.objects.values()):
        record = (obj.component or {}).get(KEY)
        if not record or obj.destroyed or not record.get('projected'):
            continue
        if due(engine, record['expires_on']):
            engine._update_object(obj.model_copy(update={'destroyed': True, 'current_hp': 0}),
                                  RAISE, obj.owner_id)
