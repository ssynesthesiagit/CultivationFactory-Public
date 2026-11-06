"""T13: compiled actions, actual inventory consumers, table commit and cold replay.

No live model calls. Explicit sealed inventory/action metadata supplies physical
weapon/tool facts; an actor mark or skill label alone does not supply them.
"""
import json
import pytest
from combat.canonical import canonical_sha256
from combat.ext.blacksmith_forge import mark_count, mark_row
from tests.worker2_support import fixture, reload, turn, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import seal, press
from tests.test_a2_blacksmith_second_pass import QUENCH, STEADY, die


def setup(margin=2, armor=False, tool=False):
    def build(bundles):
        for b in bundles:
            seal(b, 'Item strike', [{'type': 'attack', 'attack_kind': 'weapon', 'on_hit': [
                {'type': 'damage', 'flat': 10, 'damage_types': ['slashing'], 'applies_to': 'target'}]}], target='ANY_CREATURE')
            strike = b['action_catalog'][-1]
            strike['parameters']['typed']['numbers']['attack_bonus'] = 4 + margin if armor else 4 - margin
            strike['parameters']['typed']['weapon'] = {'damage_type': 'slashing'}
            strike['parameters']['typed']['inventory_key'] = 'sword'
            strike['parameters']['expected_damage'] = 10
            carry = b.setdefault('carrying', {})
            carry['items'] = [
                {'key': 'sword', 'item_id': 'test:sword', 'name': 'Test sword', 'quantity': 1,
                 'worn': False, 'weapon_action': strike['source_definition_id'], 'weight_lb': '0'},
                {'key': 'armor', 'item_id': 'test:armor', 'name': 'Test armor', 'quantity': 1,
                 'worn': True, 'category': 'light', 'weight_lb': '0'},
                {'key': 'tool', 'item_id': 'test:tool', 'name': 'Test smith tools', 'quantity': 1,
                 'worn': False, 'weight_lb': '0'},
                {'key': 'other', 'item_id': 'test:other_tool', 'name': 'Other tools', 'quantity': 1,
                 'worn': False, 'weight_lb': '0'},
            ]
            for name, key in [('Tool check', 'tool'), ('Unbound check', None), ('Wrong tool check', 'other')]:
                seal(b, name, [{'type': 'skill_check', 'ability': 'INT', 'skill': "Smith's Tools",
                               **({'tool_item_key': key} if key else {})}], target='ANY_CREATURE')
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    return build


def select(combat, table, mid, owner=ALLY, key='sword', tool=False):
    return press(combat, table, mid, 'Set current workpiece: a carried tool' if tool else 'Set current workpiece: a carried item',
        picks={'choice:needle.blacksmith_item': [json.dumps([owner, key])]})


def marks(e, smith=OWNER, owner=ALLY, key='sword'):
    return mark_count(e.state.actors[owner], smith, item_key=key)


def hammer(combat, table, mid, timing=None, destination=None, oa_use=False):
    return press(combat, table, mid, 'Hammer the Mark', picks={
        'choice:needle.blacksmith_step_timing': [timing] if timing else None,
        'choice:needle.blacksmith_step': [destination] if destination else None,
        'reaction:typed.opportunity_attack': 'first' if oa_use else None})


@pytest.mark.parametrize('margin,use', [(2, True), (3, True), (2, False)])
@pytest.mark.parametrize('armor', [False, True])
def test_other_carrier_attack_outcomes(tmp_path, monkeypatch, margin, use, armor):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(margin, armor), ally_position={'x': 4, 'y': 6})
    key = 'armor' if armor else 'sword'
    select(combat, table, mid, key=key)
    assert marks(reload(tmp_path, mid), key=key) == 0  # selection cannot create marks
    hammer(combat, table, mid)
    e = reload(tmp_path, mid)
    assert marks(e, key=key) == 1
    turn(table, mid, FOE if armor else ALLY)
    target = ALLY if armor else FOE
    before = reload(tmp_path, mid).state.actors[target].current_hp
    prompts = press(combat, table, mid, 'Item strike', target, picks={'choice:needle.blacksmith_quench': ['quench'] if use else None})
    e = reload(tmp_path, mid)
    accepted = use and margin <= 2
    assert bool(prompts) == (margin <= 2)
    assert marks(e, key=key) == (0 if accepted else 1)
    assert e.state.actors[OWNER].reaction_available == (not accepted)
    assert (e.state.actors[target].current_hp < before) == (not accepted if armor else accepted)
    assert sum(x.event_type == 'REACTION_RESOLVED' and x.source_definition_id == QUENCH for x in e.events) == int(accepted)


@pytest.mark.parametrize('name,use', [('Tool check', True), ('Tool check', False), ('Unbound check', True), ('Wrong tool check', True)])
def test_exact_native_tool_check(tmp_path, name, use):
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup())
    select(combat, table, mid, key='tool', tool=True)
    hammer(combat, table, mid)
    turn(table, mid, ALLY)
    prompts = press(combat, table, mid, name, ALLY, picks={'choice:needle.blacksmith_quench': ['quench'] if use else None})
    e = reload(tmp_path, mid)
    accepted = name == 'Tool check' and use
    assert bool(prompts) == (name == 'Tool check')
    assert marks(e, key='tool') == (0 if accepted else 1)
    bonuses = [x for x in e.events if x.event_type == 'D20_REWRITTEN' and x.source_definition_id == QUENCH]
    assert len(bonuses) == int(accepted)
    if accepted:
        assert bonuses[0].payload['bonus'] == e.state.actors[OWNER].proficiency_bonus


@pytest.mark.parametrize('timing', ['before', 'after'])
def test_hammer_native_step_once(tmp_path, timing):
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=setup())
    select(combat, table, mid)
    e = reload(tmp_path, mid)
    before = e.state.actors[OWNER].movement_remaining_ft
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    hammer(combat, table, mid, timing, cell_id(Position(x=3, y=5)))
    e = reload(tmp_path, mid)
    assert (e.state.actors[OWNER].position.x, e.state.actors[OWNER].position.y) == (3, 5)
    assert e.state.actors[OWNER].movement_remaining_ft == before
    assert marks(e) == 1
    assert len([x for x in e.events if x.event_type == 'MOVEMENT_COMMITTED' and x.source_definition_id == STEADY]) == 1


def test_hammer_exempts_only_current_workpiece_carrier(tmp_path, monkeypatch):
    die(monkeypatch)
    other = FOE + '1'
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 6, 'y': 6},
                 FOE: {'x': 4, 'y': 6}, other: {'x': 4, 'y': 7}}
    def build(bundles):
        setup()(bundles)
        for b in bundles:
            strike = next(a for a in b['action_catalog'] if a['display_name'] == 'Item strike')
            # A real compiled weapon/opportunity interface rather than a label.
            strike['parameters']['typed']['range_ft'] = 5
            strike['parameters']['typed']['weapon']['melee'] = True
            strike['range_ft'] = 5
            b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [STEADY], extra_foes=1, positions=positions, bundle_transform=build)
    select(combat, table, mid, owner=FOE)
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    prompts = hammer(combat, table, mid, 'after', cell_id(Position(x=2, y=6)), oa_use=True)
    e = reload(tmp_path, mid)
    opportunities = [p for p in prompts if 'LEAVE_REACH' in p['context']['checkpoint']]
    assert {p['context']['reactor_id'] for p in opportunities} == {other}
    assert e.state.actors[FOE].reaction_available
    assert not e.state.actors[other].reaction_available
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == other and ev.target_ids == (OWNER,) for ev in e.events)
    assert marks(e, owner=FOE) == 1
    assert e.state.actors[OWNER].position == Position(x=2, y=6)


@pytest.mark.parametrize('automatic', [False, True])
def test_two_smiths_preserve_independent_marks(tmp_path, monkeypatch, automatic):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], ally_talents=[QUENCH], ask=not automatic,
        bundle_transform=setup(), foe_position={'x': 4, 'y': 5})
    select(combat, table, mid, owner=FOE)
    hammer(combat, table, mid)
    turn(table, mid, ALLY)
    select(combat, table, mid, owner=FOE)
    hammer(combat, table, mid)
    e = reload(tmp_path, mid)
    assert marks(e, owner=FOE) == marks(e, smith=ALLY, owner=FOE) == 1
    turn(table, mid, FOE)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    # A defensive armor correction would be helpful to the AI; this weapon
    # correction attacks their own ally, so automatic smiths must decline it.
    prompts = press(combat, table, mid, 'Item strike', OWNER,
        picks={'choice:needle.blacksmith_quench': (None, ['quench'])})
    e = reload(tmp_path, mid)
    if automatic:
        assert marks(e, owner=FOE) == marks(e, smith=ALLY, owner=FOE) == 1
        assert e.state.actors[OWNER].reaction_available and e.state.actors[ALLY].reaction_available
    else:
        assert len(prompts) == 2
        decliner = prompts[0]['context']['reactor_id']
        accepter = prompts[1]['context']['reactor_id']
        assert {decliner, accepter} == {OWNER, ALLY}
        assert marks(e, smith=decliner, owner=FOE) == 1
        assert marks(e, smith=accepter, owner=FOE) == 0
        assert e.state.actors[decliner].reaction_available
        assert not e.state.actors[accepter].reaction_available


def test_ai_smith_corrects_allied_carrier_without_player_prompt(tmp_path, monkeypatch):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(), ask=False)
    select(combat, table, mid)
    hammer(combat, table, mid)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = press(combat, table, mid, 'Item strike', FOE)
    e = reload(tmp_path, mid)
    assert not prompts
    assert marks(e) == 0 and not e.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('talent', [STEADY, QUENCH])
def test_wrong_item_no_owner_and_preview_are_inert(tmp_path, monkeypatch, talent):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [talent], bundle_transform=setup())
    select(combat, table, mid, key='armor')
    hammer(combat, table, mid)
    e = reload(tmp_path, mid)
    before = e.state.model_dump(mode='json')
    e.legal_candidates(); e.legal_candidates()
    assert e.state.model_dump(mode='json') == before
    turn(table, mid, ALLY)
    assert not press(combat, table, mid, 'Item strike', FOE)
    e = reload(tmp_path, mid)
    assert marks(e, key='armor') == 1 and e.state.actors[OWNER].reaction_available


def test_once_per_round_is_smith_owned_across_items_and_turn_reset(tmp_path, monkeypatch):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup())
    select(combat, table, mid)
    hammer(combat, table, mid)
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    select(combat, table, mid, key='tool', tool=True)
    hammer(combat, table, mid)
    e = reload(tmp_path, mid)
    sword_deadlines = mark_row(e.state.actors[ALLY], OWNER, item_key='sword').data['deadlines']
    tool_deadlines = mark_row(e.state.actors[ALLY], OWNER, item_key='tool').data['deadlines']
    assert sword_deadlines != tool_deadlines
    turn(table, mid, ALLY)
    press(combat, table, mid, 'Item strike', FOE, picks={'choice:needle.blacksmith_quench': ['quench']})
    assert not reload(tmp_path, mid).state.actors[OWNER].reaction_available
    # A second consumer has resources on another item but cannot pay again.
    assert not press(combat, table, mid, 'Tool check', ALLY)
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].reaction_available
    assert not press(combat, table, mid, 'Tool check', ALLY)
    e = reload(tmp_path, mid)
    assert marks(e, key='tool') == 1 and e.state.actors[OWNER].reaction_available
    assert mark_row(e.state.actors[ALLY], OWNER, item_key='tool').data['deadlines'] == tool_deadlines


@pytest.mark.parametrize('use', [True, False])
def test_actual_marked_shield_wearer(tmp_path, monkeypatch, use):
    die(monkeypatch)
    def build(bundles):
        setup(armor=True)(bundles)
        for b in bundles:
            b['carrying']['items'].append({'key': 'shield', 'name': 'Test shield', 'item_id': 'test:shield',
                'quantity': 1, 'worn': False, 'shield': 1, 'weight_lb': '0'})
            b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build)
    select(combat, table, mid, key='shield'); hammer(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp
    press(combat, table, mid, 'Item strike', ALLY, picks={'choice:needle.blacksmith_quench': ['quench'] if use else None})
    e = reload(tmp_path, mid)
    assert marks(e, key='shield') == (0 if use else 1)
    assert (e.state.actors[ALLY].current_hp < before) == (not use)


def test_naked_actor_mark_does_not_prove_an_allied_item(tmp_path, monkeypatch):
    die(monkeypatch)
    def build(bundles):
        setup()(bundles)
        seal(bundles[0], 'Actor-only mark', [{'type': 'mark', 'mark': 'Forge Mark', 'applies_to': 'target'}], target='ANY_CREATURE')
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build)
    select(combat, table, mid)
    press(combat, table, mid, 'Actor-only mark', ALLY)
    turn(table, mid, ALLY)
    assert not press(combat, table, mid, 'Item strike', FOE)
    e = reload(tmp_path, mid)
    assert mark_count(e.state.actors[ALLY], OWNER) == 1
    assert marks(e) == 0 and e.state.actors[OWNER].reaction_available


def test_item_mark_deadlines_expire_independently():
    from tests.test_auto17_blacksmith import _engine, _bundle, ME, ALLY as OTHER
    from combat.ext.blacksmith_forge import set_marks
    from combat.ext.effect_durations import sweep
    e = _engine(_bundle([]))
    smith, holder = e.state.actors[ME], e.state.actors[OTHER]
    set_marks(e, smith, holder, 1, 'test:work', item_key='sword')
    e.state.round_number += 5
    set_marks(e, smith, holder, 1, 'test:work', item_key='sword')
    set_marks(e, smith, holder, 1, 'test:work', item_key='tool')
    e.state.round_number += 5
    sweep(e, holder, 'TEST')
    assert mark_count(holder, ME, item_key='sword') == 1
    assert mark_count(holder, ME, item_key='tool') == 1
    e.state.round_number += 5
    sweep(e, holder, 'TEST')
    assert mark_count(holder, ME, item_key='sword') == mark_count(holder, ME, item_key='tool') == 0


def test_player_smith_is_asked_on_ai_carrier_turn(tmp_path, monkeypatch):
    from tests.worker2_support import settle
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(), ask=True)
    select(combat, table, mid); hammer(combat, table, mid)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, None, auto=True, picks={'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    assert any(p['context']['reactor_id'] == OWNER and p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts)
    assert marks(e) == 0 and not e.state.actors[OWNER].reaction_available


def test_ai_hammer_and_two_beat_remain_available(tmp_path):
    from tests.test_a2_blacksmith_second_pass import execute
    TWO = 'tianxia.talent.blacksmith.two_beat_temper'
    combat, table, mid = fixture(tmp_path, [STEADY, TWO], bundle_transform=setup(), ask=False)
    select(combat, table, mid, owner=OWNER)
    e = reload(tmp_path, mid)
    before = e.state.actors[OWNER].position
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    execute(combat, mid, 'Hammer the Mark')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].position != before
    assert marks(e, owner=OWNER) == 2
    assert len([ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == STEADY]) == 1


@pytest.mark.parametrize('armor', [False, True])
def test_native_other_carrier_corrections(tmp_path, monkeypatch, armor):
    die(monkeypatch)
    def build(bundles):
        setup(armor=armor)(bundles)
        for b in bundles:
            action = next(a for a in b['action_catalog'] if a['display_name'] == 'Item strike')
            action.update(resolution_kind='ATTACK', attack_bonus=6 if armor else 2,
                          damage={'count': 1, 'sides': 2, 'modifier': 9}, damage_type='SLASHING')
            action['parameters']['attack_kind'] = 'weapon'
            b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build)
    key = 'armor' if armor else 'sword'
    select(combat, table, mid, key=key); hammer(combat, table, mid)
    turn(table, mid, FOE if armor else ALLY)
    target = ALLY if armor else FOE
    before = reload(tmp_path, mid).state.actors[target].current_hp
    press(combat, table, mid, 'Item strike', target, picks={'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    assert marks(e, key=key) == 0 and not e.state.actors[OWNER].reaction_available
    assert (e.state.actors[target].current_hp < before) == (not armor)


def test_no_quench_owner_on_actual_marked_items(tmp_path, monkeypatch):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=setup())
    select(combat, table, mid); hammer(combat, table, mid)
    turn(table, mid, ALLY)
    assert not press(combat, table, mid, 'Item strike', FOE)
    turn(table, mid, OWNER)
    select(combat, table, mid, key='tool', tool=True); hammer(combat, table, mid)
    turn(table, mid, ALLY)
    assert not press(combat, table, mid, 'Tool check', ALLY)
    e = reload(tmp_path, mid)
    assert marks(e) == marks(e, key='tool') == 1
    assert e.state.actors[OWNER].reaction_available


def test_unarmed_packet_with_weapon_parent_is_not_weapon_use(tmp_path, monkeypatch):
    die(monkeypatch)
    def build(bundles):
        setup()(bundles)
        for b in bundles:
            strike = next(a for a in b['action_catalog'] if a['display_name'] == 'Item strike')
            strike['parameters']['typed']['effects'][0]['attack_kind'] = 'unarmed'
            b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build)
    select(combat, table, mid); hammer(combat, table, mid)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    assert not press(combat, table, mid, 'Item strike', FOE)
    e = reload(tmp_path, mid)
    assert e.state.actors[FOE].current_hp == before
    assert marks(e) == 1 and e.state.actors[OWNER].reaction_available


def test_tool_prompt_names_initiator_and_checked_creature(tmp_path):
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(), named=True, owner_pb=5)
    select(combat, table, mid, key='tool', tool=True); hammer(combat, table, mid)
    prompts = press(combat, table, mid, 'Tool check', ALLY,
                    picks={'choice:needle.blacksmith_quench': ['quench']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench')
    e = reload(tmp_path, mid)
    assert prompt['action'] == 'Tool check'
    assert prompt['trigger_actor'] == e.state.actors[OWNER].display_name
    assert prompt['affected'] == e.state.actors[ALLY].display_name
    assert prompt['reactor'] == e.state.actors[OWNER].display_name
    assert marks(e, key='tool') == 0
    assert e.state.actors[OWNER].proficiency_bonus != e.state.actors[ALLY].proficiency_bonus
    bonus = next(ev for ev in e.events if ev.event_type == 'D20_REWRITTEN' and ev.source_definition_id == QUENCH)
    assert bonus.payload['bonus'] == e.state.actors[OWNER].proficiency_bonus
