"""Review regressions: native paid suppression and encounter/travel clocks."""
import json
import pytest
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.ext.resource_suppression import effective_value
from combat.typed_executor import check_mode
from tests.h1_support import ROOT
from tests.worker2_support import fixture, candidate, reload, settle, turn, OWNER, ALLY, FOE

POSITIONS = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}
TEAMS = {OWNER: 'team:bell', ALLY: 'team:bell', FOE: 'team:other'}
SOURCE = 'action:test.temporary_corruption'


def source_bundle(bundles, source_cl=10, permanent=False, holder=OWNER):
    """Synthetic public source: one temporary point with a real check penalty."""
    bundle = next(b for b in bundles if b['actor_id'] == holder)
    bundle['actor_template']['resources'].append(
        {'resource_id': bell.CORRUPTION, 'maximum': 10, 'initial': 4})
    action = {'source_definition_id': SOURCE, 'display_name': 'Test temporary Corruption',
        'owner_id': holder, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
        'costs': [], 'parameters': {'typed': {'source': SOURCE,
            'numbers': {'cl': source_cl, 'save_dc': 16, 'pb': 2, 'key_mod': 2},
            'effects': [{'type': 'condition', 'condition': 'test_temporary_corruption',
                'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED',
                'condition_data': {'points': 1, 'rule': {'check_mode': {'Perception': 'DISADVANTAGE'}}},
                'information_profile': {'tags': ['temporary_corruption'], 'permanent': permanent}}]}}}
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(SOURCE)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def game(tmp_path, *, features, rounds=12, source=False):
    combat, table, unused = fixture(tmp_path, [], owner_features=features, cl=18, named=True,
        bundle_transform=source if callable(source) else source_bundle if source else None)
    # Reuse only sealed, synthetic compiled fixture documents, not private data.
    bundles = combat._load_session(unused).engine.typed_bundle_documents
    journey = combat.journeys.create(bundles,
        combat.factory_arenas()[next(iter(combat.factory_arenas()))], POSITIONS,
        {aid: 1000 for aid in POSITIONS}, {aid: 'MANUAL' for aid in POSITIONS})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=rounds, positions=POSITIONS)['match_id']
    turn(table, mid, OWNER)
    return combat, table, jid, mid


def cast(combat, table, mid, name, choices=None):
    return settle(table, mid, candidate(combat, mid, name).candidate_id, picks=choices or {})


def terminal(combat, table, mid):
    for _ in range(80):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('encounter did not end')


def resume(tmp_path, jid):
    cold = CombatService(ROOT, tmp_path)
    state = cold.journey_state(jid)
    return cold, cold.journey_resume(jid, state['revision'])


def ledger(combat, jid):
    return combat.journeys.load(jid).state['actors'][OWNER]['source_states'][bell.BELL_SOURCE]


def test_completed_formation_keeps_remaining_clock_and_anchor_across_travel(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.FORM])
    cast(combat, table, mid, 'Begin Bell-Tower Formation',
        {'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    terminal(combat, table, mid)
    end = reload(tmp_path, mid)
    zone = next(iter(bell.placed.of(end, bell.FORM_TAG)))
    left = bell.FORMATION_ROUNDS - (end.state.round_number - zone.created_round)
    cold, journey = resume(tmp_path, jid)
    assert ledger(cold, jid)['formation']['remaining_rounds'] == left
    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 600})
    assert ledger(cold, jid)['formation']['remaining_rounds'] == left - 100
    assert cold.journey_replay(jid)['status'] == 'PASS'
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=2, positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    carried = list(bell.placed.of(engine, bell.FORM_TAG))
    assert len(carried) == 1 and carried[0].duration_rounds == left - 100
    anchor = engine.state.objects[bell.placed.data(carried[0])['anchor_id']]
    assert anchor.ac == 15 and anchor.maximum_hp == anchor.current_hp == 72
    assert set(bell.placed.data(carried[0])['chosen']) == {OWNER, ALLY}


def test_ritual_completes_during_travel_and_expires_after_eight_hours(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.FORM], rounds=2)
    cast(combat, table, mid, 'Begin Bell-Tower Formation',
        {'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    terminal(combat, table, mid)
    end = reload(tmp_path, mid)
    pending = bell.held(end.state.actors[OWNER], 'ritual')[0]
    owes = (pending.data['complete_round'] - end.state.round_number) * 6
    cold, journey = resume(tmp_path, jid)
    assert ledger(cold, jid)['ritual']['remaining_seconds'] == owes
    # Small ticks must accumulate, not round down to zero on every command.
    for _ in range(owes):
        journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 1})
    state = ledger(cold, jid)
    assert 'ritual' not in state
    assert state['formation']['remaining_seconds'] == 28800
    assert not any(json.loads(c)['condition_id'] == bell.BELL + 'ritual'
        for c in journey['actors'][OWNER]['encounter_snapshot']['conditions'].values())
    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 28799})
    assert ledger(cold, jid)['formation']['remaining_seconds'] == 1
    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 1})
    assert 'formation' not in ledger(cold, jid)
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=2, positions=POSITIONS)['match_id']
    assert not list(bell.placed.of(reload(tmp_path, second), bell.FORM_TAG))


def test_ritual_rebases_its_remaining_rounds_in_the_next_encounter(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.FORM], rounds=2)
    cast(combat, table, mid, 'Begin Bell-Tower Formation')
    terminal(combat, table, mid)
    cold, journey = resume(tmp_path, jid)
    remaining = ledger(cold, jid)['ritual']['remaining_rounds']
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=12, positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    pending = bell.held(engine.state.actors[OWNER], 'ritual')
    assert len(pending) == 1
    assert pending[0].data['complete_round'] == 1 + remaining
    terminal(cold, table, second)
    assert list(bell.placed.of(reload(tmp_path, second), bell.FORM_TAG))


def test_ritual_completed_in_travel_opens_a_field_in_next_encounter(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.FORM], rounds=2)
    cast(combat, table, mid, 'Begin Bell-Tower Formation')
    terminal(combat, table, mid)
    cold, journey = resume(tmp_path, jid)
    owes = ledger(cold, jid)['ritual']['remaining_seconds']
    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': owes + 60})
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=2, positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    assert not bell.held(engine.state.actors[OWNER], 'ritual')
    field = next(iter(bell.placed.of(engine, bell.FORM_TAG)))
    assert field.duration_rounds == bell.FORMATION_ROUNDS - 10


def corruption(engine):
    return next(c for c in engine.state.actors[OWNER].conditions.values()
        if c.source_definition_id == SOURCE)


def purify(combat, table, mid):
    engine = reload(combat.userdata_root, mid)
    cast(combat, table, mid, 'Purifying Peal', {
        'choice:needle.bell_allies_to_purify': [OWNER],
        'choice:needle.bell_purify_' + OWNER: corruption(engine).instance_id})


def assert_corruption(engine, effective, mode):
    actor = engine.state.actors[OWNER]
    assert actor.resources[bell.CORRUPTION] == 4  # never permanently reduced
    assert effective_value(engine, actor, bell.CORRUPTION) == effective
    assert check_mode(actor, 'WIS', 'Perception', engine=engine) == mode
    assert check_mode(actor, 'WIS', 'Perception') == mode  # engine-less consequence too
    assert effective_value(engine, engine.state.actors[ALLY], bell.CORRUPTION) is None


def test_paid_purifying_suppresses_a_real_consequence_until_explicit_scene_end(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.PURIFY], rounds=2, source=True)
    cast(combat, table, mid, 'Test temporary Corruption')
    assert_corruption(reload(tmp_path, mid), 4, 'DISADVANTAGE')
    purify(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[bell.QI] == 96
    assert_corruption(engine, 3, 'NORMAL')
    terminal(combat, table, mid)
    cold, journey = resume(tmp_path, jid)
    kept = journey['actors'][OWNER]['encounter_snapshot']['conditions']
    assert any(json.loads(row)['condition_id'] == bell.BELL + 'corruption_suppressed'
        for row in kept.values())
    journey = cold.journey_end_scene(jid, journey['revision'], 'The tower vigil ends.')
    assert journey['events'][-1]['kind'] == 'SCENE_ENDED'
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=2, positions=POSITIONS)['match_id']
    assert_corruption(reload(tmp_path, second), 4, 'DISADVANTAGE')


def test_ally_suppression_uses_ringers_scene_and_clears_the_cold_snapshot(tmp_path):
    combat, table, jid, mid = game(tmp_path, features=[bell.PURIFY], rounds=3,
        source=lambda bundles: source_bundle(bundles, holder=ALLY))
    turn(table, mid, ALLY)
    cast(combat, table, mid, 'Test temporary Corruption')
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    source = next(c for c in engine.state.actors[ALLY].conditions.values() if c.source_definition_id == SOURCE)
    cast(combat, table, mid, 'Purifying Peal', {
        'choice:needle.bell_allies_to_purify': [ALLY],
        'choice:needle.bell_purify_' + ALLY: source.instance_id})
    engine = reload(tmp_path, mid)
    assert effective_value(engine, engine.state.actors[ALLY], bell.CORRUPTION) == 3
    terminal(combat, table, mid)
    cold, journey = resume(tmp_path, jid)
    journey = cold.journey_end_scene(jid, journey['revision'], 'The shared watch ends.')
    snapshot = journey['actors'][ALLY]['encounter_snapshot']['conditions']
    assert not any(json.loads(row)['condition_id'] == bell.BELL + 'corruption_suppressed'
        for row in snapshot.values())
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS,
        maximum_rounds=2, positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    ally = engine.state.actors[ALLY]
    assert effective_value(engine, ally, bell.CORRUPTION) == 4
    assert check_mode(ally, 'WIS', 'Perception') == 'DISADVANTAGE'


def test_returning_clarity_suppression_expires_at_source_next_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.NINE], cl=18, named=True,
        bundle_transform=source_bundle)
    cast(combat, table, mid, 'Test temporary Corruption')
    cast(combat, table, mid, 'Ninefold Heavenly Bell',
        {'choice:needle.bell_protected_allies': [OWNER]})
    engine = reload(tmp_path, mid)
    source = corruption(engine).instance_id
    choices = {'choice:needle.bell_two_different_heavenly_tones': ['returning_clarity', 'closed_gate'],
        'choice:needle.bell_returning_clarity': [OWNER],
        'choice:needle.bell_purify_' + OWNER: source}
    for _ in range(3):
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=choices)
    assert_corruption(reload(tmp_path, mid), 3, 'NORMAL')
    # Do not pick Returning Clarity again: the previous turn's grant must end.
    for _ in range(3):
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks={
            'choice:needle.bell_two_different_heavenly_tones': ['iron_vigil', 'closed_gate'],
            'choice:needle.bell_iron_vigil': [OWNER]})
    assert_corruption(reload(tmp_path, mid), 4, 'DISADVANTAGE')


@pytest.mark.parametrize('source_cl,permanent', [(20, False), (10, True)])
def test_protected_corruption_is_not_suppressed(tmp_path, source_cl, permanent):
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.PURIFY], cl=18, named=True,
        bundle_transform=lambda b: source_bundle(b, source_cl, permanent))
    cast(combat, table, mid, 'Test temporary Corruption')
    purify(combat, table, mid)
    assert_corruption(reload(tmp_path, mid), 4, 'DISADVANTAGE')
