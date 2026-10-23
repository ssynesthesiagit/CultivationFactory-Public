"""Printed Qi choices through CombatService, session execute_intent and reload."""
import json
import zipfile
from pathlib import Path
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import auto11_service_support as S
from tests.h1_support import sheet, ROOT
from tests.cw2_service_support import add_action, seal
from combat.ext.qi_subpaths_1 import HEART, PULSE, TEA, SERVICE, NEXT, EXPOSURE

ME, ALLY, FOE = S.THIEF, S.ALLY, S.VICTIM
QI = 'resource:core.qi'


def fight(tmp_path, features, *, seed='A2GQISUB1', dc=30, ally_dc=None, ally_features=(), positions=None, foe_wis_save=None, ally_size=None, objects=None, hazard=False, cl=14, rounds=10):
    ids = [ME, ALLY, FOE]
    docs = {who: sheet(features if who == ME else list(ally_features) if who == ALLY else [], cl=cl,
                        dc=(ally_dc if who == ALLY and ally_dc is not None else dc),
                        kit={'starting_kit': S.SWORD}) for who in ids}
    # Restricted Scriptures are acquired through the same validated producer
    # as owner-authored characters, rather than a bare feature-id grant.
    from combat.feature_access import acquire, policy
    for who, doc in docs.items():
        doc.setdefault('path_and_subpath', {})['path_record_ids'] = ['tianxia.path.qi_cultivation']
        for feature in features if who == ME else ally_features if who == ALLY else ():
            if policy(feature):
                doc = acquire(doc, feature, {'kind': 'gm_authorized',
                    'reference': 'Service regression: recorded Restricted Scripture instruction',
                    'classification': 'Restricted Scripture'})
        docs[who] = doc
    for who, doc in docs.items():
        doc['identity']['display_name'] = {ME:'Cultivator', ALLY:'Ally', FOE:'Enemy'}[who]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        folder = tmp_path/'portable_characters'/who.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(docs[who], actor_id=who, reaction_plan={'ask': True}) for who in ids]
    if foe_wis_save is not None:
        bundles[2]['actor_template']['saving_throws']['WIS'] = foe_wis_save
        seal(bundles[2])
    # Explicit setup through accepted intents, sealed before genesis.
    for bundle in bundles:
        add_action(bundle, 'Test teleport', [{'type':'teleport','applies_to':'self','distance_ft':15}], target='SELF')
    add_action(bundles[0], 'Wound', [{'type':'damage','flat':100,'damage_types':['force'], 'applies_to':'target'}])
    for name in ('charmed', 'frightened', 'poisoned', 'invisible', 'diseased', 'bleeding'):
        add_action(bundles[0], 'Prepare '+name, [{'type':'save','ability':'wis','applies_to':'target',
            'on_fail':[{'type':'condition','condition':name,'applies_to':'target','expires_on':'UNTIL_REMOVED'}]}],
            typed={'numbers': {'cl':14,'pb':4,'key_mod':2,'save_dc':30}})
    add_action(bundles[0], 'Higher fright', [{'type':'save','ability':'wis','applies_to':'target',
        'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target','expires_on':'UNTIL_REMOVED'}]}],
        typed={'numbers':{'cl':18,'pb':4,'key_mod':2,'save_dc':30}})
    add_action(bundles[0], 'Prepare save disadvantage', [{'type':'next_d20_mode',
        'mode':'DISADVANTAGE','kinds':['save'],'applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    add_action(bundles[0], 'Test check', [{'type':'skill_check','ability':'wis','skill':'Medicine','dc':10,
                                        'on_success':[], 'on_failure':[]}], target='ALLY_OR_SELF')
    add_action(bundles[0], 'Test save', [{'type':'save','ability':'wis','applies_to':'target','on_fail':[], 'on_success':[]}])
    add_action(bundles[1], 'Test save', [{'type':'save','ability':'wis','applies_to':'target','on_fail':[], 'on_success':[]}])
    add_action(bundles[0], 'Test repeated Sorrow', [
        {'type':'qi_pulse','form':'sorrow','expires_on':'START_OF_SOURCE_NEXT_TURN'},
        {'type':'qi_pulse','form':'sorrow','expires_on':'START_OF_SOURCE_NEXT_TURN'}],
        target='HOSTILE_ENTITY', typed={'numbers':{'save_dc':1,'pb':4,'key_mod':2,'cl':14}})
    add_action(bundles[2], 'Prepare benefit', [{'type':'speed','flat':5,
        'applies_to':'self','expires_on':'UNTIL_REMOVED'}], target='SELF')
    add_action(bundles[2], 'Prepare wound', [{'type':'condition','condition':'bleeding',
        'applies_to':'target','expires_on':'UNTIL_REMOVED'}], target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Rage probe attack', [{'type':'attack','attack_kind':'cultivation_ranged',
        'on_hit':[],'on_miss':[]}], target='HOSTILE_ENTITY',
        typed={'range_ft':120,'numbers':{'pb':4,'key_mod':2,'save_dc':16,'cl':15,'attack_bonus':8}})
    add_action(bundles[2], 'Rage Escalation Test', [{'type':'temp_hp','applies_to':'self','flat':1}],
        target='SELF', typed={'activation_categories':['emotional_escalation']})
    if ally_size is not None:
        add_action(bundles[1], 'Prepare size', [{'type':'size_change','size':ally_size,
            'expires_on':'UNTIL_REMOVED'}], target='SELF')
    svc=CombatService(ROOT,tmp_path);table=TabletopService(svc,tmp_path)
    arena=svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    if hazard:
        arena = {**arena, 'terrain_regions': [*arena['terrain_regions'],
            {'terrain_type':'QI_HAZARD','cells':[{'x':3,'y':8}], 'movement_cost':5}]}
    if objects is not None:
        arena = {**arena, 'map_objects': objects}
    mid=svc._finish_factory_match(bundles,ids,{ME:'team:a',ALLY:'team:a',FOE:'team:b'},
        positions or {ME:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}},arena,[ME],[ALLY,FOE],
        control_modes={who:'MANUAL' for who in ids},match_seed=seed,display_name='Qi subpath choices',maximum_rounds=rounds)['match_id']
    S.to_thief(table,mid)
    return svc,table,mid


def cold(svc,mid):
    other=CombatService(svc.source_root,svc.userdata_root)
    assert other.replay(mid)['status']=='PASS'
    assert not any(e.source_definition_id=='ext:combat.ext.qi_subpaths_1' for e in S.engine(other,mid).events)
    return S.engine(other,mid)


def use(table,mid,label,target=ALLY,answer=None):
    return S.play(table,mid,S.candidate(table,mid,label,target=target),answer=answer)


def conditions(actor,name):
    return [c for c in actor.conditions.values() if c.condition_id=='condition:typed.'+name]


@pytest.mark.parametrize('benefit', ['temporary_hp','charmed','frightened','repeat'])
def test_heartmend_chooses_one_qualified_benefit_and_cold_reloads(tmp_path,benefit):
    svc,table,mid=fight(tmp_path,[HEART])
    use(table,mid,'Wound')
    if benefit in ('charmed','frightened'):
        use(table,mid,'Prepare '+benefit)
    if benefit=='repeat':
        use(table,mid,'Higher fright')
    before=cold(svc,mid);hp=before.state.actors[ALLY].current_hp
    def answer(prompt):
        source=prompt['context']['reaction_source_id']
        if source == 'choice:willing.consent': return 'accept'
        if source=='choice:needle.heartmend':return benefit
        if source=='choice:needle.source_relief':return prompt['choice']['options'][0]['id']
        return None
    result,prompts=use(table,mid,'Heartmend',answer=answer)
    assert result['status']=='COMMITTED'
    eng=cold(svc,mid);ally=eng.state.actors[ALLY]
    assert hp+6<=ally.current_hp<=hp+34
    assert eng.state.actors[ME].resources[QI]==26
    assert ally.temporary_hp==(8 if benefit=='temporary_hp' else 0)
    if benefit in ('charmed','frightened'):
        assert not conditions(ally,benefit)
    if benefit=='repeat':
        saves=[e for e in eng.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY and 'heartbreak_and_heartmend' in e.source_definition_id]
        assert saves and saves[-1].payload['mode']=='ADVANTAGE'
    assert eng.state.model_dump(mode='json')==S.engine(svc,mid).state.model_dump(mode='json')


def test_heartmend_does_not_offer_removal_of_higher_authority(tmp_path):
    svc,table,mid=fight(tmp_path,[HEART]);use(table,mid,'Higher fright')
    result,prompts=use(table,mid,'Heartmend',answer=lambda p:'accept' if p['context']['reaction_source_id']=='choice:willing.consent' else 'temporary_hp')
    menu=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.heartmend')
    assert {o['id'] for o in menu['choice']['options']}=={'temporary_hp','repeat'}
    repeat=next(o['label'] for o in menu['choice']['options'] if o['id']=='repeat')
    assert 'Cultivation Level (the number on its character sheet) is higher than yours' in repeat and 'higher-CL' not in repeat
    assert conditions(cold(svc,mid).state.actors[ALLY],'frightened')


def test_heartbreak_requires_own_pulse_and_adds_bonus_to_same_damage_packet(tmp_path):
    svc,table,mid=fight(tmp_path,[HEART,PULSE])
    labels=[g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any(': Heartbreak' in label for label in labels)
    use(table,mid,'Emotional Pulse: Pulse of Fear',target=FOE)
    S.to_thief(table,mid,end_thief=True)
    before=cold(svc,mid);assert any(c.condition_id==EXPOSURE for c in before.state.actors[FOE].conditions.values())
    # Pulse's Fear expires at the next source start; put a fresh own-source Fear on it.
    use(table,mid,'Prepare frightened',target=FOE)
    use(table,mid,': Heartbreak',target=FOE)
    eng=cold(svc,mid)
    damage=[e for e in eng.events if e.event_type=='DAMAGE_ROLLED' and 'heartbreak_and_heartmend' in e.source_definition_id]
    assert len(damage)==1
    assert damage[0].payload['modifier']==4
    assert any(c.expires_on=='END_OF_HOLDER_NEXT_TURN' for c in conditions(eng.state.actors[FOE],'reaction_denied'))
    assert eng.state.actors[ME].resources[QI]==24


def tea_answer(benefit):
    def answer(prompt):
        source=prompt['context']['reaction_source_id']
        if source=='choice:needle.nine_temperature_targets':return ALLY
        if source=='choice:willing.consent':return 'accept'
        if source=='choice:needle.nine_temperature_benefit':return benefit
        if source=='choice:needle.source_relief':return prompt['choice']['options'][0]['id']
        if source=='choice:needle.subject_destination':return 'cell:3,8'
        return None
    return answer


@pytest.mark.parametrize('benefit',['heal','temporary_hp','move','advantage','end'])
def test_nine_temperature_has_one_benefit_and_once_scene_receipt(tmp_path,benefit):
    svc,table,mid=fight(tmp_path,[TEA]);use(table,mid,'Wound')
    if benefit=='end':use(table,mid,'Prepare poisoned')
    before=cold(svc,mid).state.actors[ALLY]
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer(benefit))
    eng=cold(svc,mid);ally=eng.state.actors[ALLY]
    assert eng.state.actors[ME].resources[QI]==25
    assert bool(ally.current_hp>before.current_hp)==(benefit=='heal')
    assert ally.temporary_hp==(12 if benefit=='temporary_hp' else 0)
    assert bool(ally.position!=before.position)==(benefit=='move')
    assert bool(any(c.condition_id==NEXT for c in ally.conditions.values()))==(benefit=='advantage')
    assert not conditions(ally,'charmed')
    if benefit=='end':assert not conditions(ally,'poisoned')
    assert any(c.condition_id==SERVICE for c in ally.conditions.values())
    S.to_thief(table,mid,end_thief=True)
    result=S.act(table,mid,S.candidate(table,mid,'Nine-Temperature Service',target=ME))
    assert result['status']=='REACTION_REQUIRED'
    menu=result['reaction'];assert ALLY not in {o['id'] for o in menu['choice']['options']}


def test_automatic_nine_temperature_only_serves_allies_and_self(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    svc,table,mid=fight(tmp_path,[TEA]);cid=S.candidate(table,mid,'Nine-Temperature Service',target=ME)
    force_ai_candidate(svc,mid,ME,cid)
    result=table.auto_step(mid,table.state(mid)['last_sequence'])
    assert result['status']=='REACTION_REQUIRED',result
    assert result['reaction']['context']['reaction_source_id']=='choice:willing.consent'
    assert result['reaction']['context']['reactor_id']==ALLY


@pytest.mark.parametrize('form,expected', [('Pulse of Rage','emotional_rage'),('Pulse of Sorrow','emotional_sorrow'),
    ('Pulse of Fear','frightened'),('Hostile Joy','reaction_denied'),('Hostile Calm','emotional_calm')])
def test_each_hostile_pulse_has_only_its_printed_outcomes_and_reloads(tmp_path,form,expected):
    svc,table,mid=fight(tmp_path,[PULSE]);use(table,mid,'Emotional Pulse: '+form,target=FOE)
    eng=cold(svc,mid);foe=eng.state.actors[FOE]
    assert conditions(foe,expected)
    if form!='Pulse of Fear':assert not conditions(foe,'frightened')
    if form!='Hostile Joy':assert not conditions(foe,'concentration_mode')
    assert foe.temporary_hp==0
    assert eng.state.actors[ME].resources[QI]==28
    assert any(c.condition_id==EXPOSURE for c in foe.conditions.values())
    assert not eng.state.actors[ALLY].conditions


@pytest.mark.parametrize('form', ['Willing Joy','Willing Calm'])
def test_willing_pulse_has_no_save_and_its_own_benefit_only(tmp_path,form):
    svc,table,mid=fight(tmp_path,[PULSE])
    result,prompts=use(table,mid,'Emotional Pulse: '+form,answer=lambda p:'accept' if p['context']['reaction_source_id']=='choice:willing.consent' else ('cell:3,8' if p['context']['reaction_source_id']=='choice:needle.subject_destination' else None))
    eng=cold(svc,mid);ally=eng.state.actors[ALLY]
    assert ally.temporary_hp==(4 if form=='Willing Joy' else 0)
    assert bool(conditions(ally,'save_against'))==(form=='Willing Calm')
    assert not any(e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY for e in eng.events)
    assert (ally.position.x,ally.position.y)==(3,8)
    assert not conditions(ally,'reaction_denied')


def test_sorrow_save_spends_the_penalty_once_after_cold_reload(tmp_path):
    svc,table,mid=fight(tmp_path,[PULSE]);use(table,mid,'Emotional Pulse: Pulse of Sorrow',target=FOE)
    assert conditions(cold(svc,mid).state.actors[FOE],'emotional_sorrow')
    use(table,mid,'Test save',target=FOE)
    eng=cold(svc,mid)
    rewritten=[e for e in eng.events if e.event_type=='D20_REWRITTEN' and 'emotional_pulse' in e.source_definition_id]
    assert len(rewritten)==1 and -4<=rewritten[0].payload['bonus']<=-1
    assert not conditions(eng.state.actors[FOE],'emotional_sorrow')
    use(table,mid,'Test save',target=FOE)
    assert len([e for e in cold(svc,mid).events if e.event_type=='D20_REWRITTEN' and 'emotional_pulse' in e.source_definition_id])==1


@pytest.mark.parametrize('roll_kind',['check','save'])
def test_nine_temperature_next_roll_advantage_is_one_shared_allowance(tmp_path,roll_kind):
    svc,table,mid=fight(tmp_path,[TEA])
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer('advantage'))
    assert any(c.condition_id==NEXT for c in cold(svc,mid).state.actors[ALLY].conditions.values())
    use(table,mid,'Test '+roll_kind,target=ALLY)
    eng=cold(svc,mid)
    prefix='CHECK:' if roll_kind=='check' else 'SAVE:'
    actual=[r for r in eng.rolls if r.actor_id==ALLY and r.reason.startswith(prefix)]
    assert actual[-1].mode=='ADVANTAGE'
    assert not any(c.condition_id==NEXT for c in eng.state.actors[ALLY].conditions.values())
    use(table,mid,'Test save' if roll_kind=='check' else 'Test check',target=ALLY)
    eng=cold(svc,mid)
    second=[r for r in eng.rolls if r.actor_id==ALLY and r.reason.startswith('SAVE:' if roll_kind=='check' else 'CHECK:')]
    assert second[-1].mode=='NORMAL'


@pytest.mark.parametrize('wall_feature,wall_label,breach_label,skill,ally_size', [
    ('TAL_SAND_DUNE_WALL', 'Dune Wall', 'Force through the wall', 'Athletics', 'Large'),
    ('tianxia.subpath.qi.puzzle_cultivator.feature.puzzle_wall', 'Puzzle Wall',
     'Work the Puzzle Wall', 'Investigation', None),
])
@pytest.mark.parametrize('poisoned', [False, True])
def test_nine_temperature_real_wall_check_applies_mode_before_consumption(
        tmp_path, wall_feature, wall_label, breach_label, skill, ally_size, poisoned):
    svc,table,mid=fight(tmp_path,[TEA,wall_feature],ally_size=ally_size)
    if poisoned:
        use(table,mid,'Prepare poisoned')
        assert conditions(cold(svc,mid).state.actors[ALLY],'poisoned')
    # Raise a shipped wall through the actual table intent, next to the recipient.
    group=next(g for g in table.state(mid)['menu']['actions'] if g['label']==wall_label)
    if group.get('placement_picker'):
        # The native two-stage placement contract retains every legal square
        # behind one root candidate. Submit the exact square through that API.
        decision = svc.decision(mid)['context']
        root = next(c for c in decision['legal_candidates']
            if c['candidate_id'] == group['options'][0]['candidate_id'])
        payload = {key: root.get(key) for key in ('candidate_id','decision_id','state_version',
            'actor_id','target_ids','destination','option_ids')}
        payload['placement_destination'] = {'x':4,'y':8}
        svc.submit_intent(mid, payload, [], None)
    else:
        cid=next(o['candidate_id'] for o in group['options'] if o['destination']=={'x':4,'y':8})
        S.play(table,mid,cid)
    S.to_thief(table,mid,end_thief=True)
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer('advantage'))
    assert any(c.condition_id==NEXT for c in cold(svc,mid).state.actors[ALLY].conditions.values())
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==ALLY
    if ally_size:
        use(table,mid,'Prepare size',target=ALLY)
    # Recreate both services before executing the compiled native breach action.
    other=CombatService(ROOT,tmp_path)
    table=TabletopService(other,tmp_path)
    before=cold(other,mid)
    assert any(c.condition_id==NEXT for c in before.state.actors[ALLY].conditions.values())
    counter=before.roller.counter
    result,_=use(table,mid,breach_label,target=ALLY)
    assert result['status']=='COMMITTED'
    eng=cold(other,mid)
    rolls=[r for r in eng.rolls if r.actor_id==ALLY and r.reason.startswith('CHECK:')]
    assert len(rolls)==1
    actual=rolls[0]
    assert actual.mode==('NORMAL' if poisoned else 'ADVANTAGE')
    assert len(actual.dice)==(1 if poisoned else 2)
    assert actual.counter_start==counter
    assert actual.counter_end-counter==(1 if poisoned else 2)
    checks=[e for e in eng.events if e.event_type=='CHECK_ROLLED' and e.actor_id==ALLY]
    assert len(checks)==1 and checks[0].payload['skill']==skill
    assert checks[0].payload['actor']==actual.model_dump(mode='json')
    assert not any(c.condition_id==NEXT for c in eng.state.actors[ALLY].conditions.values())
    assert any(c.condition_id==SERVICE for c in eng.state.actors[ALLY].conditions.values())
    # The one shared allowance is gone even when cancellation correctly drew NORMAL.
    S.to_thief(table,mid)
    use(table,mid,'Test save',target=ALLY)
    eng=cold(other,mid)
    assert [r for r in eng.rolls if r.actor_id==ALLY and r.reason.startswith('SAVE:')][-1].mode=='NORMAL'


def test_manual_nine_temperature_cannot_repeat_a_benefit_for_two_recipients(tmp_path):
    svc,table,mid=fight(tmp_path,[TEA])
    cid=S.candidate(table,mid,'Nine-Temperature Service',target=ME)
    answers=[];seen=[]
    for _ in range(20):
        result=S.act(table,mid,cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];reply=S.answer_for(prompt)
        source=prompt['context']['reaction_source_id']
        if source=='choice:needle.nine_temperature_targets':
            reply={**prompt['context'],'selection':'USE','option_ids':[ME,ALLY]}
        elif source=='choice:needle.nine_temperature_benefit':
            ids={o['id'] for o in prompt['choice']['options']}
            if not seen:
                assert 'temporary_hp' in ids
                reply={**prompt['context'],'selection':'USE','option_ids':['temporary_hp']}
            else:
                assert 'temporary_hp' not in ids
                reply={**prompt['context'],'selection':'USE','option_ids':['advantage']}
            seen.append(prompt)
        elif source=='choice:willing.consent':
            reply={**prompt['context'],'selection':'USE','option_ids':['accept']}
        answers.append(reply)
    else:pytest.fail('Service did not commit')
    assert len(seen)==2
    eng=cold(svc,mid)
    assert sorted(eng.state.actors[who].temporary_hp for who in (ME,ALLY))==[0,12]
    assert all(any(c.condition_id==SERVICE for c in eng.state.actors[who].conditions.values()) for who in (ME,ALLY))


def test_hostile_pulse_target_can_accept_failure_without_rolling(tmp_path):
    svc,table,mid=fight(tmp_path,[PULSE],dc=1)
    use(table,mid,'Emotional Pulse: Pulse of Fear',target=FOE,
        answer=lambda p:'accept' if p['context']['reaction_source_id']=='choice:willing.consent' else None)
    eng=cold(svc,mid)
    assert conditions(eng.state.actors[FOE],'frightened')
    assert not conditions(eng.state.actors[FOE],'reaction_denied')
    assert not any(e.event_type=='SAVE_ROLLED' and e.actor_id==FOE for e in eng.events)
    assert eng.state.actors[ME].resources[QI]==28


def test_nine_temperature_next_save_includes_one_death_save(tmp_path):
    svc,table,mid=fight(tmp_path,[TEA])
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer('advantage'))
    for _ in range(4):use(table,mid,'Wound')
    assert cold(svc,mid).state.actors[ALLY].life_state=='DYING'
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    eng=cold(svc,mid)
    for _ in range(3):
        if any(r.actor_id==ALLY and r.reason=='SAVE:death' for r in eng.rolls):break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
        eng=cold(svc,mid)
    rolls=[r for r in eng.rolls if r.actor_id==ALLY and r.reason=='SAVE:death']
    assert rolls and rolls[-1].mode=='ADVANTAGE'
    assert not any(c.condition_id==NEXT for c in eng.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('movement',['walk','teleport'])
def test_rage_stops_voluntary_movement_away_from_perceived_hostiles(tmp_path,movement):
    svc,table,mid=fight(tmp_path,[PULSE])
    use(table,mid,'Emotional Pulse: Pulse of Rage',target=FOE)
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==FOE:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==FOE
    eng=cold(svc,mid);before=eng.state.actors[FOE].position
    assert conditions(eng.state.actors[FOE],'emotional_rage')
    if movement=='walk':
        cid=next(o['candidate_id'] for o in table.state(mid)['menu']['moves'] if o['destination']=={'x':5,'y':6})
        S.play(table,mid,cid)
    else:
        use(table,mid,'Test teleport',target=FOE,
            answer=lambda p:'cell:5,6' if p['context']['reaction_source_id']=='choice:needle.teleport_destination' else None)
    assert cold(svc,mid).state.actors[FOE].position==before


def test_nine_temperature_once_scene_limit_is_shared_between_casters(tmp_path):
    svc,table,mid=fight(tmp_path,[TEA],ally_features=[TEA])
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer('temporary_hp'))
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==ALLY
    result=S.act(table,mid,S.candidate(table,mid,'Nine-Temperature Service',target=ALLY))
    assert result['status']=='REACTION_REQUIRED'
    assert result['reaction']['context']['reaction_source_id']=='choice:needle.nine_temperature_targets'
    assert ALLY not in {o['id'] for o in result['reaction']['choice']['options']}
    cold(svc,mid)


def test_sorrow_penalty_applies_to_actual_death_save(tmp_path):
    svc,table,mid=fight(tmp_path,[PULSE])
    use(table,mid,'Emotional Pulse: Pulse of Sorrow',target=FOE)
    for _ in range(4):use(table,mid,'Wound',target=FOE)
    assert cold(svc,mid).state.actors[FOE].life_state=='DYING'
    for _ in range(3):
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
        eng=cold(svc,mid)
        rolls=[r for r in eng.rolls if r.actor_id==FOE and r.reason=='SAVE:death']
        if rolls:break
    assert rolls and -4<=rolls[-1].modifier<=-1
    assert not conditions(eng.state.actors[FOE],'emotional_sorrow')


def test_death_save_runs_d20_rewrite_checkpoint_once(tmp_path, monkeypatch):
    svc, table, mid = fight(tmp_path, [PULSE])
    use(table, mid, 'Emotional Pulse: Pulse of Sorrow', target=FOE,
        answer=lambda p: 'accept' if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    for _ in range(4): use(table, mid, 'Wound', target=FOE)
    eng = cold(svc, mid)
    calls = []
    engine_type = type(eng)
    original = engine_type._rewrite_d20
    calls = {}
    def counted(self, roll):
        if roll.reason == 'SAVE:death':
            calls.setdefault(id(self), []).append(roll)
        return original(self, roll)
    monkeypatch.setattr(engine_type, '_rewrite_d20', counted)
    for _ in range(3):
        if any(r.actor_id == FOE and r.reason == 'SAVE:death' for r in cold(svc, mid).rolls):
            break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    cold(svc, mid)
    assert calls and all(len(records) == 1 for records in calls.values())


def test_sorrow_instances_from_two_casters_survive_until_one_shared_draw(tmp_path):
    svc, table, mid = fight(tmp_path, [PULSE], ally_features=[PULSE])
    use(table, mid, 'Emotional Pulse: Pulse of Sorrow', target=FOE,
        answer=lambda p: 'accept' if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    for _ in range(2):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == ALLY
    use(table, mid, 'Emotional Pulse: Pulse of Sorrow', target=FOE,
        answer=lambda p: 'accept' if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    eng = cold(svc, mid)
    held = conditions(eng.state.actors[FOE], 'emotional_sorrow')
    assert len(held) == 2
    assert {c.source_actor_id for c in held} == {ME, ALLY}
    use(table, mid, 'Test save', target=FOE)
    eng = cold(svc, mid)
    penalties = [r for r in eng.rolls if r.actor_id == FOE and r.reason == 'Sorrow penalty']
    assert len(penalties) == 2
    assert not conditions(eng.state.actors[FOE], 'emotional_sorrow')


@pytest.mark.parametrize('form,expected',[('Pulse of Rage','reaction_denied'),('Pulse of Sorrow','emotional_sorrow'),('Pulse of Fear','reaction_denied'),('Hostile Joy','reaction_denied'),('Hostile Calm','emotional_calm')])
def test_successful_pulse_keeps_its_own_success_branch(tmp_path,form,expected):
    svc,table,mid=fight(tmp_path,[PULSE],dc=1)
    use(table,mid,'Emotional Pulse: '+form,target=FOE)
    eng=cold(svc,mid);foe=eng.state.actors[FOE]
    assert conditions(foe,expected)
    assert not conditions(foe,'frightened')
    assert not conditions(foe,'emotional_rage')
    if form=='Pulse of Sorrow':
        assert all(c.data['dice'] is False for c in conditions(foe,'emotional_sorrow'))
    if form=='Hostile Joy':
        assert not conditions(foe,'concentration_mode')
    if form=='Hostile Calm':
        assert all(c.data['escalation'] is False for c in conditions(foe,'emotional_calm'))
    assert eng.state.actors[ME].resources[QI]==28

def test_heartbreak_success_half_damage_and_target_start_expiry(tmp_path):
    svc,table,mid=fight(tmp_path,[HEART,PULSE],dc=1)
    use(table,mid,'Emotional Pulse: Pulse of Fear',target=FOE)
    S.to_thief(table,mid,end_thief=True)
    before=cold(svc,mid).state.actors[FOE].current_hp
    use(table,mid,': Heartbreak',target=FOE)
    eng=cold(svc,mid)
    damage=[e for e in eng.events if e.event_type=='DAMAGE_ROLLED' and 'heartbreak_and_heartmend' in e.source_definition_id]
    assert len(damage)==1 and damage[0].payload['modifier']==0
    assert before-eng.state.actors[FOE].current_hp==damage[0].payload['total']//2
    held=[c for c in conditions(eng.state.actors[FOE],'reaction_denied')
          if 'heartbreak_and_heartmend' in c.source_definition_id]
    assert len(held)==1
    assert held[0].expires_on==f'START_OF_TURN_AT:{FOE}:{eng.state.actors[FOE].turns_started+1}'
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==FOE:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==FOE
    assert not any('heartbreak_and_heartmend' in c.source_definition_id
                   for c in conditions(cold(svc,mid).state.actors[FOE],'reaction_denied'))


@pytest.mark.parametrize('offer,form', [
    ('Heartmend', None), ('Nine-Temperature Service', None),
    ('Emotional Pulse: Willing Joy', 'joy'), ('Emotional Pulse: Willing Calm', 'calm')])
def test_allied_player_can_refuse_willing_benefits_and_cold_reloads(tmp_path, offer, form):
    feature = HEART if offer == 'Heartmend' else TEA if offer == 'Nine-Temperature Service' else PULSE
    svc, table, mid = fight(tmp_path, [feature])
    if offer == 'Heartmend':
        use(table, mid, 'Wound')
    before = cold(svc, mid).state.actors[ALLY]
    before_hp, before_position = before.current_hp, before.position
    def refuse(prompt):
        if prompt['context'].get('reaction_source_id') == 'choice:willing.consent':
            return 'refuse'
        if prompt['context'].get('reaction_source_id') == 'choice:needle.nine_temperature_targets':
            return ALLY
        return None
    use(table, mid, offer, target=ME if offer == 'Nine-Temperature Service' else ALLY, answer=refuse)
    ally = cold(svc, mid).state.actors[ALLY]
    assert not any(c.condition_id in {SERVICE, 'condition:typed.save_against'} for c in ally.conditions.values())
    assert ally.temporary_hp == 0
    assert ally.current_hp == before_hp
    assert ally.position == before_position


def test_refused_willing_pulse_does_not_create_heartbreak_receipt(tmp_path):
    svc, table, mid = fight(tmp_path, [PULSE, HEART])
    use(table, mid, 'Emotional Pulse: Willing Joy', target=FOE,
        answer=lambda p: 'refuse' if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    eng = cold(svc, mid)
    assert not any(c.condition_id == EXPOSURE for c in eng.state.actors[FOE].conditions.values())
    assert not any(': Heartbreak' in g['label'] for g in table.state(mid)['menu']['actions'])


def test_sorrow_from_same_caster_refreshes_instead_of_stacking(tmp_path):
    svc, table, mid = fight(tmp_path, [PULSE], dc=1)
    use(table, mid, 'Test repeated Sorrow', target=FOE,
        answer=lambda p: 'accept' if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    eng = cold(svc, mid)
    held = conditions(eng.state.actors[FOE], 'emotional_sorrow')
    assert len(held) == 1 and held[0].data['dice'] is True


def test_later_successful_sorrow_replaces_same_casters_pending_failure(tmp_path):
    svc,table,mid=fight(tmp_path,[PULSE],dc=1,foe_wis_save=100)
    answers=iter(('accept','refuse'))
    use(table,mid,'Test repeated Sorrow',target=FOE,
        answer=lambda p: next(answers) if p['context'].get('reaction_source_id') == 'choice:willing.consent' else None)
    eng=cold(svc,mid)
    held=conditions(eng.state.actors[FOE],'emotional_sorrow')
    assert len(held)==1 and held[0].data['dice'] is False
    assert any(r.actor_id==FOE and r.reason.startswith('SAVE:') for r in eng.rolls)
    assert table.state(mid)['menu']['actor_id']==ME


@pytest.mark.parametrize('form,condition,dc,source_deadline', [
    ('Pulse of Sorrow','emotional_sorrow',30,True),
    ('Pulse of Sorrow','emotional_sorrow',1,True),
    ('Hostile Calm','emotional_calm',30,True),
    ('Hostile Calm','emotional_calm',1,False),
])
def test_sorrow_and_calm_status_text_names_effect_and_branch_deadline(tmp_path, form, condition, dc, source_deadline):
    svc, table, mid = fight(tmp_path, [PULSE], dc=dc)
    use(table, mid, 'Emotional Pulse: '+form, target=FOE)
    held = conditions(cold(svc, mid).state.actors[FOE], condition)
    assert held
    label = held[0].data['label'].lower()
    if condition == 'emotional_sorrow':
        assert "start of the caster's next turn" in label
    elif source_deadline:
        assert "start of cultivator's next turn" in label
    else:
        assert 'start of your next turn' in label
    if condition == 'emotional_sorrow':
        assert 'subtract' in label and ('saving throw' in label or 'attack' in label)
    else:
        assert 'opportunity attack' in label
        if source_deadline:
            assert 'rage' in label and 'fury' in label and 'berserk' in label and 'frenzy' in label
            assert 'emotional escalation' not in label


def test_manual_nine_temperature_hides_unperceived_creature_from_choice(tmp_path):
    svc, table, mid = fight(tmp_path, [TEA])
    use(table, mid, 'Prepare invisible', target=FOE)
    cid = S.candidate(table, mid, 'Nine-Temperature Service', target=ME)
    result = S.act(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['context']['reaction_source_id'] == 'choice:needle.nine_temperature_targets'
    assert FOE not in {option['id'] for option in result['reaction']['choice']['options']}
    cold(svc, mid)


def test_rage_condition_text_describes_penalty_without_compelling_attacks(tmp_path):
    svc, table, mid = fight(tmp_path, [PULSE])
    use(table, mid, 'Emotional Pulse: Pulse of Rage', target=FOE)
    held = conditions(cold(svc, mid).state.actors[FOE], 'emotional_rage')[0]
    label = held.data['label']
    assert 'attacks against anyone except' in label and 'Disadvantage' in label
    assert 'cannot take you farther' in label and 'start of Cultivator’s next turn' in label
    assert 'must attack' not in label and 'or suffer' not in label


def test_rage_makes_attack_against_non_nearest_hostile_disadvantaged(tmp_path):
    positions={ME:{'x':2,'y':6},ALLY:{'x':7,'y':6},FOE:{'x':4,'y':6}}
    svc,table,mid=fight(tmp_path,[PULSE],positions=positions)
    # The affected creature's controller owns "which creatures you perceive as
    # hostile"; a test that leaves it unanswered is not a Rage trial.
    def seen_hostile(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.emotion.rage_hostiles':
            return ME
        return None
    use(table,mid,'Emotional Pulse: Pulse of Rage',target=FOE,answer=seen_hostile)
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==FOE:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==FOE
    cid=S.candidate(table,mid,'Rage probe attack',target=ALLY)
    S.play(table,mid,cid)
    attacks=[r for r in cold(svc,mid).rolls if r.actor_id==FOE and r.reason.startswith('ATTACK:')]
    assert attacks and attacks[-1].mode=='DISADVANTAGE'


def test_nine_temperature_repeats_a_recovery_save_with_advantage(tmp_path):
    svc,table,mid=fight(tmp_path,[TEA])
    use(table,mid,'Prepare diseased',target=ALLY)
    use(table,mid,'Nine-Temperature Service',target=ME,answer=tea_answer('repeat'))
    eng=cold(svc,mid)
    recoveries=[e for e in eng.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY]
    assert recoveries and recoveries[-1].payload['mode']=='ADVANTAGE'


def test_calm_blocks_only_explicitly_classified_escalation_actions(tmp_path):
    svc,table,mid=fight(tmp_path,[PULSE])
    for _ in range(4):
        if table.state(mid)['menu']['actor_id']==FOE:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==FOE
    assert any('Rage Escalation Test' in group['label'] for group in table.state(mid)['menu']['actions'])
    S.play(table,mid,table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=ME:
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    use(table,mid,'Emotional Pulse: Hostile Calm',target=FOE)
    for _ in range(4):
        if table.state(mid)['menu']['actor_id']==FOE:break
        S.play(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==FOE
    assert not any('Rage Escalation Test' in group['label'] for group in table.state(mid)['menu']['actions'])
    assert conditions(cold(svc,mid).state.actors[FOE],'emotional_calm')


@pytest.mark.parametrize('poisoned', [False, True])
@pytest.mark.parametrize('check_path', ['end_effect', 'effect_transfer', 'sphere_check'])
def test_nine_temperature_real_end_effect_check_applies_mode_before_consumption(tmp_path, poisoned, check_path):
    feature = {'end_effect':'tianxia.talent.life.wound_memory_suturing',
               'effect_transfer':'TAL_SCOUNDREL_STEAL_ONGOING_TECHNIQUE',
               'sphere_check':'tianxia.talent.metal.bell_monastery_listening_sutra'}[check_path]
    svc, table, mid = fight(tmp_path, [TEA], ally_features=[feature],
        positions={ME:{'x':3,'y':6}, ALLY:{'x':3,'y':7}, FOE:{'x':4,'y':7}})
    # The wound is hostile and on a legal friendly target of Suturing.
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == FOE: break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == FOE
    if check_path == 'end_effect':
        use(table, mid, 'Prepare wound', target=ALLY)
        assert conditions(cold(svc, mid).state.actors[ALLY], 'bleeding')
    else:
        use(table, mid, 'Prepare benefit', target=FOE)
    S.to_thief(table, mid)
    if poisoned:
        use(table, mid, 'Prepare poisoned')
    use(table, mid, 'Nine-Temperature Service', target=ME, answer=tea_answer('advantage'))
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == ALLY: break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == ALLY
    other = CombatService(ROOT, tmp_path)
    table = TabletopService(other, tmp_path)
    before = cold(other, mid)
    assert any(c.condition_id == NEXT for c in before.state.actors[ALLY].conditions.values())
    counter = before.roller.counter
    label = {'end_effect':'Wound Memory Suturing: Bleeding',
             'effect_transfer':'STEAL ONGOING TECHNIQUE',
             'sphere_check':'Bell-Monastery Listening Sutra'}[check_path]
    result, _ = use(table, mid, label, target=ALLY if check_path == 'end_effect' else FOE)
    assert result['status'] == 'COMMITTED'
    eng = cold(other, mid)
    rolls = [r for r in eng.rolls if r.actor_id == ALLY and r.reason.startswith('CHECK:')]
    assert len(rolls) == 1
    actual = rolls[0]
    assert actual.mode == ('NORMAL' if poisoned else 'ADVANTAGE')
    assert len(actual.dice) == (1 if poisoned else 2)
    assert actual.counter_start == counter
    assert actual.counter_end - counter == (1 if poisoned else 2)
    assert actual.natural_result == (actual.dice[0] if poisoned else max(actual.dice))
    checks = [e for e in eng.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY]
    assert len(checks) == 1 and checks[0].payload['skill'] == {
        'end_effect':'Cultivation Check', 'effect_transfer':'Scoundrel Check',
        'sphere_check':'Metal Check'}[check_path]
    assert checks[0].payload['actor'] == actual.model_dump(mode='json')
    assert not any(c.condition_id == NEXT for c in eng.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == SERVICE for c in eng.state.actors[ALLY].conditions.values())
    assert eng.state.model_dump(mode='json') == S.engine(other, mid).state.model_dump(mode='json')
    S.to_thief(table, mid)
    use(table, mid, 'Test save', target=ALLY)
    assert [r for r in cold(other, mid).rolls if r.actor_id == ALLY and r.reason.startswith('SAVE:')][-1].mode == 'NORMAL'


@pytest.mark.parametrize('poisoned', [False, True])
def test_nine_temperature_direct_object_attack_draws_native_mode_and_reloads(tmp_path, poisoned):
    svc, table, mid = fight(tmp_path, [TEA], objects=[
        {'id':1, 'kind':'crate', 'x':4, 'y':7, 'material':'wood', 'hp':1000}])
    if poisoned: use(table, mid, 'Prepare poisoned')
    use(table, mid, 'Nine-Temperature Service', target=ME, answer=tea_answer('advantage'))
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == ALLY: break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    other = CombatService(ROOT, tmp_path)
    table = TabletopService(other, tmp_path)
    before = cold(other, mid)
    obj = next(o for o in before.state.objects.values() if o.position.x == 4 and o.position.y == 7)
    counter = before.roller.counter
    result, _ = use(table, mid, 'Attack an object', target=obj.object_id)
    assert result['status'] == 'COMMITTED'
    eng = cold(other, mid)
    actual = next(r for r in eng.rolls if r.actor_id == ALLY and r.reason.startswith('ATTACK:'))
    assert actual.mode == ('NORMAL' if poisoned else 'ADVANTAGE')
    assert len(actual.dice) == (1 if poisoned else 2)
    assert actual.counter_start == counter
    assert actual.counter_end - counter == len(actual.dice)
    assert not any(c.condition_id == NEXT for c in eng.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == SERVICE for c in eng.state.actors[ALLY].conditions.values())
    assert eng.state.model_dump(mode='json') == S.engine(other, mid).state.model_dump(mode='json')


@pytest.mark.parametrize('opposed', [False, True])
def test_nine_temperature_raw_hazard_save_resolves_before_consumption(tmp_path, opposed):
    svc, table, mid = fight(tmp_path, [TEA], hazard=True)
    if opposed: use(table, mid, 'Prepare save disadvantage')
    use(table, mid, 'Nine-Temperature Service', target=ME, answer=tea_answer('advantage'))
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == ALLY: break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    other = CombatService(ROOT, tmp_path)
    table = TabletopService(other, tmp_path)
    before = cold(other, mid)
    counter = before.roller.counter
    cid = next(o['candidate_id'] for o in table.state(mid)['menu']['moves'] if o.get('destination') == {'x':3,'y':8})
    result, _ = S.play(table, mid, cid)
    assert result['status'] == 'COMMITTED'
    eng = cold(other, mid)
    actual = next(r for r in eng.rolls if r.actor_id == ALLY and r.reason == 'QI_HAZARD_DEX_SAVE')
    assert actual.mode == ('NORMAL' if opposed else 'ADVANTAGE')
    assert len(actual.dice) == (1 if opposed else 2)
    assert actual.counter_start == counter
    assert actual.counter_end - counter == len(actual.dice)
    assert not any(c.condition_id == NEXT for c in eng.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == SERVICE for c in eng.state.actors[ALLY].conditions.values())
    assert eng.state.model_dump(mode='json') == S.engine(other, mid).state.model_dump(mode='json')
