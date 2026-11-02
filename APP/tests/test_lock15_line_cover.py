"""Pillar clipping is shared by line previews, targets and committed Table effects."""
import json
import zipfile
import pytest
from combat.space import effect_ray
from combat.gate2_runtime_models import Position
from combat import typed_executor as te
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests import lock8_support as S
from tests.test_lock2_persistence import act


def test_oblique_ray_crosses_pillar_square_and_is_reversible():
    start,end=Position(x=3,y=5),Position(x=11,y=4)
    ray=effect_ray(start,end)
    assert (7,4,0) in ray and (7,5,0) in ray
    assert ray==tuple(reversed(effect_ray(end,start)))
    assert effect_ray(Position(x=2,y=2),Position(x=3,y=3))==((2,2,0),(3,3,0))


@pytest.mark.parametrize('end',[(11,4,0),(4,11,0),(11,4,4),(4,3,11),(3,5,0)])
def test_voxel_ray_has_no_skipped_interior_crossing(end):
    from fractions import Fraction
    start=(3,5,0);ray=effect_ray(start,end)
    expected=set()
    # Independent slab intersection checks every voxel in the bounding box.
    import itertools
    for cell in itertools.product(*(range(min(a,b),max(a,b)+1) for a,b in zip(start,end))):
        lower,upper=Fraction(0),Fraction(1)
        for a,b,c in zip(start,end,cell):
            if b==a:
                if c!=a:upper=Fraction(-1)
            else:
                edges=sorted((Fraction(2*c-1-2*a,2*(b-a)),Fraction(2*c+1-2*a,2*(b-a))))
                lower=max(lower,edges[0]);upper=min(upper,edges[1])
        if lower<upper:expected.add(cell)
    assert set(ray)==expected
    assert ray==tuple(reversed(effect_ray(end,start)))


def test_line_membership_and_finite_height_blocking():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),me_at=(3,5),foe_at=(11,4))
    a,t=e.state.actors[S.ME],e.state.actors[S.FOE]
    area={'shape':'line','size_ft':120,'width_ft':5}
    e.grid.blocked={(7,4)}
    assert not te.in_area(e,a.position,t.position,t.position,area)
    assert t.position not in te.area_cells(e,a.position,t.position,area)
    assert t not in te._area_targets(e,a,t.position,area)
    e.grid.terrain_heights={'BLOCKED':{(7,4):5}};e.grid.finite_heights=True
    assert te.in_area(e,Position(x=3,y=5,z=2),Position(x=11,y=4,z=2),Position(x=11,y=4,z=2),area)
    e.grid.blocked.clear()
    assert te.in_area(e,a.position,t.position,t.position,area)


@pytest.mark.parametrize('pillar',[True,False])
def test_judgment_ray_table_preview_commit_reload(monkeypatch,tmp_path,pillar):
    owner,target='actor:factory.aaaaaaaa','actor:factory.bbbbbbbb'
    for pid in ('aaaaaaaa','bbbbbbbb','cccccccc'):
        doc=sheet(['RADIANCE_TAL_JUDGMENT_RAY'] if pid=='aaaaaaaa' else [],cl=15)
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Line pillar yard','width_squares':16,'height_squares':12,
        'walls':[{'shape':'rect','points':[[7,4],[8,5]],'filled':True}] if pillar else [],
        'starts':{'team1':[[3,5]],'team2':[[11,4],[5,5]]}})
    near='actor:factory.cccccccc'
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[target,near],
        control_modes={owner:'MANUAL',target:'MANUAL',near:'MANUAL'},arena_id='battlefield:map.line-pillar-yard',match_seed='L15-LINE')['match_id']
    table=TabletopService(service,tmp_path)
    while table.state(mid)['menu']['actor_id']!=owner:assert act(table,mid,'end')['status']=='COMMITTED'
    engine=service._load_session(mid).engine;state=table.state(mid)
    assert ((7,4) in engine.grid.blocked) is pillar
    candidate=next(c for c in engine.legal_candidates() if 'JUDGMENT_RAY' in c.source_definition_id and c.destination==Position(x=11,y=4))
    option=next(o for g in state['menu']['actions'] for o in g['options'] if o['candidate_id']==candidate.candidate_id)
    cells={(p['x'],p['y']) for p in option['area']['affected_cells']}
    assert ((11,4) in cells) is (not pillar)
    before=len(engine.events)
    assert table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,state['last_sequence'])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    saves=[ev for ev in loaded.engine.events[before:] if ev.event_type=='SAVE_ROLLED' and ev.actor_id==target]
    assert bool(saves) is (not pillar)
    damage=[ev for ev in loaded.engine.events[before:] if ev.event_type=='DAMAGE_COMMITTED' and target in ev.target_ids]
    assert bool(damage) is (not pillar)
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==near for ev in loaded.engine.events[before:])
    assert loaded.engine.state==service._load_session(mid).engine.state
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_ai_directional_area_keeps_unseen_aim_and_clips_covered_recipients():
    """AI may aim a self-originating ray past cover, while its recipients stay physically clipped."""
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from combat.targeting import aim_requires_line_of_effect, directional_area_aim

    engine=S.fight(S.bundle('RADIANCE_TAL_JUDGMENT_RAY'),me_at=(3,5),foe_at=(11,4),ally_at=(3,9))
    from copy import deepcopy
    observed=deepcopy(engine.state.actors[S.FOE])
    observed.entity_id='actor:factory.c4_observed_foe'
    observed.position=Position(x=4,y=5)
    engine.state.actors[observed.entity_id]=observed
    engine.state.initiative_order.append(observed.entity_id)
    engine.grid.blocked={(5,y) for y in range(engine.grid.height)}
    actor=engine.state.actors[S.ME]
    action=next(a for a in engine.action_catalog.values()
                if a.owner_id==S.ME and 'JUDGMENT_RAY' in a.source_definition_id)
    aim=Position(x=8,y=4)

    from combat.senses import perceives_cell
    assert not perceives_cell(engine,actor,aim)
    assert directional_area_aim(action)
    assert not aim_requires_line_of_effect(action)
    from combat.candidate_knowledge import query,aim_allowed
    with query(engine):
        assert aim_allowed(engine,actor,aim,action)
    policy=PolicyLibrary(ROOT).for_actor(S.ME)[0]
    candidates=build_decision_context(engine,policy,for_ai=True).legal_candidates
    candidate=next(c for c in candidates if c.source_definition_id==action.source_definition_id and c.destination==aim)
    assert candidate.metadata['hostiles_in_area']==1
    assert candidate.metadata['expected_damage']>0
    assert not te.in_area(engine,actor.position,aim,engine.state.actors[S.FOE].position,
                          action.parameters['typed']['area'])

    # A placed line makes its chosen point the effect origin, and explicit
    # sight requirements override the ordinary direction-only rule.
    placed=action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],
        'area':{**action.parameters['typed']['area'],'placed':True}}}})
    sight_required=action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],
        'requires_seen_origin':True}}})
    assert not directional_area_aim(placed) and aim_requires_line_of_effect(placed)
    assert not directional_area_aim(sight_required) and aim_requires_line_of_effect(sight_required)


def test_self_originating_cone_table_preview_commit_reload_with_sight_boundaries(tmp_path):
    """A cone aimed beyond an unseen wall cell persists, with cover still clipping its effect."""
    from combat.targeting import aim_requires_line_of_effect, directional_area_aim

    owner,target,near='actor:factory.aaaaaaaa','actor:factory.bbbbbbbb','actor:factory.cccccccc'
    for pid in ('aaaaaaaa','bbbbbbbb','cccccccc'):
        doc=sheet(['TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH'] if pid=='aaaaaaaa' else [],cl=15)
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Cone pillar yard','width_squares':16,'height_squares':12,
        'walls':[{'shape':'rect','points':[[6,0],[7,11]],'filled':True}],
        'starts':{'team1':[[3,5]],'team2':[[9,4],[5,4]]}})
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[target,near],
        control_modes={owner:'MANUAL',target:'MANUAL',near:'MANUAL'},
        arena_id='battlefield:map.cone-pillar-yard',match_seed='JRAY-CONE')['match_id']
    table=TabletopService(service,tmp_path)
    while table.state(mid)['menu']['actor_id']!=owner:
        assert act(table,mid,'end')['status']=='COMMITTED'
    engine=service._load_session(mid).engine;state=table.state(mid)
    action=next(a for a in engine.action_catalog.values()
                if a.owner_id==owner and 'HUNGER_REFINING_BREATH' in a.source_definition_id)
    assert directional_area_aim(action) and not aim_requires_line_of_effect(action)
    candidate=next((c for c in engine.legal_candidates()
                   if c.source_definition_id==action.source_definition_id and c.destination==Position(x=9,y=3)),None)
    assert candidate is not None, [(c.display_name, c.destination) for c in engine.legal_candidates()
                                   if c.source_definition_id==action.source_definition_id]
    option=next(o for g in state['menu']['actions'] for o in g['options']
                if o['candidate_id']==candidate.candidate_id)
    cells={(p['x'],p['y']) for p in option['area']['affected_cells']}
    assert (5,4) in cells and (9,4) not in cells
    before=len(engine.events)
    args=(candidate.candidate_id,candidate.decision_id,candidate.state_version,state['last_sequence'])
    answers=[]
    prompts=[]
    result=table.act(mid,*args,answers)
    for _ in range(30):
        if result['status']!='REACTION_REQUIRED':
            break
        prompt=result['reaction']
        prompts.append((prompt.get('context',{}).get('reaction_source_id'),
                        [o['id'] for o in prompt.get('choice',{}).get('options',[])]))
        answers.append({**prompt['context'],'selection':'USE',
                        'option_ids':[prompt['choice']['options'][0]['id']]})
        result=table.act(mid,*args,answers)
    assert result['status']=='COMMITTED', (result,prompts)
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    saves=[ev for ev in loaded.engine.events[before:]
           if ev.event_type=='SAVE_ROLLED' and ev.actor_id==target]
    assert not saves
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==near
               for ev in loaded.engine.events[before:])
    assert loaded.engine.state==service._load_session(mid).engine.state
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'

    # Placed areas and explicit sight-gated line/cone actions still need a
    # clear path to their chosen point when the aim cell is not perceived.
    from copy import deepcopy
    placed=action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],
        'area':{**action.parameters['typed']['area'],'placed':True}}}})
    sight_required=action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],
        'requires_seen_target':True}}})
    actor=engine.state.actors[owner];aim=Position(x=9,y=3)
    assert not directional_area_aim(placed) and aim_requires_line_of_effect(placed)
    assert not directional_area_aim(sight_required) and aim_requires_line_of_effect(sight_required)
    from combat.senses import perceives_cell
    assert not perceives_cell(engine,actor,aim)
