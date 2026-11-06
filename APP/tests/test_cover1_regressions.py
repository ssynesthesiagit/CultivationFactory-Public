"""COVER1 interactions: local zone geometry and refined armour possession."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from combat import armour
from combat.factory_compiler import _zone_spec
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from tests.test_attack_abilities import ROOT, sheet, table_fixture
from tests.test_gravity_canvas import _canvas, _row


@pytest.mark.parametrize('source,size', [('test:small-zone', 20), ('test:other-zone', 30)])
def test_zone_effect_area_is_independent_of_the_actions_outer_area(source, size):
    row = deepcopy(_row(_canvas()[0], 'World as Canvas'))
    row['source_definition_id'] = source
    typed = row['parameters']['typed']
    typed['source'] = source
    typed['area'] = {'shape': 'sphere', 'size_ft': 60}
    typed['effects'] = [{'type': 'zone', 'area': {'shape': 'sphere', 'size_ft': size}}]
    before = deepcopy(row)
    zone = _zone_spec(ActionDefinition.model_validate(row), {'name': 'Example zone'}, {})
    assert zone['size_ft'] == size
    assert row == before


@pytest.mark.parametrize('refinement,expected,worn', [(1, 20, False), (3, 21, True)])
def test_refinement_only_improves_the_armour_actually_worn_after_table_reload(tmp_path, refinement, expected, worn):
    owner = sheet(training=False)
    owner['ability_scores_and_statistics']['armor_class'] = {'base_value': 20}
    owner['equipment'] = [{'starting_kit': {'items': [], 'resolved_treasure_armor': {
        'name': 'Refined Plate', 'chassis': armour.catalog()['tianxia.mortal.armor.imperial_plate_battle_dress'],
        'refinement_bonus': refinement, 'enhancements': [],
    }}}]
    combat, table, match, actor, _ = table_fixture(tmp_path, owner)
    state = table.state(match)
    result = table.act(match, state['menu']['end_turn'], state['menu']['decision_id'],
                       state['menu']['state_version'], state['last_sequence'], [])
    assert result['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(match)
    assert fresh.engine.state.actors[actor].armor_class == expected
    kit = owner['equipment'][0]['starting_kit']
    assert (armour.wearing(20, kit, {'DEX': 4}) is not None) is worn
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'


def test_a_refined_shield_still_adds_both_its_shield_and_refinement_bonuses():
    kit = {'items': [], 'resolved_treasure_armor': {
        'chassis': armour.catalog()['tianxia.mortal.armor.shield'], 'refinement_bonus': 2,
    }}
    assert armour.armor_class(20, kit, {'DEX': 4}) == 24


@pytest.mark.parametrize('expiry', ['UNTIL_REMOVED', 'START_OF_SLOT_AT:601:0'])
@pytest.mark.parametrize('owns', [True, False])
@pytest.mark.parametrize('incoming', ['START_OF_MARKER_NEXT_TURN', 'START_OF_SLOT_AT:12:0'])
def test_crimson_refresh_recognizes_counted_and_legacy_deadlines_only_for_its_owner(expiry, owns, incoming):
    from combat.ext.blood_riders import THREAD, preserve_extended_thread
    from combat.typed_executor import mark_condition_id

    actor = SimpleNamespace(entity_id='actor:thread-owner', resources={})
    mark = SimpleNamespace(condition_id=mark_condition_id(THREAD, actor.entity_id), expires_on=expiry)
    target = SimpleNamespace(entity_id='actor:thread-target', active=True, conditions={'retained-thread': mark})
    engine = SimpleNamespace(typed_passive_rows={actor.entity_id: [{'block': 'blood_rider', 'kind': 'crimson_mark'}] if owns else []})
    # Any application of the Thread reaches Crimson Mark's own extension offer now, so the fake context
    # carries the damage_cache a real typed_executor.Context always has; no CP pool, so nothing is paid.
    ctx = SimpleNamespace(engine=engine, actor=actor, source='test:refresh', typed={'source': 'test:refresh'},
                          damage_cache={})
    before = dict(target.conditions)
    result = preserve_extended_thread(ctx, {'mark': THREAD}, target, incoming, {})
    assert result is (True if owns else None)
    assert target.conditions == before
    assert mark.expires_on == expiry


@pytest.mark.parametrize('expiry,duration', [
    ('START_OF_SLOT_AT:11:0', {'kind': 'minutes', 'amount': 1}),
    ('START_OF_SLOT_AT:12:0', {'kind': 'minutes', 'amount': 1}),
    ('UNTIL_REMOVED', {'kind': 'hours', 'amount': 1}),
])
def test_crimson_does_not_block_ordinary_refresh_or_a_paid_legacy_extension(expiry, duration):
    from combat.ext.blood_riders import THREAD, preserve_extended_thread
    from combat.typed_executor import mark_condition_id

    actor = SimpleNamespace(entity_id='actor:thread-owner')
    mark = SimpleNamespace(condition_id=mark_condition_id(THREAD, actor.entity_id), expires_on=expiry)
    target = SimpleNamespace(conditions={'thread': mark})
    engine = SimpleNamespace(typed_passive_rows={actor.entity_id: [{'block': 'blood_rider', 'kind': 'crimson_mark'}]})
    ctx = SimpleNamespace(engine=engine, actor=actor)
    assert preserve_extended_thread(ctx, {'mark': THREAD, 'duration': duration}, target,
                                    'START_OF_SLOT_AT:12:0', {}) is None
