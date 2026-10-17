"""Great Mantra's chosen-allies aura (A2GQISUB10).

Only reviewed great_mantra_aura rows opt in. One owned concentration-linked
placement follows its origin; live membership determines benefits. Precision
is a boolean grant, so overlapping auras do not stack. Endurance shares ordinary
Resistance. Motion ignores only explicitly nonmagical difficult areas and lowers
ordinary standing cost. Recipient choices use the owner's existing choice transport;
automatic recipients are perceived allies. No core ability branch is added.
"""
from . import effect, hook, placed

TAG = 'great_mantra'


def _zones(engine, actor, kind=None):
    from .. import zones
    from .qi_path import armament_condition
    return [z for z in placed.of(engine, TAG) if actor.entity_id in placed.data(z).get('chosen', [])
            and (not placed.data(z).get('armament') or (engine.state.actors.get(z.owner_id) and armament_condition(engine.state.actors[z.owner_id])))
            and zones._inside(engine, actor, z) and (kind is None or placed.data(z).get('kind') == kind)]


@effect('great_mantra_aura', harmful=False)
def mantra(ctx, row):
    from .. import stealth
    from .needle import ask, checkpoint_id
    allies = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id]
    perceived = [a.entity_id for a in allies if a is ctx.actor or stealth.sees(ctx.engine, ctx.actor, a)]
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'great_mantra_allies', ctx.source), ctx.actor,
                   'choice:needle.great_mantra_allies', [a.entity_id for a in allies],
                   labels={a.entity_id:a.display_name for a in allies}, minimum=0, maximum=len(allies),
                   default_count=len(allies), preferred=perceived, automatic_options=perceived,
                   prompt='Great Mantra: choose the allies who benefit while inside your aura')
    for old in placed.of(ctx.engine, TAG, owner_id=ctx.actor.entity_id):
        placed.drop(ctx.engine, old, 'REPLACED')
    from ..action_geometry import record_for, point
    origin = record_for(ctx.engine, ctx.actor, ctx.source)
    armament = bool(origin and origin['id'] == 'mantra:armament')
    centre = point(ctx.engine, ctx.actor)
    placed.place(ctx.engine, ctx.actor, source=ctx.source, tag=TAG,
                 cells=(centre,*placed.area(ctx.engine, centre, 'sphere', 30)), name=ctx.action.display_name,
                 placed={'kind':row['kind'], 'chosen':selected, 'damage_type':row.get('damage_type'), 'armament':int(armament)},
                 numbers=ctx.numbers, duration_rounds=10, follows_owner=not armament, concentration=True,
                 radial_volume=True, shape='sphere', size_ft=30, color='#c49cd4')


@hook('save')
def fortitude(ctx, subject, ability, named):
    if _zones(ctx.engine, subject, 'fortitude') and set(named or ()) & {'charmed','frightened','prone','forced_movement'}:
        return {'bonus':0, 'modes':['ADVANTAGE']}


@hook('attack_bonus')
def precision(ctx, actor):
    return 1 if _zones(ctx.engine, actor, 'precision') else None


@hook('d20_bonus')
def native_precision(engine, roll, intent):
    meta = engine.d20_context(roll) or {}
    actor = engine.state.actors.get(roll.actor_id)
    if meta.get('kind') != 'attack' or not actor or not _zones(engine, actor, 'precision'):
        return None
    scopes = getattr(engine, '_d20_scopes', ())
    frame = scopes[-1] if scopes else {}
    spec = frame.get('spec') or {}
    if frame.get('kind') == 'attack' and frame.get('actor_id') == roll.actor_id and spec.get('typed') is not None and callable(spec.get('before_attack_d20')):
        return None
    return {'source_id':_zones(engine, actor, 'precision')[0].source_definition_id, 'bonus':1}


@hook('damage_defenses')
def endurance(engine, actor, damage_type, typed, source_actor_id):
    types = {placed.data(z).get('damage_type','').upper() for z in _zones(engine, actor, 'endurance')}
    return [{'kind':'resistance','damage_types':sorted(types)}] if types else None


@hook('speed')
def motion(engine, actor):
    return 10 if _zones(engine, actor, 'motion') else None


@hook('stand_cost')
def motion_stand(engine, actor, normal_cost):
    return min(5, normal_cost) if _zones(engine, actor, 'motion') else None


@hook('difficult_exempt')
def motion_ground(engine, actor):
    from .. import zones
    if not _zones(engine, actor, 'motion'):
        return None
    return zones.explicitly_nonmagical_difficult_cells(engine, actor)


@hook('effect_origins')
def armament_origins(engine, actor, action):
    from .qi_path import armament_condition, armament_point
    typed = action.parameters.get('typed') or {}
    if not any(e.get('type') == 'great_mantra_aura' for e in typed.get('effects') or []):
        return None
    if armament_condition(actor) is not None:
        x,y = armament_point(actor)
        return [{'id':'mantra:armament','label':'Great Mantra from your Domain Armament','position':{'x':x,'y':y}}]


@hook('event', nested=True)
def armament_follows(engine, event_type, kwargs):
    if event_type not in {'CONDITION_APPLIED', 'CONDITION_REMOVED'}:
        return
    from .qi_path import ARMED, armament_condition, armament_point
    if (kwargs.get('payload') or {}).get('condition_id') != ARMED:
        return
    for zone in placed.of(engine, TAG):
        if not placed.data(zone).get('armament'):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner and armament_condition(owner):
            from ..gate2_runtime_models import Position
            x,y = armament_point(owner)
            center = Position(x=x,y=y)
            if center != zone.center:
                placed.reshape(engine, zone, cells=placed.area(engine, center, 'sphere', 30), center=center)
                from .. import zones
                zones.sync_inside(engine, zone.source_definition_id)


@hook('save_mode')
def native_fortitude(engine, actor, ability, dc, source, metadata):
    # Typed saves already received this contribution from fortitude above.
    # Repeating the same mode is harmless; independent Disadvantage still cancels.
    if _zones(engine, actor, 'fortitude') and set(metadata.get('named') or []) & {'charmed','frightened','prone','forced_movement'}:
        return 'ADVANTAGE'
