"""Tide-Court Footwork: selected allies cross hostiles inside the owner's Court.

Native passage keeps occupied destinations forbidden, charges creature-space
Difficult Terrain and rechecks every step. One actual crossing per owner/round
marks its hostile occupant Soaked. Recipients are explicit allies other than
self, and automatic choices are restricted to perceived allies, never preferences.

The shared passage seam is used as documented: this Court states its own grant
as one (cost, scope) pair on ``pass_through_grant``, so it narrows only its own
transit and never another ability's independent grant, and it bills the Soaked
crossing on ``pass_through_entered_cells``, which reports the voxels actually
entered, so a crossing through one owner's Court cannot spend another's round.
"""
from copy import deepcopy
from . import effect, hook, ai_controlled
from .needle import CHOICE, ask, checkpoint_id
from .passive_rows import row_of

FOOTWORK='insight.tide-court-footwork'
COURT='TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
BLOCK='water_second_pass'
SELECT='water_tide_footwork_select'
RECIPIENTS='water_tide_footwork_allies'


def courts(engine, owner):
    for zone in engine.state.zones.values():
        action=engine.action_catalog.get(zone.source_definition_id)
        typed=action.parameters.get('typed') or {} if action else {}
        if zone.active and zone.owner_id==owner.entity_id and typed.get('source')==COURT:
            yield zone


@hook('compile_action')
def selection_on_cast(action, info):
    typed=action.parameters.get('typed') or {}
    if FOOTWORK not in info['owned_ids'] or typed.get('source')!=COURT:
        return None
    return action.model_copy(update={'parameters':{**action.parameters,
        'typed':{**typed,'effects':[*deepcopy(typed.get('effects') or []),{'type':SELECT}]}}})


@hook('compile_actions')
def selection_action(info):
    if FOOTWORK not in info['owned_ids']:
        return None
    action=next((a for a in info['actions'] if (a.parameters.get('typed') or {}).get('source')==COURT),None)
    if action is None:
        return None
    from ..gate2_runtime_models import EconomyKind
    typed=deepcopy(action.parameters['typed'])
    typed.update(source=FOOTWORK,effects=[{'type':SELECT}],riders=[],duration={'kind':'instant'},area=None)
    return [action.model_copy(update={'source_definition_id':action.source_definition_id+'.footwork_allies',
        'display_name':'Tide-Court Footwork: choose allies','economy':EconomyKind.NONE,'target_kind':'SELF',
        'range_ft':None,'radius_ft':None,'concentration':False,'costs':(),
        'parameters':{'typed':typed,'player_only':True,'expected_damage':0}})]


@hook('candidate_allowed')
def needs_court(engine, actor, candidate, action):
    if action and action.source_definition_id.endswith('.footwork_allies'):
        return any(courts(engine,actor))
    return None


@effect(SELECT)
def select_allies(ctx, eff):
    from ..target_knowledge import located
    zones=list(courts(ctx.engine,ctx.actor))
    if not zones:
        return
    # Designate the whole allied roster now; a selected ally may enter the
    # Court later. Automatic selection is narrowed below to perceived allies.
    allies=[a for a in sorted(ctx.engine.state.actors.values(),key=lambda a:a.entity_id)
            if a.active and a.entity_id!=ctx.actor.entity_id and a.team_id==ctx.actor.team_id]
    options=[a.entity_id for a in allies]
    perceived=[a.entity_id for a in allies if located(ctx.engine,ctx.actor,a)]
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'TIDE_COURT_FOOTWORK',ctx.source),
        ctx.actor,CHOICE+'water_tide_footwork',options,minimum=0,maximum=len(options),default='all',
        automatic_options=perceived,name='Tide-Court Footwork',feature_id=FOOTWORK,
        labels={a.entity_id:a.display_name for a in allies},
        prompt='Tide-Court Footwork: choose allies who will benefit while inside your Court and may move through hostile creatures. '
               'They must stop in a free space. Once per round, one hostile creature crossed this way becomes Soaked.')
    for z in zones:
        z.trigger_profile={**z.trigger_profile,RECIPIENTS:list(selected)}
        ctx.engine._append_event('ZONE_CREATED',z.source_definition_id,actor_id=z.owner_id,
            payload={'zone':z.model_dump(mode='json')})


def granting_owners(engine, mover, occupant):
    """Yield each owner whose Court and selected allies make this a Court crossing.

    Yields (owner, court_voxels): the exact occupied voxels of this hostile that
    lie inside that one owner's Court. One crossing can qualify under several
    owners, and each owner is only ever told about its own voxels.
    """
    if mover.team_id==occupant.team_id:
        return
    from ..space import point
    volume=set(engine._actor_volume(occupant))
    for owner in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
        if row_of(engine,owner.entity_id,BLOCK,'tide_footwork') is None or mover.team_id!=owner.team_id:
            continue
        # The occupied hostile's footprint establishes that this transit is
        # through the Court. The mover may begin outside and cross into it.
        # Recipients are per Court, so only the Courts this ally was selected
        # into can contribute voxels to this crossing.
        cells={cell for zone in courts(engine,owner)
                 if mover.entity_id in zone.trigger_profile.get(RECIPIENTS,[])
                 for cell in (point(candidate) for candidate in zone.affected_cells)
                 if cell in volume}
        if cells:
            yield owner,cells


@hook('pass_through_grant')
def passage(engine, mover, occupant):
    """Grant difficult passage through the owner's Court voxels only.

    The cost and its scope are stated as one grant, so this Court cannot narrow
    another ability's independent whole-footprint grant; the two union.
    """
    cells=set()
    for _,owned in granting_owners(engine,mover,occupant):
        cells|=owned
    return ('difficult',cells) if cells else None


@hook('pass_through_entered_cells')
def soak_crossed(engine, mover, occupant, entered, intent):
    """Soak each hostile this ally actually entered inside some owner's Court.

    The round benefit and its mark belong to the owner whose Court was entered,
    so crossing one owner's Court never spends another's. The notice is
    transactional: the crossing it bills has already been committed.
    """
    from ..typed_reactions import triggered_context
    from ..typed_executor import run_effects
    for owner,cells in granting_owners(engine,mover,occupant):
        if not entered & cells:
            continue
        key='once_per_round:water_tide_footwork'
        if owner.turn_flags.get(key)==engine.state.round_number:
            continue
        row=row_of(engine,owner.entity_id,BLOCK,'tide_footwork')
        owner.turn_flags[key]=engine.state.round_number
        ctx=triggered_context(engine,owner,occupant,{'feature_id':FOOTWORK,'name':'Tide-Court Footwork',
            'numbers':row['numbers'],'effects':[]},intent)
        run_effects(ctx,[{'type':'mark','mark':'Soaked','applies_to':'target'}])
        engine._append_event('PASSIVE_TRIGGERED',FOOTWORK,actor_id=owner.entity_id,target_ids=(occupant.entity_id,),
            payload={'crossing_ally':mover.entity_id,'text':f'Tide-Court Footwork: {mover.display_name} crosses {occupant.display_name}, making it Soaked (once this round).'})
