"""Native Palace regressions; synthetic hostile packets isolate save provenance.

These are combat importer/table tests, not proof of a public Perfected-stage
advancement producer or a GM source-classification input workflow.
"""
import json

import pytest

from combat.ext.taiyin_palace import STATE, PICK, HAZARDS, SOURCE, FOUNDATION
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, turn

NAME = 'Perfected — True Moon Yin Palace'


from tests.palace_support import game, activate, save_mode


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
    # The shipped id is choice:needle.fracture_response (combat/ext/ice_fracture.py). None declines the
    # Fracture Mark response, so only the native PB-on-first-hit path is exercised here.
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id,
           choices={'choice:needle.fracture_response': None})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events[before:] if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert len(packets) == 2  # PB joins the first of the two hits
    # Exact PB arithmetic is pinned with fixed damage in test_mgr_t15_palace_hit_mitigation.py;
    # here the first packet must deal damage and agree with its own HP drop.
    first = packets[0].payload
    assert first['hp_damage'] >= 1
    assert first['hp_damage'] == first['hp_before'] - first['remaining_hp']
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
    # CL 5 + a -5 key modifier is 0: the grant is still recorded once, offering nothing.
    assert len(grants) == 1
    assert grants[0].payload['offered'] == 0
    assert grants[0].payload['after'] == 0
