"""Second-pass Life: real service/table intents, patient choices and cold reload."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import add_action

P = 'tianxia.talent.life.'
OTHER = 'actor:factory.worker2-ally3'
QI = 'resource:core.qi'


def find(combat, mid, *words, target=ALLY):
    e = combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.target_ids == (target,)
                and (a := e.action_catalog.get(c.source_definition_id)) and all(w in a.display_name for w in words))


def setup(bundles):
    for b in bundles:
        add_action(b, 'Injury', [{'type': 'damage', 'flat': 30, 'damage_types': ['force'], 'applies_to': 'target'}])
        add_action(b, 'Blind', [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        add_action(b, 'Poison', [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        add_action(b, 'Seal', [{'type': 'mark', 'mark': 'Pulse Seal', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])


def use(combat, table, mid, name, target, picks=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks)


def conditions(e, target):
    return {r.condition_id for r in e.state.actors[target].conditions.values()}


@pytest.mark.parametrize('talent,price', [('pulse_array_treatment', 3), ('shared_infirmary_hand', 2)])
def test_patients_get_independent_purify_choices(tmp_path, talent, price):
    combat, table, mid = fixture(tmp_path, [P+talent], extra_allies=1, bundle_transform=setup)
    for patient in (ALLY, OTHER):
        use(combat, table, mid, 'Seal', patient)
    use(combat, table, mid, 'Poison', ALLY)
    use(combat, table, mid, 'Blind', OTHER)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    prompts = settle(table, mid, find(combat, mid, 'Remove Poisoned', 'Pulse Array' if talent.startswith('pulse') else 'Shared Infirmary').candidate_id,
                     {'choice:needle.life_patients': OTHER, 'choice:needle.life_treatment': '0'})
    e = reload(tmp_path, mid)
    assert 'condition:typed.poisoned' not in conditions(e, ALLY)
    assert 'condition:typed.blinded' not in conditions(e, OTHER)
    assert e.state.actors[OWNER].resources[QI] == before-price
    assert any(p['context']['reactor_id'] == OTHER for p in prompts)
    assert any('worker2-ally3' in str(p) for p in prompts)


@pytest.mark.parametrize('talent,label', [('pulse_array_treatment', 'Pulse Array Treatment'), ('shared_infirmary_hand', 'Shared Infirmary Hand')])
@pytest.mark.parametrize('decline', [False, True])
def test_chosen_patient_and_consent_control_healing(tmp_path, talent, label, decline):
    combat, table, mid = fixture(tmp_path, [P+talent], extra_allies=1, bundle_transform=setup)
    for patient in (ALLY, OTHER):
        use(combat, table, mid, 'Injury', patient)
        use(combat, table, mid, 'Seal', patient)
    cast = find(combat, mid, 'Mend the Pulse', label)
    settle(table, mid, cast.candidate_id, {'choice:needle.life_patients': OTHER,
        'choice:needle.life_patient_consent': None if decline else 'accept'})
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].current_hp > 30
    assert (e.state.actors[OTHER].current_hp > 30) == (not decline)
    assert e.state.actors[OWNER].current_hp == 60


@pytest.mark.parametrize('cl,maximum', [(1,1),(5,2),(10,4),(15,4)])
def test_shared_infirmary_realm_limit(tmp_path, cl, maximum):
    combat, table, mid = fixture(tmp_path, [P+'shared_infirmary_hand'], cl=cl, extra_allies=5,
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':4,'y':6}, FOE:{'x':6,'y':6},
                   **{f'actor:factory.worker2-ally{i}':{'x':x,'y':y} for i,(x,y) in enumerate([(2,6),(3,5),(3,7),(2,5),(4,5)],3)}},
        bundle_transform=setup)
    use(combat, table, mid, 'Injury', ALLY)
    prompts = settle(table, mid, find(combat, mid, 'Mend the Pulse', 'Shared Infirmary').candidate_id,
                     {'choice:needle.life_patients': None})
    question = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.life_patients')
    assert question['choice']['maximum'] == maximum
    reload(tmp_path, mid)


@pytest.mark.parametrize('talent,label', [('pulse_array_treatment','Pulse Array Treatment'), ('shared_infirmary_hand','Shared Infirmary Hand')])
@pytest.mark.parametrize('body,allowed', [(False,True),(True,False)])
def test_remote_patient_respects_body_contact(tmp_path, talent, label, body, allowed):
    combat, table, mid = fixture(tmp_path, [P+talent], extra_allies=1, owner_path='Body Refining' if body else None,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6},OTHER:{'x':7,'y':6}}, bundle_transform=setup)
    for patient in (ALLY,OTHER):
        use(combat, table, mid, 'Seal', patient)
        use(combat, table, mid, 'Injury', patient)
    prompts = settle(table, mid, find(combat, mid, 'Mend the Pulse', label).candidate_id,
                     {'choice:needle.life_patients': OTHER} if allowed else {'choice:needle.life_patients': None})
    e = reload(tmp_path, mid)
    options = [o['id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.life_patients' for o in p['choice']['options']]
    assert (OTHER in options) == allowed
    assert (e.state.actors[OTHER].current_hp > 30) == allowed


def test_restorative_mend_patient_selects_one_condition(tmp_path):
    combat, table, mid = fixture(tmp_path, [P+'restorative_mend'], bundle_transform=setup)
    for name in ('Injury','Blind','Poison'):
        use(combat, table, mid, name, ALLY)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    settle(table, mid, find(combat, mid, 'Mend the Pulse + Restorative Mend').candidate_id,
           {'choice:needle.life_treatment':'3'})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp > 30
    assert 'condition:typed.blinded' in conditions(e,ALLY)
    assert 'condition:typed.poisoned' not in conditions(e,ALLY)
    assert e.state.actors[OWNER].resources[QI] == before-2


def test_restorative_mend_composes_owned_mind_cooling_and_cost(tmp_path):
    def prepare(bundles):
        setup(bundles)
        add_action(bundles[0],'Fear',[{'type':'condition','condition':'frightened','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    combat,table,mid=fixture(tmp_path,[P+'restorative_mend',P+'mind_cooling_pulse'],bundle_transform=prepare)
    for name in ('Injury','Blind','Fear'):
        use(combat,table,mid,name,ALLY)
    before=reload(tmp_path,mid).state.actors[OWNER].resources[QI]
    settle(table,mid,find(combat,mid,'Mend the Pulse + Restorative Mend','/ Purify','Remove Blinded','Mind-Cooling').candidate_id,
           {'choice:needle.purify_extra':'frightened'})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp>30
    assert not {'condition:typed.blinded','condition:typed.frightened'} & conditions(e,ALLY)
    assert e.state.actors[OWNER].resources[QI] == before-3


@pytest.mark.parametrize('permitted', [False,True])
def test_life_seal_reach_body_permission_is_compile_time_gate(tmp_path,permitted):
    permission={'talent_id':P+'life_seal_reach','record_id':'test:connection','note':'A physical Life thread connects this patient.'} if permitted else None
    combat,table,mid=fixture(tmp_path,[P+'life_seal_reach'],owner_path='Body Refining',owner_permission=permission,
        ally_position={'x':7,'y':6},bundle_transform=setup)
    for name in ('Seal','Injury'):
        use(combat,table,mid,name,ALLY)
    e=reload(tmp_path,mid)
    rows=[c for c in e.legal_candidates() if c.target_ids==(ALLY,) and 'Mend the Pulse' in c.display_name and 'Life-Seal Reach' in c.display_name]
    assert bool(rows)==permitted
    if permitted:
        before=e.state.actors[OWNER].resources[QI]
        settle(table,mid,rows[0].candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.actors[ALLY].current_hp>30
        assert e.state.actors[OWNER].resources[QI]==before-1

@pytest.mark.parametrize('cl,reach',[(1,30),(5,30),(10,60),(15,120)])
def test_array_realm_range_and_first_patient_requires_seal(tmp_path,cl,reach):
    combat,table,mid=fixture(tmp_path,[P+'pulse_array_treatment'],cl=cl,
        ally_position={'x':7,'y':6},bundle_transform=setup)
    use(combat,table,mid,'Injury',ALLY)
    e=reload(tmp_path,mid)
    assert not any(c.target_ids==(ALLY,) and 'Pulse Array Treatment' in c.display_name for c in e.legal_candidates())
    use(combat,table,mid,'Seal',ALLY)
    c=find(combat,mid,'Mend the Pulse','Pulse Array')
    assert combat._load_session(mid).engine.action_catalog[c.source_definition_id].range_ft==reach
    settle(table,mid,c.candidate_id,{'choice:needle.life_patients':None})
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp>30

@pytest.mark.parametrize('talent,label',[('pulse_array_treatment','Pulse Array Treatment'),('shared_infirmary_hand','Shared Infirmary Hand')])
def test_explicit_body_contact_permission_allows_remote_patient(tmp_path,talent,label):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    doc=sheet([P+talent],cl=15)
    doc['identity']['path']='Body Refining'
    doc['path_and_subpath']={'life_contact_permissions':{P+talent:{'talent_id':P+talent,'record_id':'test:forged-physical-thread','note':'A living physical thread remains attached to the sealed patient.'}}}
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path,[P+talent],owner_path='Body Refining',owner_bundle=bundle,extra_allies=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6},OTHER:{'x':7,'y':6}},bundle_transform=setup)
    for patient in (ALLY,OTHER):
        use(combat,table,mid,'Seal',patient)
        use(combat,table,mid,'Injury',patient)
    settle(table,mid,find(combat,mid,'Mend the Pulse',label).candidate_id,{'choice:needle.life_patients':OTHER})
    assert reload(tmp_path,mid).state.actors[OTHER].current_hp>30

@pytest.mark.parametrize('blocked',['unsealed','hidden','full_hp'])
def test_array_excludes_unavailable_patients(tmp_path,blocked):
    def prepare(bundles):
        setup(bundles)
        add_action(bundles[0],'Invisible',[{'type':'condition','condition':'invisible','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    combat,table,mid=fixture(tmp_path,[P+'pulse_array_treatment'],extra_allies=1,bundle_transform=prepare)
    use(combat,table,mid,'Seal',ALLY)
    use(combat,table,mid,'Injury',ALLY)
    if blocked!='unsealed':
        use(combat,table,mid,'Seal',OTHER)
    if blocked!='full_hp':
        use(combat,table,mid,'Injury',OTHER)
    if blocked=='hidden':
        use(combat,table,mid,'Invisible',OTHER)
    prompts=settle(table,mid,find(combat,mid,'Borrowed Breath','Pulse Array').candidate_id,{'choice:needle.life_patients':None})
    options=[o['id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.life_patients' for o in p['choice']['options']]
    assert OTHER not in options
    e=reload(tmp_path,mid)
    assert e.state.actors[OTHER].temporary_hp==0

@pytest.mark.parametrize('accept',[True,False])
def test_shared_read_patient_on_another_team_owns_consent_and_seal(tmp_path,accept):
    from combat.typed_executor import bears_mark
    combat,table,mid=fixture(tmp_path,[P+'shared_infirmary_hand'],foe_position={'x':4,'y':7},bundle_transform=setup)
    prompts=settle(table,mid,find(combat,mid,'Read the Pulse','Shared Infirmary').candidate_id,
        {'choice:needle.life_patients':FOE,'choice:needle.life_patient_consent':'accept' if accept else None})
    e=reload(tmp_path,mid)
    assert bears_mark(e.state.actors[FOE],OWNER,'Pulse Seal') == accept
    assert bears_mark(e.state.actors[ALLY],OWNER,'Pulse Seal')
    assert not bears_mark(e.state.actors[OWNER],OWNER,'Pulse Seal')
    assert any(p['context']['reactor_id']==FOE for p in prompts)
    assert any('Read the Pulse:' in str(event.payload) and FOE in event.target_ids for event in e.events) == accept

@pytest.mark.parametrize('talent,label',[('pulse_array_treatment','Pulse Array Treatment'),('shared_infirmary_hand','Shared Infirmary Hand')])
def test_group_self_cast_also_treats_chosen_patient_once(tmp_path,talent,label):
    def prepare(bundles):
        setup(bundles)
        add_action(bundles[0],'Self injury',[{'type':'damage','flat':30,'damage_types':['force'],'applies_to':'self'}],target='SELF')
    combat,table,mid=fixture(tmp_path,[P+talent],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Self injury').candidate_id)
    use(combat,table,mid,'Injury',ALLY)
    use(combat,table,mid,'Seal',ALLY)
    settle(table,mid,find(combat,mid,'Read the Pulse',target=OWNER).candidate_id)
    before_engine=reload(tmp_path,mid)
    assert before_engine.state.actors[OWNER].current_hp == 30
    assert before_engine.state.actors[ALLY].current_hp == 30
    before=before_engine.state.actors[OWNER].resources[QI]
    settle(table,mid,find(combat,mid,'Mend the Pulse',label,target=OWNER).candidate_id,{'choice:needle.life_patients':ALLY})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp>30
    assert e.state.actors[ALLY].current_hp>30
    healed=[event for event in e.events if event.event_type=='HEALING_APPLIED']
    assert sum(OWNER in event.target_ids for event in healed)==1
    assert sum(ALLY in event.target_ids for event in healed)==1
    assert e.state.actors[OWNER].resources[QI]==before-(3 if talent.startswith('pulse') else 2)

@pytest.mark.parametrize('talent,label',[('pulse_array_treatment','Pulse Array Treatment'),('shared_infirmary_hand','Shared Infirmary Hand')])
@pytest.mark.parametrize('malformed',[None,[], 'unrecorded permission'])
def test_malformed_body_contact_permission_fails_closed(tmp_path,talent,label,malformed):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    doc=sheet([P+talent],cl=15)
    doc['identity']['path']='Body Refining'
    doc['path_and_subpath']={'life_contact_permissions':malformed}
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path,[P+talent],owner_path='Body Refining',owner_bundle=bundle,extra_allies=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6},OTHER:{'x':7,'y':6}},bundle_transform=setup)
    for patient in (ALLY,OTHER):
        use(combat,table,mid,'Seal',patient)
        use(combat,table,mid,'Injury',patient)
    prompts=settle(table,mid,find(combat,mid,'Mend the Pulse',label).candidate_id,{'choice:needle.life_patients':None})
    options=[o['id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.life_patients' for o in p['choice']['options']]
    assert OTHER not in options
    e=reload(tmp_path,mid)
    assert e.state.actors[OTHER].current_hp==30
    assert not getattr(e,'_ext_failures_logged',set())
