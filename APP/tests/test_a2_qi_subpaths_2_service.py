"""Printed Explosive Pill formulas through table commits and cold replay."""
import json
import copy
import zipfile
from pathlib import Path
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import auto11_service_support as S
from tests.h1_support import ROOT, sheet
from combat import zones

PILL = 'tianxia.subpath.qi.alchemical_cultivator.feature.explosive_pill'
ME, ALLY, FOE = S.THIEF, S.ALLY, S.VICTIM
QI = 'resource:core.qi'


def fight(tmp_path, *, dc=30, cl=16, nonbreather=False, automatic=False, foe_position=(4,6)):
    ids = [ME, ALLY, FOE]
    docs = {who:sheet([PILL] if who == ME else [], cl=cl, dc=dc,
                      kit={'starting_kit':S.SWORD}) for who in ids}
    for who, doc in docs.items():
        doc['identity']['display_name'] = {ME:'Alchemist',ALLY:'Ally',FOE:'Enemy'}[who]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        if who == FOE and nonbreather:
            doc['identity']['physiology'] = {'breath_dependent':False}
        folder = tmp_path/'portable_characters'/who.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    bundles = [compile_character(docs[who],actor_id=who,reaction_plan={'ask':True}) for who in ids]
    svc = CombatService(ROOT,tmp_path)
    table = TabletopService(svc,tmp_path)
    arena = svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    modes = {who:'MANUAL' for who in ids}
    if automatic:
        modes[ME] = 'LOCAL_AUTO'
    mid = svc._finish_factory_match(bundles,ids,{ME:'team:a',ALLY:'team:a',FOE:'team:b'},
        {ME:{'x':3,'y':6},ALLY:{'x':4,'y':7},FOE:{'x':foe_position[0],'y':foe_position[1]}},arena,[ME],[ALLY,FOE],
        control_modes=modes,match_seed='A2GQISUB2',display_name='Field alchemy',maximum_rounds=10)['match_id']
    if not automatic:
        S.to_thief(table,mid)
    return svc,table,mid


def cold(svc,mid):
    other = CombatService(svc.source_root,svc.userdata_root)
    assert other.replay(mid)['status'] == 'PASS'
    engine = S.engine(other,mid)
    assert engine.state.model_dump(mode='json') == S.engine(svc,mid).state.model_dump(mode='json')
    assert not any(e.source_definition_id == 'ext:combat.ext.qi_subpaths_2' for e in engine.events)
    return engine


def use(svc,table,mid,form,answer=None,aim=(4,6)):
    label = 'Explosive Pill: '+form+' Pill'
    engine = S.engine(svc,mid)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith(label+' at ')
                     and c.destination is not None and (c.destination.x,c.destination.y)==aim)
    response,prompts = S.play(table,mid,candidate.candidate_id,answer=answer)
    assert response['status'] == 'COMMITTED'
    return prompts


@pytest.mark.parametrize('form,kind,count', [('Flame','FIRE',6),('Frost','COLD',4),('Venom','POISON',4),('Impact','FORCE',4)])
@pytest.mark.parametrize('dc,cl', [(30,16),(1,16),(30,17)])
def test_damaging_formulas_resolve_each_creature_and_reload(tmp_path,form,kind,count,dc,cl):
    svc,table,mid = fight(tmp_path,dc=dc,cl=cl)
    before = cold(svc,mid)
    use(svc,table,mid,form)
    eng = cold(svc,mid)
    actor,ally,foe = [eng.state.actors[i] for i in (ME,ALLY,FOE)]
    assert actor.resources[QI] == 27
    assert actor.current_hp < before.state.actors[ME].current_hp
    assert ally.current_hp < before.state.actors[ALLY].current_hp
    assert foe.current_hp < before.state.actors[FOE].current_hp
    saves = [e for e in eng.events if e.event_type=='SAVE_ROLLED' and PILL in e.source_definition_id]
    assert len(saves)==3 and {e.actor_id for e in saves}=={ME,ALLY,FOE}
    success = next(e for e in saves if e.actor_id==FOE).payload['success']
    assert success == (dc==1)
    rolls = [r for r in eng.rolls if PILL in r.reason and r.reason.startswith('DAMAGE:')]
    assert len(rolls)==1 and rolls[0].expression == f'{count+(2 if cl>=17 else 0)}d6+0'
    hp_damage = before.state.actors[FOE].current_hp-foe.current_hp
    assert hp_damage == (rolls[0].total//2 if success else rolls[0].total)
    if form=='Frost':
        speed = [m for m in foe.modifiers.values() if m.target_field=='speed_ft']
        assert speed and speed[-1].value == (-5 if success else -15)
        assert speed[-1].expires_on == 'START_OF_SOURCE_NEXT_TURN'
    if form=='Venom':
        poison = [c for c in foe.conditions.values() if c.condition_id=='condition:typed.poisoned']
        assert bool(poison) == (not success)
        if poison:
            assert poison[0].expires_on == 'START_OF_SOURCE_NEXT_TURN'
    if form=='Impact':
        assert any(c.condition_id=='condition:typed.prone' for c in foe.conditions.values()) == (not success)


def test_venom_nonbreather_has_advantage_without_immunity(tmp_path):
    svc,table,mid=fight(tmp_path,nonbreather=True)
    use(svc,table,mid,'Venom')
    eng=cold(svc,mid)
    save=next(e for e in eng.events if e.event_type=='SAVE_ROLLED' and PILL in e.source_definition_id and e.actor_id==FOE)
    assert save.payload['mode']=='ADVANTAGE'
    assert eng.state.actors[FOE].current_hp<400


def test_smoke_is_concentrated_fifteen_foot_cloud_with_chosen_viewers(tmp_path, monkeypatch):
    from combat import targeting
    # The creation event seals policy; an arbitrary engine attribute does not
    # configure a saved fight. Configure the opt-in before creating the match.
    monkeypatch.setattr(targeting, 'rules', lambda: {
        'concealment_miss_percent': 20, 'total_concealment_miss_percent': 50})
    svc,table,mid=fight(tmp_path)
    def answer(prompt):
        if prompt['context']['reaction_source_id']=='choice:needle.cloud_viewers':return ALLY
        return None
    prompts=use(svc,table,mid,'Smoke',answer)
    eng=cold(svc,mid)
    zone=next(z for z in zones.typed_zones(eng) if PILL in z.source_definition_id)
    assert zone.trigger_profile['size_ft']==15
    assert zone.trigger_profile['spreads'] is True
    assert zone.concentration_link
    assert set(zone.trigger_profile['lightly_obscured_viewer_ids'])=={ME,ALLY}
    assert not zones.hidden_from(eng,eng.state.actors[ME],eng.state.actors[FOE])
    assert not zones.hidden_from(eng,eng.state.actors[ALLY],eng.state.actors[FOE])
    assert zones.hidden_from(eng,eng.state.actors[FOE],eng.state.actors[ALLY])
    # Exercise the opt-in combat policy against the committed, reloaded cloud.
    # A selected viewer retains the partial concealment policy; the cloud remains
    # independently heavy for an unselected viewer.
    assert targeting.concealment_percent(eng,eng.state.actors[ME],eng.state.actors[FOE])==20
    assert targeting.concealment_percent(eng,eng.state.actors[FOE],eng.state.actors[ALLY])==50
    # An independent overlapping cloud still obscures the target for the
    # selected observer; permission applies only to the Smoke cloud they chose.
    independent=copy.deepcopy(zone)
    independent.zone_id=zone.zone_id+':independent-obscuration'
    independent.source_definition_id='test:independent-obscuration'
    independent.trigger_profile={**zone.trigger_profile}
    independent.trigger_profile.pop('lightly_obscured_viewer_ids',None)
    eng.state.zones[independent.zone_id]=independent
    assert zones.hidden_from(eng,eng.state.actors[ME],eng.state.actors[FOE])
    assert targeting.concealment_percent(eng,eng.state.actors[ME],eng.state.actors[FOE])==50
    assert prompts and eng.state.actors[ME].resources[QI]==27
    S.to_thief(table,mid,end_thief=True)
    # Starting another turn does not silently remove the one-minute cloud.
    assert any(PILL in z.source_definition_id for z in zones.typed_zones(cold(svc,mid)))


def test_automatic_smoke_viewers_are_allies_and_self(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    svc,table,mid=fight(tmp_path)
    real = svc.controller
    class SmokeController:
        def choose_primary_action(self, context):
            # Switching control invalidates the old candidate. Select from
            # the actual automatic decision's current legal alternatives,
            # including its native lazy square-picker action. The automatic
            # placement resolver chooses and journals that action's square.
            candidate = next(c for c in context.legal_candidates
                if c.display_name.startswith('Explosive Pill: Smoke Pill')
                and (c.metadata.get('placement_picker') or
                     c.destination is not None and (c.destination.x,c.destination.y)==(4,6)))
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    svc.controller = SmokeController()
    svc.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    result=table.auto_step(mid,table.state(mid)['last_sequence'])
    assert result['status']=='COMMITTED',result
    eng=cold(svc,mid)
    zone=next(z for z in zones.typed_zones(eng) if PILL in z.source_definition_id)
    assert set(zone.trigger_profile['lightly_obscured_viewer_ids'])=={ME,ALLY}
    assert FOE not in zone.trigger_profile['lightly_obscured_viewer_ids']


def test_smoke_flows_around_pillar_and_stops_at_solid_surface_after_reload(tmp_path):
    # Commit and reload the shared flood-fill geometry against the arena pillars.
    svc,table,mid=fight(tmp_path)
    use(svc,table,mid,'Smoke',aim=(9,5))
    eng=cold(svc,mid)
    zone=next(z for z in zones.typed_zones(eng) if PILL in z.source_definition_id)
    from combat.typed_executor import area_cells
    from combat.gate2_runtime_models import Position
    profile=zone.trigger_profile
    flowing=area_cells(eng,zone.center,zone.center,{'shape':'sphere','size_ft':15,'spreads':True})
    straight=area_cells(eng,zone.center,zone.center,{'shape':'sphere','size_ft':15,'spreads':False})
    assert len(flowing)>len(straight), 'no open route around the arena pillars was added'
    blocked={(int(x),int(y)) for x,y in eng.grid.blocked}
    assert not any((cell.x,cell.y) in blocked for cell in flowing), 'smoke crossed a solid barrier'
    assert profile['spreads'] is True


def test_impact_push_distance_is_chosen_by_player(tmp_path):
    svc,table,mid=fight(tmp_path)
    def answer(prompt):
        src=prompt['context']['reaction_source_id']
        if src=='choice:needle.displacement_distance':return '5'
        if src=='choice:needle.directed_movement':return 'east'
        return None
    prompts=use(svc,table,mid,'Impact',answer)
    eng=cold(svc,mid)
    chosen=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.displacement_distance']
    assert chosen and {o['id'] for o in chosen[0]['choice']['options']}=={'15','10','5','0'}
    # A clear route must perform the chosen movement; an unchanged position is not success.
    before=(4,6)
    after=eng.state.actors[FOE].position
    assert (after.x,after.y)==(before[0]+1,before[1])
    moves=[e for e in eng.events if 'MOV' in e.event_type and e.actor_id==FOE]
    assert moves, 'Impact choice committed no movement event'


@pytest.mark.parametrize('answer_id,expected_x', [('0',4),('15',7)])
def test_impact_distance_boundaries_commit_after_reload(tmp_path,answer_id,expected_x):
    svc,table,mid=fight(tmp_path)
    def answer(prompt):
        src=prompt['context']['reaction_source_id']
        if src=='choice:needle.displacement_distance':return answer_id
        if src=='choice:needle.directed_movement':return 'east'
        return None
    use(svc,table,mid,'Impact',answer)
    eng=cold(svc,mid)
    foe=eng.state.actors[FOE]
    assert foe.position.x==expected_x
    moves=[e for e in eng.events if 'MOV' in e.event_type and e.actor_id==FOE]
    assert bool(moves)==(answer_id!='0')


def test_impact_successful_save_pushes_five_feet_after_reload(tmp_path):
    svc,table,mid=fight(tmp_path,dc=1)
    def answer(prompt):
        src=prompt['context']['reaction_source_id']
        if src=='choice:needle.directed_movement':return 'east'
        return None
    use(svc,table,mid,'Impact',answer)
    eng=cold(svc,mid)
    assert (eng.state.actors[FOE].position.x,eng.state.actors[FOE].position.y)==(5,6)
    assert not any(c.condition_id=='condition:typed.prone' for c in eng.state.actors[FOE].conditions.values())


def test_impact_native_barrier_stops_chosen_push_after_reload(tmp_path):
    svc,table,mid=fight(tmp_path,foe_position=(18,6))
    def answer(prompt):
        src=prompt['context']['reaction_source_id']
        if src=='choice:needle.displacement_distance':return '5'
        if src=='choice:needle.directed_movement':return 'east'
        return None
    use(svc,table,mid,'Impact',answer)
    eng=cold(svc,mid)
    # The map's sealed east wall leaves the legal position unchanged.
    assert (eng.state.actors[FOE].position.x,eng.state.actors[FOE].position.y)==(18,6)


@pytest.mark.parametrize('form,condition',[('Frost','speed_ft'),('Venom','poisoned')])
def test_owner_start_removes_the_short_rider_after_reload(tmp_path,form,condition):
    svc,table,mid=fight(tmp_path)
    use(svc,table,mid,form)
    eng=cold(svc,mid)
    foe=eng.state.actors[FOE]
    assert any(PILL in m.source_definition_id for m in foe.modifiers.values()) if form=='Frost' else any(c.condition_id=='condition:typed.poisoned' for c in foe.conditions.values())
    S.to_thief(table,mid,end_thief=True)
    foe=cold(svc,mid).state.actors[FOE]
    assert not any(PILL in m.source_definition_id for m in foe.modifiers.values()) if form=='Frost' else not any(c.condition_id=='condition:typed.poisoned' for c in foe.conditions.values())
