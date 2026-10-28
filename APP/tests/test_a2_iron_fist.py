"""Printed Iron Fist second-pass mechanics through table intents and cold replay."""
import pytest

from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, action_sender, reload, settle, turn, resolve

TRAIN = 'TAL_IRON_FIST_IRON_FIST_TRAINING'
SWEEP = 'TAL_IRON_FIST_SWEEPING_KICK'
FLOW = 'TAL_IRON_FIST_FLOWING_COMBINATION'
ADEPT = 'insight.flowing-combination-adept'
WAR = 'TAL_IRON_FIST_THOUSAND_HAND_WAR_BODY'
PALM = 'TAL_IRON_FIST_PALM_THAT_MOVES_THE_EMPTY_BELL'
FOCUS = 'resource:core.martial_focus'
OPEN = {'type': 'mark', 'mark': 'Opened', 'duration': {'kind': 'one_minute'}, 'applies_to': 'target'}
BURDEN = 'condition:typed.standing_burden'


def pick(prompt):
    source = prompt['context']['reaction_source_id']
    ids = [o['id'] for o in prompt['choice']['options']]
    if source == 'choice:needle.directed_movement':
        return ['south']
    if source == 'choice:needle.flowing_combination':
        return ['Shove: Prone']
    if source == 'choice:needle.iron_fist_step':
        return ['cell:3,7'] if 'cell:3,7' in ids else []
    if source == 'choice:needle.area_recipients':
        return [RIGHT]
    if 'movement' in source or 'rider_step' in source:
        return []
    return ids[:max(1, prompt['choice'].get('minimum', 1))]


@pytest.mark.parametrize('opened', [False, True])
@pytest.mark.parametrize('ai', [False, True])
def test_sweeping_kick_damages_and_charges_actual_standing_only_if_preopened(tmp_path, opened, ai):
    c, t, m = fight(tmp_path, [TRAIN, SWEEP], left_score=50,
                    prepare=[OPEN] if opened else [])
    if opened:
        settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    e = reload(c, m)
    amount = next(a.parameters['typed']['numbers']['key_mod'] for a in e.action_catalog.values()
                  if a.display_name == 'Shove: Prone')
    _, prompts = settle(action_sender(c, t, m, 'Shove: Prone', ai=ai, target_id=RIGHT), pick)
    e = reload(c, m)
    target = e.state.actors[RIGHT]
    assert target.current_hp == 1000 - max(1, amount)
    assert any(x.condition_id.endswith('.prone') for x in target.conditions.values())
    assert any(x.condition_id == BURDEN for x in target.conditions.values()) == opened
    assert not any(v.event_type == 'GM_RIDER' and 'Sweeping Kick' in str(v.payload) for v in e.events)
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    e = reload(c, m)
    stood = next(v for v in reversed(e.events) if v.event_type == 'STOOD_UP' and v.actor_id == RIGHT)
    assert stood.payload['cost_ft'] == (25 if opened else 15)
    turn(t, m, LEFT)
    assert not any(x.condition_id == BURDEN for x in reload(c, m).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('kind', ['Grapple', 'Shove: Push 5 ft'])
def test_sweeping_kick_never_adds_prone_damage_to_other_options(tmp_path, kind):
    c, t, m = fight(tmp_path, [TRAIN, SWEEP], left_score=50, prepare=[OPEN])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    e = reload(c, m)
    label = kind + ' + Sweeping Kick' if any(a.display_name == kind + ' + Sweeping Kick'
                 for a in e.action_catalog.values()) else kind
    settle(lambda a: act(t, m, label, a, target_id=RIGHT), pick)
    target = reload(c, m).state.actors[RIGHT]
    assert target.current_hp == 1000
    assert not any(x.condition_id == BURDEN for x in target.conditions.values())


def test_sweeping_kick_successful_save_does_nothing(tmp_path):
    c, t, m = fight(tmp_path, [TRAIN, SWEEP], right_score=100)
    settle(lambda a: act(t, m, 'Shove: Prone', a, target_id=RIGHT), pick)
    target = reload(c, m).state.actors[RIGHT]
    assert target.current_hp == 1000
    assert not any(x.condition_id in (BURDEN, 'condition:typed.prone') for x in target.conditions.values())


@pytest.mark.parametrize('owned', [False, True])
@pytest.mark.parametrize('opened', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_flowing_adept_dc_step_and_focus_are_bound_to_its_free_attempt(tmp_path, owned, opened, failed):
    attack = {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
              'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}
    c, t, m = fight(tmp_path, [TRAIN, FLOW, *([ADEPT] if owned else [])], left_score=50,
                    right_score=14 if failed else 100, prepare=[*([OPEN] if opened else []), attack],
                    prepare_attack_bonus=100, prepare_costs=[(FOCUS, 1)])
    original = reload(c, m)
    base_dc = next(a.parameters['typed']['numbers']['save_dc'] for a in original.action_catalog.values()
                   if a.display_name == 'Shove: Prone')
    _, prompts = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    e = reload(c, m)
    save = next(v for v in e.events if v.event_type == 'SAVE_ROLLED'
                and v.source_definition_id == 'passive:TAL_IRON_FIST_FLOWING_COMBINATION')
    assert save.payload['dc'] == base_dc + int(owned)
    steps = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.iron_fist_step']
    assert bool(steps) == (owned and failed)
    assert e.state.actors[LEFT].position.y == (7 if owned and failed else 6)
    assert e.state.actors[LEFT].resources[FOCUS] == int(owned and opened)
    # The persistent action catalog must keep its original save DC.
    assert next(a.parameters['typed']['numbers']['save_dc'] for a in e.action_catalog.values()
                if a.display_name == 'Shove: Prone') == base_dc
    before = len(e.events)
    settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), pick)
    e = reload(c, m)
    assert not any(v.event_type == 'SAVE_ROLLED' and v.source_definition_id == save.source_definition_id
                   for v in e.events[before:])


@pytest.mark.parametrize('failed', [False, True])
@pytest.mark.parametrize('ai', [False, True])
def test_palm_direction_is_selected_once_and_save_controls_distance_and_prone(tmp_path, failed, ai):
    c, t, m = fight(tmp_path, [TRAIN, PALM], left_score=50, right_score=14 if failed else 100,
                    positions={LEFT: {'x': 3, 'y': 3}, RIGHT: {'x': 4, 'y': 3}}, left_attack_bonus=100)
    _, prompts = settle(action_sender(c, t, m, 'Palm That Moves the Empty Bell', ai=ai, target_id=RIGHT), pick)
    e = reload(c, m)
    target = e.state.actors[RIGHT]
    assert target.current_hp < 1000
    assert any(x.condition_id.endswith('.prone') for x in target.conditions.values()) == failed
    assert target.position.z == 0
    if not ai:
        assert (target.position.x, target.position.y) == (4, 7 if failed else 4)
        assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.directed_movement']) == 1
    else:
        assert (target.position.x, target.position.y) == (5, 3)  # the arena pillar blocks the second eastward step
    assert e.state.actors[LEFT].resources[FOCUS] == 0
    assert not any(v.event_type == 'GM_RIDER' and 'GM should resolve' in str(v.payload) for v in e.events)


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_thousand_hand_selects_recipients_and_ai_only_harms_enemies(tmp_path, ai, failed):
    c, t, m = fight(tmp_path, [TRAIN, WAR], left_score=50, right_score=14 if failed else 100,
                    ally=[], extra_witness=True, witness_team='team:opponents',
                    positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 2, 'y': 6}})
    witness = 'actor:factory.auto111-witness'
    before = reload(c, m)
    _, prompts = settle(action_sender(c, t, m, 'Thousand-Hand War Body', ai=ai), pick)
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp < 1000
    for friend in [LEFT, ALLY]:
        assert e.state.actors[friend].current_hp == before.state.actors[friend].current_hp
        assert not bears_mark(e.state.actors[friend], LEFT, 'Opened')
    assert (e.state.actors[witness].current_hp < 1000) == ai
    assert bears_mark(e.state.actors[RIGHT], LEFT, 'Opened')
    assert any(x.condition_id.endswith('.reaction_denied') for x in e.state.actors[RIGHT].conditions.values()) == failed
    assert e.state.actors[LEFT].resources[FOCUS] == 0
    if not ai:
        choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.area_recipients')
        assert RIGHT in [o['id'] for o in choice['choice']['options']]
        assert {LEFT, ALLY} <= {o['id'] for o in choice['choice']['options']}
        assert 'Dexterity' in choice['trigger'] or 'Dexterity' in str(choice)
    assert not any(v.event_type == 'GM_RIDER' and 'Thousand-Hand' in str(v.payload) for v in e.events)


@pytest.mark.parametrize('ai', [False, True])
def test_falling_leaf_secondary_targets_use_printed_origin_and_ai_enemy_side(tmp_path, ai):
    leaf = 'TAL_IRON_FIST_FALLING_LEAF_SWEEP'
    witness = 'actor:factory.auto111-witness'
    c, t, m = fight(tmp_path, [TRAIN, leaf], left_score=50, prepare=[OPEN] if ai else [], ally=[],
                    extra_witness=True, witness_team='team:opponents',
                    positions={LEFT: {'x': 1, 'y': 6}, RIGHT: {'x': 2, 'y': 6}, ALLY: {'x': 1, 'y': 7}})
    # Witness's shared fixture square (3,5) lies within five feet of the
    # primary target; the allied user is also within that printed radius.
    if ai:
        settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    def sweep_pick(p):
        if p['context']['reaction_source_id'] == 'choice:needle.iron_fist.Falling Leaf Sweep targets':
            return [witness]
        return pick(p)
    settle(action_sender(c, t, m, 'Shove: Prone', ai=ai, target_id=RIGHT), sweep_pick)
    e = reload(c, m)
    assert any(x.condition_id.endswith('.prone') for x in e.state.actors[witness].conditions.values())
    for friend in (LEFT, ALLY):
        assert not any(x.condition_id.endswith('.prone') for x in e.state.actors[friend].conditions.values())
    saves = [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == witness]
    assert len(saves) == 1


def test_sweeping_kick_printed_minimum_one_damage(tmp_path):
    def numbers(bundle):
        if bundle['actor_template']['entity_id'] != LEFT:
            return
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Shove: Prone':
                action['parameters']['typed']['numbers'].update(key_mod=-3, save_dc=100)
            if '.natural.' in action['source_definition_id']:
                action['parameters']['typed']['weapon']['damage']['modifier'] = -3
    c, t, m = fight(tmp_path, [TRAIN, SWEEP], bundle_edit=numbers)
    settle(lambda a: act(t, m, 'Shove: Prone', a, target_id=RIGHT), pick)
    assert reload(c, m).state.actors[RIGHT].current_hp == 999


def test_sweeping_kick_uses_iron_fist_modifier_when_cultivation_key_differs(tmp_path):
    def scores(doc, aid):
        if aid == LEFT:
            for row in doc['ability_scores_and_statistics']['abilities']:
                score = {'STR': 30, 'DEX': 12, 'CON': 50}.get(row['ability'], 14)
                row.update(score=score, modifier=(score - 10) // 2)
    c, t, m = fight(tmp_path, [TRAIN, SWEEP], sheet_edit=scores, right_score=1)
    settle(lambda a: act(t, m, 'Shove: Prone', a, target_id=RIGHT), pick)
    assert reload(c, m).state.actors[RIGHT].current_hp == 990  # STR +10, not the CON key's +20


@pytest.mark.parametrize('move', [False, True])
def test_thousand_hand_immediate_step_uses_half_current_speed_and_no_ordinary_credit(tmp_path, move):
    c, t, m = fight(tmp_path, [TRAIN, WAR], left_score=50, prepare_target='SELF',
                    prepare=[{'type': 'speed', 'applies_to': 'self', 'flat': -10, 'duration': 'one_minute'}])
    settle(lambda a: act(t, m, 'Prepare', a), pick)
    e = reload(c, m)
    assert e.state.actors[LEFT].speed_ft == 30
    assert e._effective_speed(e.state.actors[LEFT]) == 20
    start = reload(c, m).state.actors[LEFT]
    allowance = start.movement_remaining_ft
    def destination(p):
        if p['context']['reaction_source_id'] == 'choice:needle.rider_step':
            assert '10 feet' in p['trigger'] or '10 feet' in str(p)
            ids = {o['id'] for o in p['choice']['options']}
            assert 'cell:3,8' in ids and 'cell:3,9' not in ids
            return ['cell:3,8'] if move else []
        return pick(p)
    _, prompts = settle(lambda a: act(t, m, 'Thousand-Hand War Body', a), destination)
    e = reload(c, m)
    actor = e.state.actors[LEFT]
    assert actor.position.y == (8 if move else 6)
    assert actor.movement_remaining_ft == allowance
    assert not actor.turn_flags.get('oa_free_ft')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts)


def test_thousand_hand_empty_recipient_choice_still_pays_and_does_not_harm_anyone(tmp_path):
    c, t, m = fight(tmp_path, [TRAIN, WAR], left_score=50, ally=[])
    def nobody(p):
        return [] if p['context']['reaction_source_id'] == 'choice:needle.area_recipients' else pick(p)
    settle(lambda a: act(t, m, 'Thousand-Hand War Body', a), nobody)
    e = reload(c, m)
    assert all(a.current_hp == 1000 for a in e.state.actors.values())
    assert not any(v.event_type == 'SAVE_ROLLED' for v in e.events)
    assert e.state.actors[LEFT].resources[FOCUS] == 0


@pytest.mark.parametrize('talent,label', [(WAR, 'Thousand-Hand War Body'), (PALM, 'Palm That Moves the Empty Bell')])
def test_long_rest_techniques_cannot_repeat_in_the_same_fight_after_focus_returns(tmp_path, talent, label):
    c, t, m = fight(tmp_path, [TRAIN, talent], left_score=50,
                    prepare_target='SELF', prepare=[{'type': 'gain_resource', 'resource_id': FOCUS, 'flat': 1, 'applies_to': 'self'}])
    settle(lambda a: act(t, m, label, a, target_id=RIGHT if talent == PALM else None), pick)
    settle(lambda a: act(t, m, 'Prepare', a), pick)
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e.state.actors[LEFT].resources[FOCUS] == 1
    assert not any(c.display_name == label for c in e.legal_candidates())


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('failed', [False, True])
def test_thousand_hand_player_can_explicitly_choose_an_ally(tmp_path, mode, failed):
    c, t, m = fight(tmp_path, [TRAIN, WAR], left_score=50, right_score=14 if failed else 100, ally=[],
                    positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 2, 'y': 6}})
    c.set_controller_mode(m, actor_id=LEFT, controller_mode=mode)
    def friend(p):
        if p['context']['reaction_source_id'] == 'choice:needle.area_recipients':
            assert {LEFT, RIGHT, ALLY} <= {o['id'] for o in p['choice']['options']}
            return [ALLY]
        return pick(p)
    _, prompts = settle(lambda a: act(t, m, 'Thousand-Hand War Body', a), friend)
    e = reload(c, m)
    assert e.state.actors[ALLY].current_hp < 1000
    assert bears_mark(e.state.actors[ALLY], LEFT, 'Opened')
    assert any(x.condition_id.endswith('.reaction_denied') for x in e.state.actors[ALLY].conditions.values()) == failed
    assert e.state.actors[RIGHT].current_hp == 1000
    assert not bears_mark(e.state.actors[RIGHT], LEFT, 'Opened')
    assert e.state.actors[LEFT].current_hp == 1000
    assert e.state.actors[LEFT].resources[FOCUS] == 0
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED']) == 1


@pytest.mark.parametrize('automatic_mover', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_flowing_adept_off_turn_owner_answers_after_opportunity_attack(tmp_path, automatic_mover, failed):
    c, t, m = fight(tmp_path, [TRAIN, FLOW, ADEPT], left_score=50,
                    right_score=14 if failed else 100, left_kit={'items': []},
                    prepare=[OPEN], prepare_costs=[(FOCUS, 1)], left_attack_bonus=100)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    turn(t, m, RIGHT)
    original = reload(c, m)
    base_dc = next(a.parameters['typed']['numbers']['save_dc'] for a in original.action_catalog.values()
                   if a.display_name == 'Shove: Prone')
    state = t.state(m)
    move = next(o for o in state['menu']['moves'] if o['destination'] == {'x': 5, 'y': 6})
    if automatic_mover:
        from combat.gate4_adapters import ManualControllerAdapter
        real = c.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (move['candidate_id'], ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        c.controller = Controller()
        c.set_controller_mode(m, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
        send = lambda a: t.auto_step(m, t.state(m)['last_sequence'], a)
    else:
        send = lambda a: t.act(m, move['candidate_id'], state['menu']['decision_id'],
                              state['menu']['state_version'], state['last_sequence'], a)
    _, prompts = resolve(send, {'choice:needle.flowing_combination': ['Shove: Prone'],
                                'choice:needle.iron_fist_step': ['cell:3,7']})
    e = reload(c, m)
    assert e.state.current_actor_id == RIGHT
    assert any(v.event_type == 'ATTACK_ROLLED' and v.actor_id == LEFT
               and 'opportunity' in v.source_definition_id for v in e.events)
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.flowing_combination')
    assert 'Grapple' in str(choice) and 'Prone' in str(choice)
    save = next(v for v in e.events if v.event_type == 'SAVE_ROLLED'
                and v.source_definition_id == 'passive:TAL_IRON_FIST_FLOWING_COMBINATION')
    assert save.payload['dc'] == base_dc + 1
    assert e.state.actors[LEFT].resources[FOCUS] == 1
    steps = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.iron_fist_step']
    assert bool(steps) == failed
    assert e.state.actors[LEFT].position.y == (7 if failed else 6)



def test_thousand_hand_automatic_uses_only_currently_perceived_recipients(tmp_path):
    from combat.target_knowledge import located
    witness = 'actor:factory.auto111-witness'
    c, t, m = fight(tmp_path, [TRAIN, WAR], left_score=50, ally=[], extra_witness=True,
                    positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 2, 'y': 6}},
                    cause_target='SELF', cause=[{'type': 'condition', 'condition': 'invisible',
                                                'applies_to': 'self', 'duration': 'one_minute'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a), pick)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert not located(e, e.state.actors[LEFT], e.state.actors[RIGHT])
    assert located(e, e.state.actors[LEFT], e.state.actors[witness])
    settle(action_sender(c, t, m, 'Thousand-Hand War Body', ai=True), pick)
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp == 1000
    assert not bears_mark(e.state.actors[RIGHT], LEFT, 'Opened')
    assert e.state.actors[witness].current_hp < 1000
    assert bears_mark(e.state.actors[witness], LEFT, 'Opened')
    assert e.state.actors[ALLY].current_hp == 1000
