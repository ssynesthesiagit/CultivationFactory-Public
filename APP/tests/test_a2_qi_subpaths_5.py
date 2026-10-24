"""Printed Qi Subpaths 5 effects through committed service/session actions."""
import pytest
from combat.gate2_runtime_models import ActionIntent
from combat.flight import profile
from tests.worker2_support import fixture, reload, candidate, settle, turn, OWNER, ALLY, FOE
from combat.ext.qi_subpaths_five import SOUND, CLOUD


def execute(combat, mid, c, *, reactions=()):
    session = combat._load_session(mid)
    session.mechanical.execute_intent(ActionIntent(intent_id='qi5:'+c.candidate_id, decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids,destination=c.destination,option_ids=c.option_ids,
        reaction_decisions=tuple(reactions)))


@pytest.mark.parametrize('cl,count',[(3,1),(11,2),(17,3)])
@pytest.mark.parametrize('kind',['Psychic','Thunder'])
def test_note_damage_penalty_paid_and_reloaded(tmp_path,cl,count,kind):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'instrument_of_qi'],cl=cl,owner_dc=100,ask=False)
    c=candidate(combat,mid,'Instrument of Qi: '+kind,target=FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    execute(combat,mid,c)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-1
    assert e.state.actors[FOE].current_hp<e.state.actors[FOE].maximum_hp
    assert any(c.condition_id=='condition:typed.qi5_note_penalty' for c in e.state.actors[FOE].conditions.values())
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:')]
    assert any(r.expression.startswith(str(count)+'d6') for r in rolls)
    assert e.state.actors[ALLY].current_hp==e.state.actors[ALLY].maximum_hp


@pytest.mark.parametrize('cl,count',[(6,2),(14,3),(18,4)])
def test_melody_healing_in_session_and_reload(tmp_path,cl,count):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        b=bundles[0]
        sid='action:test.qi5.wound'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Wound for healing test','owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,'parameters':{'free_primary':True,'typed':{'effects':[{'type':'damage','flat':59,'damage_types':['force'],'applies_to':'target'}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=cl,ask=False,bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Wound for healing test',target=ALLY))
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp == 1
    execute(combat,mid,candidate(combat,mid,'Healing Melody',target=ALLY))
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp>1
    assert e.state.actors[OWNER].resources['resource:core.qi']==98
    assert any(r.expression.startswith(str(count)+'d8') for r in e.rolls if r.reason.startswith('HEALING:'))


@pytest.mark.parametrize('shared_medium,offered',[ (False,False), (True,True) ])
def test_melody_admits_only_deliverable_recipients_before_payment(tmp_path,shared_medium,offered):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        b=bundles[0];sid='action:test.qi5.deafen_foe'
        bundles[2]['actor_template'].update(fly_speed_ft=30,hover=True)
        owner_sid='action:test.qi5.share_medium'
        b['action_catalog'].append({'source_definition_id':owner_sid,'display_name':'Share medium for Melody test',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
            'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'deafened','applies_to':'self',
                'duration':'one_minute','condition_data':{'sound_medium':'water'}}]}}})
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Deafen foe for Melody test',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':30,
            'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'deafened','applies_to':'target',
                'duration':'one_minute','condition_data':({'sound_medium':'water'} if shared_medium else {})}]}}})
        b['actor_template']['action_ids'].extend([owner_sid,sid])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=6,ask=False,
        foe_position={'x':6,'y':6},bundle_transform=setup)
    if shared_medium:
        execute(combat,mid,candidate(combat,mid,'Share medium for Melody test'))
    execute(combat,mid,candidate(combat,mid,'Deafen foe for Melody test',target=FOE))
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.deafened' for c in e.state.actors[FOE].conditions.values())
    assert profile(e,e.state.actors[FOE]).hover
    rows=[c for c in e.legal_candidates() if c.source_definition_id.endswith('healing_melody') and c.target_ids==(FOE,)]
    assert bool(rows)==offered
    if offered:
        execute(combat,mid,rows[0])
        e=reload(tmp_path,mid)
        assert e.state.actors[OWNER].resources['resource:core.qi']==98
    else:
        assert e.state.actors[OWNER].resources['resource:core.qi']==100
        assert e.state.actors[OWNER].action_available


def test_unrelated_manual_fight_does_not_enroll_generic_choice_probe(tmp_path):
    modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'}
    combat,table,mid=fixture(tmp_path,[],ask=False,modes=modes)
    engine=reload(tmp_path,mid)
    assert not engine.typed_ask_reactors
    calls=[]
    original=combat._ask_during_ai_step
    def counted(*args,**kwargs):
        calls.append(True)
        return original(*args,**kwargs)
    combat._ask_during_ai_step=counted
    result=table.auto_step(mid,table.state(mid)['last_sequence'],[])
    assert result['status']=='COMMITTED', result
    assert calls==[]


def test_melody_removes_a_permitted_condition_from_selected_recipient(tmp_path):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        b=bundles[0];sid='action:test.qi5.frighten_ally'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Frighten ally for Melody test','owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'frightened','applies_to':'target','duration':'one_minute'}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=6,ask=True,bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Frighten ally for Melody test',target=ALLY).candidate_id)
    assert any(c.condition_id=='condition:typed.frightened' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())
    melody_id=candidate(combat,mid,'Healing Melody',target=ALLY).candidate_id
    settle(table,mid,melody_id,choices={'choice:needle.qi5_melody':['frightened']})
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[ALLY].conditions.values())
    assert e.state.actors[ALLY].current_hp==60


def test_ai_caster_keeps_manual_recipient_choice_for_melody_step(tmp_path):
    modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'}
    def only_melody(bundles):
        from combat.canonical import canonical_sha256
        b=bundles[0]
        sid='action:test.qi5.wound_ally'
        b['action_catalog']=[a for a in b['action_catalog'] if a.get('display_name')=='Healing Melody']
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Wound ally for Melody test','owner_id':OWNER,'economy':'BONUS_ACTION','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,'parameters':{'typed':{'effects':[{'type':'damage','flat':50,'damage_types':['force'],'applies_to':'target'}]}}})
        b['actor_template']['action_ids']=[a['source_definition_id'] for a in b['action_catalog']]
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=6,ask=False,modes=modes,bundle_transform=only_melody)
    before=reload(tmp_path,mid).state.actors[ALLY].position
    wound=candidate(combat,mid,'Wound ally for Melody test',target=ALLY)
    execute(combat,mid,wound)
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp==10
    from combat.gate4_adapters import ManualControllerAdapter
    real=combat.controller
    class SelectedMelodyController:
        def choose_primary_action(self,context):
            choices=[c for c in context.legal_candidates if c.display_name=='Healing Melody' and c.target_ids==(ALLY,)]
            assert choices, 'the AI target filter must offer the injured, perceived ally'
            return ManualControllerAdapter(lambda _: (choices[0].candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):
            return getattr(real,name)
    combat.controller=SelectedMelodyController()
    result=table.auto_step(mid,table.state(mid)['last_sequence'],[])
    assert result['status']=='REACTION_REQUIRED', result
    prompt=result['reaction']
    assert prompt['context']['reactor_id']==ALLY
    assert prompt['context']['reaction_source_id']=='choice:needle.rider_step'
    destination=next(o for o in prompt['choice']['options'] if not o.get('label','').startswith('Stay where you are'))
    answer={**prompt['context'],'selection':'USE','option_ids':[destination['id']]}
    result=table.auto_step(mid,0,[answer])
    assert result['status']=='COMMITTED', result
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].position!=before


@pytest.mark.parametrize('name,cost,condition',[('shattering_note',4,'deafened'),('requiem_of_the_heavens',8,'stunned')])
@pytest.mark.parametrize('dc',[100,-100])
def test_sonic_area_affects_creatures_and_save_branches(tmp_path,name,cost,condition,dc):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+name],cl=18,owner_dc=dc,ask=False,modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'},foe_position={'x':5,'y':6})
    label='Shattering Note' if name=='shattering_note' else 'Requiem of the Heavens: Thunder'
    c=candidate(combat,mid,label,at=(5,6)) if name=='shattering_note' else candidate(combat,mid,label)
    execute(combat,mid,c)
    e=reload(tmp_path,mid)
    if name=='shattering_note':
        from combat.ext.qi_subpaths_five import concentration_presentation
        note_label,note_reading=concentration_presentation(SOUND+'shattering_note')
        assert 'Concentration saves from this damage only' in note_label
        assert 'ends when that damage resolves' in note_reading
    if name=='requiem_of_the_heavens' and dc>0:
        from combat.presentation import condition_label, _condition_detail
        penalty=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.qi5_concentration')
        assert 'Concentration saves' in condition_label(penalty.condition_id,penalty.data)
        assert 'until the end of the source\'s next turn' in _condition_detail(penalty.data)
    assert e.state.actors[OWNER].resources['resource:core.qi']==100-cost
    assert e.state.actors[FOE].current_hp<60
    if name=='shattering_note':
        assert e.state.actors[ALLY].current_hp<60
        assert any(c.condition_id=='condition:typed.deafened' for c in e.state.actors[ALLY].conditions.values())
    else:
        assert e.state.actors[ALLY].current_hp==60
        assert not e.state.actors[ALLY].conditions
    cs=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.'+condition]
    assert bool(cs)==(dc>0 or name=='shattering_note')
    if cs:
        assert cs[0].expires_on.startswith(('END_OF_SOURCE_TURN_AT:', 'START_OF_SOURCE_TURN_AT:','START_OF_SOURCE_NEXT_TURN'))


def test_song_waits_for_start_then_frightens_only_enemy(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'song_of_fear'],cl=14,owner_dc=100,ask=False,foe_position={'x':5,'y':6})
    execute(combat,mid,candidate(combat,mid,'Song of Fear'))
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[FOE].conditions.values())
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[ALLY].conditions.values())


def test_song_of_fear_removes_its_frightened_condition_after_leaving_area(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'song_of_fear'],cl=14,owner_dc=100,ask=False,
        foe_position={'x':6,'y':6})
    execute(combat,mid,candidate(combat,mid,'Song of Fear'))
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[FOE].conditions.values())
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and c.destination.x>=10]
    assert moves, 'the frightened creature can choose a route out of the field'
    execute(combat,mid,max(moves,key=lambda c:c.destination.x))
    assert any(c.condition_id=='condition:typed.frightened' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id=='condition:typed.frightened' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_melody_charmed_repeat_uses_stored_save_with_advantage_and_exact_removal(tmp_path):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        b=bundles[0];sid='action:test.qi5.precharm'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Charm ally for Melody test',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,
            'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'charmed','applies_to':'target',
                'duration':'one_minute','condition_data':{'origin_save':{'ability':'int','dc':-100}}}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=6,ask=True,bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Charm ally for Melody test',target=ALLY))
    assert any(c.condition_id=='condition:typed.charmed' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())
    settle(table,mid,candidate(combat,mid,'Healing Melody',target=ALLY).candidate_id,
           choices={'choice:needle.qi5_melody':['charmed:0']})
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.charmed' for c in e.state.actors[ALLY].conditions.values())
    repeated=[r for r in e.rolls if r.actor_id==ALLY and r.reason.startswith('SAVE:')]
    assert repeated and repeated[-1].mode=='ADVANTAGE'
    assert repeated[-1].reason.endswith(':int')


def test_melody_selects_exact_charm_instance_and_preserves_the_other_after_reload(tmp_path):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        b=bundles[0]
        for name,dc in [('hard',100),('easy',-100)]:
            sid='action:test.qi5.charm_'+name
            b['action_catalog'].append({'source_definition_id':sid,'display_name':name.title()+' Song',
                'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,
                'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'charmed','applies_to':'target',
                    'duration':'one_minute','condition_data':{'origin_save':{'ability':'wis' if name=='hard' else 'int','dc':dc}}}]}}})
            b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'healing_melody'],cl=6,ask=True,bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Hard Song',target=ALLY))
    execute(combat,mid,candidate(combat,mid,'Easy Song',target=ALLY))
    before=reload(tmp_path,mid)
    charms=[c for c in before.state.actors[ALLY].conditions.values() if c.condition_id=='condition:typed.charmed']
    assert len(charms)==2
    hard=next(c for c in charms if c.data['origin_save']['ability']=='wis')
    easy=next(c for c in charms if c.data['origin_save']['ability']=='int')
    prompts=settle(table,mid,candidate(combat,mid,'Healing Melody',target=ALLY).candidate_id,
                   choices={'choice:needle.qi5_melody':['charmed:1']})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.qi5_melody')
    labels={o['id']:o.get('label','') for o in p['choice']['options']}
    assert any('Hard Song' in label and 'Wisdom' in label for label in labels.values())
    assert any('Easy Song' in label and 'Intelligence' in label for label in labels.values())
    after=reload(tmp_path,mid)
    remaining=[c for c in after.state.actors[ALLY].conditions.values() if c.condition_id=='condition:typed.charmed']
    assert [c.instance_id for c in remaining]==[hard.instance_id]
    repeated=[r for r in after.rolls if r.actor_id==ALLY and r.reason.startswith('SAVE:')]
    assert repeated and repeated[-1].reason.endswith(':int') and repeated[-1].mode=='ADVANTAGE'


def test_demon_king_blocks_possession_from_lower_cl_source(tmp_path):
    from combat.canonical import canonical_sha256
    from tests.h1_support import sheet
    def setup(bundles):
        b=bundles[2];sid='action:test.qi5.lower_cl_possession'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Lower CL possession probe',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':30,
            'parameters':{'typed':{'numbers':{'cl':6},'effects':[{'type':'condition','condition':'possessed','applies_to':'target',
                'duration':'one_minute'}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=['tianxia.subpath.qi.demon_prison_seal_cultivator.feature.demon_king_behind_the_seal'],
        cl=18,ask=False,foe_sheet=sheet([],cl=6),bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Demon King Behind the Seal'))
    form=reload(tmp_path,mid)
    protected=form.state.actors[OWNER]
    assert any(c.data.get('qi5_defensive_form') and c.data.get('source_cl')==18 for c in protected.conditions.values())
    form_riders=[str(e.payload.get('rider')) for e in form.events if e.event_type=='GM_RIDER']
    assert any('The GM applies any End Strain or Corruption consequences' in rider for rider in form_riders)
    assert not any('remain unresolved' in rider or 'require automation' in rider for rider in form_riders)
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Lower CL possession probe',target=OWNER))
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.possessed' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('source_cl,involuntary,blocked',[(6,True,True),(6,False,False),(18,True,False),(20,True,False)])
def test_demon_king_transformation_protection_respects_involuntariness_and_cl(tmp_path,source_cl,involuntary,blocked):
    from combat.canonical import canonical_sha256
    from tests.h1_support import sheet
    def setup(bundles):
        b=bundles[2];sid='action:test.qi5.transform_'+str(source_cl)+'_'+str(involuntary)
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Transformation probe',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':30,
            'parameters':{'typed':{'numbers':{'cl':source_cl},'effects':[{'type':'condition','condition':'transformed',
                'applies_to':'target','involuntary':involuntary,'duration':'one_minute'}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=['tianxia.subpath.qi.demon_prison_seal_cultivator.feature.demon_king_behind_the_seal'],
        cl=18,ask=False,foe_sheet=sheet([],cl=20),bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Demon King Behind the Seal'))
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Transformation probe',target=OWNER))
    e=reload(tmp_path,mid)
    transformed=any(c.condition_id=='condition:typed.transformed' for c in e.state.actors[OWNER].conditions.values())
    assert transformed is not blocked


@pytest.mark.parametrize('name,speed,hover,cost',[('cloud_step',20,False,2),('cloud_immortal',60,True,8)])
def test_cloud_flight_is_native_without_instant_movement(tmp_path,name,speed,hover,cost):
    combat,table,mid=fixture(tmp_path,[],owner_features=[CLOUD+name],cl=18,ask=False)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    execute(combat,mid,candidate(combat,mid,name.replace('_',' ').title()))
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position==before
    assert profile(e,e.state.actors[OWNER]).speed_ft==speed
    assert profile(e,e.state.actors[OWNER]).hover==hover
    assert e.state.actors[OWNER].resources['resource:core.qi']==100-cost
    if name=='cloud_immortal':
        riders=[str(event.payload.get('rider')) for event in e.events if event.event_type=='GM_RIDER']
        assert any('Ask the GM to adjudicate' in rider and '4d10 Force damage' in rider for rider in riders)


@pytest.mark.parametrize('gap,cadence',[(0,1),(3,2),(6,0)])
def test_chains_authority_repeat_clock_and_escape_action(tmp_path,gap,cadence):
    from tests.h1_support import sheet
    source='tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],cl=15,foe_sheet=sheet([],cl=15-gap),owner_dc=100,ask=False)
    execute(combat,mid,candidate(combat,mid,'Chains of Qi',target=FOE))
    e=reload(tmp_path,mid)
    hold=next(c for c in e.state.actors[FOE].conditions.values() if c.data.get('qi5_chain'))
    assert hold.data['repeat_every']==cadence
    assert hold.data['rule']['no_teleport']
    assert hold.data['prepared_for_sealing']
    assert not any(c.condition_id=='condition:typed.reaction_denied' for c in e.state.actors[FOE].conditions.values())
    assert e.state.actors[OWNER].resources['resource:core.qi']==97
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Break Chains of Qi'))
    e=reload(tmp_path,mid)
    assert not e.state.actors[FOE].action_available
    assert any(c.data.get('qi5_chain') for c in e.state.actors[FOE].conditions.values())
    before=len(e.rolls)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    repeats=[r for r in e.rolls[before:] if r.actor_id==FOE and r.reason.startswith('SAVE:')]
    assert bool(repeats)==(cadence==1)


def test_chains_success_is_short_lock_without_restraint(tmp_path):
    source='tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],cl=6,owner_dc=-100,ask=False)
    execute(combat,mid,candidate(combat,mid,'Chains of Qi',target=FOE))
    e=reload(tmp_path,mid)
    cs=list(e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.restrained' for c in cs)
    assert any(c.data.get('rule',{}).get('no_teleport') for c in cs)
    assert any(c.condition_id=='condition:typed.reaction_denied' for c in cs)
    assert all(c.expires_on.startswith(('START_OF_SOURCE_TURN_AT:','START_OF_SOURCE_NEXT_TURN')) for c in cs)


def test_feather_reduces_native_fall_and_triples_dexterity_high_jump(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.flight import jump_score
    def setup(bundles):
        b=bundles[0];sid='action:test.qi5.ground'
        b['actor_template'].update(fly_speed_ft=30,hover=True)
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Ground for falling test','owner_id':OWNER,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'SELF','parameters':{'typed':{'effects':[{'type':'condition','condition':'blinded','applies_to':'self','duration':'one_minute','condition_data':{'flight_disabled':1}}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    def dex_jump(bundles):
        setup(bundles)
        from tests.h1_support import sheet
        from combat.factory_compiler import compile_character
        document=sheet(['TAL_ATHLETICS_MIGHTY_CONDITIONING'],cl=3)
        document['ability_scores_and_statistics']['abilities']=[
            {'ability':a,'score':10 if a=='STR' else 18 if a=='DEX' else 16,
             'modifier':0 if a=='STR' else 4 if a=='DEX' else 3}
            for a in ('STR','DEX','CON','INT','WIS','CHA')]
        document.setdefault('path_and_subpath',{})['path_feature_record_ids']=[CLOUD+'light_as_a_feather']
        bundles[0]=compile_character(document,actor_id=OWNER,reaction_plan={'ask':False})
        sid='action:test.qi5.ground'
        bundles[0]['action_catalog'].append({'source_definition_id':sid,'display_name':'Ground for falling test','owner_id':OWNER,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'SELF','parameters':{'typed':{'effects':[{'type':'condition','condition':'blinded','applies_to':'self','duration':'one_minute','condition_data':{'flight_disabled':1}}]}}})
        bundles[0]['actor_template']['action_ids'].append(sid)
        bundles[0].pop('bundle_sha256',None);bundles[0]['bundle_sha256']=canonical_sha256(bundles[0])
    combat,table,mid=fixture(tmp_path,['TAL_ATHLETICS_MIGHTY_CONDITIONING'],owner_features=[CLOUD+'light_as_a_feather'],cl=3,ask=False,bundle_transform=dex_jump,
        positions={OWNER:{'x':3,'y':6,'z':8},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}})
    execute(combat,mid,candidate(combat,mid,'Ground for falling test'))
    e=reload(tmp_path,mid)
    rolled=next(r for r in e.rolls if r.reason=='FALLING_DAMAGE')
    assert e.state.actors[OWNER].current_hp==60-max(0,rolled.total-15)
    assert e.state.actors[OWNER].position.z==0
    actor=e.state.actors[OWNER]
    score,bonus=jump_score(e,actor)
    assert score==18
    assert max(0,3+(score-10)//2)+bonus==21
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination.z>=2]
    assert moves, 'the doubled Dexterity height is represented in legal movement'
    execute(combat,mid,max(moves,key=lambda c:c.destination.z))
    e=reload(tmp_path,mid)
    assert any(evt.event_type=='MOVEMENT_COMMITTED' and evt.actor_id==OWNER
               and any(p.get('z',0)>0 for p in (evt.payload or {}).get('path',[])) for evt in e.events)


def test_requiem_player_can_choose_an_ally_and_exclude_enemies(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'requiem_of_the_heavens'],cl=18,owner_dc=-100,ask=True)
    c=candidate(combat,mid,'Requiem of the Heavens: Thunder')
    settle(table,mid,c.candidate_id,choices={'choice:needle.area_recipients':[ALLY]})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp<60
    assert e.state.actors[FOE].current_hp==60
    assert e.state.actors[OWNER].current_hp==60


def test_note_penalty_reduces_exactly_one_native_attack_after_reload(tmp_path):
    from tests.worker2_support import sealed_native_attack
    def setup(bundles):
        sealed_native_attack(bundles[2],'Native penalty probe',damage_type='FORCE',count=1,sides=4,modifier=0,attack_bonus=20)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'instrument_of_qi'],cl=3,owner_dc=100,ask=False,bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Instrument of Qi: Psychic',target=FOE))
    e=reload(tmp_path,mid)
    penalty=next(c.data['penalty'] for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.qi5_note_penalty')
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Native penalty probe',target=OWNER))
    e=reload(tmp_path,mid)
    rolled=next(r for r in reversed(e.rolls) if r.actor_id==FOE and r.reason.startswith('ATTACK:'))
    assert rolled.total-sum(rolled.dice)==20-penalty
    assert not any(c.condition_id=='condition:typed.qi5_note_penalty' for c in e.state.actors[FOE].conditions.values())


from combat.ext import effect


@effect('test_qi5_scenery')
def make_object(ctx,row):
    from combat.gate2_runtime_models import RuntimeObjectState,Position
    ctx.engine._update_object(RuntimeObjectState(object_id='object:test.qi5',object_kind='formation_anchor',
        position=Position(x=5,y=6),ac=10,current_hp=300,maximum_hp=300,unattended=True,flammable=False,
        component={'name':'Unattended test anchor','blocks':False}),ctx.source)


@pytest.mark.parametrize('name,label,damaging,empty',[('shattering_note','Shattering Note',True,False),('requiem_of_the_heavens','Requiem of the Heavens: Thunder',True,False),('requiem_of_the_heavens','Requiem of the Heavens: Psychic',False,False),('requiem_of_the_heavens','Requiem of the Heavens: Psychic',False,True)])
def test_thunder_doubles_objects_but_psychic_does_not(tmp_path,name,label,damaging,empty):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        b=bundles[0];sid='action:test.qi5.scenery'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Place test anchor','owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','parameters':{'free_primary':True,'typed':{'effects':[{'type':'test_qi5_scenery'}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+name],cl=18,owner_dc=100,ask=empty,bundle_transform=setup,
        foe_position={'x':5,'y':6},modes={OWNER:('MANUAL' if empty else 'LOCAL_AUTO'),ALLY:'MANUAL',FOE:'MANUAL'})
    execute(combat,mid,candidate(combat,mid,'Place test anchor'))
    c=candidate(combat,mid,label,at=(5,6)) if name=='shattering_note' else candidate(combat,mid,label)
    if empty:
        settle(table,mid,c.candidate_id,choices={'choice:needle.area_recipients':[]})
    else:
        execute(combat,mid,c)
    e=reload(tmp_path,mid)
    obj=e.state.objects['object:test.qi5']
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:')]
    assert obj.current_hp==300-2*rolls[0].total if damaging else obj.current_hp==300
    if empty:
        assert not rolls
        assert all(a.current_hp==60 for a in e.state.actors.values())


@pytest.mark.parametrize('kind,resisted',[('FIRE',True),('PSYCHIC',False),('RADIANT',False),('VOID',False)])
def test_demon_king_native_flight_and_resistance_exceptions(tmp_path,kind,resisted):
    from tests.worker2_support import sealed_native_attack
    def setup(bundles):
        sealed_native_attack(bundles[2],'Form defense probe',damage_type=kind,count=1,sides=4,modifier=10,attack_bonus=100)
    source='tianxia.subpath.qi.demon_prison_seal_cultivator.feature.demon_king_behind_the_seal'
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],cl=18,ask=False,bundle_transform=setup)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    execute(combat,mid,candidate(combat,mid,'Demon King Behind the Seal'))
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==60
    assert e.state.actors[OWNER].position==before
    assert e.state.actors[OWNER].resources['resource:core.qi']==92
    assert profile(e,e.state.actors[OWNER]).speed_ft==40
    assert profile(e,e.state.actors[OWNER]).hover
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Form defense probe',target=OWNER))
    e=reload(tmp_path,mid)
    rolled=next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:'))
    assert e.state.actors[OWNER].current_hp==60-(rolled.total//2 if resisted else rolled.total)


def test_cloud_step_opportunity_attack_has_disadvantage(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_features=[CLOUD+'cloud_step'],cl=6,ask=False,
        foe_position={'x':4,'y':6},ally_position={'x':7,'y':6})
    execute(combat,mid,candidate(combat,mid,'Cloud Step'))
    engine=combat._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination.x==2 and c.destination.y==6 and c.destination.z==0)
    execute(combat,mid,c)
    e=reload(tmp_path,mid)
    rolled=[r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('ATTACK:')]
    assert rolled and all(r.mode=='DISADVANTAGE' for r in rolled)


def test_note_auto_chooses_enemy_after_action_is_used(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'instrument_of_qi'],cl=3,owner_dc=100,ask=False,
        modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    execute(combat,mid,candidate(combat,mid,'Dodge'))
    for _ in range(4):
        e=reload(tmp_path,mid)
        if e.state.actors[OWNER].resources['resource:core.qi']==99:
            break
        assert e.state.current_actor_id==OWNER
        settle(table,mid,'unused',auto=True)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==99
    assert any(c.condition_id=='condition:typed.qi5_note_penalty' for c in e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.qi5_note_penalty' for c in e.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id=='condition:typed.qi5_note_penalty' for c in e.state.actors[OWNER].conditions.values())


def test_chains_successful_escape_releases_exact_hold_after_reload(tmp_path):
    source='tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
    second_source='action:test.second_caster_chain'
    from tests.h1_support import sheet
    foe=sheet([],cl=15)
    foe['ability_scores_and_statistics']['abilities']=[
        {'ability':a,'score':1000 if a=='STR' else 10,'modifier':495 if a=='STR' else 0}
        for a in ('STR','DEX','CON','INT','WIS','CHA')]
    def add_second_caster(bundles):
        from combat.canonical import canonical_sha256
        b=bundles[1]
        b['action_catalog'].append({'source_definition_id':second_source,'display_name':'Second caster chain','owner_id':ALLY,'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'parameters':{'free_primary':True,'typed':{'source':'system:test.second_caster','numbers':{'cl':15,'save_dc':100},'effects':[{'type':'condition','condition':'restrained','applies_to':'target','duration':'concentration','qi5_chain':True}]}}})
        b['actor_template']['action_ids'].append(second_source)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],cl=15,foe_sheet=foe,owner_dc=100,ask=True,bundle_transform=add_second_caster)
    execute(combat,mid,candidate(combat,mid,'Chains of Qi',target=FOE))
    first=next(c for c in reload(tmp_path,mid).state.actors[FOE].conditions.values() if c.data.get('qi5_chain'))
    turn(table,mid,ALLY)
    execute(combat,mid,candidate(combat,mid,'Second caster chain',target=FOE))
    both=reload(tmp_path,mid).state.actors[FOE].conditions.values()
    assert any(c.instance_id==first.instance_id for c in both)
    other=next(c for c in both if c.instance_id!=first.instance_id and c.data.get('qi5_chain'))
    turn(table,mid,FOE)
    escape=candidate(combat,mid,'Break Chains of Qi')
    settle(table,mid,escape.candidate_id,choices={'choice:needle.qi5_escape':[first.instance_id], 'choice:needle.qi5_escape_kind':['strength']})
    e=reload(tmp_path,mid)
    assert not any(c.instance_id==first.instance_id for c in e.state.actors[FOE].conditions.values())
    assert any(c.instance_id==other.instance_id for c in e.state.actors[FOE].conditions.values())
    assert e.state.actors[FOE].action_available is False


def test_chains_blocks_self_phasing_but_allows_granting_phase_to_ally(tmp_path):
    from combat.canonical import canonical_sha256
    source='tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
    def add_phase_actions(bundles):
        b=bundles[0]
        source_id='action:test.qi5.apply_chain'
        rows=[
            {'source_definition_id':'action:test.qi5.phase_self','display_name':'Phase self test',
             'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
             'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'incorporeal','applies_to':'self','duration':'one_minute'}]}}},
            {'source_definition_id':'action:test.qi5.phase_ally','display_name':'Phase ally test',
             'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ALLY_OR_SELF','range_ft':30,
             'parameters':{'free_primary':True,'typed':{'effects':[{'type':'condition','condition':'incorporeal','applies_to':'target','duration':'one_minute'}]}}},
        ]
        b['action_catalog'].extend(rows)
        b['actor_template']['action_ids'].extend(row['source_definition_id'] for row in rows)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
        foe=bundles[2]
        foe['action_catalog'].append({'source_definition_id':source_id,'display_name':'Apply Chains test',
            'owner_id':FOE,'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
            'parameters':{'free_primary':True,'typed':{'numbers':{'cl':15,'save_dc':100},'effects':[
                {'type':'condition','condition':'restrained','applies_to':'target','duration':'concentration','qi5_chain':True}]}}})
        foe['actor_template']['action_ids'].append(source_id)
        foe.pop('bundle_sha256',None);foe['bundle_sha256']=canonical_sha256(foe)
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],owner_dc=100,ask=False,bundle_transform=add_phase_actions)
    turn(table,mid,FOE)
    execute(combat,mid,candidate(combat,mid,'Apply Chains test',target=OWNER))
    assert any(c.data.get('qi5_chain') for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    turn(table,mid,OWNER)
    held=reload(tmp_path,mid).state.actors[OWNER]
    assert any(c.data.get('qi5_chain') for c in held.conditions.values())

    execute(combat,mid,candidate(combat,mid,'Phase self test'))
    after_self=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.incorporeal' for c in after_self.state.actors[OWNER].conditions.values())

    execute(combat,mid,candidate(combat,mid,'Phase ally test',target=ALLY))
    after_ally=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.incorporeal' for c in after_ally.state.actors[ALLY].conditions.values())
    assert any(c.data.get('qi5_chain') for c in after_ally.state.actors[OWNER].conditions.values())


def test_chains_second_turn_repeat_cadence_survives_reload(tmp_path):
    from tests.h1_support import sheet
    source='tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
    combat,table,mid=fixture(tmp_path,[],owner_features=[source],cl=15,foe_sheet=sheet([],cl=12),owner_dc=100,ask=False)
    execute(combat,mid,candidate(combat,mid,'Chains of Qi',target=FOE))
    first=reload(tmp_path,mid)
    hold=next(c for c in first.state.actors[FOE].conditions.values() if c.data.get('qi5_chain'))
    riders=[str(event.payload.get('rider')) for event in first.events if event.event_type=='GM_RIDER']
    assert any('The GM should stop you from calling a bound real item' in rider for rider in riders)
    assert hold.data['repeat_every']==2
    initial=sum(r.actor_id==FOE and r.reason.startswith('SAVE:') for r in first.rolls)
    turn(table,mid,FOE)
    after_one=reload(tmp_path,mid)
    assert sum(r.actor_id==FOE and r.reason.startswith('SAVE:') for r in after_one.rolls)==initial
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,FOE)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    after_two=reload(tmp_path,mid)
    assert sum(r.actor_id==FOE and r.reason.startswith('SAVE:') for r in after_two.rolls)>initial


@pytest.mark.parametrize('dc',[100,-100])
def test_shattering_note_deafened_conditions_expire_on_each_save_branch(tmp_path,dc):
    combat,table,mid=fixture(tmp_path,[],owner_features=[SOUND+'shattering_note'],cl=18,owner_dc=dc,ask=False,
        foe_position={'x':5,'y':6})
    execute(combat,mid,candidate(combat,mid,'Shattering Note',at=(5,6)))
    assert any(c.condition_id=='condition:typed.deafened' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())
    turn(table,mid,FOE)
    turn(table,mid,OWNER)
    if dc<0:
        assert not any(c.condition_id=='condition:typed.deafened' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id=='condition:typed.deafened' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('protected', [True, False], ids=['cloud-step', 'unprotected'])
def test_cloud_step_native_roster_opportunity_and_ordinary_attack_reload(tmp_path, protected):
    """Native Opportunity Attacks are protected after reload; ordinary attacks stay Normal."""
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet

    doc = sheet([], cl=6)
    if protected:
        doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [CLOUD+'cloud_step']
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': False})
    combat = CombatService(ROOT, tmp_path)
    mid = combat.persistence.create_match(match_seed='QI5-NATIVE-CLOUD', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [OWNER, AN], 'team_by_actor': {OWNER:'a', AN:'b'},
            'starting_positions': {OWNER:{'x':4,'y':6}, AN:{'x':5,'y':6}}}).match_id
    for aid in (OWNER, AN):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    if protected:
        execute(combat, mid, candidate(combat, mid, 'Cloud Step'))
    before = reload(tmp_path, mid)
    assert AN not in before.typed_actor_ids and AN not in before.runtime_actor_ids
    assert bool([c for c in before.state.actors[OWNER].conditions.values()
                 if c.condition_id == 'condition:typed.general_flight']) is protected
    c = next(c for c in before.legal_candidates() if c.kind.value == 'MOVE'
             and (c.destination.x, c.destination.y, c.destination.z) == (4,4,0))
    execute(combat, mid, c, reactions=[ReactionDecision(checkpoint='LEAVE_REACH', reactor_id=AN,
        reaction_source_id='system:combat.opportunity_attack', selection='USE')])
    after = reload(tmp_path, mid)
    attacks = [e for e in after.events if e.event_type == 'ATTACK_ROLLED'
               and e.source_definition_id == 'system:combat.opportunity_attack']
    assert len(attacks) == 1 and attacks[0].actor_id == AN and attacks[0].target_ids == (OWNER,)
    assert attacks[0].payload['mode'] == ('DISADVANTAGE' if protected else 'NORMAL')
    assert not after.state.actors[AN].reaction_available

    turn(table, mid, AN)
    e = reload(tmp_path, mid)
    c = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE'
             and (c.destination.x, c.destination.y, c.destination.z) == (5,5,0))
    execute(combat, mid, c)
    e = reload(tmp_path, mid)
    c = next(c for c in e.legal_candidates()
             if c.source_definition_id == 'action:an_eui.paired_bi_shou_assault' and c.target_ids == (OWNER,))
    execute(combat, mid, c)
    later = reload(tmp_path, mid)
    ordinary = [e for e in later.events if e.event_type == 'ATTACK_ROLLED'
                and e.source_definition_id == 'action:an_eui.paired_bi_shou_assault']
    assert ordinary and all(e.payload['mode'] == 'NORMAL' for e in ordinary)
    assert bool([c for c in later.state.actors[OWNER].conditions.values()
                 if c.condition_id == 'condition:typed.general_flight']) is protected
