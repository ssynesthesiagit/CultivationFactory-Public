"""The one table-owner world-fact path is journaled and survives a cold replay.

Consumers: CombatService.journey_world_fact and journey_verify. Recording a world
fact must dispatch journey_world_fact_committed (so effect consumers actually
store the fact) and must journal the command under the table owner, so a cold
replay rebuilds the saved scene instead of finding a bare checkpoint.
"""
import json

from tests.test_journey_activities_native import (
    B, EFFECT, EFFECTS, catalog, controlling_source_base, game,
)

TABLE_OWNER = 'table_owner'


def test_world_fact_is_journaled_and_survives_cold_replay(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    state = world(EFFECT, 'effect', 'nightmare', {
        'id': 'nightmare', 'label': 'Ordinary nightmare', 'category': 'ordinary_nightmare',
        'source': 'external:bad-sleep', 'save_ability': '', 'save_dc': 0}, B)
    # The committed notification ran, so the effect consumer stored the fact.
    assert state['actors'][B]['source_states'][EFFECTS]['nightmare']['label'] == 'Ordinary nightmare'
    registry = json.loads(cold().journeys.path(jid).read_text())
    segments = registry['replays'][jid]
    # One journaled command, not an extra checkpoint segment.
    assert len(segments) == 1
    assert [(c['actor_id'], c['kind']) for c in segments[0]['commands']] == [(TABLE_OWNER, 'world_fact')]
    proof = cold().journey_replay(jid)
    assert proof['status'] == 'PASS' and proof['commands'] == 1
    assert proof['state_sha256'] == segments[0]['commands'][-1]['state_sha256']
    # The fact and the effect it stored are still there after the cold replay.
    restored = cold().journey_state(jid)
    assert restored == state
    assert restored['actors'][B]['source_states'][EFFECTS]['nightmare']['category'] == 'ordinary_nightmare'
