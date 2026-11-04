"""Merged save collectors retain numeric support and final provider credit."""
import pytest

from tests.cw2_service_support import add_action
from tests.test_a2_foundations3 import pool
from tests.test_spirit_dew_maintenance import WAR
from tests.test_spirit_dew_protection import AEGIS
from tests.test_spirit_dew_review_boundaries import _supporter
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


@pytest.mark.parametrize('concentration', [True, False])
def test_numeric_support_and_dew_attribution_survive_table_reload(tmp_path, monkeypatch, concentration):
    from combat import support_values

    calls = []

    def bonus(engine, provider, beneficiary, source, purpose):
        calls.append((provider.entity_id, beneficiary.entity_id, source, purpose))
        return 4

    # Isolate transport from the Vessel's separately tested choice/ownership
    # policy. Native grants, saves, settlement and persistence remain intact.
    monkeypatch.setattr(support_values, 'resolve_save_bonus', bonus)

    def prepare(bundles):
        bundles[1]['actor_template']['saving_throws']['CON' if concentration else 'WIS'] = 100
        if concentration:
            add_action(bundles[0], 'Prepare Concentration support', [
                {'type': 'advantage', 'on': 'the next Concentration saving throw',
                 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
            effects = [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}]
        else:
            effects = [{'type': 'save', 'ability': 'WIS', 'applies_to': 'target',
                'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                             'duration': {'kind': 'until_end_of_your_next_turn'}}], 'on_success': []}]
        add_action(bundles[2], 'Support pressure', effects)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=_supporter(AEGIS),
        ally_talents=[WAR], bundle_transform=prepare, named=True, seed='DEW-MERGED-SUPPORT')
    support_name = 'Prepare Concentration support' if concentration else 'Radiant Aegis of the Heart'
    settle(table, mid, candidate(combat, mid, support_name, target=ALLY).candidate_id, choices={})
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    if concentration:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'War Song').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Support pressure', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE' and saved.payload['success'] is True
    assert calls and all(row[:2] == (OWNER, ALLY) for row in calls)
    assert {row[3] for row in calls} == {'concentration' if concentration else 'fear'}
    if concentration:
        assert saved.payload['modifier'] == engine.state.actors[ALLY].saving_throws['CON'] + 4
        assert engine.state.actors[ALLY].concentration is not None
        assert not any(c.data.get('rule', {}).get('concentration_mode') == 'ADVANTAGE'
                       for c in engine.state.actors[ALLY].conditions.values())
    else:
        # Typed saves transport this same numeric bonus by reducing the DC.
        assert saved.payload['dc'] == 12
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == 1
