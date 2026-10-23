"""A fight ends when no side can still act, and the summary opens with it.

Owner 2026-10-21: "if both people are down it should end, neither of us can
advance the fight"; "the fight should end though and i want stats at the end".
A side is defeated when every creature on it is down and none of them has an
in-combat way back by itself; a conscious ally or summon keeps its side live.

These are table-level tests: a real CombatService match, an accepted table
action, then a cold reload of the saved fight.
"""
import json
import zipfile

import pytest

from combat import ext
from combat.gate2_runtime_models import TerminalKind
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import HOLD, on_hold

PROJECTS = {"left": "11111111", "right": "33333333"}
LEFT, RIGHT = [FACTORY_ACTOR_PREFIX + PROJECTS[name] for name in ("left", "right")]
ACTOR_BY_PROJECT = {"left": LEFT, "right": RIGHT}
FORCE = "test:mutual_knockout"


def install_duel(tmp_path, monkeypatch):
    for name in PROJECTS.values():
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet([], cl=10)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Mutual knockout yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"]], opponent_actor_ids=[RIGHT],
                                      control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"},
                                      arena_id="battlefield:map.mutual-knockout-yard",
                                      match_seed="MUTUAL-KO")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def damage(engine, actor_id, by=None):
    actor = engine.state.actors[actor_id]
    by = by or next(key for key in (LEFT, RIGHT) if key != actor_id)
    engine._commit_damage(actor, actor.current_hp, "FORCE", FORCE, by, None, reaction_depth=0)


def self_recovery(*actor_ids):
    def provider(engine, actor):
        return True if actor.entity_id in actor_ids else None
    return provider


def test_mutual_knockout_in_one_resolution_ends_as_a_draw_with_a_summary(tmp_path, monkeypatch):
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def knockout(engine):
        with engine.victory_deferred():
            damage(engine, LEFT)
            damage(engine, RIGHT)

    on_hold(monkeypatch, knockout)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    state = result["state"]
    assert state["presentation"]["terminal"] is True
    assert state["presentation"]["terminal_result"]["kind"] == "DRAW_SIMULTANEOUS"
    assert state["presentation"]["terminal_result"]["winning_team_id"] is None
    assert state["presentation"]["terminal_result"]["reason"] == "Mutual knockout: no combatant on any side can act."
    # The table receives the end-of-fight statistics with the end, not only after a reload.
    assert state["summary"]["actors"], state.get("summary")

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.terminal_result.kind == TerminalKind.DRAW_SIMULTANEOUS
    assert all(loaded.engine.state.actors[key].current_hp == 0 for key in (LEFT, RIGHT))
    ended = [event.sequence for event in loaded.engine.events if event.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    after = [event for event in loaded.engine.events if event.sequence > ended[0]]
    # The ending turn closes with its own TURN_ENDED cleanup; nothing else follows.
    assert [(event.event_type, event.actor_id) for event in after] == [("TURN_ENDED", LEFT)]
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    # A reloaded finished fight also serves the summary the button reads.
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)["summary"]["actors"]


def test_a_downed_side_with_no_way_back_loses_and_the_summary_opens(tmp_path, monkeypatch):
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def knockout(engine):
        damage(engine, LEFT)

    on_hold(monkeypatch, knockout)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    state = result["state"]
    assert state["presentation"]["terminal"] is True
    terminal = state["presentation"]["terminal_result"]
    assert terminal["kind"] == "VICTORY"
    assert state["summary"]["actors"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    winner = loaded.engine.state.actors[RIGHT].team_id
    assert loaded.engine.state.terminal_result.kind == TerminalKind.VICTORY
    assert loaded.engine.state.terminal_result.winning_team_id == winner
    assert loaded.engine.state.actors[LEFT].life_state == "DYING"
    assert loaded.verify()["status"] == "PASS"


def test_both_sides_with_a_self_recovery_keep_fighting(tmp_path, monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "self_recovery", [self_recovery(LEFT, RIGHT)])
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def knockout(engine):
        with engine.victory_deferred():
            damage(engine, LEFT)
            damage(engine, RIGHT)

    on_hold(monkeypatch, knockout)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.terminal_result is None
    assert all(loaded.engine.state.actors[key].life_state == "DYING" for key in (LEFT, RIGHT))
    assert loaded.verify()["status"] == "PASS"


def test_one_recovering_side_beats_a_side_that_cannot_recover(tmp_path, monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "self_recovery", [self_recovery(LEFT)])
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def knockout(engine):
        with engine.victory_deferred():
            damage(engine, LEFT)
            damage(engine, RIGHT)

    on_hold(monkeypatch, knockout)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    terminal = loaded.engine.state.terminal_result
    assert terminal.kind == TerminalKind.VICTORY
    assert terminal.winning_team_id == loaded.engine.state.actors[LEFT].team_id
    assert terminal.reason == "All opposing combatants are down and cannot recover."
    assert loaded.verify()["status"] == "PASS"


def test_a_conscious_ally_keeps_its_side_in_the_fight(tmp_path, monkeypatch):
    from tests.test_tabletop_hunt6 import ALLY, table_fight

    combat, table, mid = table_fight(tmp_path, [])

    def knockout(engine):
        damage(engine, LEFT)

    on_hold(monkeypatch, knockout)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.terminal_result is None
    assert loaded.engine.state.actors[LEFT].life_state == "DYING"
    assert loaded.engine.state.actors[ALLY].active and loaded.engine.state.actors[ALLY].current_hp > 0
    assert loaded.verify()["status"] == "PASS"


def test_no_turn_or_resource_event_runs_after_match_ended(monkeypatch):
    # The observed saved fight ran the Golden Core turn_start resource gain after
    # the death-save turn_start subscriber had ended the match. Dispatch must stop
    # at the subscriber that ends it, so the next turn_start subscriber never runs.
    # The ending turn still closes (its own TURN_ENDED cleanup); no further turn starts.
    from tests.test_auto_tabik import AN, ME, _engine, _turn

    engine, _ = _engine([])
    ext.effects()

    def finishing_rule(engine, actor):
        if engine.state.terminal_result is not None or actor.entity_id != AN:
            return
        engine._defeat(engine.state.actors[ME], "test:finishing_rule", final=True)
        engine._check_victory()

    def gain_after_the_end(engine, actor):
        engine._append_event("RESOURCE_GAINED", "test:after_end", actor_id=actor.entity_id,
                             payload={"resource_id": "resource:core.qi", "requested": 1, "gained": 1, "current": 3})

    monkeypatch.setitem(ext._HOOKS, "turn_start",
                        [*ext._HOOKS.get("turn_start", []), finishing_rule, gain_after_the_end])
    _turn(engine, AN)
    terminal = engine.state.terminal_result
    assert terminal is not None and terminal.kind == TerminalKind.VICTORY
    ended = [event.sequence for event in engine.events if event.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    after = [event for event in engine.events if event.sequence > ended[0]]
    # Only the ending turn's own close follows MATCH_ENDED.
    assert [(event.event_type, event.actor_id) for event in after] == [("TURN_ENDED", AN)]
    assert not any(event.event_type == "TURN_STARTED" for event in after)
    assert not any(event.event_type == "RESOURCE_GAINED" and event.source_definition_id == "test:after_end"
                   for event in engine.events)


def test_the_ending_turn_still_runs_its_end_of_turn_cleanup(monkeypatch):
    # Lead 2026-10-21: the turn in which the match ends keeps its own turn_end
    # subscribers; only further turns stop.
    from tests.test_auto_tabik import AN, ME, _engine, _turn

    engine, _ = _engine([])
    ext.effects()
    cleaned = []

    def finishing_rule(engine, actor):
        if engine.state.terminal_result is not None or actor.entity_id != AN:
            return
        engine._defeat(engine.state.actors[ME], "test:finishing_rule", final=True)
        engine._check_victory()

    def cleanup(engine, actor):
        cleaned.append(actor.entity_id)

    monkeypatch.setitem(ext._HOOKS, "turn_start",
                        [*ext._HOOKS.get("turn_start", []), finishing_rule])
    monkeypatch.setitem(ext._HOOKS, "turn_end", [*ext._HOOKS.get("turn_end", []), cleanup])
    _turn(engine, AN)
    assert engine.state.terminal_result is not None
    assert cleaned == [AN], "the ending turn's own cleanup must run"
    starts = len([event for event in engine.events if event.event_type == "TURN_STARTED"])
    engine.end_turn("test:after-end")
    assert cleaned == [AN], "no further turn starts or runs cleanup"
    assert len([event for event in engine.events if event.event_type == "TURN_STARTED"]) == starts


def test_the_ending_turn_cleans_up_at_the_table(tmp_path, monkeypatch):
    # Table level: the HOLD action ends the fight in the middle of LEFT's turn.
    # That turn still runs its turn_end cleanup; the table receives the summary.
    combat, table, mid = install_duel(tmp_path, monkeypatch)
    ext.effects()
    cleaned = []
    monkeypatch.setitem(ext._HOOKS, "turn_end",
                        [*ext._HOOKS.get("turn_end", []), lambda engine, actor: cleaned.append(actor.entity_id)])

    on_hold(monkeypatch, lambda engine: damage(engine, LEFT))
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    state = result["state"]
    assert state["presentation"]["terminal"] is True
    assert state["summary"]["actors"]
    assert LEFT in cleaned, "the ending turn's turn_end cleanup ran"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    terminal = [event for event in loaded.engine.events if event.event_type == "MATCH_ENDED"]
    assert len(terminal) == 1
    after = [event for event in loaded.engine.events if event.sequence > terminal[0].sequence]
    assert [(event.event_type, event.actor_id) for event in after] == [("TURN_ENDED", LEFT)]
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("fell", [("left",), ("left", "right")])
def test_a_saved_doomed_fight_ends_once_with_the_summary_after_a_cold_reload(tmp_path, monkeypatch, fell):
    # Lead 2026-10-21: an open saved fight whose side is already down with no way
    # back ends on the next check after a cold reload, once, with the summary.
    from combat import victory

    combat, table, mid = install_duel(tmp_path, monkeypatch)
    monkeypatch.setattr(victory, "decide", lambda engine: None)  # save the fight open
    on_hold(monkeypatch, lambda engine: [damage(engine, ACTOR_BY_PROJECT[name]) for name in fell])
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    monkeypatch.undo()
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.engine.state.terminal_result is None
    assert sorted(saved.engine.state.actors[ACTOR_BY_PROJECT[name]].life_state for name in fell) == ["DYING"] * len(fell)

    fresh = CombatService(ROOT, tmp_path)
    reopened = TabletopService(fresh, tmp_path)
    assert reopened.state(mid)["presentation"]["terminal"] is False
    result = act(reopened, mid, "end")
    assert result["status"] == "COMMITTED", result
    state = result["state"]
    assert state["presentation"]["terminal"] is True
    expected = TerminalKind.VICTORY if len(fell) == 1 else TerminalKind.DRAW_SIMULTANEOUS
    assert state["presentation"]["terminal_result"]["kind"] == expected.value
    assert state["summary"]["actors"]
    loaded = fresh._load_session(mid)
    assert loaded.engine.state.terminal_result.kind == expected
    assert len([event for event in loaded.engine.events if event.event_type == "MATCH_ENDED"]) == 1
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    # A later read serves the same summary and cannot end the match a second time.
    assert reopened.state(mid)["summary"]["actors"]
    assert len([event for event in fresh._load_session(mid).engine.events
                if event.event_type == "MATCH_ENDED"]) == 1


def test_a_later_turn_of_the_same_creature_that_ends_the_match_still_closes(monkeypatch):
    # Review F7R fix 1: a stale per-actor guard skipped the closing TURN_ENDED and
    # turn_end cleanup when the same creature's next turn start ended the match.
    from tests.test_auto_tabik import AN, ME, _engine

    engine, _ = _engine([])
    ext.effects()
    cleaned = []

    def finishing_rule(engine, actor):
        if engine.state.terminal_result is not None or actor.entity_id != ME or engine.state.round_number < 2:
            return
        engine._defeat(engine.state.actors[AN], "test:finishing_rule", final=True)
        engine._check_victory()

    monkeypatch.setitem(ext._HOOKS, "turn_start",
                        [*ext._HOOKS.get("turn_start", []), finishing_rule])
    monkeypatch.setitem(ext._HOOKS, "turn_end",
                        [*ext._HOOKS.get("turn_end", []), lambda engine, actor: cleaned.append((engine.state.round_number, actor.entity_id))])
    engine.end_turn("test:first-turn-end")  # ME's first turn closes normally
    if engine.state.current_actor_id == AN:
        engine.end_turn("test:foe-turn-end")
    assert engine.state.current_actor_id == ME and engine.state.round_number == 2
    terminal = engine.state.terminal_result
    assert terminal is not None and terminal.kind == TerminalKind.VICTORY
    closes = [event for event in engine.events if event.event_type == "TURN_ENDED" and event.actor_id == ME]
    assert len(closes) == 2, "the second ME turn must close with its own TURN_ENDED"
    ended = [event.sequence for event in engine.events if event.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    assert [(event.event_type, event.actor_id) for event in engine.events if event.sequence > ended[0]] == [("TURN_ENDED", ME)]
    assert cleaned[-1] == (2, ME), "the ending turn's turn_end cleanup ran for the second turn"

