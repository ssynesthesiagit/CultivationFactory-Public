"""Real accepted table transactions, cold reload and mechanical replay."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate
from tests.formation_support import settle, turn, reload
from tests.h1_support import sheet
from tests.cw2_service_support import seal, add_action

REFLECT = 'tianxia.talent.formations.reflecting_gate'
DEVOURS = 'tianxia.talent.formations.formation_devours_technique'


def reflection(tmp_path, *, automatic=False, excluded=False, dc=1):
    def prepare(bundles):
        # The foe's real printed save technique; setup only lowers its DC to
        # make the owner's check deterministic without replacing engine rolls.
        for a in bundles[2]['action_catalog']:
            if a['display_name'] == 'Binding Word':
                a['parameters']['typed']['numbers']['save_dc'] = dc
                if excluded:
                    a['parameters']['typed']['source_category'] = 'Secret Inheritance'
                    if excluded == 'printed':
                        a['parameters']['typed'].pop('source_category')
                        a['parameters']['typed']['source'] = 'tianxia.talent.formations.heaven_and_earth_become_the_diagram'
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [REFLECT],
        foe_sheet=sheet(['TAL_FATE_BINDING_WORD'], cl=15), seed='A2FORMATIO-REFLECT',
        ask=not automatic, positions={OWNER: {'x':3,'y':6}, ALLY:{'x':4,'y':6}, FOE:{'x':8,'y':6}},
        bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5,6)).candidate_id)
    turn(table, mid, FOE)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    return combat, table, mid


@pytest.mark.parametrize('pick,target', [('miss', None), ('rebound', FOE), ('redirect:' + ALLY, ALLY)])
def test_reflect_save_technique_choices_payment_and_cold_reload(tmp_path, pick, target):
    combat, table, mid = reflection(tmp_path)
    before=reload(tmp_path,mid)
    prompts=settle(table,mid,candidate(combat,mid,'Binding Word',target=OWNER).candidate_id,
                   {'choice:needle.reflecting_gate':pick})
    assert any(p['context']['reaction_source_id']=='choice:needle.reflecting_gate' for p in prompts)
    after=reload(tmp_path,mid)
    assert after.state.actors[OWNER].resources['resource:core.qi'] == before.state.actors[OWNER].resources['resource:core.qi']-2
    assert not after.state.actors[OWNER].reaction_available
    assert after.state.actors[FOE].resources['resource:core.qi'] == before.state.actors[FOE].resources['resource:core.qi']-2
    saves=[r for r in after.rolls if r.reason.startswith('SAVE:') and 'TAL_FATE_BINDING_WORD' in r.reason]
    assert [r.actor_id for r in saves] == ([] if target is None else [target])


@pytest.mark.parametrize('excluded,decline,dc', [(True,False,1),(False,True,1),(False,False,99)])
def test_reflect_secret_decline_and_failed_check_preserve_original_target(tmp_path,excluded,decline,dc):
    combat,table,mid=reflection(tmp_path,excluded=excluded,dc=dc)
    before=reload(tmp_path,mid)
    prompts=settle(table,mid,candidate(combat,mid,'Binding Word',target=OWNER).candidate_id,
                  {'choice:needle.reflecting_gate':None if decline else 'rebound'})
    after=reload(tmp_path,mid)
    saves=[r for r in after.rolls if r.reason.startswith('SAVE:') and 'TAL_FATE_BINDING_WORD' in r.reason]
    assert [r.actor_id for r in saves]==[OWNER]
    paid=0 if excluded or decline else 2
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']-paid
    if excluded: assert not any(p['context']['reaction_source_id']=='choice:needle.reflecting_gate' for p in prompts)


def test_automatic_reflection_harms_enemy_with_allies_in_range(tmp_path):
    combat,table,mid=reflection(tmp_path,automatic=True)
    settle(table,mid,candidate(combat,mid,'Binding Word',target=OWNER).candidate_id)
    after=reload(tmp_path,mid)
    saves=[r for r in after.rolls if r.reason.startswith('SAVE:') and 'TAL_FATE_BINDING_WORD' in r.reason]
    assert [r.actor_id for r in saves]==[FOE]


@pytest.mark.parametrize('automatic', [False, True])
def test_devour_partial_area_prevents_crossing_only_and_reloads(tmp_path, automatic):
    def prepare(bundles):
        add_action(bundles[2], 'Boundary blast', [{'type':'save','ability':'DEX','dc':'cultivation',
            'on_fail':[{'type':'damage','dice':{'count':1,'sides':6,'modifier':10},'damage_types':['force'],'applies_to':'target'}],
            'on_success':[{'type':'damage','dice':{'count':1,'sides':6,'modifier':10},'damage_types':['force'],'applies_to':'target'}]}],
            target='SELF', typed={'area':{'shape':'sphere','size_ft':60,'who':'enemies'},'numbers':{'save_dc':1,'cl':15,'pb':5,'key_mod':0}})
    combat,table,mid=fixture(tmp_path,[DEVOURS],seed='A2FORMATIO-DEVOUR',
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':10},FOE:{'x':8,'y':6}},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Combat Array: Nourishing Cycle',at=(5,6)).candidate_id)
    turn(table,mid,FOE)
    if automatic:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid)
    prompts=settle(table,mid,candidate(combat,mid,'Boundary blast').candidate_id,
                   {'choice:needle.formation_devours_technique':'prevent'})
    after=reload(tmp_path,mid)
    if not automatic:
        assert any('prevent' in [o['id'] for o in p['choice']['options']] for p in prompts if p['context']['reaction_source_id']=='choice:needle.formation_devours_technique')
    assert after.state.actors[OWNER].current_hp==before.state.actors[OWNER].current_hp
    assert after.state.actors[ALLY].current_hp<before.state.actors[ALLY].current_hp
    assert after.state.actors[FOE].current_hp==before.state.actors[FOE].current_hp
    assert [r.actor_id for r in after.rolls[len(before.rolls):] if r.reason.startswith('SAVE:')]==[ALLY]
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']-3
    # No suppression leaks into a later activation after a cold reload.
    if automatic:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Boundary blast').candidate_id,{'choice:needle.formation_devours_technique':None})
    final=reload(tmp_path,mid)
    assert final.state.actors[OWNER].current_hp<after.state.actors[OWNER].current_hp

@pytest.mark.parametrize('sovereign', [False, True])
def test_keyed_ally_step_grant_player_destination_and_once_per_turn(tmp_path, sovereign):
    talent='tianxia.talent.formations.'+('sovereign_of_the_world_diagram' if sovereign else 'formation_step')
    combat,table,mid=fixture(tmp_path,[talent],seed='A2FORMATIO-STEP')
    settle(table,mid,candidate(combat,mid,'Sovereign of the World-Diagram' if sovereign else 'Combat Array: Nourishing Cycle',
                             **({} if sovereign else {'at':(5,6)})).candidate_id)
    turn(table,mid,ALLY)
    e=reload(tmp_path,mid)
    moves=[c for c in e.legal_candidates() if c.source_definition_id=='system:formation.keyed_step']
    assert moves
    chosen=next(c for c in moves if c.destination and (c.destination.x,c.destination.y)==(5,7))
    settle(table,mid,chosen.candidate_id)
    after=reload(tmp_path,mid)
    assert after.state.actors[ALLY].position==chosen.destination
    assert not after.state.actors[ALLY].bonus_action_available
    assert not any(c.source_definition_id=='system:formation.keyed_step' for c in after.legal_candidates())
    turn(table,mid,FOE)
    enemy=reload(tmp_path,mid)
    assert not any(c.source_definition_id=='system:formation.keyed_step' for c in enemy.legal_candidates())
    turn(table,mid,ALLY)
    again=reload(tmp_path,mid)
    assert any(c.source_definition_id=='system:formation.keyed_step' for c in again.legal_candidates())


def test_manual_reflector_can_protect_a_creature_of_another_side(tmp_path):
    def prepare(bundles):
        for a in bundles[1]['action_catalog']:
            if a['display_name']=='Binding Word': a['parameters']['typed']['numbers']['save_dc']=1
        seal(bundles[1])
    combat,table,mid=fixture(tmp_path,[REFLECT],ally_talents=['TAL_FATE_BINDING_WORD'],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':8,'y':6},FOE:{'x':6,'y':6}},
        bundle_transform=prepare,seed='A2FORMATIO-MANUAL-PROTECT')
    settle(table,mid,candidate(combat,mid,'Combat Array: Nourishing Cycle',at=(5,6)).candidate_id)
    turn(table,mid,ALLY)
    before=reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Binding Word',target=FOE).candidate_id,
           {'choice:needle.reflecting_gate':'miss'})
    after=reload(tmp_path,mid)
    assert not any(r.reason.startswith('SAVE:') and 'TAL_FATE_BINDING_WORD' in r.reason for r in after.rolls)
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']-2


def test_reflection_excludes_secret_classified_by_its_printed_record(tmp_path):
    combat,table,mid=reflection(tmp_path,excluded='printed')
    before=reload(tmp_path,mid)
    prompts=settle(table,mid,candidate(combat,mid,'Binding Word',target=OWNER).candidate_id,
                  {'choice:needle.reflecting_gate':'miss'})
    after=reload(tmp_path,mid)
    assert not any(p['context']['reaction_source_id']=='choice:needle.reflecting_gate' for p in prompts)
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']
    saves=[r for r in after.rolls if r.reason.startswith('SAVE:')]
    assert [r.actor_id for r in saves]==[OWNER]


def test_automatic_reflection_leaves_beneficial_effect_on_ally(tmp_path):
    def prepare(bundles):
        add_action(bundles[2], 'Boundary gift', [{'type':'temp_hp', 'flat':7, 'applies_to':'target'}])
    combat,table,mid=fixture(tmp_path,[REFLECT],seed='A2FORMATIO-GIFT',
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':8,'y':6}},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Combat Array: Nourishing Cycle',at=(5,6)).candidate_id)
    turn(table,mid,FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Boundary gift',target=OWNER).candidate_id)
    after=reload(tmp_path,mid)
    assert after.state.actors[OWNER].temporary_hp==7
    assert after.state.actors[FOE].temporary_hp==before.state.actors[FOE].temporary_hp
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']


def test_reflected_ally_scoped_benefit_keeps_selected_recipient_through_reload(tmp_path):
    def prepare(bundles):
        add_action(bundles[2], 'Ally gift', [{'type':'temp_hp', 'flat':7, 'applies_to':'ally'}])
        bundles[2]['action_catalog'][-1]['parameters']['typed']['numbers']['save_dc']=1
        seal(bundles[2])
    combat,table,mid=fixture(tmp_path,[REFLECT],seed='A2FORMATIO-ALLY-RECIPIENT',
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':8,'y':6}},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Combat Array: Nourishing Cycle',at=(5,6)).candidate_id)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid)
    prompts=settle(table,mid,candidate(combat,mid,'Ally gift',target=OWNER).candidate_id,
           {'choice:needle.reflecting_gate':'redirect:'+ALLY})
    after=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.reflecting_gate' for p in prompts)
    assert after.state.actors[ALLY].temporary_hp==7
    assert after.state.actors[OWNER].temporary_hp==before.state.actors[OWNER].temporary_hp
    assert after.state.actors[OWNER].resources['resource:core.qi']==before.state.actors[OWNER].resources['resource:core.qi']-2


@pytest.mark.parametrize('sovereign', [False, True])
def test_keyed_ally_step_ai_menu_visibility_and_manual_execution_reload(tmp_path, sovereign):
    talent='tianxia.talent.formations.'+('sovereign_of_the_world_diagram' if sovereign else 'formation_step')
    combat,table,mid=fixture(tmp_path,[talent],seed='A2FORMATIO-AI-STEP')
    settle(table,mid,candidate(combat,mid,'Sovereign of the World-Diagram' if sovereign else 'Combat Array: Nourishing Cycle',
                             **({} if sovereign else {'at':(5,6)})).candidate_id)
    turn(table,mid,ALLY)
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='LOCAL_AUTO')
    engine=reload(tmp_path,mid)
    suggestion=combat.suggest(mid)  # exercise the public service's built-in AI decision route
    assert suggestion['schema']=='TianxiaFactoryCombatSuggestion.v1'
    ai_menu=__import__('combat.gate4_context',fromlist=['build_decision_context']).build_decision_context(
        engine, combat.policies.for_actor(ALLY)[0], for_ai=True)
    assert any(c.source_definition_id=='system:formation.keyed_step' for c in ai_menu.legal_candidates), {
        'player_only': engine.action_catalog['system:formation.keyed_step'].parameters.get('player_only'),
        'raw_step_candidates': [(c.kind.value, c.actor_id, c.target_ids, c.destination, c.metadata)
                                for c in engine.legal_candidates() if c.source_definition_id=='system:formation.keyed_step'],
        'ai_actor': ai_menu.active_actor_id,
        'ai_ids': [c.source_definition_id for c in ai_menu.legal_candidates if 'formation' in c.source_definition_id],
    }
    # The same accepted table/session route executes the granted action, then survives replay.
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='MANUAL')
    engine=reload(tmp_path,mid)
    chosen=next(c for c in engine.legal_candidates()
                if c.source_definition_id=='system:formation.keyed_step' and c.destination
                and (c.destination.x,c.destination.y)==(5,7))
    settle(table,mid,chosen.candidate_id)
    after=reload(tmp_path,mid)
    assert after.state.actors[ALLY].position==chosen.destination
    assert not any(c.source_definition_id=='system:formation.keyed_step' for c in after.legal_candidates())


def test_secret_category_line_does_not_classify_a_body_mention():
    from combat.ext.qiweaving_common import classifies_as_secret_inheritance
    assert classifies_as_secret_inheritance({}, 'Diagram\nSecret Formation Inheritance\nAction Type: Action')
    assert not classifies_as_secret_inheritance({}, 'Ordinary Array\nThis cannot suppress a Secret Formation Inheritance.')


def test_devours_reads_activation_recipient_not_original_intent():
    """The accepted intent remains replay-stable after declaration redirection."""
    from types import SimpleNamespace
    from combat.ext.formation_riders import _reached

    original = SimpleNamespace(entity_id=OWNER)
    rebound = SimpleNamespace(entity_id=FOE)
    engine = SimpleNamespace(
        _active_intent=SimpleNamespace(target_ids=(OWNER,)),
        state=SimpleNamespace(actors={OWNER: original, FOE: rebound}),
    )
    action = SimpleNamespace(parameters={'typed': {'_activation_redirect_recipient_id': FOE}})
    reached = _reached(engine, SimpleNamespace(entity_id='caster'), action, action.parameters['typed'])
    assert reached == [rebound]
    assert engine._active_intent.target_ids == (OWNER,)


def test_devours_transient_policy_is_retired_at_activation_end():
    """Subscriber intent isolation; service counter cleanup is covered in the r9 cases."""
    from types import SimpleNamespace
    from combat import ext
    from combat.ext.formation_riders import CAUGHT

    action = SimpleNamespace(source_definition_id='test:boundary-technique')
    actor = SimpleNamespace(entity_id=FOE)
    candidate_row = SimpleNamespace()
    first = object()
    second = object()
    engine = SimpleNamespace(**{CAUGHT: {
        'source': action.source_definition_id, 'actor': FOE,
        'activation_intent': id(first), 'mode': 'prevent', 'far': [OWNER]}})

    # A nested or subsequent activation cannot retire a different intent's
    # policy; the accepted intent that set it always can.
    ext.run('activation_end', engine, actor, action, candidate_row, second)
    assert CAUGHT in engine.__dict__
    ext.run('activation_end', engine, actor, action, candidate_row, first)
    assert CAUGHT not in engine.__dict__


def test_side_neutral_redirect_retains_harmful_recipient_classification():
    """Hostile targeting is relaxed for redirection without relaxing Charm."""
    from combat.recipients import allowed

    pair_support = __import__('tests.test_lock5_recipients', fromlist=['pair_engine', 'AN'])
    engine, actor, action = pair_support.pair_engine()
    target = engine.state.actors[pair_support.AN]
    engine._apply_condition(actor, 'condition:typed.charmed', 'test:charm', target.entity_id,
                            expires_on='UNTIL_REMOVED')
    from combat.technique_interception import redirected_action
    neutralized = redirected_action(action, 'ANY_CREATURE')
    assert neutralized.parameters['harmful'] is True
    assert not allowed(engine, actor, target, neutralized)
