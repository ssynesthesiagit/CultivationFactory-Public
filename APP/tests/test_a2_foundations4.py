"""Foundation base triggers through CombatService, session intents and cold reload."""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, ALLY, fixture, settle, candidate, reload, turn, sealed_native_attack

S = 'sword_bones_v0_2B'
B = 'true_blackblood_physique_v0_2C'
R = 'weak_reed_tendons_v0_2B'
C = 'white_crane_cloud_step_v0_2B'
T = 'taiyin_lunar_body_v0_2B'
V = 'verdant_returning_spring_v0_2B'
NAMES = {S: 'Severance Edge', B: 'Blackblood Pressure', R: 'Reed Flex', C: 'Crane Breath', T:'Lunar Yin Dew', V:'Spring Dew'}
POOLS = {k: 'resource:foundation.' + v.lower().replace(' ', '_') for k, v in NAMES.items()}
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}}


def setup(tmp_path, foundation=S, *, held=0, wounded=False, miss=False, attacks=1, ask=False, ally=False, prepare=False, modes=None,
          stage='Awakened', status=None, pressure_dc=None, extra_transform=None):
    doc = sheet([], kit=KIT)
    doc['foundation'] = {'foundation_id': foundation, 'stage': stage,
        'resource': {'name': NAMES[foundation], 'resource_id': 'tianxia.resource.foundation.' + foundation,
                     'maximum': 1, 'current': held}}
    if status is not None:
        doc['foundation']['status'] = status
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': ask})
    # Make printed attacks deterministic without replacing engine methods.
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('typed', {}).get('weapon'):
            action['attack_bonus'] = 100
            action['parameters']['typed']['attack_bonus'] = 100
    sealed_native_attack(owner, 'Owner hit', attack_bonus=100, modifier=0, attacks=attacks)
    if wounded:
        owner['actor_template']['maximum_hp'] = 20
    owner.pop('bundle_sha256', None); owner['bundle_sha256'] = canonical_sha256(owner)
    def transform(bundles):
        if prepare:
            from tests.cw2_service_support import add_action
            add_action(bundles[0], 'Lie down', [{'type':'condition', 'condition':'prone', 'applies_to':'self'}], target='SELF')
            add_action(bundles[0], 'Bind self', [{'type':'condition', 'condition':'restrained', 'applies_to':'self'}], target='SELF')
            for name, ability, hazards in [('Poison pressure','con',['poisoned']), ('Prone pressure', 'dex', ['prone']), ('Restraint pressure', 'str', ['restrained']), ('Cold pressure', 'dex', [])]:
                add_action(bundles[2], name, [{'type':'save', 'ability':ability, 'dc':pressure_dc or 30,
                    'applies_to':'target', 'on_fail':[{'type':'condition', 'condition':h, 'applies_to':'target'} for h in hazards], 'on_success':[]}],
                    typed={'numbers': {'pb':4, 'key_mod':2, 'save_dc':pressure_dc, 'cl':15}}
                          if pressure_dc is not None else None)
            add_action(bundles[2], 'Forced movement pressure', [{'type':'save', 'ability':'str', 'dc':30,
                'applies_to':'target', 'on_fail':[{'type':'forced_movement','distance_ft':5,'direction':'away','applies_to':'target'}], 'on_success':[]}],
                typed={'numbers': {'pb':4, 'key_mod':2, 'save_dc':30, 'cl':15}})
            add_action(bundles[2], 'Poison damage pressure', [{'type':'save', 'ability':'dex', 'dc':30,
                'applies_to':'target', 'on_fail':[{'type':'damage','flat':1,'damage_types':['poison'],'applies_to':'target'}], 'on_success':[]}],
                typed={'numbers': {'pb':4, 'key_mod':2, 'save_dc':30, 'cl':15}})
            add_action(bundles[1], 'Friendly poison pressure', [{'type':'save','ability':'con','applies_to':'target','on_fail':[{'type':'condition','condition':'poisoned','applies_to':'target'}],'on_success':[]}])
            add_action(bundles[1], 'Friendly damage', [{'type':'damage','flat':12,'damage_types':['fire'],'applies_to':'target'}])
            add_action(bundles[1], 'Friendly large damage', [{'type':'damage','flat':20,'damage_types':['fire'],'applies_to':'target'}])
            add_action(bundles[2], 'Pin owner', [{'type':'condition','condition':'grappled','applies_to':'target'}, {'type':'condition','condition':'pinned','applies_to':'target'}])
            add_action(bundles[0], 'Lose reactions', [{'type':'reaction_denied','applies_to':'self','duration':{'kind':'until_end_of_next_turn'}}], target='SELF')
            add_action(bundles[2], 'Deny reaction against foe', [{'type':'deny_reactions_against','applies_to':'target'}])
            add_action(bundles[2], 'Movement packet', [{'type':'forced_movement','distance_ft':5,'direction':'away','applies_to':'target'}])
            add_action(bundles[2], 'Constitution pressure', [{'type':'save','ability':'con','dc':30,'applies_to':'target','on_fail':[],'on_success':[]}])
        if extra_transform:
            extra_transform(bundles)
        sealed_native_attack(bundles[2], 'Hostile hit', modifier=12 if wounded else 6,
                             attack_bonus=-100 if miss else 100, attacks=attacks)
        if ally:
            sealed_native_attack(bundles[1], 'Friendly hit', attack_bonus=100, modifier=12)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, ask=ask, seed='A2GFOU4',
                   bundle_transform=transform, foe_position={'x': 5, 'y': 6}, ally_position={'x': 4, 'y': 7}, modes=modes)
    return combat, table, mid


def own_attack(combat, mid, target=FOE):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if c.target_ids == (target,)
                and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('weapon')
                and '#throw' not in c.source_definition_id)


def move(combat, table, mid, feet):
    engine = combat._load_session(mid).engine
    choices = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.movement_cost_ft == feet]
    assert choices
    settle(table, mid, choices[0].candidate_id)


def attack_owner(combat, table, mid, *, choices=None):
    turn(table, mid, FOE)
    return settle(table, mid, candidate(combat, mid, 'Hostile hit', target=OWNER).candidate_id, choices=choices)


def gains(engine, pool):
    return [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool]


def test_severance_generated_after_weapon_hit_and_cannot_pay_that_hit(tmp_path):
    combat, table, mid = setup(tmp_path)
    move(combat, table, mid, 5)
    settle(table, mid, own_attack(combat, mid).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOLS[S]]
    gain = gains(engine, POOLS[S])[0]
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER)
    assert engine.events.index(gain) > engine.events.index(damage)


@pytest.mark.parametrize('foundation', [S, B])
def test_held_resource_adds_one_pb_to_weapon_hit(tmp_path, foundation):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True)
    move(combat, table, mid, 5)
    prompts = settle(table, mid, own_attack(combat, mid).candidate_id,
           choices={f'reaction:typed.foundation.{foundation}.sword_bone_cut' if foundation == S else
                    f'reaction:typed.foundation.{foundation}.blackblood_return': 'USE'})
    engine = reload(tmp_path, mid)
    extra = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert len(extra) == 2
    assert extra[-1].payload['hp_damage'] == 4
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOLS[foundation]]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith(
        'sword_bone_cut' if foundation == S else 'blackblood_return'))
    assert ' attack hit ' in prompt['summary']
    assert prompt['action'] and prompt['action'] in prompt['summary']
    assert prompt['affected'] == reload(tmp_path, mid).state.actors[FOE].display_name
    assert ('Sword Bone Cut' if foundation == S else 'Blackblood Return') in prompt['summary']
    assert '4 damage' in prompt['summary']
    assert ('severance edge' if foundation == S else 'blackblood pressure') in prompt['table_note']


@pytest.mark.parametrize('foundation,expected', [(S, 6), (B, 6), (R, 4)])
def test_base_guard_spends_one_resource_and_one_reaction(tmp_path, foundation, expected):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True)
    kind = {S:'sheath_bone_guard', B:'blackblood_guard', R:'bend_without_breaking_guard'}[foundation]
    prompts = attack_owner(combat, table, mid, choices={f'reaction:typed.foundation.{foundation}.{kind}': 'USE'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith(kind))
    assert 'would deal' in prompt['summary'] and 'damage' in prompt['summary']
    assert 'resource:foundation.' not in prompt['table_note'] and 'Reaction' in prompt['table_note']
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[POOLS[foundation]] == 0
    assert not actor.reaction_available
    reductions = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == f'foundation.{foundation}.{kind}']
    assert reductions and f'reduce damage by {expected}' in str(reductions[-1].payload)


@pytest.mark.parametrize('wounded,expected', [(False, 0), (True, 1)])
def test_blackblood_requires_hostile_damage_and_bloodied_conscious_owner(tmp_path, wounded, expected):
    combat, table, mid = setup(tmp_path, B, wounded=wounded)
    attack_owner(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[B]] == expected
    if expected:
        assert gains(engine, POOLS[B])
        assert engine.state.actors[OWNER].current_hp > 0


@pytest.mark.parametrize('feet,expected', [(0, 0), (5, 0), (10, 1)])
def test_reed_miss_requires_ten_feet_since_last_owner_turn(tmp_path, feet, expected):
    combat, table, mid = setup(tmp_path, R, miss=True)
    if feet:
        move(combat, table, mid, feet)
    attack_owner(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[R]] == expected
    assert engine._effective_speed(engine.state.actors[OWNER]) == 35


def test_reed_frame_adds_movement_to_turn_budget(tmp_path):
    combat, table, mid = setup(tmp_path, R)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 35
    move(combat, table, mid, 35)
    assert reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft == 0


def test_light_body_recovery_is_one_combined_temp_hp_offer(tmp_path):
    combat, table, mid = setup(tmp_path, C, held=1)
    settle(table, mid, candidate(combat, mid, 'Light-Body Recovery').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 6
    assert engine.state.actors[OWNER].resources[POOLS[C]] == 0
    assert not engine.state.actors[OWNER].bonus_action_available


@pytest.mark.parametrize('restrained', [False, True])
def test_light_body_optional_standing_respects_zero_speed(tmp_path, restrained):
    combat, table, mid = setup(tmp_path, C, held=1, prepare=True)
    settle(table, mid, candidate(combat, mid, 'Lie down').candidate_id)
    if restrained:
        settle(table, mid, candidate(combat, mid, 'Bind self').candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    prompts = settle(table, mid, candidate(combat, mid, 'Light-Body Recovery').candidate_id,
        choices={'choice:needle.light_body_stand':'stand'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.temporary_hp == 6
    assert owner.movement_remaining_ft == before
    assert any(c.condition_id == 'condition:typed.prone' for c in owner.conditions.values()) == restrained
    assert bool(prompts) != restrained
    if restrained:
        assert any(c.condition_id == 'condition:typed.restrained' for c in owner.conditions.values())


@pytest.mark.parametrize('foundation,feature,attack', [
    (S, 'severing_clarity', 'Prone pressure'),
    (R, 'reed_recovery', 'Restraint pressure'),
    (B, 'blackblood_refusal', 'Constitution pressure'),
])
def test_scoped_postroll_bonus_keeps_natural_and_adds_pb_after_rolled(tmp_path, foundation, feature, attack):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    rid = f'reaction:typed.foundation.{foundation}.{feature}'
    prompts = settle(table, mid, candidate(combat, mid, attack, target=OWNER).candidate_id, choices={rid:'USE'})
    assert prompts and any(p['context']['reaction_source_id'] == rid for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 0
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewrites and rewrites[-1].source_definition_id == f'foundation.{foundation}.{feature}'
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves and saves[-1].payload['modifier'] == 6
    assert engine.state.actors[OWNER].reaction_available
    receipts = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == f'foundation.{foundation}.{feature}']
    assert receipts and NAMES[foundation].lower() in str(receipts[-1].payload.get('log', '')).lower()
    assert ('severing clarity' if feature == 'severing_clarity' else
            'blackblood refusal' if feature == 'blackblood_refusal' else 'reed recovery') in receipts[-1].payload['log'].lower()


def test_automated_foe_turn_pauses_for_manual_foundation_guard_context(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Hostile hit', target=OWNER).candidate_id
    from combat.gate4_adapters import ManualControllerAdapter
    real_controller = combat.controller
    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real_controller, name)
    combat.controller = FixedController()
    result = table.auto_step(mid, 0)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['context']['reaction_source_id'].endswith('blackblood_guard')
    assert 'Hostile hit' in prompt['summary'] and 'damage' in prompt['summary']
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].display_name in prompt['summary']
    assert 'blackblood pressure' in prompt['table_note'] and 'Reaction' in prompt['table_note']
    # Pausing for the player leaves payment pending until their explicit answer.
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOLS[B]] == 1


@pytest.mark.parametrize('foundation', [S, R, B])
def test_unscoped_save_does_not_offer_or_spend_scoped_bonus(tmp_path, foundation):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Cold pressure', target=OWNER).candidate_id)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 1
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']


@pytest.mark.parametrize('foundation,feature,action', [
    (R, 'reed_recovery', 'Forced movement pressure'),
    (B, 'blackblood_refusal', 'Poison damage pressure'),
])
def test_foundation_save_bonuses_receive_explicit_hazard_tags(tmp_path, foundation, feature, action):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    rid = f'reaction:typed.foundation.{foundation}.{feature}'
    prompts = settle(table, mid, candidate(combat, mid, action, target=OWNER).candidate_id, choices={rid:'USE'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == rid for p in prompts), (prompts, [e.model_dump(mode='json') for e in engine.events if e.event_type in ('SAVE_ROLLED', 'D20_REWRITTEN')])
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 0
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == f'foundation.{foundation}.{feature}' for e in engine.events)


def test_severance_expiry_survives_turn_and_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    move(combat, table, mid, 5)
    settle(table, mid, own_attack(combat, mid).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOLS[S]] == 1
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOLS[S]] == 0


@pytest.mark.parametrize('foundation,ability', [(T,'Preserving Moon Breath'),(V,'Spring Renewal Pulse')])
@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_support_grants_one_combined_offer_to_one_allied_recipient(tmp_path, foundation, ability, target):
    combat, table, mid = setup(tmp_path, foundation, held=1, prepare=True)
    actions = [c for c in combat._load_session(mid).engine.legal_candidates()
               if combat._load_session(mid).engine.action_catalog.get(c.source_definition_id)
               and combat._load_session(mid).engine.action_catalog[c.source_definition_id].display_name == ability]
    assert actions and all(FOE not in c.target_ids for c in actions)
    settle(table, mid, candidate(combat, mid, ability, target=target).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[target].temporary_hp == 6
    assert engine.state.actors[FOE].temporary_hp == 0
    assert engine.state.actors[OWNER if target == ALLY else ALLY].temporary_hp == 0
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 0
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Cold pressure', target=target).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.foundations4_support' for c in engine.state.actors[target].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Poison pressure', target=target).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == target]
    assert rolls[-1].payload['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.foundations4_support' for c in engine.state.actors[target].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Poison pressure', target=target).candidate_id)
    rolls = [e for e in reload(tmp_path, mid).events if e.event_type == 'SAVE_ROLLED' and e.actor_id == target]
    assert rolls[-1].payload['mode'] != 'ADVANTAGE'


@pytest.mark.parametrize('foundation,feature', [(S,'severing_clarity'),(R,'reed_recovery')])
def test_named_pin_escape_receives_postroll_bonus_without_reroll(tmp_path, foundation, feature):
    combat, table, mid = setup(tmp_path, foundation, held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Pin owner', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    rid=f'reaction:typed.foundation.{foundation}.{feature}'
    prompts=settle(table, mid, candidate(combat, mid, 'Escape grapple').candidate_id, choices={rid:'USE'})
    assert any(p['context']['reaction_source_id'] == rid for p in prompts)
    engine=reload(tmp_path, mid)
    checks=[e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert checks[-1].payload['actor']['modifier'] == 6
    assert len(checks[-1].payload['actor']['dice']) == 1
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 0


@pytest.mark.parametrize('foundation', [S,B,R])
def test_guard_cannot_pay_without_reaction_permission(tmp_path, foundation):
    combat, table, mid=setup(tmp_path,foundation,held=1,prepare=True)
    settle(table,mid,candidate(combat,mid,'Lose reactions').candidate_id)
    attack_owner(combat,table,mid)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 1
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOLS[foundation]]


@pytest.mark.parametrize('foundation', [S, B, R])
def test_guard_honors_attacker_specific_reaction_prohibition(tmp_path, foundation):
    combat, table, mid = setup(tmp_path, foundation, held=1, prepare=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Deny reaction against foe', target=OWNER).candidate_id)
    attack_owner(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOLS[foundation]]


def test_blackblood_pressure_observes_nested_hostile_damage(tmp_path):
    from combat import ext, typed_executor
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True)
    def nested_packet(engine, event_type, kwargs):
        if event_type != 'MOVEMENT_COMMITTED' or engine.__dict__.get('_f4_nested_packet_done'):
            return
        action = engine.action_catalog.get(kwargs.get('source_definition_id'))
        if action is None or action.owner_id != FOE:
            return
        engine._f4_nested_packet_done = True
        actor = engine.state.actors[action.owner_id]
        target = engine.state.actors[OWNER]
        typed = action.parameters.get('typed') or {}
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent, typed, [target], target, {})
        typed_executor.run_effects(ctx, [{'type':'damage','flat':40,'damage_types':['fire'],'applies_to':'target'}])
    ext.hook('event')(nested_packet)
    try:
        turn(table, mid, FOE)
        prompts = settle(table, mid, candidate(combat, mid, 'Movement packet', target=OWNER).candidate_id,
                         choices={f'reaction:typed.foundation.{B}.blackblood_guard': 'USE'})
        engine = reload(tmp_path, mid)
    finally:
        ext._HOOKS['event'].remove(nested_packet)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith('blackblood_guard'))
    assert 'Movement packet' in prompt['summary'] and 'damage' in prompt['summary']
    assert 'blackblood pressure' in prompt['table_note'] and 'Reaction' in prompt['table_note']
    assert engine.state.actors[OWNER].current_hp == 26
    assert engine.state.actors[OWNER].resources[POOLS[B]] == 1


@pytest.mark.parametrize('foundation,feature', [(S,'sword_bone_cut'),(B,'blackblood_return')])
def test_native_multiattack_spends_once_and_adds_one_flat_pb_packet(tmp_path, foundation, feature):
    combat, table, mid=setup(tmp_path,foundation,held=1,attacks=2)
    settle(table,mid,candidate(combat,mid,'Owner hit',target=FOE).candidate_id,
        choices={f'reaction:typed.foundation.{foundation}.{feature}':'USE'})
    engine=reload(tmp_path,mid)
    damage=[e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert len(damage) == 3
    assert damage[1].payload['hp_damage'] == 4
    assert engine.state.actors[OWNER].resources[POOLS[foundation]] == 0
    spent=[e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOLS[foundation]]
    assert len(spent) == 1


@pytest.mark.parametrize('foundation,ability', [(T,'Preserving Moon Breath'),(V,'Spring Renewal Pulse')])
def test_support_protects_qualifying_save_even_from_a_friendly_source(tmp_path, foundation, ability):
    combat,table,mid=setup(tmp_path,foundation,held=1,prepare=True)
    settle(table,mid,candidate(combat,mid,ability,target=OWNER).candidate_id)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Friendly poison pressure',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.foundations4_support' for c in engine.state.actors[OWNER].conditions.values())


EXPRESSION_ACTION = 'Foundation expression: Refined: Venom-Dark Marrow'
VENOM = f'foundation.{B}.refined_venom_dark_marrow'
EXPRESSION_SOURCE = '.foundation_expression.refined_venom_dark_marrow'
REFUSAL = f'reaction:typed.foundation.{B}.blackblood_refusal'
REFUSAL_FEATURE = f'foundation.{B}.blackblood_refusal'


def select_venom_dark_marrow(combat, table, mid):
    settle(table, mid, candidate(combat, mid, EXPRESSION_ACTION).candidate_id)


def flip_control(combat, mid, actor, mode):
    session = combat._load_session(mid)
    metadata = combat._read_metadata(mid, session)
    metadata['participant_control_modes'][actor] = mode
    combat._write_metadata(mid, metadata)


def test_selected_venom_dark_marrow_adds_one_more_pb_to_the_same_refusal_roll(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    engine = reload(tmp_path, mid)
    selected = next(c for c in engine.state.actors[OWNER].conditions.values()
                    if c.condition_id == 'condition:typed.foundation_combat.expression')
    assert selected.data['feature'] == VENOM
    assert selected.data['name'] == 'Refined: Venom-Dark Marrow'
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
                     choices={REFUSAL: 'USE'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REFUSAL)
    assert 'Refined: Venom-Dark Marrow is selected' in prompt['table_note']
    assert '1 blackblood pressure' in prompt['table_note']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOLS[B]] == 0
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(saves) == 1
    assert saves[0].payload['modifier'] == 10  # 2 save + 4 base PB + 4 Venom-Dark Marrow PB
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert len(rewrites) == 1 and rewrites[0].source_definition_id == REFUSAL_FEATURE
    assert rewrites[0].payload['operation'] == 'replace'
    assert rewrites[0].payload['original']['natural_result'] == rewrites[0].payload['result']['natural_result']
    assert len(rewrites[0].payload['result']['dice']) == 1
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload.get('resource_id') == POOLS[B]]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1
    assert spends[0].source_definition_id == REFUSAL_FEATURE
    receipts = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == REFUSAL_FEATURE]
    assert 'add 8 to the roll' in receipts[-1].payload['log']
    assert owner.reaction_available


def test_refined_owner_without_a_selected_expression_keeps_the_base_bonus(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True, stage='Refined')
    engine = reload(tmp_path, mid)
    assert any(a.source_definition_id.endswith(EXPRESSION_SOURCE) for a in engine.action_catalog.values())
    assert not any(c.condition_id == 'condition:typed.foundation_combat.expression'
                   for c in engine.state.actors[OWNER].conditions.values())
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
                     choices={REFUSAL: 'USE'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REFUSAL)
    assert not prompt['table_note']
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['modifier'] == 6
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload.get('resource_id') == POOLS[B]]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1


def test_awakened_owner_has_no_venom_dark_marrow_expression_to_select(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True)
    engine = reload(tmp_path, mid)
    assert not any(a.source_definition_id.endswith(EXPRESSION_SOURCE) for a in engine.action_catalog.values())
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
                     choices={REFUSAL: 'USE'})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['modifier'] == 6


def test_declining_the_refusal_spends_nothing_and_keeps_the_expression(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id)
    assert any(p['context']['reaction_source_id'] == REFUSAL for p in prompts)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOLS[B]] == 1
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert next(c for c in owner.conditions.values()
                if c.condition_id == 'condition:typed.foundation_combat.expression')
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
             choices={REFUSAL: 'USE'})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['modifier'] == 10
    assert engine.state.actors[OWNER].resources[POOLS[B]] == 0


def test_ai_owner_auto_selects_a_refined_expression_under_its_printed_name(tmp_path):
    # The AI default is the first owned printed expression (Clotted Iron Blood), chosen once per fight.
    # Venom-Dark Marrow's Refusal path is covered by the manual selection tests above.
    combat, table, mid = setup(tmp_path, B, held=1, prepare=True, stage='Refined')
    turn(table, mid, FOE)
    flip_control(combat, mid, OWNER, 'LOCAL_AUTO')
    turn(table, mid, OWNER)          # the real AI selects the expression at its turn start
    engine = reload(tmp_path, mid)
    selected = next(c for c in engine.state.actors[OWNER].conditions.values()
                    if c.condition_id == 'condition:typed.foundation_combat.expression')
    assert selected.data['feature'] == f'foundation.{B}.refined_clotted_iron_blood'
    assert selected.data['name'] == 'Refined: Clotted Iron Blood'


def test_ai_owner_without_the_expression_declines_the_same_save(tmp_path):
    from tests.cw2_service_support import add_action
    def close_pressure(bundles):
        add_action(bundles[2], 'Close pressure', [{'type': 'save', 'ability': 'con', 'dc': 24,
            'applies_to': 'target', 'on_fail': [], 'on_success': []}],
            typed={'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 24, 'cl': 15}})
    combat, table, mid = setup(tmp_path, B, held=1, prepare=True, stage='Awakened',
                               extra_transform=close_pressure)
    turn(table, mid, FOE)
    flip_control(combat, mid, OWNER, 'LOCAL_AUTO')
    turn(table, mid, OWNER)
    flip_control(combat, mid, OWNER, 'MANUAL')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    flip_control(combat, mid, OWNER, 'LOCAL_AUTO')
    settle(table, mid, candidate(combat, mid, 'Close pressure', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOLS[B]] == 1
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['modifier'] == 2
    assert saves[-1].payload['success'] is False  # 16 + 4 < 24: the base PB alone cannot flip it
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']


@pytest.mark.parametrize('held', [0, 1])
def test_selected_expression_does_not_widen_the_refusal_scope(tmp_path, held):
    combat, table, mid = setup(tmp_path, B, held=held, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Cold pressure', target=OWNER).candidate_id)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[B]] == held
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']


def test_selected_expression_without_pressure_never_offers_the_refusal(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=0, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']


def test_venom_dark_marrow_selection_survives_commit_and_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert next(c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == 'condition:typed.foundation_combat.expression')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
             choices={REFUSAL: 'USE'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOLS[B]] == 0
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['modifier'] == 10
    assert next(c for c in owner.conditions.values()
                if c.condition_id == 'condition:typed.foundation_combat.expression')
