"""A2GBODSUB6: committed table choices, defense ordering and cold reload."""
import pytest
from combat.canonical import canonical_sha256
from combat.ext.adaptations import RECORD
from tests.worker2_support import (fixture, candidate, settle, turn, reload, sealed_native_attack, OWNER, ALLY, FOE)

R = 'tianxia.subpath.body.ryujin.feature.'
A = 'tianxia.subpath.body.heaven_answering_adaptive_body.feature.'
STAMINA = 'resource:core.stamina'


def build(tmp_path, mids, **kwargs):
    def seal(bundles):
        sealed_native_attack(bundles[2], 'Hostile Fire', count=1, sides=2, modifier=18, attack_bonus=100)
        sealed_native_attack(bundles[2], 'Hostile Force', damage_type='FORCE', count=1, sides=2, modifier=18, attack_bonus=100)
        for action in bundles[0]['action_catalog']:
            typed=action.get('parameters',{}).get('typed') or {}
            if typed.get('numbers'): typed['numbers']['attack_bonus']=100
        for b in bundles:
            b['actor_template']['maximum_hp'] = 1000
            b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)
    return fixture(tmp_path, mids, primary='Stamina', cl=18, owner_path='Body Refining',
                   bundle_transform=seal, **kwargs)


def use(combat, table, mid, name, *, target=None, at=None, choices=None):
    c = candidate(combat, mid, name, target=target, at=at)
    return settle(table, mid, c.candidate_id, choices=choices or {})


def last_damage(engine,kind):
    return next(r.total for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and '.hostile_'+kind+':' in r.reason)


def damage(combat, table, mid, name='Hostile Fire', *, choices=None):
    if table.state(mid)['menu']['actor_id']==FOE:
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table, mid, FOE)
    return use(combat, table, mid, name, target=OWNER, choices=choices)


@pytest.mark.parametrize('grow', [True, False])
def test_form_flight_hover_size_profiles_and_reload(tmp_path, grow):
    combat, table, mid = build(tmp_path, [R+'ryujin_ascendant_form', R+'dragon_s_breath', R+'storm_step'],
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':9,'y':8}, FOE:{'x':8,'y':6}})
    prompts = use(combat, table, mid, 'Ryūjin Ascendant Form', choices={'choice:needle.ryujin_size':['large'] if grow else None})
    assert any(p['context']['reaction_source_id']=='choice:needle.ryujin_size' for p in prompts)
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert not any('Fly Speed of 60 feet with Hover' in str((event.payload or {}).get('rider'))
                   for event in engine.events if event.event_type == 'GM_RIDER')
    from combat import ext, dynamic_size
    from combat.flight import profile
    assert profile(engine, actor).speed_ft==60 and profile(engine, actor).hover
    assert dynamic_size.current_category(engine, actor) == ('Large' if grow else 'Medium')
    assert actor.resources[STAMINA] == 93
    assert engine._footprint(actor).width_cells == (2 if grow else 1)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table, mid, OWNER)
    names={engine.action_catalog[c.source_definition_id].display_name for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id in engine.action_catalog}
    assert "Dragon's Breath (Ascendant)" in names and "Dragon's Breath" not in names
    assert 'Storm Step (Ascendant)' in names and 'Storm Step' not in names
    e=combat._load_session(mid).engine
    flying=next(c for c in e.legal_candidates() if c.destination and c.destination.z==1 and c.kind.value=='MOVE')
    settle(table, mid, flying.candidate_id, choices={})
    assert reload(tmp_path, mid).state.actors[OWNER].position.z==1


def test_storm_step_player_landing_enemy_only_and_declined_burst(tmp_path):
    combat, table, mid = build(tmp_path, [R+'storm_step'],
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':6,'y':7}, FOE:{'x':7,'y':6}}, owner_dc=50)
    prompts=use(combat,table,mid,'Storm Step',choices={'choice:needle.teleport_destination':['cell:6,6'], 'choice:needle.storm_recipients':[FOE]})
    engine=reload(tmp_path,mid)
    assert (engine.state.actors[OWNER].position.x,engine.state.actors[OWNER].position.y)==(6,6)
    assert engine.state.actors[ALLY].current_hp==1000
    assert engine.state.actors[FOE].current_hp<1000
    assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    assert any(p['context']['reaction_source_id']=='choice:needle.storm_recipients' for p in prompts)
    hp = engine.state.actors[FOE].current_hp
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Storm Step', choices={'choice:needle.teleport_destination':['cell:6,5'],
                                                'choice:needle.storm_recipients':None})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (6,5)
    assert engine.state.actors[FOE].current_hp == hp
    assert engine.state.actors[ALLY].current_hp == 1000


@pytest.mark.parametrize('name', ["Dragon's Breath", "Dragon's Roar"])
@pytest.mark.parametrize('ally_save', [True, False])
def test_cones_affect_every_creature_with_both_save_outcomes_after_reload(tmp_path,name,ally_save):
    combat,table,mid=build(tmp_path,[R+('dragon_s_breath' if name.endswith('Breath') else 'dragon_s_roar')],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':7},FOE:{'x':5,'y':6}},owner_dc=1 if ally_save else 50)
    prompts = use(combat,table,mid,name,at=(5,6), choices={'choice:needle.ryujin_damage':['THUNDER']} if name.endswith('Breath') else {})
    if name.endswith('Breath'):
        assert any(p['context']['reaction_source_id']=='choice:needle.ryujin_damage' for p in prompts)
    e=reload(tmp_path,mid)
    assert any(x.event_type=='DAMAGE_COMMITTED' and x.payload.get('damage_type')=='THUNDER' for x in e.events)
    assert e.state.actors[FOE].current_hp<1000
    assert e.state.actors[ALLY].current_hp<1000
    assert any(x.event_type=='DAMAGE_COMMITTED' and ALLY in (x.target_ids or ()) for x in e.events)
    if name.endswith('Roar'):
        foe_conditions=list(e.state.actors[FOE].conditions.values())
        ally_conditions=list(e.state.actors[ALLY].conditions.values())
        for conditions in (foe_conditions, ally_conditions):
            assert any(c.condition_id.endswith('reaction_denied') for c in conditions) is ally_save
            assert any(c.condition_id.endswith('stunned') and c.expires_on=='START_OF_SOURCE_NEXT_TURN'
                       for c in conditions) is (not ally_save)


@pytest.mark.parametrize('fragile', [True, False])
def test_explicit_fragility_override_applies_to_cone_objects_after_reload(tmp_path,fragile):
    combat,table,mid=object_fixture(tmp_path,'dragon_s_breath',fragile_override=fragile)
    use(combat,table,mid,"Dragon's Breath",at=(5,6),choices={'choice:needle.ryujin_damage':['THUNDER']})
    e=reload(tmp_path,mid)
    obj=next(o for o in e.state.objects.values() if o.component.get('material')=='glass' and o.unattended)
    assert obj.component['fragile'] is fragile
    assert (1000-obj.current_hp>0) is fragile


def test_flesh_reaction_resistance_precedes_pb_reduction(tmp_path):
    combat,table,mid=build(tmp_path,[A+'flesh_remembers_pain'])
    damage(combat,table,mid)
    e=reload(tmp_path,mid); first=last_damage(e,'fire'); assert e.state.actors[OWNER].current_hp==1000-first
    assert next(c for c in e.state.actors[OWNER].conditions.values() if c.condition_id==RECORD).data['damage'][0]['type']=='FIRE'
    damage(combat,table,mid,choices={'choice:needle.adapt_response':['use']})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==1000-first-max(0,last_damage(e,'fire')//2-4)
    assert e.state.actors[OWNER].resources[STAMINA]==99


@pytest.mark.parametrize('kind', ['Fire','Force'])
def test_counter_evolution_gains_before_packet_and_cold_reload(tmp_path,kind):
    combat,table,mid=build(tmp_path,[A+'flesh_remembers_pain',A+'ten_thousand_answers',A+'perfect_counter_evolution'])
    damage(combat,table,mid,'Hostile '+kind,choices={'choice:needle.adapt_response':['use']})
    e=reload(tmp_path,mid); actor=e.state.actors[OWNER]
    amount=last_damage(e,kind.lower())
    assert actor.current_hp == 1000-max(0,amount//2-4 if kind=='Fire' else amount-8)
    assert actor.resources[STAMINA]==98 and not actor.reaction_available
    assert next(c for c in actor.conditions.values() if c.condition_id==RECORD).data['damage']==[{'type':kind.upper(),'by':FOE}]
    assert not any(x.event_type=='GM_RIDER' and x.source_definition_id==A+'perfect_counter_evolution' for x in e.events)


def test_ten_thousand_answers_keeps_automatic_resistance_on_reload(tmp_path):
    combat,table,mid=build(tmp_path,[A+'flesh_remembers_pain',A+'ten_thousand_answers'])
    damage(combat,table,mid)
    first=last_damage(reload(tmp_path,mid),'fire')
    damage(combat,table,mid,choices={'choice:needle.adapt_response':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==1000-first-max(0,last_damage(e,'fire')//2-4)
    assert 'FIRE' in {m.value for m in e.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'}


def test_return_lesson_counter_upgrade_and_target_duration(tmp_path):
    combat,table,mid=build(tmp_path,[A+'flesh_remembers_pain',A+'return_the_lesson',A+'perfect_counter_evolution'],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':8,'y':8},FOE:{'x':4,'y':6}})
    damage(combat,table,mid,choices={'choice:needle.adapt_response':['use']})
    turn(table,mid,OWNER)
    e=combat._load_session(mid).engine
    attack=next(c for c in e.legal_candidates() if c.target_ids==(FOE,) and 'unarmed' in e.action_catalog[c.source_definition_id].display_name.lower())
    settle(table,mid,attack.candidate_id,choices={'choice:needle.return_lesson':['speed']})
    e=reload(tmp_path,mid)
    assert any(r.expression.startswith('4d8') for r in e.rolls)
    assert e._effective_speed(e.state.actors[FOE])==0
    # Speed 0 ends at the start of the target's next turn, not at the source's turn boundary.
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert e._effective_speed(e.state.actors[FOE])==30


def affliction_fixture(tmp_path, mids, *, repeat=False, save_dc=50, seed='WORKER2-AFFLICTION'):
    def seal(bundles):
        b=bundles[2]
        condition={'type':'condition','condition':'poisoned','applies_to':'target','duration':'one_minute'}
        if repeat: condition['repeat_save']={'ability':'CON','when':'end'}
        sid='action:test.hostile_affliction'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Hostile Affliction','owner_id':FOE,
            'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
            'parameters':{'typed':{'source':sid,'numbers':{'save_dc':save_dc,'cl':18,'pb':4},
                'effects':[{'type':'save','ability':'con','applies_to':'target','on_fail':[condition],'on_success':[]}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    return fixture(tmp_path,mids,primary='Stamina',cl=18,owner_path='Body Refining',bundle_transform=seal,seed=seed)


@pytest.mark.parametrize('repeat',[True,False])
def test_meridians_records_and_repeats_original_save_through_service(tmp_path,repeat):
    combat,table,mid=affliction_fixture(tmp_path,[A+'meridians_remember_affliction'],repeat=repeat)
    turn(table,mid,FOE)
    use(combat,table,mid,'Hostile Affliction',target=OWNER)
    e=reload(tmp_path,mid)
    record=next(c for c in e.state.actors[OWNER].conditions.values() if c.condition_id==RECORD)
    assert record.data['afflictions'][0]['condition']=='poisoned'
    turn(table,mid,OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={'choice:needle.meridian_repeat':'first'})
    e=reload(tmp_path,mid)
    assert any(x.event_type=='D20_REWRITTEN' and x.payload.get('bonus')==4 for x in e.events)
    assert e.state.actors[OWNER].resources[STAMINA]==(100 if repeat else 98)


def test_counter_affliction_successful_reroll_withholds_poison_and_keeps_adaptation(tmp_path):
    # This fixed match seed rolls 1 then 20 for the hostile save and its reroll (after initiative).
    combat,table,mid=affliction_fixture(tmp_path,[A+'meridians_remember_affliction',A+'perfect_counter_evolution'],
        save_dc=12,seed='A2GBODSUB6R3-SUCCESS-8')
    turn(table,mid,FOE)
    prompts=use(combat,table,mid,'Hostile Affliction',target=OWNER,
        choices={'reaction:typed.'+A+'perfect_counter_evolution':'first','choice:needle.counter_affliction':['poisoned']})
    e=reload(tmp_path,mid); actor=e.state.actors[OWNER]
    assert any(x.event_type=='D20_REWRITTEN' and x.source_definition_id==A+'perfect_counter_evolution' for x in e.events)
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.source_definition_id=='action:test.hostile_affliction']
    assert saves and saves[-1].payload['success'] is True
    assert not any(c.condition_id.endswith('poisoned') for c in actor.conditions.values())
    assert next(c for c in actor.conditions.values() if c.condition_id==RECORD).data['afflictions'][0]['condition']=='poisoned'
    assert actor.resources[STAMINA]==98 and not actor.reaction_available
    assert len([p for p in prompts if p['context']['reaction_source_id']=='reaction:typed.'+A+'perfect_counter_evolution'])==1
    spent=[x for x in e.events if x.event_type=='RESOURCE_SPENT' and x.source_definition_id==A+'perfect_counter_evolution']
    windows=[x for x in e.events if x.event_type=='REACTION_WINDOW_OPENED' and x.source_definition_id==A+'perfect_counter_evolution']
    assert len(spent)==1 and spent[0].payload['amount']==2 and spent[0].payload['resource_id']==STAMINA
    assert len(windows)==1 and actor.turn_flags['_round_counter_evolution']==e.state.round_number


def test_counter_affliction_retains_real_record_after_reroll(tmp_path):
    combat,table,mid=affliction_fixture(tmp_path,[A+'meridians_remember_affliction',A+'perfect_counter_evolution'])
    turn(table,mid,FOE)
    prompts=use(combat,table,mid,'Hostile Affliction',target=OWNER,
        choices={'reaction:typed.'+A+'perfect_counter_evolution':'first','choice:needle.counter_affliction':['poisoned']})
    e=reload(tmp_path,mid)
    assert any(c.condition_id==RECORD and c.data['afflictions'][0]['condition']=='poisoned' for c in e.state.actors[OWNER].conditions.values())
    assert e.state.actors[OWNER].resources[STAMINA]==98
    assert any(x.event_type=='D20_REWRITTEN' for x in e.events)
    assert not any(x.event_type=='GM_RIDER' and x.source_definition_id==A+'perfect_counter_evolution' for x in e.events)


def test_dragon_scales_ac_resistance_and_unarmed_rider_service(tmp_path):
    combat,table,mid=build(tmp_path,[R+'dragon_scales','tianxia.path.body_refining.feature.unarmored_defense'], owner_ac=16,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':8,'y':8},FOE:{'x':4,'y':6}})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].armor_class==17
    e=combat._load_session(mid).engine
    attack=next(c for c in e.legal_candidates() if c.target_ids==(FOE,) and 'unarmed' in e.action_catalog[c.source_definition_id].display_name.lower())
    settle(table,mid,attack.candidate_id,choices={})
    e=reload(tmp_path,mid)
    assert any(x.event_type=='DAMAGE_COMMITTED' and x.payload.get('damage_type')=='LIGHTNING' for x in e.events)
    assert 'LIGHTNING' in {m.value for m in e.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'} or any(row.get('kind')=='resistance' and 'LIGHTNING' in row.get('damage_types',[]) for row in e.typed_passive_rows[OWNER])


def object_fixture(tmp_path, feature, *, fragile_override=None):
    import json, zipfile
    from combat.factory_compiler import compile_character
    combat,table,_=build(tmp_path,[R+feature],positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':8},FOE:{'x':8,'y':8}})
    ids=[OWNER,ALLY,FOE]; bundles=[]
    for aid in ids:
        with zipfile.ZipFile(tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')/'current.zip') as archive:
            doc=json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
        bundles.append(compile_character(doc,actor_id=aid,reaction_plan={'ask':True}))
    arena=dict(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    glass={'id':1,'x':5,'y':6,'kind':'custom','material':'glass','hp':1000,'blocks':False,'unattended':True}
    if fragile_override is not None:
        glass['fragile']=fragile_override
    arena['map_objects']=[
        glass,
        {'id':2,'x':5,'y':6,'kind':'custom','material':'glass','hp':1000,'blocks':False,'unattended':False},
        {'id':3,'x':5,'y':6,'kind':'custom','material':'wood','hp':1000,'blocks':False,'unattended':True},
        {'id':4,'x':5,'y':6,'kind':'formation_anchor','material':'stone','hp':1000,'blocks':False,'unattended':False},
        {'id':5,'x':5,'y':6,'kind':'custom','material':'stone','hp':1000,'blocks':False,'unattended':True,'artifact':True,'immune':['THUNDER']},
    ]
    mid=combat._finish_factory_match(bundles,ids,{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},
        {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':8},FOE:{'x':8,'y':8}},arena,[OWNER,ALLY],[FOE],
        control_modes={a:'MANUAL' for a in ids},match_seed='A2GBODSUB6-OBJECTS',display_name='Object cone',maximum_rounds=10)['match_id']
    turn(table,mid,OWNER)
    return combat,table,mid


@pytest.mark.parametrize('feature,name',[('dragon_s_breath',"Dragon's Breath"),('dragon_s_roar',"Dragon's Roar")])
def test_object_clauses_apply_once_only_to_printed_categories(tmp_path,feature,name):
    combat,table,mid=object_fixture(tmp_path,feature)
    use(combat,table,mid,name,at=(5,6))
    e=reload(tmp_path,mid)
    damage={k:1000-v.current_hp for k,v in e.state.objects.items()}
    assert damage['object:map.1']>0
    assert damage['object:map.2']==0
    if feature=='dragon_s_breath':
        assert damage['object:map.3']==damage['object:map.4']==0
    else:
        assert damage['object:map.3']==damage['object:map.4']==damage['object:map.1']
        assert damage['object:map.5']==0
        rolled=next(r.total for r in e.rolls if r.reason.startswith('DAMAGE:'))
        assert damage['object:map.1']==rolled*2



def test_storm_step_automatic_recipients_remain_enemy_only(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat,table,mid=build(tmp_path,[R+'storm_step'],owner_dc=50,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':6,'y':7},FOE:{'x':7,'y':6}})
    picked=candidate(combat,mid,'Storm Step',at=(6,6)).candidate_id
    real=combat.controller
    class Controller:
        def choose_primary_action(self,context):
            return ManualControllerAdapter(lambda _context:(picked,())).choose_primary_action(context)
        def __getattr__(self,name):
            return getattr(real,name)
    combat.controller=Controller()
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,picked,auto=True)
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp==1000
    assert e.state.actors[FOE].current_hp<1000


def test_meridians_selects_one_of_multiple_actual_afflictions(tmp_path):
    def seal(bundles):
        b=bundles[2]; sid='action:test.multiple_afflictions'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Multiple Afflictions','owner_id':FOE,
            'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
            'parameters':{'typed':{'source':sid,'numbers':{'save_dc':50,'cl':18,'pb':4},
                'effects':[{'type':'save','ability':'con','applies_to':'target','on_fail':[
                    {'type':'condition','condition':n,'applies_to':'target','duration':'one_minute'}
                    for n in ['poisoned','blinded']], 'on_success':[]}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[A+'meridians_remember_affliction'],primary='Stamina',cl=18,bundle_transform=seal)
    turn(table,mid,FOE)
    prompts=use(combat,table,mid,'Multiple Afflictions',target=OWNER,
        choices={'choice:needle.adapt_affliction':['poisoned']})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.adapt_affliction')
    assert {o['id'] for o in prompt['choice']['options']}=={'poisoned','blinded'}
    e=reload(tmp_path,mid)
    records=next(c.data['afflictions'] for c in e.state.actors[OWNER].conditions.values() if c.condition_id==RECORD)
    assert len(records)==1 and records[0]['condition']=='poisoned'
