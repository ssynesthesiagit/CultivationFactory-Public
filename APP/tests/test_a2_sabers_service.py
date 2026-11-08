"""Printed Sabers choices through accepted table/session intents and cold replay."""
import pytest
from combat.gate5_service import CombatService, CombatServiceError
from tests.h1_support import ROOT
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, action_sender, settle, turn
from tests.test_auto92_sabers import DAO
from combat.typed_executor import mark_condition_id
P = 'tianxia.talent.sabers.'


def cold(c, m):
    s = CombatService(ROOT, c.userdata_root)._load_session(m)
    assert s.verify()['status'] == 'PASS'
    assert s.mechanical.replay()['status'] == 'PASS'
    return s.engine


def attacks(e, source=None):
    return [r for r in e.events if r.event_type == 'ATTACK_ROLLED' and r.actor_id == LEFT
            and (source is None or source in r.source_definition_id)]


@pytest.mark.parametrize('success', [False, True])
def test_feint_projected_save_payment_and_current_turn_expiry(tmp_path, success):
    c,t,m=fight(tmp_path,[P+'beheading_feint'],left_kit=DAO,right_score=214 if success else 14,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':6,'y':1}})
    label='Beheading Feint (projected saber qi; 30 feet)'
    assert not any(g['label']=='Beheading Feint' and g['options'] for g in t.state(m)['menu']['actions'])
    settle(action_sender(c,t,m,label,target_id=RIGHT))
    e=cold(c,m);me=e.state.actors[LEFT];foe=e.state.actors[RIGHT]
    assert me.resources['resource:core.qi']==98
    assert bool([x for x in me.conditions.values() if x.condition_id.endswith('feint_next')]) != success
    assert any(x.condition_id==mark_condition_id('Guard Pressured',LEFT) for x in foe.conditions.values()) != success
    denied=[x for x in foe.conditions.values() if x.condition_id.endswith('no_opportunity_attacks')]
    assert bool(denied)==success
    if success:assert denied[0].data['against']==LEFT and foe.reaction_available
    turn(t,m,RIGHT)
    e=cold(c,m)
    assert not any(x.condition_id.endswith('feint_next') for x in e.state.actors[LEFT].conditions.values())
    assert not any(x.condition_id.endswith('no_opportunity_attacks') for x in e.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('hit',[True,False])
def test_feint_only_next_sabers_roll_consumes_even_on_miss(tmp_path, hit):
    c,t,m=fight(tmp_path,[P+'beheading_feint',P+'forward_cut'],left_kit=DAO,
        left_attack_bonus=100 if hit else -100,
        prepare=[{'type':'attack','attack_kind':'cultivation_melee','count':1,
                  'on_hit':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}])
    settle(action_sender(c,t,m,'Beheading Feint',target_id=RIGHT))
    settle(action_sender(c,t,m,'Prepare',target_id=RIGHT))
    assert any(x.condition_id.endswith('feint_next') for x in cold(c,m).state.actors[LEFT].conditions.values())
    settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT))
    e=cold(c,m)
    roll=attacks(e,'forward_cut')[-1]
    assert 'ADVANTAGE' in str(roll.payload),roll.payload
    assert not any(x.condition_id.endswith('feint_next') for x in e.state.actors[LEFT].conditions.values())
    assert any(x.event_type=='GM_RIDER' and 'beheading_feint' in x.source_definition_id for x in e.events), 'unresolved non-OA movement reactions remain visible'


@pytest.mark.parametrize('owned,resource,label',[(True,'Qi','Beheading Feint (projected saber qi; 30 feet)'),
                                               (True,'Stamina','Beheading Feint'),(False,'Qi',None)])
def test_feint_projection_uses_sealed_qi_and_physical_requires_saber(tmp_path,owned,resource,label):
    c,t,m=fight(tmp_path,[P+'beheading_feint'] if owned else [],left_resource=resource)
    labels=[g['label'] for g in t.state(m)['menu']['actions']]
    if label and 'projected' in label:
        assert label in labels
    else:
        assert not any('Beheading Feint' in x for x in labels)
    cold(c,m)


@pytest.mark.parametrize('ally,decline',[ (False,False),(True,False),(True,True)])
def test_execution_presence_kill_asks_willing_recipient_and_ends_one_fear(tmp_path,ally,decline):
    def hp(b):
        if b['actor_template']['entity_id']==RIGHT:b['actor_template']['maximum_hp']=1
    who=ALLY if ally else LEFT
    fear=[{'type':'condition','condition':'frightened','applies_to':'target' if ally else 'self'},
          {'type':'condition','condition':'frightened','applies_to':'target' if ally else 'self'}]
    c,t,m=fight(tmp_path,[P+'execution_platform_presence',P+'forward_cut'],left_kit=DAO,
        left_attack_bonus=100,ally=True if ally else None,bundle_edit=hp,
        prepare=fear,prepare_target='ALLY_OR_SELF' if ally else 'SELF')
    settle(action_sender(c,t,m,'Prepare',target_id=who))
    before=sum(x.condition_id=='condition:typed.frightened' for x in cold(c,m).state.actors[who].conditions.values())
    assert before
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    def choose(p):
        if p['context']['reaction_source_id']=='choice:needle.execution_presence':return [who]
        if p['context']['reaction_source_id']=='choice:needle.execution_consent':return [] if decline else ['accept']
        return [o['id'] for o in (p.get('choice') or {}).get('options',[])][:1]
    _,prompts=settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT),choose)
    e=cold(c,m)
    assert not e.state.actors[RIGHT].active
    assert sum(x.condition_id=='condition:typed.frightened' for x in e.state.actors[who].conditions.values())==before-(not decline)
    consent=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.execution_consent']
    assert bool(consent)==ally
    if ally:assert consent[0]['context']['reactor_id']==ALLY
    assert e.state.actors[LEFT].resources['resource:core.qi']==97


def test_execution_bonus_once_each_current_turn_and_saber_only(tmp_path):
    mark={'type':'mark','mark':'Guard Pressured','applies_to':'target','duration':{'kind':'rounds','amount':10}}
    def attack_numbers(b):
        weapon=next((a for a in b['action_catalog'] if ((a.get('parameters') or {}).get('typed') or {}).get('weapon') and 'Dao' in a['display_name']),None)
        for a in b['action_catalog']:
            if a['display_name']=='Repeated saber' or ((a.get('parameters') or {}).get('typed') or {}).get('weapon'):
                a['parameters']['typed']['numbers'].update(attack_bonus=100,weapon_attack_bonus=100)
                if a['display_name']=='Repeated saber':a['parameters']['typed']['weapon_source_id']=weapon['source_definition_id']
    c,t,m=fight(tmp_path,[P+'execution_platform_presence'],left_kit=DAO,bundle_edit=attack_numbers,
        prepare=[mark],extra_actions=[('Repeated saber',{'target_kind':'HOSTILE_ENTITY',
          'effects':[{'type':'attach_saber_weapon'},{'type':'attack','attack_kind':'weapon','count':2,
           'on_hit':[{'type':'damage','weapon_damage':True}]}]})])
    settle(action_sender(c,t,m,'Prepare',target_id=RIGHT))
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    settle(action_sender(c,t,m,'Repeated saber',target_id=RIGHT))
    e=cold(c,m)
    bonuses=[x for x in e.events if x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id.endswith('execution_platform_presence')
             and '+1d8' in str(x.payload)]
    assert len(bonuses)==1
    settle(action_sender(c,t,m,'Repeated saber',target_id=RIGHT))
    e=cold(c,m)
    assert sum(x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id.endswith('execution_platform_presence')
               and '+1d8' in str(x.payload) for x in e.events)==1
    # A real Opportunity Attack on the opponent's turn earns a fresh bonus.
    turn(t,m,RIGHT)
    from tests.test_auto92_sabers import _walk_away
    from tests.test_auto42_stars import resolve
    state,move=_walk_away(c,t,m,RIGHT,LEFT)
    resolve(lambda answers:t.act(m,move.candidate_id,state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'],answers))
    e=cold(c,m)
    assert sum(x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id.endswith('execution_platform_presence')
               and '+1d8' in str(x.payload) for x in e.events)==2


@pytest.mark.parametrize('recipient',['enemy','ally','decline'])
def test_circle_player_selects_distinct_creatures_and_actual_reach(tmp_path,recipient):
    def reach(b):
        if b['actor_template']['entity_id']==LEFT:
            for a in b['action_catalog']:
                if ((a.get('parameters') or {}).get('typed') or {}).get('weapon') and 'Dao' in a['display_name']:
                    a['range_ft']=10
    c,t,m=fight(tmp_path,[P+'circle_cleaving_saber'],left_kit=DAO,ally=True,left_attack_bonus=100,left_score=50,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':3,'y':1},ALLY:{'x':1,'y':3}},bundle_edit=reach)
    who=RIGHT if recipient=='enemy' else ALLY
    def pick(p):
        if p['context']['reaction_source_id']=='choice:needle.beauty_targets':
            assert LEFT not in [o['id'] for o in p['choice']['options']]
            assert {RIGHT,ALLY}.issubset({o['id'] for o in p['choice']['options']})
            return [] if recipient=='decline' else [who]
        return [o['id'] for o in p['choice']['options']][:1]
    settle(action_sender(c,t,m,'Circle-Cleaving Saber',target_id=RIGHT),pick)
    e=cold(c,m)
    assert len(attacks(e,'circle_cleaving_saber'))==(0 if recipient=='decline' else 1)
    if recipient!='decline':
        assert e.state.actors[who].current_hp<1000
        linked=e.action_catalog[next(a for a in e.action_catalog.values() if a.display_name=='Circle-Cleaving Saber').parameters['range_from_action']]
        assert attacks(e,'circle_cleaving_saber')[0].payload['modifier']==linked.parameters['typed']['numbers']['attack_bonus']
        assert any(x.condition_id==mark_condition_id('Guard Pressured',LEFT) for x in e.state.actors[who].conditions.values())
    assert e.state.actors[LEFT].resources['resource:core.qi']==98


@pytest.mark.parametrize('talent,label',[('beheading_feint','Beheading Feint'),('circle_cleaving_saber','Circle-Cleaving Saber')])
def test_sabers_automatic_actions_commit_without_player_pause(tmp_path,talent,label):
    c,t,m=fight(tmp_path,[P+talent],left_kit=DAO,left_attack_bonus=100,left_score=50)
    settle(action_sender(c,t,m,label,ai=True,target_id=RIGHT))
    e=cold(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi']==98
    assert any(x.event_type=='GM_RIDER' and talent in x.source_definition_id for x in e.events)==(talent=='beheading_feint')


def test_circle_excludes_hidden_creatures(tmp_path):
    c,t,m=fight(tmp_path,[P+'circle_cleaving_saber'],left_kit=DAO,ally=True,left_attack_bonus=100,left_score=50,
        cause=[{'type':'condition','condition':'invisible','applies_to':'self','duration':{'kind':'rounds','amount':2}}],cause_target='SELF')
    turn(t,m,RIGHT)
    settle(action_sender(c,t,m,'Cause'))
    turn(t,m,LEFT)
    assert any(x.condition_id.endswith('.invisible') for x in cold(c,m).state.actors[RIGHT].conditions.values())
    def pick(p):
        if p['context']['reaction_source_id']=='choice:needle.beauty_targets':
            ids=[o['id'] for o in p['choice']['options']]
            assert RIGHT not in ids and LEFT not in ids
            return [ALLY]
        return [o['id'] for o in p['choice']['options']][:1]
    settle(action_sender(c,t,m,'Circle-Cleaving Saber',target_id=ALLY),pick)
    e=cold(c,m)
    assert e.state.actors[RIGHT].current_hp==1000
    assert e.state.actors[ALLY].current_hp<1000


@pytest.mark.parametrize('talent,label',[('beheading_feint','Beheading Feint'),('circle_cleaving_saber','Circle-Cleaving Saber')])
def test_sabers_live_bound_weapon_reach_expires_through_service(monkeypatch,tmp_path,talent,label):
    from tests.test_lock_choices import install
    def bonus(engine,actor,action,opportunity):
        if 'Dao' not in action.display_name:
            return None
        held=next((c for c in actor.conditions.values() if c.condition_id=='condition:typed.ignore_difficult'),None)
        if held is None:return None
        return {'source_id':held.source_definition_id,'condition_id':held.instance_id,'feet':5}
    install(monkeypatch,'attack_reach_bonus',bonus)
    c,t,m=fight(tmp_path,[P+talent],left_kit=DAO,left_attack_bonus=100,left_score=50,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':3,'y':1}},prepare_target='SELF',
        prepare=[{'type':'condition','condition':'ignore_difficult','applies_to':'self','expires_on':'END_OF_CURRENT_TURN'}])
    def offered():
        return any(g['label']==label and any(RIGHT in o.get('target_ids',[]) for o in g['options'])
                   for g in t.state(m)['menu']['actions'])
    assert not offered()
    settle(action_sender(c,t,m,'Prepare'))
    cold(c,m)
    assert offered()
    settle(action_sender(c,t,m,label,target_id=RIGHT))
    e=cold(c,m)
    if talent=='circle_cleaving_saber':assert e.state.actors[RIGHT].current_hp<1000
    else:assert any(x.condition_id.endswith('feint_next') for x in e.state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not offered()
    cold(c,m)



def test_execution_presence_checks_bloodied_before_this_hits_damage(tmp_path):
    c,t,m=fight(tmp_path,[P+'execution_platform_presence',P+'forward_cut'],left_kit=DAO,left_score=50,left_attack_bonus=100,
        prepare=[{'type':'damage','applies_to':'target','flat':490,'damage_types':['force']}])
    settle(action_sender(c,t,m,'Prepare',target_id=RIGHT))
    assert cold(c,m).state.actors[RIGHT].current_hp==510
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT))
    e=cold(c,m)
    assert e.state.actors[RIGHT].current_hp<=500
    def bonuses(e):
        return sum(x.event_type=='PASSIVE_TRIGGERED' and '+1d8' in str(x.payload) for x in e.events)
    assert bonuses(e)==0, 'crossing half HP with this hit does not make the victim Bloodied at hit time'
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT))
    assert bonuses(cold(c,m))==1


def test_circle_requires_held_saber_but_projected_feint_does_not(tmp_path):
    c,t,m=fight(tmp_path,[P+'circle_cleaving_saber',P+'beheading_feint'],left_kit=DAO)
    e=cold(c,m)
    stow=next(a.display_name for a in e.action_catalog.values() if a.owner_id==LEFT
              and a.parameters.get('equipment_grip',{}).get('held') == 0)
    settle(action_sender(c,t,m,stow))
    labels=[g['label'] for g in t.state(m)['menu']['actions'] if g['options']]
    assert 'Circle-Cleaving Saber' not in labels and 'Beheading Feint' not in labels
    assert 'Beheading Feint (projected saber qi; 30 feet)' in labels
    cold(c,m)



def test_execution_presence_uses_guard_pressure_from_another_caster(tmp_path):
    c,t,m=fight(tmp_path,[P+'execution_platform_presence',P+'forward_cut'],left_kit=DAO,left_attack_bonus=100,
        cause=[{'type':'mark','mark':'Guard Pressured','applies_to':'self',
                'duration':{'kind':'until_start_of_your_next_turn'}}],cause_target='SELF')
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    turn(t,m,RIGHT)
    settle(action_sender(c,t,m,'Cause'))
    turn(t,m,LEFT)
    e=cold(c,m)
    assert any(x.condition_id==mark_condition_id('Guard Pressured',RIGHT) for x in e.state.actors[RIGHT].conditions.values())
    settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT))
    e=cold(c,m)
    assert any(x.event_type=='PASSIVE_TRIGGERED' and '+1d8' in str(x.payload) for x in e.events)


@pytest.mark.parametrize('talent,label', [('circle_cleaving_saber', 'Circle-Cleaving Saber'),
                                          ('beheading_feint', 'Beheading Feint')])
@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('unavailable', ['stowed', 'disarmed'])
def test_alternate_held_saber_supplies_physical_expression_after_first_unavailable(tmp_path, talent, label, ai, unavailable):
    kit = {'items': [*DAO['items'], {'item_id': 'tianxia.mortal.weapon.duan_dao',
                                   'name': 'Duan Dao', 'quantity': 1}]}
    def numbers(bundle):
        if bundle['actor_template']['entity_id'] != LEFT:
            return
        for action in bundle['action_catalog']:
            if action['source_definition_id'].endswith('.weapon.dao'):
                action['parameters']['expected_damage'] = 10000  # the best weapon is disarmed
            if action['source_definition_id'].endswith('.weapon.duan_dao'):
                action['range_ft'] = 10
                action['parameters']['typed']['numbers']['attack_bonus'] = 73
                # Distinct sealed damage proves the delivery never falls back to the first saber.
                action['parameters']['typed']['weapon']['damage'] = {'count': 1, 'sides': 4, 'modifier': 123}
    c,t,m = fight(tmp_path, [P+talent], left_kit=kit, left_score=50,
                  positions={LEFT:{'x':1,'y':1}, RIGHT:{'x':3,'y':1}}, bundle_edit=numbers,
                  prepare_target='SELF', prepare=[{'type':'condition','condition':'disarmed','applies_to':'self'}])
    e = cold(c,m)
    first = next(a for a in e.action_catalog.values() if a.owner_id == LEFT
                 and a.source_definition_id.endswith('.weapon.dao'))
    second = next(a for a in e.action_catalog.values() if a.owner_id == LEFT
                  and a.source_definition_id.endswith('.weapon.duan_dao'))
    stow = next(a.display_name for a in e.action_catalog.values() if a.owner_id == LEFT
                and a.parameters.get('equipment_grip', {}).get('weapon') == first.source_definition_id
                and a.parameters['equipment_grip']['held'] == 0)
    settle(action_sender(c,t,m,stow if unavailable == 'stowed' else 'Prepare'))
    e = cold(c,m)
    from combat.ext.hand_occupancy import weapon_grips
    assert first.source_definition_id not in weapon_grips(e,e.state.actors[LEFT])
    assert second.source_definition_id in weapon_grips(e,e.state.actors[LEFT])
    expressions = [a for a in e.action_catalog.values() if a.owner_id == LEFT
                   and a.display_name.startswith(label)
                   and a.parameters.get('range_from_action') == second.source_definition_id]
    assert len(expressions) == 1, 'every eligible base saber needs a selectable physical expression'
    expression = expressions[0]
    assert 'Duan Dao' in expression.display_name
    settle(action_sender(c,t,m,expression.display_name,ai=ai,target_id=RIGHT))
    e = cold(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi'] == 98
    if talent == 'circle_cleaving_saber':
        roll = attacks(e,'circle_cleaving_saber')[-1]
        assert roll.payload['modifier'] == 73
        assert e.state.actors[RIGHT].current_hp <= 873
    else:
        assert any(x.condition_id.endswith('feint_next') for x in e.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('decline', [False, True])
def test_execution_presence_blinded_player_can_offer_known_ally_fear_removal(tmp_path, decline):
    def hp(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['maximum_hp'] = 1
    c,t,m = fight(tmp_path, [P+'execution_platform_presence', P+'forward_cut'], left_kit=DAO,
                  left_score=50, left_attack_bonus=100, ally=True, bundle_edit=hp,
                  prepare_target='ALLY_OR_SELF', prepare=[
                      {'type':'condition','condition':'frightened','applies_to':'target'},
                      {'type':'condition','condition':'blinded','applies_to':'self'}])
    settle(action_sender(c,t,m,'Prepare',target_id=ALLY))
    e = cold(c,m)
    from combat.senses import perceives
    assert not perceives(e,e.state.actors[LEFT],e.state.actors[ALLY])
    assert any(x.condition_id.endswith('.frightened') for x in e.state.actors[ALLY].conditions.values())
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    def pick(prompt):
        source = prompt['context']['reaction_source_id']
        if source == 'choice:needle.execution_presence':
            assert ALLY in {o['id'] for o in prompt['choice']['options']}
            return [ALLY]
        if source == 'choice:needle.execution_consent':
            assert prompt['context']['reactor_id'] == ALLY
            return [] if decline else ['accept']
        return [o['id'] for o in prompt['choice']['options']][:1]
    _,prompts = settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT),pick)
    e = cold(c,m)
    assert not e.state.actors[RIGHT].active
    assert any(p['context']['reaction_source_id'] == 'choice:needle.execution_consent' for p in prompts)
    assert bool([x for x in e.state.actors[ALLY].conditions.values() if x.condition_id.endswith('.frightened')]) == decline


@pytest.mark.parametrize('miss', [False, True])
def test_circle_multiple_recipients_pb_cap_and_only_actual_hits_in_mark_choice(tmp_path, miss):
    witness = 'actor:factory.auto111-witness'
    def defenses(bundle):
        if miss and bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['armor_class'] = 10000
    c,t,m = fight(tmp_path, [P+'circle_cleaving_saber'], left_kit=DAO, ally=True,
                  extra_witness=True, left_pb=2, left_score=50, left_attack_bonus=100,
                  positions={LEFT:{'x':3,'y':6}, RIGHT:{'x':4,'y':6}, ALLY:{'x':4,'y':5}},
                  bundle_edit=defenses)
    # Invalid selections cannot exceed PB or repeat a creature; no partial commit.
    send = action_sender(c,t,m,'Circle-Cleaving Saber',target_id=RIGHT)
    paused = send([])
    assert paused['status'] == 'REACTION_REQUIRED'
    assert paused['reaction']['context']['reaction_source_id'] == 'choice:needle.beauty_targets'
    before = cold(c,m).state.model_dump(mode='json')
    for invalid in ([RIGHT, ALLY, witness], [RIGHT, RIGHT]):
        with pytest.raises(CombatServiceError) as rejected:
            send([{**paused['reaction']['context'], 'selection':'USE', 'option_ids':invalid}])
        assert rejected.value.diagnostic.code == 'COMBAT_AI_INTENT_INVALID'
        assert rejected.value.diagnostic.details['reason'] == 'invalid extension choice options'
        assert cold(c,m).state.model_dump(mode='json') == before
    selected = [RIGHT, ALLY]
    expected_hits = {ALLY} if miss else set(selected)
    def pick(prompt):
        source = prompt['context']['reaction_source_id']
        if source == 'choice:needle.beauty_targets':
            ids = {o['id'] for o in prompt['choice']['options']}
            assert {RIGHT, ALLY, witness} <= ids and LEFT not in ids
            assert prompt['choice']['maximum'] == 2
            return selected
        if source == 'choice:needle.choose_hit_target':
            assert {o['id'] for o in prompt['choice']['options']} == expected_hits
            return [ALLY]
        return [o['id'] for o in prompt['choice']['options']][:1]
    _,prompts = settle(action_sender(c,t,m,'Circle-Cleaving Saber',target_id=RIGHT),pick)
    e = cold(c,m)
    rolls = attacks(e,'circle_cleaving_saber')
    assert len(rolls) == 2
    assert [r.target_ids[0] for r in rolls] == selected
    assert e.state.actors[witness].current_hp == 1000
    assert (e.state.actors[RIGHT].current_hp < 1000) != miss
    assert e.state.actors[ALLY].current_hp < 1000
    assert {aid for aid,a in e.state.actors.items() if any(
        x.condition_id == mark_condition_id('Guard Pressured',LEFT) for x in a.conditions.values())} == {ALLY}
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.choose_hit_target' for p in prompts) == 1
    assert e.state.actors[LEFT].resources['resource:core.qi'] == 98


@pytest.mark.parametrize('blinded', [False, True])
def test_execution_ai_uses_perception_and_manual_ally_keeps_consent(tmp_path, blinded):
    def hp(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['maximum_hp'] = 1
    effects = [{'type':'condition','condition':'frightened','applies_to':'target'}]
    if blinded:
        effects.append({'type':'condition','condition':'blinded','applies_to':'self'})
    c,t,m = fight(tmp_path, [P+'execution_platform_presence', P+'forward_cut'], left_kit=DAO,
                  left_score=50, left_attack_bonus=100, ally=True, bundle_edit=hp,
                  prepare_target='ALLY_OR_SELF', prepare=effects)
    settle(action_sender(c,t,m,'Prepare',target_id=ALLY))
    settle(action_sender(c,t,m,'Execution Platform Presence'))
    def decline(prompt):
        assert prompt['context']['reaction_source_id'] == 'choice:needle.execution_consent'
        assert prompt['context']['reactor_id'] == ALLY
        return []
    _,prompts = settle(action_sender(c,t,m,'Forward Cut',ai=True,target_id=RIGHT),decline)
    e = cold(c,m)
    assert not e.state.actors[RIGHT].active
    assert bool(prompts) != blinded
    assert any(x.condition_id.endswith('.frightened') for x in e.state.actors[ALLY].conditions.values())
    assert not any(x.event_type == 'CONDITION_REMOVED' and ALLY in x.target_ids for x in e.events)
