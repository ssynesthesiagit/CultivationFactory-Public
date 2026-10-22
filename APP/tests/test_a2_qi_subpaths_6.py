"""Qi subpath combat rules through service intents, sealed fixtures and reload.

Fixture actions produce saves, pushes and falls through native effect dispatch;
they grant no feature behavior. All benefits under test come from owned rows.
"""
from copy import deepcopy
import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

EARTH = 'tianxia.subpath.qi.mountain_core_cultivator.feature.earth_resilience'
FLOW = 'tianxia.subpath.qi.yin_yang_cultivator.feature.balanced_flow'
QI = 'resource:core.qi'


def prepare(bundles, *, airborne=False, surface=None, large=False):
    for b in bundles:
        if b['actor_id'] == OWNER:
            if airborne:
                b['actor_template'].update(fly_speed_ft=30, hover=True)
        if b['actor_id'] == FOE:
            if large:
                b['actor_template']['size_category'] = 'Large'
            base = deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Grapple'))
            numbers = deepcopy(base['parameters']['typed']['numbers'])
            numbers['attack_bonus'] = 100
            numbers['save_dc'] = 100
            actions = {
                'Probe attack': [{'type':'attack','attack_kind':'cultivation_ranged', 'on_hit':[
                    {'type':'damage','flat':1,'formula':'none','damage_types':['force']}]}],
                'Probe save': [{'type':'save','ability':'str','on_fail':[], 'on_success':[]}],
                'Probe push': [{'type':'forced_movement','applies_to':'target','distance_ft':20,'direction':'away'}],
                'Probe size': [{'type':'save','ability':'str','max_size_larger':1,
                    'on_fail':[{'type':'forced_movement','distance_ft':20,'direction':'away'}]}],
            }
            for name, effects in actions.items():
                a = deepcopy(base)
                a.update(source_definition_id='action:test.qisub6.'+name.replace(' ','_'), display_name=name,
                         economy='NONE', target_kind='HOSTILE_ENTITY', range_ft=100, costs=[])
                a['parameters']={'typed': {'source': name, 'effects':effects,'numbers':numbers,
                    'duration':{'kind':'instant'},'riders':[]},'expected_damage':0,'free_primary':True}
                b['action_catalog'].append(a)
                b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256',None)
        b['bundle_sha256']=canonical_sha256(b)


def _act(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat,mid,name,target=target).candidate_id)


@pytest.mark.parametrize('owns,airborne,expected_ac,expected_mode,pushed',[
    (True,False,15,'ADVANTAGE',10),(False,False,14,'NORMAL',20),
    (True,True,14,'NORMAL',20)])
def test_earth_grounded_queries_real_packets_reload(tmp_path, owns, airborne, expected_ac, expected_mode, pushed):
    combat,table,mid=fixture(tmp_path,[EARTH] if owns else [],
        positions={OWNER:{'x':5,'y':8,**({'z':2} if airborne else {})},
                   ALLY:{'x':3,'y':3},FOE:{'x':3,'y':8}},
        bundle_transform=lambda b:prepare(b,airborne=airborne),seed='QISUB6-EARTH')
    turn(table,mid,FOE)
    _act(combat,table,mid,'Probe attack',OWNER)
    engine=reload(tmp_path,mid)
    attack=[e for e in engine.events if e.event_type=='ATTACK_ROLLED'][-1]
    assert attack.payload['target_ac']==expected_ac
    _act(combat,table,mid,'Probe save',OWNER)
    engine=reload(tmp_path,mid)
    save=[e for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]
    assert save.payload['mode']==expected_mode
    before=engine.state.actors[OWNER].position
    _act(combat,table,mid,'Probe push',OWNER)
    engine=reload(tmp_path,mid)
    assert engine.grid.distance_ft(before,engine.state.actors[OWNER].position)==pushed
    assert not any(e.event_type=='GM_RIDER' and EARTH in e.source_definition_id for e in engine.events)


@pytest.mark.parametrize('current', ['yin','yang'])
def test_flow_palm_cost_recipients_and_cold_reload(tmp_path,current):
    combat,table,mid=fixture(tmp_path,[FLOW],seed='QISUB6-PALM')
    # Change the current on the next actual turn via the turn-start transport.
    while table.state(mid)['menu']['actor_id']==OWNER:
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    for _ in range(5):
        if table.state(mid)['menu']['actor_id']==OWNER:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.balanced_flow':[current]})
    engine=reload(tmp_path,mid)
    condition=next(c for c in engine.state.actors[OWNER].conditions.values()
                   if c.condition_id=='condition:typed.yin_yang_current')
    assert condition.data['current']==current
    if current=='yin':
        assert 'Speed by 10 feet until the start of your next turn' in condition.data['label']
    else:
        assert 'Proficiency Bonus (4)' in condition.data['label'] and 'once per turn' in condition.data['label']
    # Ordinary healing still rolls at full HP; TEMP_HP_GRANT verifies recipient.
    qi=engine.state.actors[OWNER].resources[QI]
    settle(table,mid,candidate(combat,mid,'Restorative Palm',target=ALLY).candidate_id,
           choices={'choice:needle.restorative_palm_step':['cell:4,5']})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[QI]==qi-2
    hp_events=[e for e in engine.events if e.event_type=='HEALING_APPLIED']
    assert hp_events[-1].target_ids==(ALLY,)
    if current=='yin':
        assert engine.state.actors[ALLY].temporary_hp==4
        assert engine.state.actors[OWNER].temporary_hp==0
        assert engine.state.actors[FOE].temporary_hp==0
    else:
        assert engine.state.actors[ALLY].temporary_hp==0
        assert any(e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY for e in engine.events)
    assert not any(e.event_type=='GM_RIDER' and FLOW in e.source_definition_id for e in engine.events)

@pytest.fixture(autouse=True)
def fixture_world_effects(monkeypatch):
    from combat import ext, falling
    def launch(ctx, effect):
        falling.displace(ctx.engine, ctx.target, 4, ctx.source, intent=ctx.intent)
    def footing(ctx, effect):
        ctx.engine._apply_condition(ctx.target, 'condition:typed.fixture_surface', ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'rule': {'surface_contact': dict(effect['contact'])}, 'label':'Fixture footing'})
    def incorporeal(ctx, effect):
        ctx.engine._apply_condition(ctx.target,'condition:typed.fixture_incorporeal',ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data={'rule':{'incorporeal':True}})
    def ailment(ctx, effect):
        data={'origin_save':{'ability':'CON','dc':1},'ration_save_category':effect.get('category')}
        if 'label' in effect:
            data['label']=effect['label']
        ctx.engine._apply_condition(ctx.target,'condition:typed.'+effect['name'],ctx.source,ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',data=data)
    def large(ctx, effect):
        from combat.dynamic_size import apply_growth
        apply_growth(ctx.engine,ctx.target,'Large',ctx.source,source_actor_id=ctx.actor.entity_id,expires_on='UNTIL_REMOVED')
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_large',large)
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_ailment',ailment)
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_launch',launch)
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_surface',footing)
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_incorporeal',incorporeal)


def extra_prepare(bundles, name, effects, *, large_owner=False):
    prepare(bundles)
    for b in bundles:
        if b['actor_id']==FOE:
            a=deepcopy(next(a for a in b['action_catalog'] if a['display_name']=='Probe push'))
            a.update(display_name=name,source_definition_id='action:test.qisub6.extra')
            a['parameters']['typed'].update(source='QISUB6-extra',effects=([{'type':'qisub6_fixture_large'}] if large_owner else [])+deepcopy(effects))
            b['action_catalog'].append(a)
            b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256',None)
        b['bundle_sha256']=canonical_sha256(b)


@pytest.mark.parametrize('owns', [False,True])
def test_earth_actual_fall_landing_reduction_and_reload(tmp_path,owns):
    combat,table,mid=fixture(tmp_path,[EARTH] if owns else [],cl=6,
        bundle_transform=lambda b:extra_prepare(b,'Probe launch',[{'type':'qisub6_fixture_launch'}]),
        seed='QISUB6-FALL')
    turn(table,mid,FOE)
    _act(combat,table,mid,'Probe launch',OWNER)
    engine=reload(tmp_path,mid)
    falls=[e for e in engine.events if e.event_type=='PASSIVE_TRIGGERED' and 'fall_distance_ft' in e.payload]
    assert falls and falls[-1].payload['fall_distance_ft']==20
    assert engine.state.actors[OWNER].position.z==0
    taken=falls[-1].payload['damage_taken']
    assert (taken==0) if owns else (taken>0)
    assert any(c.condition_id=='condition:typed.prone' for c in engine.state.actors[OWNER].conditions.values()) is (not owns)


@pytest.mark.parametrize('contact', [
    {'material':'wood','stable':True,'touching':True},
    {'material':'water','stable':False,'touching':False},
    {'material':'metal','stable':False,'touching':True},
    {'material':'stone','stable':True,'touching':True}])
def test_earth_authored_footing_veto_survives_commit_reload(tmp_path,contact):
    combat,table,mid=fixture(tmp_path,[EARTH],bundle_transform=lambda b:extra_prepare(b,
        'Probe footing',[{'type':'qisub6_fixture_surface','contact':contact}]),seed='QISUB6-SURFACE')
    turn(table,mid,FOE)
    _act(combat,table,mid,'Probe footing',OWNER)
    reload(tmp_path,mid)
    _act(combat,table,mid,'Probe attack',OWNER)
    engine=reload(tmp_path,mid)
    [attack]=[e for e in engine.events if e.event_type=='ATTACK_ROLLED']
    assert attack.payload['target_ac']==(15 if contact['material']=='stone' else 14)


@pytest.mark.parametrize('owns', [True,False])
def test_earth_effective_shove_size_keeps_large_target_out_of_medium_shove(tmp_path,owns):
    combat,table,mid=fixture(tmp_path,[EARTH] if owns else [],bundle_transform=lambda b:extra_prepare(b,
        'Limited shove',[{'type':'save','ability':'str','max_size_larger':1,
            'on_fail':[{'type':'forced_movement','applies_to':'target','distance_ft':20,'direction':'away'}]}],large_owner=True),
        positions={OWNER:{'x':5,'y':11},ALLY:{'x':3,'y':3},FOE:{'x':3,'y':11}},seed='QISUB6-SIZE')
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    _act(combat,table,mid,'Limited shove',OWNER)
    engine=reload(tmp_path,mid)
    assert engine.grid.distance_ft(before,engine.state.actors[OWNER].position)==(0 if owns else 20)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED']
    assert len(saves)==(0 if owns else 1)


def flow_prepare(bundles):
    prepare(bundles)
    for b in bundles:
        if b['actor_id']==OWNER:
            a=deepcopy(next(a for a in b['action_catalog'] if a['display_name']=='Grapple'))
            for label,effect in [('Qi packet',{'type':'damage','dice':{'count':1,'sides':4},'formula':'none','damage_types':['force']}),
                                 ('Qi healing',{'type':'healing','dice':{'count':1,'sides':4},'formula':'none'})]:
                row=deepcopy(a)
                row.update(display_name=label,source_definition_id='action:test.qisub6.'+label.replace(' ','_'),
                    economy='NONE',range_ft=100,target_kind='ANY_CREATURE',costs=[[QI,1]])
                row['parameters']={'typed':{'source':label,'numbers':deepcopy(a['parameters']['typed']['numbers']),
                    'effects':[{'applies_to':'target',**effect}],'duration':{'kind':'instant'},'riders':[]},'expected_damage':0,'free_primary':True}
                b['action_catalog'].append(row)
                b['actor_template']['action_ids'].append(row['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


def choose_current(table,mid,current):
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    for _ in range(5):
        if table.state(mid)['menu']['actor_id']==OWNER:return
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={'choice:needle.balanced_flow':[current]})
    raise AssertionError('No owner turn')


def test_flow_yang_bonus_shared_by_damage_healing_then_resets(tmp_path):
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=flow_prepare,seed='QISUB6-YANG')
    choose_current(table,mid,'yang')
    _act(combat,table,mid,'Qi packet',FOE)
    engine=reload(tmp_path,mid)
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and FOE in e.target_ids][-1]
    roll=[r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1]
    assert roll.modifier==4
    assert damage.payload['reduced_to']==roll.total
    _act(combat,table,mid,'Qi healing',ALLY)
    engine=reload(tmp_path,mid)
    rolls=[r for r in engine.rolls if r.reason.startswith('HEALING:')]
    assert rolls[-1].modifier==0
    choose_current(table,mid,'yang')
    _act(combat,table,mid,'Qi packet',FOE)
    engine=reload(tmp_path,mid)
    assert [r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1].modifier==4


def test_flow_yang_player_can_save_bonus_for_later_roll_service_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=flow_prepare,seed='QISUB6-YANG-CHOICE')
    choose_current(table,mid,'yang')
    prompts=settle(table,mid,candidate(combat,mid,'Qi packet',target=FOE).candidate_id,
        choices={'choice:needle.balanced_yang':['save']})
    ballot=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.balanced_yang')
    assert 'Proficiency Bonus (4)' in next(o['label'] for o in ballot['choice']['options'] if o['id']=='increase')
    assert 'later damage or healing roll' in next(o['label'] for o in ballot['choice']['options'] if o['id']=='save')
    trigger=ballot['moment']
    assert ballot['action']=='Qi packet' and ballot['by']==reload(tmp_path,mid).state.actors[FOE].display_name
    assert 'damage roll' in trigger.lower() and reload(tmp_path,mid).state.actors[FOE].display_name in trigger
    engine=reload(tmp_path,mid)
    damage=[r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1]
    assert damage.modifier==0
    assert engine.state.actors[OWNER].turn_flags.get('_round_balanced_yang') is None
    prompts=settle(table,mid,candidate(combat,mid,'Qi healing',target=ALLY).candidate_id,
        choices={'choice:needle.balanced_yang':['increase']})
    ballot=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.balanced_yang')
    trigger=ballot['moment']
    assert ballot['action']=='Qi healing' and ballot['by']==reload(tmp_path,mid).state.actors[ALLY].display_name
    assert 'healing roll' in trigger.lower() and reload(tmp_path,mid).state.actors[ALLY].display_name in trigger
    engine=reload(tmp_path,mid)
    healing=[r for r in engine.rolls if r.reason.startswith('HEALING:')][-1]
    assert healing.modifier==4
    assert engine.state.actors[OWNER].turn_flags['_round_balanced_yang']==f"{engine.state.round_number}:{OWNER}"


def test_flow_yang_owner_choice_applies_to_qi_area_damage_on_another_turn(tmp_path):
    def setup(bundles):
        flow_prepare(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        base=deepcopy(next(a for a in owner['action_catalog'] if a['display_name']=='Grapple'))
        action=deepcopy(base)
        action.update(display_name='Qi hazard',source_definition_id='action:test.qisub6.qi_hazard',
            economy='ACTION',target_kind='SELF',range_ft=None,costs=[[QI,1]])
        zone_spec={'shape':'sphere','size_ft':30,'centered_on_self':True,
            'duration':{'kind':'rounds','amount':10},'name':'Qi hazard',
            'triggers':[{'name':'Qi hazard','on':['start'],'who':'any','effects':[
                {'type':'save','ability':'DEX','on_success':[],'on_fail':[
                    {'type':'damage','dice':{'count':1,'sides':4},'formula':'none','damage_types':['force']}]}]}]}
        action['parameters']={'typed':{'source':'Qi hazard','sphere':'tianxia.sphere.qi_cultivation',
            'numbers':deepcopy(base['parameters']['typed']['numbers']),'effects':[
                {'type':'zone','applies_to':'self','distance_ft':5,'duration':'one_minute'}],
            'duration':{'kind':'instant'},'riders':[],'zone_spec':zone_spec},'expected_damage':0}
        owner['action_catalog'].append(action);owner['actor_template']['action_ids'].append(action['source_definition_id'])
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=setup,seed='QISUB6-YANG-OFFTURN')
    choose_current(table,mid,'yang')
    settle(table,mid,candidate(combat,mid,'Qi hazard').candidate_id)
    # The next actor's start-of-turn zone trigger resolves a roll owned by OWNER.
    menu=table.state(mid)['menu']
    prompts=settle(table,mid,menu['end_turn'],choices={'choice:needle.balanced_yang':['save']})
    engine=reload(tmp_path,mid)
    choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.balanced_yang')
    assert choice['context']['reactor_id']==OWNER
    assert engine.state.current_actor_id != OWNER
    trigger=choice['moment']
    assert choice['action']=='Qi hazard'
    assert 'damage roll' in trigger.lower() and 'Qi hazard' in trigger
    group = choice['by']
    for actor_id in (OWNER, ALLY, FOE):
        name=engine.state.actors[actor_id].display_name
        assert name in trigger and name in group
    assert [r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1].modifier==0
    assert engine.state.actors[OWNER].turn_flags.get('_round_balanced_yang') is None


def test_flow_ai_yin_harms_enemy_and_preserves_limit_after_ally_damage(tmp_path):
    from tests.test_c2_review import auto_send
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=flow_prepare,ask=False,seed='QISUB6-YIN')
    assert auto_send(combat,table,mid,candidate(combat,mid,'Qi packet',target=ALLY).candidate_id)['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[ALLY])==30
    assert auto_send(combat,table,mid,candidate(combat,mid,'Qi packet',target=FOE).candidate_id)['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[FOE])==20
    assert engine._effective_speed(engine.state.actors[OWNER])==30
    assert auto_send(combat,table,mid,candidate(combat,mid,'Qi packet',target=FOE).candidate_id)['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[FOE])==20
    choose_current(table,mid,'yin')
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[FOE])==30


def test_flow_yin_player_option_label_is_readable_service_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=flow_prepare,seed='QISUB6-YIN-LABEL')
    choose_current(table,mid,'yin')
    prompts=settle(table,mid,candidate(combat,mid,'Qi packet',target=FOE).candidate_id,
                   choices={'choice:needle.balanced_yin':[FOE]})
    ballot=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.balanced_yin')
    label=next(o['label'] for o in ballot['choice']['options'] if o['id']==FOE)
    assert label==f"Reduce {reload(tmp_path,mid).state.actors[FOE].display_name}'s Speed by 10 feet"
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[FOE])==20


RATION = 'tianxia.subpath.qi.culinary_cultivator.feature.sealed_field_rations'
RP = 'resource:named.sealed_field_ration.0'


def ration_kit(kind,count=2,age=0):
    return {'sealed_field_rations':[{'kind':kind,'count':count,'age_hours':age,
        'maker_cl':15,'maker_pb':4,'maker_key_mod':2}]}


@pytest.mark.parametrize('kind',['restorative','fortifying','marching','bracing'])
def test_ration_administer_recipient_stock_turn_limit_cold_reload(tmp_path,kind):
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit(kind),seed='QISUB6-RATION-'+kind)
    name='Administer '+kind.title()+' Ration'
    picks={'choice:needle.marching_ration':['cell:4,5']}
    settle(table,mid,candidate(combat,mid,name,target=ALLY).candidate_id,choices=picks)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[RP]==1
    assert engine.state.actors[OWNER].resource_maximums[RP]==2
    assert not [c for c in engine.legal_candidates() if c.display_name==name and c.target_ids==(ALLY,)]
    assert not [c for c in engine.legal_candidates() if c.display_name==name and c.target_ids==(FOE,)]
    if kind=='restorative':
        assert [e for e in engine.events if e.event_type=='HEALING_APPLIED'][-1].target_ids==(ALLY,)
    if kind=='fortifying':
        assert engine.state.actors[ALLY].temporary_hp>=4
        assert engine.state.actors[OWNER].temporary_hp==0
        assert engine.state.actors[FOE].temporary_hp==0
    if kind=='marching':
        assert engine.state.actors[ALLY].position.y==5
        assert any(c.condition_id=='condition:typed.culinary_marching' for c in engine.state.actors[ALLY].conditions.values())
    if kind=='bracing':
        assert any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('age', [0,24,25])
def test_ration_expiry_and_no_unrecorded_servings(tmp_path,age):
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('restorative',age=age),seed='QISUB6-AGE')
    engine=reload(tmp_path,mid)
    rations=[c for c in engine.legal_candidates() if c.display_name=='Consume Restorative Ration']
    assert bool(rations)==(age<24)
    if rations:
        settle(table,mid,rations[0].candidate_id)
        engine=reload(tmp_path,mid)
        assert engine.state.actors[OWNER].resources[RP]==1
        assert engine.state.actors[OWNER].bonus_action_available is False
        assert engine.state.actors[OWNER].action_available


def test_fractional_ration_age_is_integer_only_after_compile_commit_reload(tmp_path):
    age=0.5
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('restorative',age=age),seed='QISUB6-AGE-FRACTION')
    engine=reload(tmp_path,mid)
    action=next(a for a in engine.action_catalog.values() if a.display_name=='Consume Restorative Ration')
    stored=action.parameters['culinary_ration']
    assert stored['age_seconds']==1800
    assert stored['remaining_rounds']==14100
    assert 'age_hours' not in stored
    assert type(stored['age_seconds']) is int and type(stored['remaining_rounds']) is int
    assert not any(type(v) is float for v in stored.values())
    settle(table,mid,candidate(combat,mid,'Consume Restorative Ration').candidate_id)
    engine=reload(tmp_path,mid)
    action=next(a for a in engine.action_catalog.values() if a.display_name=='Consume Restorative Ration')
    assert action.parameters['culinary_ration']['age_seconds']==1800
    assert 'age_hours' not in action.parameters['culinary_ration']


def test_nearly_expired_ration_is_available_at_cutoff_then_expires(tmp_path):
    # 23:59:53 leaves one six-second combat round in the integer clock.
    age=23 + 59/60 + 53/3600
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('restorative',age=age),seed='QISUB6-AGE-BOUNDARY')
    engine=reload(tmp_path,mid)
    row=next(a.parameters['culinary_ration'] for a in engine.action_catalog.values()
             if a.display_name=='Consume Restorative Ration')
    assert row['remaining_rounds']==1
    assert any(c.display_name=='Consume Restorative Ration' for c in engine.legal_candidates())
    # Advancing a full initiative cycle moves the fight from round 1 to 2.
    for _ in range(3):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    assert engine.state.round_number==2
    assert not any(c.display_name=='Consume Restorative Ration' for c in engine.legal_candidates())


def test_ration_feature_without_prepared_items_has_no_free_serving(tmp_path):
    combat,table,mid=fixture(tmp_path,[RATION],seed='QISUB6-EMPTY')
    engine=reload(tmp_path,mid)
    assert not any('Ration' in c.display_name for c in engine.legal_candidates())
    assert not any(k.startswith('resource:named.sealed_field_ration.') for k in engine.state.actors[OWNER].resources)

@pytest.mark.parametrize('kind,name,category', [('bitter','poisoned',None),('courage','frightened',None),
    ('bitter','fixture_disease','disease'),('courage','fixture_morale','morale')])
@pytest.mark.parametrize('source_cl,mode', [(15,'ADVANTAGE'),(21,'NORMAL')])
def test_ration_repeat_original_save_authority_and_removal(tmp_path,kind,name,category,source_cl,mode):
    def setup(bundles):
        extra_prepare(bundles,'Apply ailment',[{'type':'qisub6_fixture_ailment','name':name,'category':category}])
        for b in bundles:
            if b['actor_id']==FOE:
                b['cl']=source_cl
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit(kind),bundle_transform=setup,seed='QISUB6-REPEAT')
    turn(table,mid,FOE)
    _act(combat,table,mid,'Apply ailment',ALLY)
    reload(tmp_path,mid)
    turn(table,mid,OWNER)
    _act(combat,table,mid,'Administer '+kind.title()+' Ration',ALLY)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY]
    assert len(saves)==1 and saves[0].payload['mode']==mode and saves[0].payload['dc']==1
    assert not any(c.condition_id=='condition:typed.'+name for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[OWNER].resources[RP]==1


def test_ration_repeat_custom_unlabeled_condition_has_readable_choice(tmp_path):
    def setup(bundles):
        extra_prepare(bundles,'Apply ailment',[{'type':'qisub6_fixture_ailment','name':'custom_mycotoxin',
            'category':'bodily_toxin'}])
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('bitter'),bundle_transform=setup,
        seed='QISUB6-RATION-READABLE')
    turn(table,mid,FOE)
    _act(combat,table,mid,'Apply ailment',ALLY)
    turn(table,mid,OWNER)
    prompts=settle(table,mid,candidate(combat,mid,'Administer Bitter Ration',target=ALLY).candidate_id)
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ration_repeat')
    assert next(o['label'] for o in prompt['choice']['options'] if 'custom_mycotoxin' in o['id'])=='Custom Mycotoxin'


def test_bracing_one_native_save_consumes_the_death_save_benefit_too(tmp_path):
    def setup(b):
        prepare(b)
        owner=next(v for v in b if v['actor_id']==OWNER)
        foe=next(v for v in b if v['actor_id']==FOE)
        a=deepcopy(next(a for a in foe['action_catalog'] if a['display_name']=='Probe save'))
        a.update(owner_id=OWNER,target_kind='ANY_CREATURE',source_definition_id='action:test.qisub6.owner_save')
        owner['action_catalog'].append(a);owner['actor_template']['action_ids'].append(a['source_definition_id'])
        for bundle in b:
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('bracing'),bundle_transform=setup,seed='QISUB6-BRACING')
    _act(combat,table,mid,'Administer Bracing Ration',ALLY)
    reload(tmp_path,mid)
    _act(combat,table,mid,'Probe save',ALLY)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY][-1].payload['mode']=='ADVANTAGE'
    assert not any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())
    _act(combat,table,mid,'Probe save',ALLY)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY][-1].payload['mode']=='NORMAL'


def test_bracing_expires_at_end_of_recipient_next_turn_after_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('bracing'),seed='QISUB6-BRACING-EXPIRY')
    _act(combat,table,mid,'Administer Bracing Ration',ALLY)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    assert engine.state.current_actor_id==ALLY
    assert any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())


def test_bracing_advantage_applies_to_first_death_save_service_reload(tmp_path,monkeypatch):
    from combat.ext import life_state
    monkeypatch.setattr(life_state,'DEATH_SAVES_FOR_ALL',True)
    def setup(bundles):
        prepare(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        foe=next(b for b in bundles if b['actor_id']==FOE)
        action=deepcopy(next(a for a in foe['action_catalog'] if a['display_name']=='Probe attack'))
        action.update(display_name='Probe bracing hit',owner_id=OWNER,target_kind='ANY_CREATURE',
            source_definition_id='action:test.qisub6.probe_bracing_hit')
        action['parameters']['typed']['effects'][0]['on_hit'][0]['flat']=5
        owner['action_catalog'].append(action);owner['actor_template']['action_ids'].append(action['source_definition_id'])
        ally=next(b for b in bundles if b['actor_id']==ALLY)
        ally['actor_template']['maximum_hp']=5
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('bracing'),bundle_transform=setup,seed='QISUB6-BRACING-DEATH')
    # Bracing's death-save mode makes the later zero-HP hit enter the native dying flow.
    _act(combat,table,mid,'Administer Bracing Ration',ALLY)
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp==5
    _act(combat,table,mid,'Probe bracing hit',ALLY)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==0
    assert engine.state.actors[ALLY].life_state=='DYING'
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    rolls=[r for r in engine.rolls if r.reason=='SAVE:death' and r.actor_id==ALLY]
    assert rolls and rolls[-1].mode=='ADVANTAGE'
    assert not any(c.condition_id=='condition:typed.culinary_bracing' for c in engine.state.actors[ALLY].conditions.values())


STONE = 'tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense'


def stone_prepare(bundles, airborne=False, other=False):
    prepare(bundles,airborne=airborne)
    if other:
        b=next(b for b in bundles if b['actor_id']==OWNER)
        b.setdefault('senses',{}).setdefault('rows',[]).append(
            {'feature_id':'fixture:independent_tremorsense','sense':'tremorsense','range_ft':10,'when':'always'})
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


@pytest.mark.parametrize('owns,airborne,other,feet,moving',[
    (True,False,False,30,True),(False,False,False,0,False),
    (True,True,False,0,False),(True,True,True,10,False)])
def test_stone_sense_contact_motion_and_independent_grant_reload(tmp_path,owns,airborne,other,feet,moving):
    from combat import senses
    combat,table,mid=fixture(tmp_path,[STONE] if owns else [],
        positions={OWNER:{'x':3,'y':8,**({'z':2} if airborne else {})},ALLY:{'x':3,'y':3},FOE:{'x':6,'y':8}},
        bundle_transform=lambda b:stone_prepare(b,airborne,other),seed='QISUB6-STONE')
    engine=reload(tmp_path,mid)
    assert senses.of(engine,engine.state.actors[OWNER]).get('tremorsense',{}).get('range_ft',0)==feet
    assert not senses.pinpoints(engine,engine.state.actors[OWNER],engine.state.actors[FOE])
    turn(table,mid,FOE)
    move=next(c for c in table.state(mid)['menu']['moves'] if c['destination']['x']==7 and c['destination']['y']==8)
    settle(table,mid,move['candidate_id'])
    engine=reload(tmp_path,mid)
    assert senses.pinpoints(engine,engine.state.actors[OWNER],engine.state.actors[FOE]) is moving


@pytest.mark.parametrize('owns,name,cost',[(True,'Rubble',5),(True,'Ice',10),(False,'Rubble',10)])
def test_mountain_footing_named_ground_actual_move_reload(tmp_path,monkeypatch,owns,name,cost):
    from combat import ext,zones
    from combat.gate2_runtime_models import Position,ZoneState
    def ground(ctx,eff):
        pos=Position(x=4,y=8)
        zone=ZoneState(zone_id='zone:test.qisub6.ground',source_definition_id=ctx.source,
            owner_id=zones.MAP_OWNER,active=True,center=pos,radius_cells=0,affected_cells=(pos,),
            concentration_link=False,created_round=ctx.engine.state.round_number,
            trigger_profile={'kind':zones.KIND,'name':name,'terrain':[name.lower()],
                'difficult':'all','visual':{'material':name.lower()},'numbers':dict(ctx.numbers)})
        ctx.engine.state.zones[zone.zone_id]=zone
        ctx.engine._append_event('ZONE_CREATED',ctx.source,actor_id=ctx.actor.entity_id,
            payload={'zone':zone.model_dump(mode='json')})
    monkeypatch.setitem(ext.effects(),'qisub6_fixture_ground',ground)
    combat,table,mid=fixture(tmp_path,[STONE] if owns else [],
        positions={OWNER:{'x':3,'y':8},ALLY:{'x':3,'y':3},FOE:{'x':6,'y':8}},
        bundle_transform=lambda b:extra_prepare(b,'Probe ground',[{'type':'qisub6_fixture_ground'}]),
        seed='QISUB6-FOOTING')
    turn(table,mid,FOE);_act(combat,table,mid,'Probe ground',OWNER)
    reload(tmp_path,mid);turn(table,mid,OWNER)
    before=reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    move=next(c for c in table.state(mid)['menu']['moves'] if c['destination']['x']==4 and c['destination']['y']==8)
    settle(table,mid,move['candidate_id'])
    engine=reload(tmp_path,mid)
    assert before-engine.state.actors[OWNER].movement_remaining_ft==cost


def test_yang_successful_qi_attack_spends_bonus_once_after_cold_reload(tmp_path,monkeypatch):
    from combat import ext

    def setup(bundles):
        flow_prepare(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        action=deepcopy(next(a for a in owner['action_catalog'] if a['display_name']=='Qi packet'))
        action.update(display_name='Qi strike',source_definition_id='action:test.qisub6.qi_hit')
        action['parameters']['typed']['effects']=[{'type':'attack','attack_kind':'cultivation_ranged',
            'on_hit':[{'type':'damage','dice':{'count':1,'sides':4},'formula':'none','damage_types':['force']}]}]
        owner['action_catalog'].append(action)
        owner['actor_template']['action_ids'].append(action['source_definition_id'])
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)

    def hit(engine,roll,intent):
        if 'qi_hit' in roll.reason:
            return {'source_id':'test:qisub6.fixture_hit','operation':'replace','natural_result':20}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'d20_result',[hit,*ext._HOOKS.get('d20_result',[])])

    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=setup,seed='QISUB6-YANG-HIT')
    choose_current(table,mid,'yang')
    prompts=settle(table,mid,candidate(combat,mid,'Qi strike',target=FOE).candidate_id,
                   choices={'choice:needle.balanced_yang':['increase']})
    ballot=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.balanced_yang')
    assert any(o['id']=='increase' for o in ballot['choice']['options'])
    engine=reload(tmp_path,mid)
    attack=[e for e in engine.events if e.event_type=='ATTACK_ROLLED'][-1]
    assert attack.payload['provisional_hit'] is True
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and FOE in e.target_ids][-1]
    attack_roll=[r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1]
    assert attack_roll.modifier==4
    assert damage.payload['reduced_to']==attack_roll.total
    assert engine.state.actors[OWNER].turn_flags['_round_balanced_yang']==f"{engine.state.round_number}:{OWNER}"

    _act(combat,table,mid,'Qi healing',ALLY)
    engine=reload(tmp_path,mid)
    later_roll=[r for r in engine.rolls if r.reason.startswith('HEALING:')][-1]
    assert later_roll.modifier==0


def test_yang_missed_qi_attack_preserves_bonus_for_damage_packet(tmp_path,monkeypatch):
    from combat import ext
    def setup(bundles):
        flow_prepare(bundles)
        b=next(v for v in bundles if v['actor_id']==OWNER)
        a=deepcopy(next(a for a in b['action_catalog'] if a['display_name']=='Qi packet'))
        a.update(display_name='Qi miss',source_definition_id='action:test.qisub6.qi_miss')
        a['parameters']['typed']['effects']=[{'type':'attack','attack_kind':'cultivation_ranged',
            'on_hit':[{'type':'damage','dice':{'count':1,'sides':4},'formula':'none','damage_types':['force']}]}]
        b['action_catalog'].append(a);b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    def miss(engine,roll,intent):
        if 'qi_miss' in roll.reason:
            return {'source_id':'test:qisub6.fixture_miss','operation':'replace','natural_result':1}
    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'d20_result',[miss,*ext._HOOKS.get('d20_result',[])])
    combat,table,mid=fixture(tmp_path,[FLOW],bundle_transform=setup,seed='QISUB6-YANG-MISS')
    choose_current(table,mid,'yang')
    _act(combat,table,mid,'Qi miss',FOE)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='ATTACK_ROLLED'][-1].payload['provisional_hit'] is False
    _act(combat,table,mid,'Qi packet',FOE)
    engine=reload(tmp_path,mid)
    assert [r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1].modifier==4


def test_palm_player_can_heal_enemy_ai_prefers_allies_service_reload(tmp_path):
    from combat.gate4_context import build_decision_context
    combat,table,mid=fixture(tmp_path,[FLOW],positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}},seed='QISUB6-PALM-SIDE')
    engine=reload(tmp_path,mid)
    policy=combat.policies.for_actor(OWNER)[0]
    automatic=build_decision_context(engine,policy,for_ai=True)
    palms=[c for c in automatic.legal_candidates if c.display_name=='Restorative Palm']
    assert palms and any(FOE in c.target_ids for c in palms)
    _act(combat,table,mid,'Restorative Palm',FOE)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='HEALING_APPLIED'][-1].target_ids==(FOE,)


@pytest.mark.parametrize('accept',[True,False])
def test_ration_enemy_consent_and_ai_side_preserve_unconsumed_stock(tmp_path,accept):
    from combat.gate4_context import build_decision_context
    combat,table,mid=fixture(tmp_path,[RATION],owner_kit=ration_kit('fortifying'),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}},seed='QISUB6-RATION-CONSENT')
    engine=reload(tmp_path,mid)
    ai=build_decision_context(engine,combat.policies.for_actor(OWNER)[0],for_ai=True)
    assert not [c for c in ai.legal_candidates if c.display_name=='Administer Fortifying Ration' and FOE in c.target_ids]
    settle(table,mid,candidate(combat,mid,'Administer Fortifying Ration',target=FOE).candidate_id,
        choices={'choice:willing.consent':['accept' if accept else 'refuse']})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[RP]==(1 if accept else 2)
    assert (engine.state.actors[FOE].temporary_hp>0) is accept
    assert (engine.state.actors[FOE].turn_flags.get('_round_ration_consumed') is not None) is accept


def test_carried_ration_is_not_a_qi_technique_and_preserves_yang(tmp_path):
    combat,table,mid=fixture(tmp_path,[FLOW,RATION],owner_kit=ration_kit('restorative'),
        bundle_transform=flow_prepare,seed='QISUB6-FOOD-POWER')
    choose_current(table,mid,'yang')
    _act(combat,table,mid,'Consume Restorative Ration',OWNER)
    engine=reload(tmp_path,mid)
    assert [r for r in engine.rolls if r.reason.startswith('HEALING:')][-1].modifier==2
    _act(combat,table,mid,'Qi packet',FOE)
    engine=reload(tmp_path,mid)
    assert [r for r in engine.rolls if r.reason.startswith('DAMAGE:')][-1].modifier==4
