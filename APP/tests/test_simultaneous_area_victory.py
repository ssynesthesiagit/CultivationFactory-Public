"""An area effect resolves for every recipient before combat can end.

Owner 2026-10-01 friendly fire (LUNA27): unrestricted areas include their user
where the shape covers it. A user defeated by its own area must not end the
match before the remaining recipients save and take their results; when the
batch defeats every side the result is a simultaneous draw
(gate2_engine.victory_deferred via typed_executor.simultaneous).
"""
import pytest

from combat import typed_executor as te
from combat.gate2_runtime_models import TerminalKind
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_riders_lane5 import FOE, ME, _bundle, _engine, _place, _use
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, RIGHT, act, on_hold, table_fight

SCREAM = "TAL_SOUND_WORLD_SPLITTING_SCREAM"


def _scream(foe_hp):
    # Exercise the permitted explicit self-inclusion exception, rather than
    # requiring the real line to violate the 2026-10-06 owner recipient rule.
    bundle = _bundle([SCREAM], dc=50)
    for action in bundle['action_catalog']:
        area = action.get('parameters', {}).get('typed', {}).get('area')
        if area:
            area['include_self'] = True
            area['exclude_self'] = False
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = max(foe.maximum_hp, foe_hp)
    foe.current_hp = foe_hp
    start = len(engine.events)
    _use(engine, _place(engine, "World-Splitting Scream", foe.position))
    return engine, me, foe, engine.events[start:]


def test_user_defeated_by_its_own_line_does_not_spare_the_rest_of_the_line():
    engine, me, foe, events = _scream(900)
    assert me.current_hp == 0 and not me.active  # 60 HP inside its own 12d10 line
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (FOE,)]
    assert len(damage) == 1 and foe.current_hp == 900 - damage[0].payload["hp_damage"] > 0
    assert any(c.condition_id == "condition:typed.deafened" for c in foe.conditions.values())
    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1 and ended[0].sequence > damage[0].sequence
    assert engine.state.terminal_result.kind == TerminalKind.VICTORY
    assert engine.state.terminal_result.winning_team_id == foe.team_id


def test_area_that_defeats_both_sides_is_a_simultaneous_draw():
    engine, me, foe, events = _scream(1)
    assert not me.active and not foe.active
    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1 and engine.state.terminal_result.kind == TerminalKind.DRAW_SIMULTANEOUS
    assert engine.state.terminal_result.winning_team_id is None


def test_hold_nests_runs_one_check_and_a_failed_batch_discards_it():
    engine = _engine(_bundle([SCREAM], dc=50))
    foe = engine.state.actors[FOE]
    with engine.victory_deferred():
        with engine.victory_deferred():
            engine._commit_damage(foe, foe.current_hp, "FORCE", "test:batch", ME, None, reaction_depth=0)
        assert engine.state.terminal_result is None  # still inside the outer batch
    assert engine.state.terminal_result.kind == TerminalKind.VICTORY
    assert sum(e.event_type == "MATCH_ENDED" for e in engine.events) == 1

    engine = _engine(_bundle([SCREAM], dc=50))
    foe = engine.state.actors[FOE]
    with pytest.raises(RuntimeError):
        with engine.victory_deferred():
            engine._commit_damage(foe, foe.current_hp, "FORCE", "test:batch", ME, None, reaction_depth=0)
            raise RuntimeError("paused")
    assert engine.state.terminal_result is None and engine._victory_pending is False
    assert getattr(engine, "_victory_hold", 0) == 0


def test_single_recipient_keeps_the_immediate_check():
    engine = _engine(_bundle([SCREAM], dc=50))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.resolution_kind == "TYPED")
    ctx = te.Context(engine, me, action, None, {"numbers": {"save_dc": 99}}, [foe], foe, {})
    with te.simultaneous(ctx, [foe]):
        engine._commit_damage(foe, foe.current_hp, "FORCE", "test:single", ME, None, reaction_depth=0)
        assert engine.state.terminal_result is not None


def test_table_batch_defeating_everyone_commits_reloads_and_replays_as_a_draw(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    everyone = (LEFT, ALLY, RIGHT)

    def blast(engine):
        # One unrestricted area save over both teams; the user is listed first.
        user = engine.state.actors[LEFT]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT)
        subjects = [engine.state.actors[key] for key in everyone]
        ctx = te.Context(engine, user, action, engine._active_intent, {"numbers": {"save_dc": 99}}, subjects, None, {})
        te.block_save(ctx, {"type": "save", "ability": "dex", "on_success": [], "on_fail": [
            {"type": "damage", "applies_to": "target", "flat": 9999, "damage_types": ["force"]}]})

    on_hold(monkeypatch, blast)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    saves = [e.actor_id for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert saves[-3:] == list(everyone)  # every recipient saved, including after the user fell
    assert all(engine.state.actors[key].current_hp == 0 for key in everyone)
    assert engine.state.terminal_result.kind == TerminalKind.DRAW_SIMULTANEOUS
    assert sum(e.event_type == "MATCH_ENDED" for e in engine.events) == 1
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
