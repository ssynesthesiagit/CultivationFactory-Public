"""External field facts admitted by the existing native world-owner boundary.

Consumers: Dreams sleep, Sand Sources, Weather and observer plane/light queries.
No declaration grants a feature or manufactures a mechanical damage receipt.
Latest immutable records are sealed into combat bundles at encounter creation.
Missing facts stay unknown. Native conditions/zones take precedence over sleep,
weather and terrain declarations. Privacy is the admission contract's readers.
"""
from copy import deepcopy
from . import hook
from ..journey import require, integer

SOURCE = 'system:scene.fields'
KINDS = {'plane', 'sleep', 'sand_source', 'weather', 'lighting', 'surface', 'obscuration'}


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source != SOURCE or kind not in KINDS:
        return None
    return {'value_type':'document', 'maximum_seconds':86400, 'authority':'table_owner',
            'description':'Mapped world facts for this scene; no acquisition or event authority.'}


@hook('fact_admission_validate')
def validate(session, source, subject, kind, scope, value):
    if source != SOURCE or kind not in KINDS:
        return None
    if kind == 'plane':
        require(set(value)=={'plane_id'} and type(value['plane_id']) is str and 0<len(value['plane_id'])<=120,
                'Name this creature’s actual plane, or leave the fact unknown.')
    elif kind == 'sleep':
        require(set(value)=={'asleep'} and type(value['asleep']) is int and value['asleep'] in (0,1), 'Record actual sleep as 0 or 1.')
    else:
        fields = {'cells'} | ({'sign','severity'} if kind=='weather' else {'level'} if kind=='lighting' else
                             {'material','degree'} if kind=='obscuration' else {'material'} if kind=='surface' else set())
        supplied=set(value)-({'difficult'} if kind=='surface' else set())
        require(supplied==fields and isinstance(value['cells'],list) and value['cells'], 'Supply the exact mapped field.')
        for cell in value['cells']:
            require(isinstance(cell,list) and len(cell)==3 and all(integer(v) for v in cell)
                    and session.grid.in_bounds(tuple(cell[:2])), 'Field cells must be integer coordinates on this map.')
        if kind=='weather':
            from .weather_signs import CATEGORIES
            require(value['sign'] in CATEGORIES and integer(value['severity'],1) and value['severity']<=4, 'Choose a Weather Sign and severity 1–4.')
        if kind=='lighting':
            require(value['level'] in ('bright','dim','darkness'), 'Choose Bright Light, Dim Light or darkness.')
        if kind=='surface':
            require(value['material'] in ('ice','snow','mud','shallow_water','frost','slick_ground','stone','sand','wood','earth'),
                    'Choose an actual mapped surface material.')
            require(type(value.get('difficult',0)) is int and value.get('difficult',0) in (0,1),
                    'Record whether this surface actually is difficult terrain as 0 or 1.')
        if kind=='obscuration':
            require(value['material'] in ('smoke','ash','heat_distortion','fog','mist','steam','dust')
                    and value['degree'] in ('light','heavy'),'Choose the actual obscuring material and degree.')
    return True


@hook('journey_combat_bundle')
def snapshot(bundle, session, aid):
    from ..fact_consent_admission import read
    records = {}
    for row in session.state.get('fact_consent_admission', []):
        if row['source']!=SOURCE:
            continue
        key=(row['subject'],row['kind']) if row['kind'] in ('plane','sleep') else (row['subject'],row['kind'],row['scope'])
        records[key]=row
    selected=[]
    for row in records.values():
        # read validates the actual newest declaration in this scope even when
        # expired. Singleton transitions are retained as negative knowledge:
        # dropping an expired newer plane/sleep state would revive older input.
        current=read(session,SOURCE,row['subject'],row['kind'],row['scope'],row['subject'])
        if current is None and row['kind'] not in ('plane','sleep'):
            continue
        selected.append(deepcopy(row))
    return {**bundle, 'scene_field_facts':selected,
            'scene_field_clock':{'num':session.clock().numerator,'den':session.clock().denominator},
            'scene_field_sequence_floor':max((r['sequence'] for r in session.state.get('fact_consent_admission',[])),default=0)}



def facts(engine, viewer, kind, subject=None, *, mechanical=False):
    """Known inputs, or engine-only world truth when a rule requires it.

    Mechanical truth is never an observer view. Plane/sleep/weather consumers
    can settle their rules without disclosing the underlying private record.
    Singleton state selects its newest receipt before testing expiry, so an
    expired transition never resurrects a stale initial plane or sleep fact.
    """
    from ..combat_world_facts import records,clock
    rows=[r for r in records(engine) if r['source']==SOURCE and r['kind']==kind
          and (subject is None or r['subject']==subject)]
    if kind in ('plane','sleep'):
        latest={}
        for r in rows:
            latest[r['subject']]=r
        rows=list(latest.values())
    else:
        latest={}
        for r in rows:
            latest[(r['subject'],r['scope'])]=r
        rows=list(latest.values())
    return [r for r in rows if r['expires_at']>clock(engine)
            and (mechanical or viewer.entity_id in (r['subject'],*r['readers']))]


@hook('journey_encounter_settled')
def continue_world_facts(session,aid,engine,actor):
    from ..combat_world_facts import records
    incoming=[r for r in records(engine) if r['source']==SOURCE and r['subject']==aid]
    if not incoming:return
    history=session.state.setdefault('fact_consent_admission',[])
    existing={r['receipt_id'] for r in history}
    for row in incoming:
        if row['receipt_id'] not in existing:
            history.append(deepcopy(row));existing.add(row['receipt_id'])
    history.sort(key=lambda r:r['sequence'])


def plane(engine, actor):
    """Authoritative sealed plane; absence is unknown, never 'material'."""
    rows = facts(engine, actor, 'plane', actor.entity_id,mechanical=True)
    return rows[-1]['value']['plane_id'] if rows else None


def same_plane(engine, viewer, target):
    own = plane(engine, viewer)
    rows = facts(engine, viewer, 'plane', target.entity_id,mechanical=True)
    other = rows[-1]['value']['plane_id'] if rows else None
    return own is not None and own==other


def planes_differ(engine,viewer,target):
    first,second=plane(engine,viewer),plane(engine,target)
    return first is not None and second is not None and first!=second


@hook('perception_admission')
def plane_presence(engine,viewer,target):
    if not planes_differ(engine,viewer,target):
        return None
    from . import run_strict
    return None if True in run_strict('interplanar_perception_allowed',engine,viewer,target) else False


@hook('target_aim_present')
def plane_aim(engine,actor,target,action):
    if planes_differ(engine,actor,target) and not ((action.parameters.get('typed') or {}).get('cross_plane_targeting') if action else False):
        return False
    return None


def sleeping(engine, viewer, target):
    from .dreams_core import asleep
    rows = facts(engine, viewer, 'sleep', target.entity_id,mechanical=True)
    began = max((e.sequence for e in engine.events if e.event_type=='WORLD_FACT_DECLARED'
                 and rows and e.payload.get('receipt_id')==rows[-1]['receipt_id']),default=0)
    disturbed = any(e.event_type=='DAMAGE_COMMITTED' and target.entity_id in e.target_ids
                   and e.sequence>began and int(e.payload.get('hp_damage') or 0)+int(e.payload.get('temporary_hp_absorbed') or 0)>0 for e in engine.events)
    return asleep(target) or bool(rows and rows[-1]['value']['asleep']==1 and not disturbed)


@hook('hide_concealment_basis')
def dark_basis(engine, viewer, target):
    from ..illumination import level_at
    return ['darkness'] if level_at(engine,viewer,target.position)=='darkness' else None


def cells(engine, viewer, kind):
    return {tuple(c) for row in facts(engine,viewer,kind) for c in row['value']['cells']}


def weather_severity(engine, viewer, target, sign):
    occupied = {(p.x,p.y,p.z) for p in __import__('combat.spatial_areas',fromlist=['actor_positions']).actor_positions(engine,target)}
    return max((r['value']['severity'] for r in facts(engine,viewer,'weather',mechanical=True) if r['value']['sign']==sign
                and occupied.intersection(map(tuple,r['value']['cells']))), default=0)


@hook('journey_view')
def privacy(state, viewer_id):
    if not state.get('fact_consent_admission'):
        return None
    result = deepcopy(state)
    for aid, actor in result['actors'].items():
        actor.get('bundle',{}).pop('scene_field_facts',None)
    return result


@hook('presentation_hidden_conditions')
def private_world_records(engine,actor):
    from ..combat_world_facts import HISTORY
    return [iid for iid,c in actor.conditions.items() if c.condition_id==HISTORY] or None


@hook('presentation_hidden_history_conditions')
def private_world_history(events):
    from ..combat_world_facts import HISTORY
    return [e.payload['instance_id'] for e in events if not isinstance(e,dict)
            and e.payload.get('condition_id')==HISTORY and e.payload.get('instance_id')] or None


@hook('zones')
def mapped_fields(engine):
    """Native mapped field consumers of actual admitted world-owner facts.

    The immutable fact history owns location, replacement and expiry, as native
    object state owns derived walls. No second zone ledger can outlive it. A
    surface is difficult only when explicitly declared; material alone does not
    imply a cost. Obscuration is never fabricated from an attack name or tag.
    """
    from ..gate2_runtime_models import ZoneState,Position
    from ..zones import MAP_OWNER
    viewer=next(iter(engine.state.actors.values()),None)
    if viewer is None:return None
    result=[]
    for kind in ('surface','obscuration'):
        for row in facts(engine,viewer,kind,mechanical=True):
            value=row['value']
            if kind=='surface' and not value.get('difficult'):continue
            cells=tuple(Position(x=x,y=y,z=z) for x,y,z in value['cells'])
            result.append(ZoneState(zone_id='zone:scene-field:'+row['receipt_id'],source_definition_id=SOURCE,
                owner_id=MAP_OWNER,center=cells[0],radius_cells=0,affected_cells=cells,concentration_link=False,
                duration_rounds=None,created_round=engine.state.round_number,
                trigger_profile={'kind':'TYPED','name':value['material'].replace('_',' ').title(),
                    'shape':'painted','size_ft':5,'map':True,'terrain':[],
                    'difficult':'all' if value.get('difficult') else None,
                    'obscured':value.get('degree'),'visual':{'material':value['material']},
                    'triggers':[],'inside':[],'talents':[],'numbers':{}}))
    return result or None
