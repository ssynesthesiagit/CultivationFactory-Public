"""Native table transactions for the Mercurial progression; no model or GUI."""
import pytest
from combat.ext import mgr_reserve_mercurial_cultivator_mercurial_qi as m
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE
from tests.h1_support import sheet
from tests.mgr_mercurial_support import source_candidate


def features(cl):
    return [m.PREFIX + name for name, minimum in m.LEVELS.items() if minimum <= cl]


@pytest.mark.parametrize('cl,expected', [(2, 0), (3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_owned_progression_and_default_inert(tmp_path, cl, expected):
    combat, table, mid = fixture(tmp_path, features(cl), cl=cl)
    engine = reload(tmp_path, mid)
    rows = [r for r in engine.typed_passive_rows[OWNER] if r.get('block') == m.BLOCK]
    assert len(rows) == expected
    assert not any(r.get('block') == m.BLOCK for r in engine.typed_passive_rows[FOE])
    assert not any('.mercurial.' in aid for aid in engine.state.actors[FOE].action_ids)
    for label, level in (('Liquid Form', 6), ('Quicksilver Step', 14), ('Prima Materia', 18)):
        assert sum(a.display_name == label for a in engine.action_catalog.values() if a.owner_id == OWNER) == int(cl >= level)


def test_reviewed_mechanics_cover_all_five_native_records_and_turn_clocks(tmp_path):
    import json
    from pathlib import Path
    root = Path(__file__).parents[1]
    reviewed = json.loads((root / 'authority/typed_mechanics/reviewed_final.d/mgr_mercurial_cultivator.json').read_text())['mechanics']
    assert {m.PREFIX + name for name in m.LEVELS} <= set(reviewed)

    combat, table, mid = fixture(tmp_path, features(18), cl=18)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    turn_stamp = m.stamp(engine)
    assert turn_stamp == f'{engine.state.round_number}:{engine.state.current_slot_index}:{OWNER}'
    actor.turn_flags['_round_mercurial_step'] = turn_stamp
    actor.turn_flags['_round_mercurial_liquid_free'] = engine.state.round_number
    engine.state.current_slot_index += 1
    assert actor.turn_flags['_round_mercurial_step'] != m.stamp(engine)
    assert actor.turn_flags['_round_mercurial_liquid_free'] == engine.state.round_number
    engine.state.round_number += 1
    assert actor.turn_flags['_round_mercurial_liquid_free'] != engine.state.round_number


def test_secondary_qi_effective_level_does_not_borrow_body_progression(tmp_path):
    from combat.factory_compiler import compile_character
    document = sheet(features(18), cl=18)
    document['path_and_subpath']['paths'] = [
        {'path_id': 'tianxia.path.body_refining', 'effective_cl': 18, 'key_ability': 'CON'},
        {'path_id': 'tianxia.path.qi_cultivation', 'effective_cl': 3, 'key_ability': 'INT'}]
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, features(18), cl=18, owner_bundle=bundle)
    engine = reload(tmp_path, mid)
    rows = [r for r in engine.typed_passive_rows[OWNER] if r.get('block') == m.BLOCK]
    assert [r['kind'] for r in rows] == ['mercurial_qi']
    assert rows[0]['numbers']['cl'] == 3 and rows[0]['numbers']['pb'] == 2
    assert not any('.mercurial.' in aid for aid in engine.state.actors[OWNER].action_ids)


def test_liquid_form_paid_table_commit_cold_reload_and_expiry(tmp_path):
    combat, table, mid = fixture(tmp_path, features(6), cl=6)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[m.QI]
    settle(table, mid, candidate(combat, mid, 'Liquid Form').candidate_id)
    engine = reload(tmp_path, mid)
    assert m.held(engine.state.actors[OWNER], 'liquid_form')
    assert engine.state.actors[OWNER].resources[m.QI] == before - 2
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert not m.held(reload(tmp_path, mid).state.actors[OWNER], 'liquid_form')


def test_prima_payment_discount_and_once_scene_survive_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, features(18), cl=18)
    initial = reload(tmp_path, mid).state.actors[OWNER].resources[m.QI]
    settle(table, mid, candidate(combat, mid, 'Prima Materia').candidate_id)
    engine = reload(tmp_path, mid)
    assert m.held(engine.state.actors[OWNER], 'prima_materia')
    assert engine.state.actors[OWNER].resources[m.QI] == initial - 8
    from combat.typed_reactions import additional_defenses
    rows = additional_defenses(engine, engine.state.actors[OWNER], 'FIRE', None, FOE)
    assert any(r.get('feature_id') == m.PREFIX + 'prima_materia' and r['kind'] == 'resistance' for r in rows)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert not any(engine.action_catalog[c.source_definition_id].display_name == 'Prima Materia'
                   for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    settle(table, mid, candidate(combat, mid, 'Liquid Form').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[m.QI] == initial - 8


def test_quicksilver_step_landing_payment_arrival_and_replay(tmp_path):
    combat, table, mid = fixture(tmp_path, features(14), cl=14)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[m.QI]
    c = candidate(combat, mid, 'Quicksilver Step')
    prompts = settle(table, mid, c.candidate_id, choices={
        'choice:needle.teleport_destination': 'first', 'choice:needle.mercurial.arrival': ['temporary_hp']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[m.QI] == before - 4
    assert actor.temporary_hp == actor.proficiency_bonus
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mercurial.arrival' for p in prompts)


def test_transmutation_real_qi_sphere_attack_cost_tell_and_native_damage(tmp_path):
    from tests.worker2_support import ALLY
    combat, table, mid = fixture(tmp_path, [*features(3), 'FIRE_BASE_IGNITE'],
        ally_talents=['tianxia.path.qi_cultivation.feature.qi_sensing'], cl=3, seed='MERCURIAL-FIRE')
    before = reload(tmp_path, mid).state.actors[OWNER].resources[m.QI]
    prompts = settle(table, mid, source_candidate(combat, mid, 'FIRE_BASE_IGNITE', FOE).candidate_id,
        choices={'choice:needle.mercurial.transmute': ['COLD'], 'choice:needle.mercurial.tell': ['Frost']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[m.QI] == before - 1
    assert m.held(engine.state.actors[OWNER], 'tell').data['expression'] == 'Frost'
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mercurial.transmute' for p in prompts)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert damage and damage[0].payload['damage_type'] == 'COLD'
    perceived = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(ALLY,), include_menu=False)['fog_perception']
    assert set(perceived) == {ALLY}
    assert any('Quicksilver Tell:' in row['details'].get('text', '') and 'frost' in row['details']['text']
               for row in perceived[ALLY]['information'])


@pytest.mark.parametrize('defender_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_mercurial_reaction_before_real_damage_and_assimilation(tmp_path, defender_mode):
    combat, table, mid = fixture(tmp_path, [], ally_talents=features(10),
        foe_sheet=sheet(['FIRE_BASE_IGNITE'], cl=10),
        cl=10, seed='MERCURIAL-ADAPT')
    from tests.worker2_support import ALLY
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=defender_mode)
    before = reload(tmp_path, mid).state.actors[ALLY].resources[m.QI]
    prompts = settle(table, mid, source_candidate(combat, mid, 'FIRE_BASE_IGNITE', ALLY).candidate_id,
        choices={'choice:needle.mercurial.adapt': ['FIRE'], 'choice:needle.mercurial.reposition': None})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ALLY]
    assert actor.resources[m.QI] == before - 3
    assert not actor.reaction_available
    assert m.held(actor, 'adaptation').data['damage_type'] == 'FIRE'
    assert m.held(actor, 'assimilated').data['source_kind'] == 'Sphere'
    assert m.held(actor, 'assimilated').data['source_cl'] == 10
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mercurial.adapt' for p in prompts) == (defender_mode == 'MANUAL')
    perceived = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(ALLY,), include_menu=False)['fog_perception']
    assert set(perceived) == {ALLY}
    learned = [r for r in perceived[ALLY]['information'] if r['source_id'] == m.PREFIX + 'mercurial_adaptation']
    assert len(learned) == 1
    assert set(learned[0]['details']) == {'text'}
    assert 'Source Cultivation Level was 10' in learned[0]['details']['text']
    assert 'Sphere-based' in learned[0]['details']['text']
    other = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(OWNER,), include_menu=False)['fog_perception']
    assert not any(r.get('source_id') == m.PREFIX + 'mercurial_adaptation' for r in other[OWNER].get('information', ()))


@pytest.mark.parametrize('accept', [True, False])
@pytest.mark.parametrize('ask', [True, False])
def test_quicksilver_companion_owns_consent_and_extra_qi(tmp_path, accept, ask):
    from tests.worker2_support import ALLY
    combat, table, mid = fixture(tmp_path, features(14), cl=14, ask=ask)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[m.QI]
    prompts = settle(table, mid, candidate(combat, mid, 'Quicksilver Step').candidate_id, choices={
        'choice:needle.teleport_destination': 'first', 'choice:needle.mercurial.companion': [ALLY],
        'choice:willing.consent': ['accept' if accept else 'refuse'],
        'choice:needle.mercurial.companion_landing': 'first',
        'choice:needle.mercurial.arrival': ['temporary_hp']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[m.QI] == before - 4 - (2 if accept else 0)
    assert any(p['context']['reactor_id'] == ALLY for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent')
    carried = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY and e.payload.get('teleport')]
    assert bool(carried) == accept
    if accept:
        assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[ALLY]) <= 5


def test_liquid_crosses_creature_space_without_terrain_surcharge_or_later_oa(tmp_path):
    arena = {'stable_id': 'battlefield:mercurial-corridor', 'width_squares': 10, 'height_squares': 8,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': [{'terrain_type': 'BLOCKED',
        'cells': [{'x': x, 'y': y} for x in range(10) for y in range(8) if y != 6]}]}
    combat, table, mid = fixture(tmp_path, features(6), cl=6, battlefield=arena,
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Liquid Form').candidate_id)
    engine = combat._load_session(mid).engine
    moves = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination]
    assert not any((c.destination.x, c.destination.y) == (4, 6) for c in moves)
    move = next(c for c in moves if (c.destination.x, c.destination.y) == (6, 6))
    assert move.movement_cost_ft == 15
    assert any((p.x, p.y) == (4, 6) for p in move.canonical_path)
    prompts = settle(table, mid, move.candidate_id)
    assert not prompts
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (6, 6)
    assert actor.movement_remaining_ft == 15
    assert FOE in m.held(actor, 'liquid_form').data['crossed_ids']


def test_liquid_repeats_one_real_grapple_escape_with_native_bonus_and_advantage(tmp_path):
    from tests.worker2_support import ALLY
    from combat.ext.ability_source import escape_bonus
    combat, table, mid = fixture(tmp_path, features(6), cl=6, seed='MERCURIAL-GRIP',
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 3, 'y': 5}, team_overrides={ALLY: 'team:opponents'})
    for grappler in (FOE, ALLY):
        for _ in range(4):
            turn(table, mid, grappler)
            engine = combat._load_session(mid).engine
            if any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == grappler
                   for c in engine.state.actors[OWNER].conditions.values()):
                break
            choices = [c for c in engine.legal_candidates() if c.target_ids == (OWNER,)
                and ((engine.action_catalog[c.source_definition_id].parameters or {}).get('typed') or {}).get('unarmed_option') == 'grapple']
            assert choices
            settle(table, mid, choices[0].candidate_id)
            engine = reload(tmp_path, mid)
            if any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == grappler
                   for c in engine.state.actors[OWNER].conditions.values()):
                break
            settle(table, mid, table.state(mid)['menu']['end_turn'])
        else:
            pytest.fail('Deterministic native grapple never landed')
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    grips = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == 'condition:typed.grappled']
    assert len(grips) == 2
    selected, other = grips
    bonus = escape_bonus(engine, engine.state.actors[OWNER])
    first = len(engine.rolls)
    settle(table, mid, candidate(combat, mid, 'Liquid Form').candidate_id, choices={
        'choice:needle.mercurial.escape': [selected.instance_id], 'choice:needle.physical_escape_skill': ['STR']})
    engine = reload(tmp_path, mid)
    checks = [r for r in engine.rolls[first:] if r.actor_id == OWNER and r.reason.startswith('CHECK:')]
    assert len(checks) == 1 and checks[0].mode == 'ADVANTAGE'
    assert checks[0].modifier == bonus
    assert other.instance_id in engine.state.actors[OWNER].conditions
    if checks[0].total >= selected.data['escape_dc']:
        assert selected.instance_id not in engine.state.actors[OWNER].conditions
