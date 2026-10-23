"""Native Palace regressions; synthetic hostile packets isolate save provenance.

These are combat importer/table tests, not proof of a public Perfected-stage
advancement producer or a GM source-classification input workflow.
"""
import json

import pytest

from combat.factory_compiler import compile_character
from combat.ext.taiyin_palace import STATE, PICK, HAZARDS, SOURCE, FOUNDATION
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import add_action, seal

NAME = 'Perfected — True Moon Yin Palace'


def game(tmp_path, *, stage='Perfected', allies=0, cl=5, score=8, foe_sheet=None):
    doc = sheet(['ICE_BASE_SHARD_NEEDLE', 'FIRE_BASE_IGNITE'], cl=cl, score=score,
                foundation={'foundation_id': FOUNDATION, 'stage': stage,
                    'resource': {'name': 'Lunar Yin Dew', 'resource_id': 'tianxia.resource.foundation.' + FOUNDATION,
                                 'maximum': 1, 'current': 0}})
    # Foundation acquisition comes from the imported sheet, not manually added effects.
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': stage,
                    'resource': {'name': 'Lunar Yin Dew', 'resource_id': 'tianxia.resource.foundation.' + FOUNDATION,
                                 'maximum': 1, 'current': 0}}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    for action in bundle['action_catalog']:
        typed = action.get('parameters', {}).get('typed', {})
        if typed.get('source') == SOURCE:
            # The export scrambles text: formulas as well as prose. Keep this
            # table fixture's signed CL + key input public-stable; native grant
            # folding, payment and persistence remain under test.
            for eff in typed.get('effects', []):
                if eff.get('type') == 'temp_hp':
                    eff['formula'] = 'text:your cultivation level + your path key ability modifier'
        if typed.get('source') in {'ICE_BASE_SHARD_NEEDLE', 'FIRE_BASE_IGNITE'}:
            action['attack_bonus'] = 100
            typed['attack_bonus'] = 100
            # Two real hit resolutions in one technique exercise the shared allowance.
            for eff in typed.get('effects', []):
                if eff.get('type') == 'attack':
                    eff['count'] = 2
    seal(bundle)

    def setup(bundles):
        # An unrelated Fire control should not depend on public-export
        # parsing of Ignite's menu variants (the native Ice hit is kept).
        add_action(bundles[0], 'Unrelated fire strikes', [
            {'type': 'attack', 'count': 2, 'attack_kind': 'ranged',
             'on_hit': [{'type': 'damage', 'weapon_damage': True, 'applies_to': 'target'}]}],
            typed={'sphere': 'tianxia.sphere.fire', 'attack_bonus': 100,
                   'weapon': {'damage': {'count': 1, 'sides': 4, 'modifier': 0},
                              'damage_type': 'FIRE', 'fixed_damage': 1},
                   'range_ft': 120, 'numbers': {'attack_bonus': 100}})
        packets = [('cold', [], 'cold'), ('necrotic', [], 'necrotic'),
                   ('fire', [], 'fire'), ('force', [], 'force'),
                   *[(tag, [tag], None) for tag in sorted(HAZARDS - {'damage:cold', 'cold'})],
                   ('generic fear', ['frightened'], None),
                   ('generic anti-healing', ['anti_healing'], None)]
        for b in bundles[1:3]:
            for name, tags, damage in packets:
                add_action(b, 'Pressure ' + name, [{'type': 'save', 'ability': 'con', 'dc': 1,
                    'applies_to': 'target', 'save_categories': tags,
                    'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': [damage], 'applies_to': 'target'}] if damage else [],
                    'on_success': []}])
        add_action(bundles[2], 'Sleep owner', [{'type': 'condition', 'condition': 'asleep',
                                             'applies_to': 'target'}])
        add_action(bundles[2], 'Piercing ward', [{'type': 'resistance', 'applies_to': 'self',
                   'damage_types': ['piercing'], 'duration': 'one_minute'}], target='SELF')
        add_action(bundles[0], 'Capacity check', [
            {'type': 'gain_resource', 'resource_id': 'resource:foundation.lunar_yin_dew',
             'flat': 1, 'applies_to': 'self'},
            {'type': 'gain_resource', 'resource_id': 'resource:foundation.lunar_yin_dew',
             'flat': 1, 'applies_to': 'self'}], target='SELF')
    return fixture(tmp_path, [], owner_bundle=bundle, extra_allies=allies, foe_sheet=foe_sheet,
                   battlefield={'stable_id': 'battlefield:palace-regression', 'display_name': 'Palace regression field',
                                'width_squares': 20, 'height_squares': 14,
                                'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []},
                   bundle_transform=setup, seed='MGR15PALACE')


def activate(combat, table, mid, selected=(OWNER, ALLY)):
    return settle(table, mid, candidate(combat, mid, NAME, target=OWNER).candidate_id,
                  choices={PICK: list(selected)})


def save_mode(combat, table, mid, target, packet, source=FOE):
    turn(table, mid, source)
    settle(table, mid, candidate(combat, mid, 'Pressure ' + packet, target=target).candidate_id)
    events = combat._load_session(mid).engine.events
    return next(e.payload['mode'] for e in reversed(events)
                if e.event_type == 'SAVE_ROLLED' and e.actor_id == target)


def test_native_selection_cost_persistence_and_single_signed_grant(tmp_path, monkeypatch):
    # Public exports scramble rulebook prose. Supply presentation-only text;
    # activation, costs, recipient choices and saves still use native mechanics.
    from combat import tabletop_service
    monkeypatch.setattr(tabletop_service, '_rules_texts', lambda: {SOURCE:
        '#### Perfected — True Moon Yin Palace\n'
        '**Effect:** True Moon Yin Palace protects chosen allies within 30 feet for 1 minute.\n'
        '**Cost:** Bonus Action; once per long rest.'})
    combat, table, mid = game(tmp_path, allies=1)
    prompts = activate(combat, table, mid, (ALLY,))
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == PICK)
    assert 'True Moon Yin Palace' in prompt['summary']
    assert 'chosen allies within 30 feet for 1 minute' in prompt['summary']
    assert prompt['choice']['cost'] == '1 use'
    assert ALLY in {option['id'] for option in prompt['choice']['options']}
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    field = next(c for c in owner.conditions.values() if c.condition_id == STATE)
    assert json.loads(field.data['chosen']) == [ALLY]
    assert field.expires_on.startswith('START_OF_SLOT_AT:')
    assert owner.temporary_hp == 4
    assert not owner.bonus_action_available
    assert len([e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.actor_id == OWNER]) == 1
    assert not [c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == NAME]
    assert save_mode(combat, table, mid, ALLY, 'cold') == 'ADVANTAGE'
    assert save_mode(combat, table, mid, OWNER, 'cold') == 'NORMAL'
    assert save_mode(combat, table, mid, 'actor:factory.worker2-ally3', 'cold') == 'NORMAL'
    reload(tmp_path, mid)


@pytest.mark.parametrize('packet', sorted(HAZARDS - {'damage:cold', 'cold'}))
def test_only_stilling_save_categories_require_hostility(tmp_path, packet):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    assert save_mode(combat, table, mid, OWNER, packet) == 'ADVANTAGE'
    expected = 'NORMAL' if packet in {'hostile_stilling_pressure', 'hostile_stillness'} else 'ADVANTAGE'
    assert save_mode(combat, table, mid, OWNER, packet, source=ALLY) == expected
    reload(tmp_path, mid)


@pytest.mark.parametrize('packet', ['necrotic', 'fire', 'force', 'generic fear', 'generic anti-healing'])
def test_unrelated_sources_do_not_qualify(tmp_path, packet):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    assert save_mode(combat, table, mid, OWNER, packet) == 'NORMAL'
    reload(tmp_path, mid)


def test_palace_expires_after_ten_native_rounds(tmp_path):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    start = reload(tmp_path, mid).state.round_number
    while combat._load_session(mid).engine.state.round_number < start + 10:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == STATE for c in engine.state.actors[OWNER].conditions.values())
    assert save_mode(combat, table, mid, ALLY, 'cold') == 'NORMAL'


@pytest.mark.parametrize('stage', ['Awakened', 'Integrated', 'Refined'])
def test_unperfected_import_has_no_palace_action(tmp_path, stage):
    combat, table, mid = game(tmp_path, stage=stage)
    engine = reload(tmp_path, mid)
    assert NAME not in {engine.action_catalog[c.source_definition_id].display_name
                        for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog}


def test_sleep_bars_activation(tmp_path):
    from combat.ext.taiyin_palace import conscious_activation

    combat, table, mid = game(tmp_path)
    offered = candidate(combat, mid, NAME, target=OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Sleep owner', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    # Sleeping actors may have their turn skipped. Query the real admission
    # guard against the previously offered action and the committed condition.
    owner = engine.state.actors[OWNER]
    assert any(c.condition_id == 'condition:typed.asleep' for c in owner.conditions.values())
    assert conscious_activation(engine, owner, offered, engine.action_catalog[offered.source_definition_id]) is False


def test_real_aligned_technique_gets_one_pb_and_unrelated_fire_gets_none(tmp_path):
    combat, table, mid = game(tmp_path)
    # Shard Needle's native defense-aware type choice now selects Cold, one
    # of the actual printed choices; no test installs alignment metadata.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Piercing ward', target=FOE).candidate_id)
    turn(table, mid, OWNER)
    activate(combat, table, mid)
    before = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id,
           choices={'choice:fracture_response': None})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events[before:] if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert len(packets) == 2  # PB joins the first of the two hits
    assert engine.state.actors[OWNER].turn_flags.get('true_moon_yin_palace_hit') == 1
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    before = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, 'Unrelated fire strikes', target=FOE).candidate_id)
    packets = [e for e in reload(tmp_path, mid).events[before:]
               if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert [e.payload['hp_damage'] for e in packets] == [1, 1]
    assert not reload(tmp_path, mid).state.actors[OWNER].turn_flags.get('true_moon_yin_palace_hit')


def test_native_boundary_exit_and_owner_movement_reenter_the_selected_ally(tmp_path):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid, (ALLY,))
    turn(table, mid, ALLY)

    def move_to(x, y):
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination and (c.destination.x, c.destination.y) == (x, y))
        settle(table, mid, move.candidate_id)

    # At 30 feet, then just beyond the boundary, through committed movement.
    move_to(9, 6)
    assert save_mode(combat, table, mid, ALLY, 'cold') == 'ADVANTAGE'
    turn(table, mid, ALLY)
    move_to(10, 6)
    assert save_mode(combat, table, mid, ALLY, 'cold') == 'NORMAL'
    # The Palace travels with its owner; selected recipients are not sticky buffs.
    turn(table, mid, OWNER)
    move_to(4, 6)
    assert save_mode(combat, table, mid, ALLY, 'cold') == 'ADVANTAGE'
    reload(tmp_path, mid)


def test_dew_capacity_stays_one_through_native_gain_events(tmp_path):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    pool = 'resource:foundation.lunar_yin_dew'
    assert owner.resource_maximums[pool] == 1
    # This is a capacity check, not an invented Palace Dew generator.
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.payload.get('resource_id') == pool]
    settle(table, mid, candidate(combat, mid, 'Capacity check', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool] == 1
    assert engine.state.actors[OWNER].resource_maximums[pool] == 1
    assert [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
            and e.payload.get('resource_id') == pool]


def test_signed_zero_boundary_does_not_grant_a_positive_pool(tmp_path):
    combat, table, mid = game(tmp_path, cl=5, score=1)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 0
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.actor_id == OWNER]
    assert len(grants) <= 1
    assert all(e.payload['offered'] == 0 for e in grants)
