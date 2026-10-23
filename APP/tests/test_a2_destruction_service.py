"""Printed Destruction shapes through accepted table intents and cold reload."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, settle, turn, cell_send
from tests.test_auto62_destruction import triple_fight, OTHER, SPHERE, P
from combat.ext.destruction_shapes import MANTLE_ACTIVE


def marker(e):
    return next(c for c in e.state.actors[LEFT].conditions.values() if c.condition_id == MANTLE_ACTIVE)


def verify(c, m):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    fresh = CombatService(ROOT, c.userdata_root)._load_session(m)
    assert fresh.verify()['status'] == 'PASS'
    assert fresh.mechanical.replay()['status'] == 'PASS'
    return fresh.engine


def auto_sender(c,t,m,label,xy=None):
    from combat.gate4_adapters import ManualControllerAdapter
    real=c.controller
    class Controller:
        def choose_primary_action(self,context):
            chosen=next(v for v in context.legal_candidates if v.display_name.startswith(label)
                and (xy is None or (v.destination is not None and (v.destination.x,v.destination.y)==xy)))
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self,n):return getattr(real,n)
    c.controller=Controller();c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    return lambda answers:t.auto_step(m,t.state(m)['last_sequence'],answers)


@pytest.mark.parametrize('spheres', [[], [SPHERE]], ids=['unrelated', 'destruction-without-crossing'])
def test_unowned_crossing_absent_from_catalog_and_table_after_intent_and_reload(tmp_path, spheres):
    compiled = []
    def capture(bundle):
        compiled.append(bundle)
    c,t,m = fight(tmp_path, spheres=spheres,
        prepare=[{'type':'condition', 'condition':'a2_ownership_probe', 'applies_to':'self'}],
        prepare_target='SELF', bundle_edit=capture)
    # TabletopService.act commits through session.mechanical.execute_intent.
    settle(lambda answers: act(t,m,'Prepare',answers))
    e = verify(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi'] == 100
    assert any(row.condition_id.endswith('a2_ownership_probe')
               for row in e.state.actors[LEFT].conditions.values())
    def crossing(name):
        return name.startswith('Ruin-Crossing Step')
    assert not any(crossing(row['display_name']) for bundle in compiled
                   for row in bundle['action_catalog'])
    assert not any(crossing(row.display_name) for row in e.action_catalog.values())
    from combat.tabletop_service import TabletopService
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    fresh_table = TabletopService(CombatService(ROOT,c.userdata_root),c.userdata_root)
    assert not any(crossing(group['label']) for group in fresh_table.state(m)['menu']['actions'])


@pytest.mark.parametrize('ai', [False, True])
def test_mantle_pulse_hits_every_other_creature_including_ally_and_freezes_parameters(tmp_path, ai):
    c,t,m = triple_fight(tmp_path, [P+'calamity_mantle', P+'withering_break'], spheres=[SPHERE], third_ally=True)
    settle(lambda a: act(t,m,'Blast Type: Withering Break',a))
    settle(lambda a: act(t,m,'Calamity Mantle',a))
    before = reload(c,m)
    frozen = dict(marker(before).data)
    assert frozen['runtime'] == 1 and frozen['final_cp'] == 0
    settle(lambda a: act(t,m,'Blast Type: Unshaped Ruin (Force)',a))
    if ai:
        settle(auto_sender(c,t,m,'Calamity Mantle: Pulse'))
    else:
        settle(lambda a:act(t,m,'Calamity Mantle: Pulse',a))
    e=verify(c,m)
    damage=[v for v in e.events[len(before.events):] if v.event_type=='DAMAGE_COMMITTED']
    assert {a for v in damage for a in v.target_ids} == {RIGHT,OTHER}
    assert all(v.payload['damage_type']=='NECROTIC' for v in damage)
    assert e.state.actors[LEFT].current_hp==before.state.actors[LEFT].current_hp
    assert e.state.actors[OTHER].current_hp < before.state.actors[OTHER].current_hp
    assert all(any(v.target_field=='healing_reduction' for v in e.state.actors[aid].modifiers.values()) for aid in (RIGHT,OTHER))


@pytest.mark.parametrize('remove', [False, True])
def test_mantle_minute_and_late_no_action_concentration_removal_survive_reload(tmp_path, remove):
    c,t,m=fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE],maximum_rounds=20)
    before=reload(c,m).state.actors[LEFT].resources['resource:core.qi']
    settle(lambda a:act(t,m,'Calamity Mantle (1 CP, Concentration)',a))
    e=verify(c,m); row=marker(e); expiry=row.data['expiry'];seq=row.data['concentration_started_sequence']
    assert e.state.actors[LEFT].concentration.started_sequence==seq
    assert e.state.actors[LEFT].resources['resource:core.qi']==before-1
    if remove:
        settle(lambda a:act(t,m,'Calamity Mantle: Remove Concentration (2 CP)',a))
        e=verify(c,m)
        assert marker(e).data['expiry']==expiry and marker(e).expires_on==expiry
        assert e.state.actors[LEFT].concentration is None
        assert e.state.actors[LEFT].resources['resource:core.qi']==before-3
    settle(lambda a:act(t,m,'end',a));turn(t,m,LEFT)
    assert marker(verify(c,m)).data['expiry']==expiry
    for _ in range(9):
        settle(lambda a:act(t,m,'end',a));turn(t,m,LEFT)
    e=verify(c,m)
    assert not any(c.condition_id==MANTLE_ACTIVE for c in e.state.actors[LEFT].conditions.values())
    assert e.state.actors[LEFT].concentration is None


def test_base_mantle_expires_next_turn_and_has_no_reminders(tmp_path):
    c,t,m=fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE])
    settle(lambda a:act(t,m,'Calamity Mantle',a));e=verify(c,m)
    assert marker(e).data['runtime']==1
    settle(lambda a:act(t,m,'end',a));turn(t,m,LEFT)
    e=verify(c,m)
    assert not any(v.condition_id==MANTLE_ACTIVE for v in e.state.actors[LEFT].conditions.values())
    assert not any(v.event_type=='GM_RIDER' for v in e.events)


@pytest.mark.parametrize('length,anywhere,cost',[(10,False,0),(10,True,1),(15,False,1),(30,True,2),(40,False,1)])
def test_crossing_lengths_and_player_landing_survive_reload(tmp_path,length,anywhere,cost):
    c,t,m=fight(tmp_path,[P+'ruin_crossing_step'],spheres=[SPHERE],positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6}})
    before=reload(c,m); qi=before.state.actors[LEFT].resources['resource:core.qi']
    label='Ruin-Crossing Step' if not cost else f'Ruin-Crossing Step: {length} feet'+(', Choose Landing' if anywhere else '')+f' ({cost} CP)'
    landing=(5,6) if anywhere else ((8,6) if length==40 else (3+length//5,6))
    def pick(prompt):
        if prompt['context']['reaction_source_id']=='choice:needle.teleport_destination':
            ids=[o['id'] for o in prompt['choice']['options']]
            assert f'cell:{landing[0]},{landing[1]}' in ids
            return [f'cell:{landing[0]},{landing[1]}']
        return [o['id'] for o in prompt.get('choice',{}).get('options',[])][:1]
    _,prompts=settle(cell_send(t,m,label,(5,6)),pick)
    e=verify(c,m)
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==landing
    assert e.state.actors[LEFT].resources['resource:core.qi']==qi-cost
    assert any(p['context']['reaction_source_id']=='choice:needle.teleport_destination' for p in prompts)
    assert e.state.actors[RIGHT].current_hp < before.state.actors[RIGHT].current_hp
    assert not any(v.event_type=='GM_RIDER' for v in e.events)


def test_paid_mantle_halves_success_damage_and_freezes_deepen(tmp_path):
    c,t,m=fight(tmp_path,[P+'calamity_mantle',P+'withering_break'],spheres=[SPHERE],right_score=214)
    settle(lambda a:act(t,m,'Blast Type: Withering Break',a))
    settle(lambda a:act(t,m,'Deepen the Calamity: on',a))
    settle(lambda a:act(t,m,'Calamity Mantle (1 CP, Concentration)',a))
    before=verify(c,m);qi=before.state.actors[LEFT].resources['resource:core.qi'];stored=dict(marker(before).data)
    assert stored['dice_count']==8 and stored['final_cp']>0
    settle(lambda a:act(t,m,'Deepen the Calamity: off',a))
    settle(lambda a:act(t,m,'Calamity Mantle: Pulse',a))
    e=verify(c,m)
    events=e.events[len(before.events):]
    saves=[v for v in events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT]
    damage=[v for v in events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    rolls=[v for v in events if v.event_type=='DAMAGE_ROLLED' and RIGHT in v.target_ids]
    assert saves and all(v.payload['success'] for v in saves)
    assert damage and rolls and damage[0].payload['hp_damage']==rolls[0].payload['total']//2
    assert e.state.actors[LEFT].resources['resource:core.qi']==qi
    assert not any(v.target_field=='healing_reduction' for v in e.state.actors[RIGHT].modifiers.values())


def test_mantle_ends_on_failed_concentration(tmp_path):
    c,t,m=fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE],
        cause=[{'type':'damage','flat':400,'damage_types':['force']}])
    settle(lambda a:act(t,m,'Calamity Mantle (1 CP, Concentration)',a))
    assert marker(verify(c,m)).expires_on=='CONCENTRATION_END'
    settle(lambda a:act(t,m,'end',a));turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=verify(c,m)
    assert not any(v.condition_id==MANTLE_ACTIVE for v in e.state.actors[LEFT].conditions.values())
    assert any(v.event_type=='CONCENTRATION_ENDED' for v in e.events)


@pytest.mark.parametrize("ai", [False, True])
def test_crossing_area_harms_enemies_only_and_prompt_picks_landing(tmp_path, ai):
    from tests.auto_worker1_support import ALLY
    c,t,m=fight(tmp_path,[P+'ruin_crossing_step'],spheres=[SPHERE],ally=[],
        positions={LEFT:{'x':3,'y':6},ALLY:{'x':4,'y':6},RIGHT:{'x':5,'y':6}})
    before=reload(c,m)
    _,prompts=settle(auto_sender(c,t,m,'Ruin-Crossing Step: 10 feet, Choose Landing (1 CP)',(5,6)) if ai else cell_send(t,m,'Ruin-Crossing Step: 10 feet, Choose Landing (1 CP)',(5,6)))
    e=verify(c,m)
    assert e.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp
    assert e.state.actors[RIGHT].current_hp < before.state.actors[RIGHT].current_hp
    if not ai:
        assert any(p['context']['reaction_source_id']=='choice:needle.teleport_destination' for p in prompts)


def test_removing_mantle_concentration_preserves_older_technique(tmp_path):
    def edit(bundle):
        for a in bundle['action_catalog']:
            if a['display_name']=='Prepare':
                a['parameters']['typed']['duration']={'kind':'minutes','amount':1,'concentration':True}
    c,t,m=fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE],prepare_target='SELF',
        prepare=[{'type':'condition','condition':'a2_other_concentration','applies_to':'self'}],bundle_edit=edit)
    settle(lambda a:act(t,m,'Prepare',a))
    older=verify(c,m).state.actors[LEFT].concentration.started_sequence
    settle(lambda a:act(t,m,'Calamity Mantle (1 CP, Concentration)',a))
    assert marker(verify(c,m)).data['concentration_started_sequence'] != older
    settle(lambda a:act(t,m,'Calamity Mantle: Remove Concentration (2 CP)',a))
    e=verify(c,m)
    assert e.state.actors[LEFT].concentration.started_sequence==older
    assert any(v.condition_id.endswith('a2_other_concentration') for v in e.state.actors[LEFT].conditions.values())
    assert marker(e).expires_on==marker(e).data['expiry']


def test_markerless_saved_mantle_keeps_legacy_state_and_enemy_only_pulse(tmp_path):
    def legacy(bundle):
        for a in bundle['action_catalog']:
            for row in a.get('parameters',{}).get('typed',{}).get('effects',[]):
                if row.get('type')=='destruction_calamity_mantle_activate':row.pop('runtime',None)
    c,t,m=triple_fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE],third_ally=True,bundle_edit=legacy)
    settle(lambda a:act(t,m,'Calamity Mantle',a));before=verify(c,m)
    assert 'runtime' not in marker(before).data
    settle(lambda a:act(t,m,'Calamity Mantle: Pulse',a));e=verify(c,m)
    assert e.state.actors[OTHER].current_hp==before.state.actors[OTHER].current_hp
    assert e.state.actors[RIGHT].current_hp<before.state.actors[RIGHT].current_hp


def test_frozen_crushing_mantle_keeps_collision_refinement_after_type_change(tmp_path):
    # The arena's pillar at 9,6 is stationary; an allied blocker would be
    # pulsed first and pushed out of the way before the enemy's blast.
    c,t,m=fight(tmp_path,[P+'calamity_mantle',P+'crushing_break',P+'fracturing_break',P+'hammer_through_the_line'],
        spheres=[SPHERE],positions={LEFT:{'x':7,'y':6},RIGHT:{'x':8,'y':6}})
    settle(lambda a:act(t,m,'Blast Type: Crushing Break',a))
    settle(lambda a:act(t,m,'Calamity Mantle',a));before=verify(c,m)
    settle(lambda a:act(t,m,'Blast Type: Fracturing Break',a))
    settle(lambda a:act(t,m,'Calamity Mantle: Pulse',a));e=verify(c,m)
    assert any(v.condition_id.endswith('prone') for v in e.state.actors[RIGHT].conditions.values())
    damage=[v for v in e.events[len(before.events):] if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    assert len(damage)==2 and all(v.payload['damage_type']=='BLUDGEONING' for v in damage)


def test_mantle_finishes_all_recipients_when_last_enemy_drops(tmp_path):
    from tests.auto_worker1_support import ALLY
    def fragile(doc,aid):
        if aid != LEFT:doc['ability_scores_and_statistics']['hit_points']['maximum']=1
    c,t,m=fight(tmp_path,[P+'calamity_mantle'],spheres=[SPHERE],ally=[],sheet_edit=fragile,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':3,'y':5}})
    settle(lambda a:act(t,m,'Calamity Mantle',a))
    settle(lambda a:act(t,m,'Calamity Mantle: Pulse',a));e=verify(c,m)
    assert e.state.actors[RIGHT].current_hp==0
    assert e.state.actors[ALLY].current_hp==0
    assert e.state.actors[LEFT].current_hp==1000


@pytest.mark.parametrize('upward', [False, True], ids=['down', 'up'])
@pytest.mark.parametrize('anywhere', [False, True], ids=['endpoint', 'chosen'])
def test_vertical_crossing_commits_altitude_and_player_choice_after_cold_replay(tmp_path, upward, anywhere):
    length = 15 if anywhere else 10
    start_z = 0 if upward else (4 if anywhere else 3)
    enemy_z = start_z + (1 if upward else -1)
    landing_z = 2 if anywhere or upward else 1
    def flying(bundle):
        # Seal native flight before creation so turn-start falling cannot erase the aim.
        bundle['actor_template'].update(fly_speed_ft=30, hover=True)
    c,t,m = fight(tmp_path,[P+'ruin_crossing_step'],spheres=[SPHERE],bundle_edit=flying,
        positions={LEFT:{'x':3,'y':6,'z':start_z}, RIGHT:{'x':3,'y':6,'z':enemy_z}})
    before = verify(c,m)
    label = 'Ruin-Crossing Step: 15 feet, Choose Landing (2 CP)' if anywhere else 'Ruin-Crossing Step'
    def send(answers):
        state = t.state(m)
        menu = state['menu']
        engine = c._load_session(m).engine
        source = next(key for key,row in engine.action_catalog.items() if row.display_name == label)
        candidate = next(v for v in engine.legal_candidates()
            if v.source_definition_id == source and v.destination is not None
            and (v.destination.x,v.destination.y,v.destination.z) == (3,6,enemy_z))
        return t.act(m,candidate.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    def pick(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.teleport_destination':
            options = prompt['choice']['options']
            ids = [o['id'] for o in options]
            assert len(ids) == len(set(ids))
            chosen = f'cell:3,6,{landing_z}'
            assert chosen in ids
            assert any(str(landing_z * 5) in o['label'] and 'feet' in o['label'] for o in options if o['id'] == chosen)
            return [chosen]
        return [o['id'] for o in prompt.get('choice',{}).get('options',[])][:1]
    _,prompts = settle(send,pick)
    e = verify(c,m)
    actor = e.state.actors[LEFT]
    assert (actor.position.x,actor.position.y,actor.position.z) == (3,6,landing_z)
    assert actor.resources['resource:core.qi'] == before.state.actors[LEFT].resources['resource:core.qi'] - (2 if anywhere else 0)
    assert e.state.actors[RIGHT].current_hp < before.state.actors[RIGHT].current_hp
    assert any(p['context']['reaction_source_id']=='choice:needle.teleport_destination' for p in prompts)
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==LEFT and v.payload['destination']['z']==landing_z
               for v in e.events[len(before.events):])
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
