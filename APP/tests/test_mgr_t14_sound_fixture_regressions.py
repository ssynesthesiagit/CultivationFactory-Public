"""Keep synthetic area and speech deliveries meaningful without optional data."""
import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_base import checks
from tests.test_mgr_t14_sound_read import READ
from tests.test_mgr_t14_sound_review import voiced_scene


def test_scene_area_commits_damage_to_both_teams(tmp_path):
    combat, table, mid = fixture(tmp_path, [], ask=False,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        bundle_transform=checks({}, damage='THUNDER', area={'shape': 'cube', 'size_ft': 15}))
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Thunder delivery', at=(3, 6)).candidate_id)
    after = reload(tmp_path, mid)
    for target in (OWNER, FOE):
        packets = [e for e in after.events if e.sequence > before.state.event_sequence
                   and e.event_type == 'DAMAGE_COMMITTED' and target in e.target_ids
                   and e.actor_id == ALLY and 'sound_scene.damage' in e.source_definition_id]
        assert len(packets) == 1, 'Both friendly and hostile recipients must receive the fixture packet'
        assert packets[0].payload['hp_damage'] == 20
        assert before.state.actors[target].current_hp - after.state.actors[target].current_hp == 20


@pytest.mark.parametrize('silenced', [False, True])
def test_scene_voice_receipt_without_production_voice_catalogue(tmp_path, monkeypatch, request, silenced):
    from combat import speech
    # Remove the optional catalogue before requesting the scoped speech fixture.
    monkeypatch.setitem(speech.rules(), 'needs_voice', {})
    scene = request.getfixturevalue('voiced_scene')
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=scene)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Become invisible').candidate_id)
    if silenced:
        settle(table, mid, candidate(combat, mid, 'Become silent').candidate_id)
    engine = reload(tmp_path, mid)
    voices = [c for c in engine.legal_candidates()
              if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Speak in scene']
    assert bool(voices) == (not silenced)
    if not silenced:
        settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    receipts = [e for e in reload(tmp_path, mid).events if e.payload.get('sound_scene_receipt')
                and e.payload['source_actor_id'] == FOE and e.target_ids == (OWNER,)]
    assert len(receipts) == (0 if silenced else 1)
    if receipts:
        assert receipts[0].payload['hidden_source'] == 1
