"""Larger-team placement preserves neutral fighters and full footprints."""
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.relations import NEUTRAL_TEAM
from tests.test_factory_live_match import ROOT, _install


@pytest.mark.parametrize('arena_id', ['battlefield:map.builtin-sect-trial-platform', 'battlefield:map.r25-neutral-yard'])
def test_neutral_fighter_survives_larger_team_setup_and_reload(tmp_path, monkeypatch, arena_id):
    left = [f'left-{n}' for n in range(3)]
    right = [f'right-{n}' for n in range(3)]
    for pid in left + right + ['witness']:
        _install(tmp_path, pid)
    combat = CombatService(ROOT, tmp_path)
    original = combat._factory_owner_sheet

    def large_witness(pid):
        sheet = original(pid)
        if pid == 'witness':
            sheet.setdefault('identity', {})['size'] = 'Large'
        return sheet

    monkeypatch.setattr(combat, '_factory_owner_sheet', large_witness)
    combat.tabletop_maps.save({'display_name': 'R25 neutral yard', 'width_squares': 20, 'height_squares': 14,
                              'starts': {'team1': [[2, 6]], 'team2': [[17, 6]]}})
    mid = combat.create_factory_match(project_ids=left,
        opponent_actor_ids=[FACTORY_ACTOR_PREFIX + p for p in right],
        neutral_actor_ids=[FACTORY_ACTOR_PREFIX + 'witness'], arena_id=arena_id,
        match_seed='R25-NEUTRAL-SETUP', prefight={p: [] for p in left + right + ['witness']})['match_id']
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert len(engine.state.actors) == 7
    assert engine.state.actors[FACTORY_ACTOR_PREFIX + 'witness'].team_id == NEUTRAL_TEAM
    occupied = set()
    for actor in engine.state.actors.values():
        cells = set(engine.grid.footprint_cells(actor.position, engine._footprint(actor.entity_id)))
        assert not cells & occupied
        assert not cells & engine.grid.blocked
        occupied.update(cells)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
