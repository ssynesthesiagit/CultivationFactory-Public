"""Thread Meridian Lock blocks real custom paid self-relocation actions."""
from tests.test_a2_thread import fixture, settle, cold, LOCK
from tests.test_r4_integration import reach, candidate, P, F

STORM = 'tianxia.subpath.body.ryujin.feature.storm_step'
FORM = 'tianxia.subpath.body.ryujin.feature.ryujin_ascendant_form'


def _apply_lock(table, mid, ascendant=False):
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F), decline=True)
    reach(table, mid, F)
    if ascendant:
        settle(table, mid, candidate(table, mid, 'Ryūjin Ascendant Form'))
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Meridian Lock', F))
    reach(table, mid, F)


def _storm_candidates(engine, ascendant):
    return [c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == STORM
            and bool(engine.action_catalog[c.source_definition_id].parameters.get('ryujin_ascendant')) == ascendant]


def test_paid_storm_step_and_ascendant_are_denied_under_lock_after_cold_reload(tmp_path):
    for ascendant in (False, True):
        case = tmp_path / str(ascendant)
        case.mkdir()
        _, table, mid = fixture(case, [LOCK], foe_score=2, foe_x=8, foe_mids=[STORM, FORM],
                                foe_resources=[{'name': 'Stamina', 'maximum': 30}])
        _apply_lock(table, mid, ascendant)
        engine = cold(case, mid)
        assert any(c.data.get('thread_meridian_lock') == 1
                   for c in engine.state.actors[F].conditions.values())
        stamina_before = engine.state.actors[F].resources['resource:core.stamina']
        assert _storm_candidates(engine, ascendant) == []
        assert engine.state.actors[F].resources['resource:core.stamina'] == stamina_before


def test_unlocked_paid_storm_step_moves_and_persists(tmp_path):
    _, table, mid = fixture(tmp_path, [LOCK], foe_score=500, foe_x=8, foe_mids=[STORM, FORM],
                            foe_resources=[{'name': 'Stamina', 'maximum': 30}])
    _apply_lock(table, mid)
    engine = cold(tmp_path, mid)
    assert not any(c.data.get('thread_meridian_lock') == 1
                   for c in engine.state.actors[F].conditions.values())
    offers = _storm_candidates(engine, False)
    assert offers
    before = engine.state.actors[F].position
    stamina_before = engine.state.actors[F].resources['resource:core.stamina']
    chosen = next((c for c in offers if c.destination and c.destination != before), offers[0])
    settle(table, mid, chosen.candidate_id)
    after = cold(tmp_path, mid)
    assert after.state.actors[F].position != before
    assert after.state.actors[F].resources['resource:core.stamina'] == stamina_before - 3
