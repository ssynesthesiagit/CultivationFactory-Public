"""Second pass: printed capacity and Circulation through table/reducer transactions."""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, candidate, reload
from tests.test_auto103_daemonic import sow, cycle
from tests.test_a2_daemonic import form_prepare, P, ESSENCE

INSIGHT = 'insight.devil-qi-circulation'


def capacity_setup(b):
    form_prepare(b)
    for r in b[0]['actor_template']['resources']:
        if r['resource_id'] == ESSENCE: r.update(initial=12,maximum=12)
    add_action(b[0], 'End Seed', [{'type':'remove_condition','applies_to':'self','condition':'stance.demon_seed'}], target='SELF')
    seal(b[0])


def test_furnace_capacity_gains_above_base_then_clamps_on_seed_end(tmp_path):
    combat,table,mid=fixture(tmp_path,[P+'SECOND_FURNACE_DEMON_HEART'],bundle_transform=capacity_setup)
    before=reload(tmp_path,mid).state.actors[OWNER]
    assert before.resource_maximums[ESSENCE]==12
    sow(combat,table,mid)
    assert reload(tmp_path,mid).state.actors[OWNER].resource_maximums[ESSENCE]==16
    settle(table,mid,candidate(combat,mid,'Gain Essence').candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[ESSENCE]==13
    settle(table,mid,candidate(combat,mid,'End Seed').candidate_id)
    owner=reload(tmp_path,mid).state.actors[OWNER]
    assert owner.resource_maximums[ESSENCE]==12 and owner.resources[ESSENCE]==12
    cycle(table,mid,OWNER);sow(combat,table,mid)
    assert reload(tmp_path,mid).state.actors[OWNER].resource_maximums[ESSENCE]==16


def test_furnace_capacity_expires_at_real_minute(tmp_path):
    combat,table,mid=fixture(tmp_path,[P+'SECOND_FURNACE_DEMON_HEART'],bundle_transform=capacity_setup)
    sow(combat,table,mid)
    for _ in range(11):cycle(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resource_maximums[ESSENCE]==12
    changes=[ev for ev in e.events if ev.event_type=='RESOURCE_MAXIMUM_CHANGED']
    assert [ev.payload['maximum'] for ev in changes]==[16,12]


def circulation_bundle(cl=15, insight=True, extra=()):
    doc=sheet([P+'HUNGER_REFINING_BREATH',P+'THOUSAND_MOUTH_DEVOURING_ART',P+'DEMON_MARK',*extra],cl=cl,dc=100)
    if insight:doc['spheres_and_talents']['cultivation_insight_record_ids']=[INSIGHT]
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    return compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})


def circulation_setup(b):
    form_prepare(b)
    for index in [1,2]:
        b[index]['actor_template']['maximum_hp']=1000
        b[index]['actor_template']['saving_throws']['CON']=-100
        seal(b[index])
    add_action(b[0],'Single type Daemonic test',[{'type':'save','ability':'con','on_fail':[{'type':'damage','applies_to':'target','flat':2,'damage_types':['necrotic']}],'on_success':[]}])
    test=b[0]['action_catalog'][-1]
    test['parameters']['typed']['source']=P+'HUNGER_REFINING_BREATH'
    seal(b[0])


@pytest.mark.parametrize('kind',['fire','force','acid'])
def test_circulation_replaces_single_type_and_rewards_once_scene(tmp_path,kind):
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=circulation_setup)
    # Settings are unavailable before Seed; the retained selection lasts the scene.
    e=reload(tmp_path,mid)
    assert not [c for c in e.legal_candidates() if 'devil_qi_circulation' in c.source_definition_id]
    sow(combat,table,mid)
    settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: '+kind.title()).candidate_id)
    for _ in range(2):
        settle(table,mid,candidate(combat,mid,'Single type Daemonic test',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids]
    assert len(packets)==2 and all(ev.payload['damage_type']==kind.upper() for ev in packets)
    grants=[ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT]
    assert len(grants)==1 and e.state.actors[OWNER].resources[ESSENCE]==5
    cycle(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Single type Daemonic test',target=FOE).candidate_id)
    assert len([ev for ev in reload(tmp_path,mid).events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1


@pytest.mark.parametrize('prepared_kind',['fire',None])
def test_circulation_actual_ai_multi_recipient_harms_only_enemies(tmp_path,prepared_kind):
    from tests.test_a2_daemonic import select_native_primary
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=circulation_setup)
    sow(combat,table,mid)
    if prepared_kind:
        settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: '+prepared_kind.title()).candidate_id)
    from combat.target_knowledge import can_see
    e=reload(tmp_path,mid)
    assert can_see(e,e.state.actors[OWNER],e.state.actors[ALLY])
    assert e._distance_actor_to_actor(e.state.actors[OWNER],e.state.actors[ALLY])<=60
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    # Select the printed primary; production LOCAL_AUTO handles the nested
    # multiple-recipient choice with both the ally and enemy visible/in range.
    select_native_primary(combat,mid,'Thousand-Mouth Devouring Art',OWNER)
    result=combat.local_step(mid)
    assert result['status']=='COMMITTED',result
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED']
    assert packets and all(ev.target_ids==(FOE,) for ev in packets)
    assert all(ev.payload['damage_type']==(prepared_kind or 'necrotic').upper() for ev in packets)
    assert e.state.actors[ALLY].current_hp==1000
    assert any(c.data.get('kind')==(prepared_kind or 'necrotic') for c in e.state.actors[OWNER].conditions.values())
    assert len([ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1


def test_circulation_initial_type_choice_and_non_damaging_save(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=circulation_setup)
    sow(combat,table,mid)
    cycle(table,mid,OWNER)
    e=reload(tmp_path,mid)
    mark=next(c for c in e.legal_candidates() if c.target_ids==(FOE,)
              and e.action_catalog[c.source_definition_id].display_name.startswith('Demon Mark'))
    prompts=settle(table,mid,mark.candidate_id,
                   {'choice:needle.devil_qi_circulation':'acid'})
    assert any(p['context']['reaction_source_id']=='choice:needle.devil_qi_circulation' for p in prompts)
    e=reload(tmp_path,mid)
    assert any(c.data.get('kind')=='acid' for c in e.state.actors[OWNER].conditions.values())
    assert not [ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT]
    settle(table,mid,candidate(combat,mid,'Single type Daemonic test',target=FOE).candidate_id)
    assert len([ev for ev in reload(tmp_path,mid).events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1


def test_generic_capacity_sources_stack_and_restore_independently(tmp_path):
    def setup(b):
        capacity_setup(b)
        for name,amount in [('A',2),('B',4)]:
            condition={'A':'prone','B':'poisoned'}[name]
            anchor='condition:typed.'+condition
            add_action(b[0],'Capacity '+name,[{'type':'condition','applies_to':'self','condition':condition,'expires_on':'UNTIL_REMOVED'},
                                             {'type':'resource_capacity','resource_id':ESSENCE,'anchor':anchor,'amount':amount}],target='SELF')
            add_action(b[0],'End '+name,[{'type':'remove_condition','applies_to':'self','condition':condition}],target='SELF')
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[P+'DEMON_SEED'],bundle_transform=setup)
    for name in ['A','B','A']:
        settle(table,mid,candidate(combat,mid,'Capacity '+name).candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].resource_maximums[ESSENCE]==18
    settle(table,mid,candidate(combat,mid,'End A').candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].resource_maximums[ESSENCE]==16
    settle(table,mid,candidate(combat,mid,'End B').candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].resource_maximums[ESSENCE]==12


def test_circulation_seed_rider_keeps_its_type_on_other_sphere_variant(tmp_path):
    def setup(b):
        circulation_setup(b)
        b[2]['actor_template']['armor_class']=1
        add_action(b[0],'Other-sphere strike',[{'type':'attack','attack_kind':'unarmed','count':1,
                   'on_hit':[{'type':'damage','applies_to':'target','flat':2,'damage_types':['fire']}],
                   'on_miss':[]}])
        a=b[0]['action_catalog'][-1]
        a['parameters']['typed'].update(source='CONTROL_NON_DAEMONIC',option_of='CONTROL_NON_DAEMONIC_VARIANT')
        seal(b[0]);seal(b[2])
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=setup,foe_position={'x':3,'y':7})
    sow(combat,table,mid)
    settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: Acid').candidate_id)
    settle(table,mid,candidate(combat,mid,'Other-sphere strike',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and ev.actor_id==OWNER]
    assert [ev.payload['damage_type'] for ev in packets]==['FIRE','ACID']
    assert packets[1].payload.get('display_source_id')


def test_circulation_retains_original_type_option_and_only_rewards_selected_type(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=circulation_setup)
    sow(combat,table,mid)
    settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: Fire').candidate_id)
    settle(table,mid,candidate(combat,mid,'Single type Daemonic test',target=FOE).candidate_id,
           {'choice:needle.devil_qi_damage':'necrotic'})
    e=reload(tmp_path,mid)
    assert not [ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT]
    settle(table,mid,candidate(combat,mid,'Single type Daemonic test',target=FOE).candidate_id,
           {'choice:needle.devil_qi_damage':'fire'})
    e=reload(tmp_path,mid)
    assert [ev.payload['damage_type'] for ev in e.events if ev.event_type=='DAMAGE_COMMITTED']==['NECROTIC','FIRE']
    assert len([ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1


def test_circulation_shared_roll_rewards_later_failed_save(tmp_path):
    def setup(b):
        circulation_setup(b)
        b[1]['actor_template']['saving_throws']['CON']=100
        seal(b[1])
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(),bundle_transform=setup)
    sow(combat,table,mid)
    settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: Fire').candidate_id)
    # A deliberate manual choice of both creatures is printed-legal. Automatic
    # recipients are separately covered by the mixed-side enemy-only regression.
    settle(table,mid,candidate(combat,mid,'Thousand-Mouth Devouring Art').candidate_id,
           {'choice:needle.rider_targets':[ALLY,FOE],'choice:needle.devil_qi_damage':'fire'})
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED']
    assert [ev.target_ids for ev in packets]==[(ALLY,),(FOE,)]
    assert all(ev.payload['damage_type']=='FIRE' for ev in packets)
    assert len([ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1


def test_circulation_black_sun_retains_substituted_type_until_resource_spend(tmp_path):
    from tests.worker2_support import turn
    def setup(b):
        circulation_setup(b)
        b[2]['actor_template']['saving_throws']['WIS']=-100
        add_action(b[2],'Spend Qi',[],target='SELF')
        pool=b[2]['actor_template']['resources'][0]['resource_id']
        b[2]['action_catalog'][-1]['costs']=[[pool,1]]
        seal(b[2])
    combat,table,mid=fixture(tmp_path,[],owner_bundle=circulation_bundle(extra=[P+'BLACK_SUN_OVER_THE_DANTIAN']),bundle_transform=setup)
    sow(combat,table,mid)
    settle(table,mid,candidate(combat,mid,'Devil-Qi Circulation: Fire').candidate_id)
    cycle(table,mid,OWNER)
    e=reload(tmp_path,mid)
    sun=next(c for c in e.legal_candidates() if c.target_ids==(FOE,)
             and e.action_catalog[c.source_definition_id].display_name.startswith('Black Sun Over the Dantian'))
    settle(table,mid,sun.candidate_id,{'choice:needle.devil_qi_damage':'fire'})
    e=reload(tmp_path,mid)
    assert not [ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED']
    assert len([ev for ev in e.events if ev.event_type=='RESOURCE_GAINED' and ev.source_definition_id==INSIGHT])==1
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Spend Qi').candidate_id)
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED']
    assert len(packets)==1 and packets[0].payload['damage_type']=='FIRE' and packets[0].target_ids==(FOE,)
