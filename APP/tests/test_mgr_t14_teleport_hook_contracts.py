"""Distance-limit providers must not replace the existing teleport motion hook."""
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, fixture, candidate, settle, reload
from tests.cw2_service_support import add_action


def test_unowned_native_teleport_keeps_both_hook_contracts_inert(tmp_path):
    def setup(bundles):
        add_action(bundles[0], 'Plain teleport', [
            {'type': 'teleport', 'distance_ft': 10, 'applies_to': 'self', 'picks_destination': True}
        ], target='SELF')
    combat, table, mid = fixture(tmp_path, [], bundle_transform=setup)
    before = reload(tmp_path, mid)
    start = before.state.actors[OWNER].position
    prompts = settle(table, mid, candidate(combat, mid, 'Plain teleport').candidate_id,
        choices={'choice:needle.teleport_destination': ['cell:3,7']})
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    assert engine.grid.distance_ft(start, engine.state.actors[OWNER].position) == 5
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.fracture_response' for p in prompts)
    assert not any(e.payload.get('checkpoint') == 'TELEPORT_DISTANCE_REDUCED' for e in engine.events)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
