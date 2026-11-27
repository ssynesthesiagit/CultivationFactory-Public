"""SOL139: recorded initiative and every owner-sheet Path, without fight edits."""
from copy import deepcopy

import pytest

from combat.gate5_service import CombatService
from combat.fighter_picker import card_fields
from combat.tabletop_service import TabletopService
from tests.h48_table_support import fixture, assert_reload_verify_replay
from tests.test_fighter_picker import ROOT, PID, SHEET, _install


def test_recorded_initiative_survives_table_commit_reload_and_refresh(tmp_path, monkeypatch):
    combat, table, mid, _, commit = fixture(tmp_path, [], seed='SOL139-rolls')
    engine = combat._load_session(mid).engine
    expected = {e.actor_id: e.payload['total'] for e in engine.events if e.event_type == 'INITIATIVE_ROLLED'}
    assert expected
    def totals(state):
        return {r['entity_id']: r['initiative'] for r in state['presentation']['actors']}
    state = table.state(mid)
    assert totals(state) == expected
    cached = table._initiative_cache[mid][1]
    assert totals(table.state(mid)) == expected
    assert table._initiative_cache[mid][1] is cached
    state['presentation']['actors'][0]['initiative'] = -999
    assert totals(table.state(mid)) == expected
    commit(state['menu']['end_turn'])
    assert totals(table.state(mid)) == expected
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert totals(fresh.state(mid)) == expected
    assert_reload_verify_replay(combat, mid, tmp_path)


def test_summons_inherit_recorded_total_and_unrolled_joiner_is_null(tmp_path, monkeypatch):
    combat, table, mid, _, _ = fixture(tmp_path, ['TAL_DEATH_CORPSE_SERVANT'], seed='SOL139-summons')
    session = combat._load_session(mid)
    engine = session.engine
    rolls = {e.actor_id: e.payload['total'] for e in engine.events if e.event_type == 'INITIATIVE_ROLLED'}
    creatures = [a for a in engine.state.actors.values() if a.summon is not None]
    assert creatures
    rows = {r['entity_id']: r for r in table.state(mid)['presentation']['actors']}
    for actor in creatures:
        assert rows[actor.entity_id]['initiative'] == rolls[actor.owner_id]
        assert rows[actor.entity_id]['initiative_from'] == actor.owner_id
    # Exercise the table boundary with an ordinary later arrival without an initiative receipt.
    # Its owner_id alone must not be mistaken for a summon.
    joined = next(a for a in engine.state.actors.values() if a.summon is None).model_copy(deep=True)
    joined.entity_id = 'actor:late-unrolled'
    joined.owner_id = creatures[0].owner_id
    engine.state.actors[joined.entity_id] = joined
    engine.state.state_version += 1
    monkeypatch.setattr(table, '_load_state_session', lambda _: session)
    rows = {r['entity_id']: r for r in table.state(mid)['presentation']['actors']}
    assert rows[joined.entity_id]['initiative'] is None
    assert 'initiative_from' not in rows[joined.entity_id]
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reloaded = {r['entity_id']: r for r in fresh.state(mid)['presentation']['actors']}
    for actor in creatures:
        assert reloaded[actor.entity_id]['initiative'] == rolls[actor.owner_id]
    assert_reload_verify_replay(combat, mid, tmp_path)


@pytest.mark.parametrize('names', [[], ['Body Refining'], ['Qi Cultivation', 'Body Refining'],
                                 ['Soul Cultivation', 'Body Refining', 'Qi Cultivation']])
def test_factory_cards_preserve_all_paths_in_sheet_order(tmp_path, names):
    sheet = deepcopy(SHEET)
    sheet['identity']['path'] = 'Legacy primary'
    sheet['path_and_subpath'] = {'paths': [{'path_id': f'path:{i}', 'display_name': name} for i, name in enumerate(names)]}
    _install(tmp_path, PID, sheet)
    service = CombatService(ROOT, tmp_path)
    expected = names or ['Legacy primary']
    [row] = service.factory_characters()
    assert row['paths'] == expected and row['path'] == expected[0]
    row['paths'].append('corrupted caller')
    assert service.factory_characters()[0]['paths'] == expected


def test_path_card_fallbacks_are_names_or_empty_lists():
    assert card_fields({})['paths'] == []
    assert card_fields({})['path'] is None
    assert card_fields({'path_and_subpath': {'path': {'name': 'Qi Cultivation'}}})['paths'] == ['Qi Cultivation']
    assert card_fields({'path_and_subpath': {'paths': [{'name': 'Soul Cultivation'}]}})['paths'] == ['Soul Cultivation']
