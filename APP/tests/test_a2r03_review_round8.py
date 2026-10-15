"""Rebuke preserves its paid rider until an eligible Frame resistance check."""
from tests.test_a2r03_review_round5 import _owner_action
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SACRED_BARE, _sacred, _service_fight,
    _candidate, _play, _engine, _until,
)


def test_rebuke_unscoped_then_pressure_contest_commits_and_reloads(tmp_path, monkeypatch):
    def prepare(bundles):
        for name, hazards in [('Unscoped contest', []), ('Pressure contest', ['forced_movement'])]:
            _owner_action(bundles, name, [{
                'type': 'contest_against', 'harmful': True, 'applies_to': 'target',
                'actor_check': {'kind': 'check', 'ability': 'STR', 'hazards': hazards},
                'target_check': {'kind': 'check', 'ability': 'STR'},
                'on_success': [], 'on_fail': [],
            }])

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE,
                                       prepare=prepare)
    _until(table, mid, FIGHTER)
    _play(table, mid, _candidate(table, mid, 'Unarmed Strike', SERVICE_FOE), answer='frame')
    condition = 'condition:typed.saint_body_frame_advantage'

    def rider(engine):
        return [c for c in engine.state.actors[FIGHTER].conditions.values()
                if c.condition_id == condition]

    assert rider(_engine(combat, mid))
    for name, mode, retained in [('Unscoped contest', 'NORMAL', True),
                                  ('Pressure contest', 'ADVANTAGE', False),
                                  ('Pressure contest', 'NORMAL', False)]:
        _play(table, mid, _candidate(table, mid, name, SERVICE_FOE))
        cold = _engine(combat, mid)
        assert bool(rider(cold)) is retained
        roll = next(r for r in reversed(cold.rolls)
                    if r.actor_id == FIGHTER and r.reason.startswith('CHECK:'))
        assert roll.mode == mode
