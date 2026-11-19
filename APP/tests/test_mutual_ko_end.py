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

PROJECTS = {"left": "11111111", "right": "33333333", "ally": "22222222"}
LEFT, RIGHT, ALLY = [FACTORY_ACTOR_PREFIX + PROJECTS[name] for name in ("left", "right", "ally")]
ACTOR_BY_PROJECT = {"left": LEFT, "right": RIGHT, "ally": ALLY}
FORCE = "test:mutual_knockout"


def install_duel(tmp_path, monkeypatch, ally=False, left_talents=()):
    names = [PROJECTS["left"], PROJECTS["right"]] + ([PROJECTS["ally"]] if ally else [])
    for name in names:
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json",
                             json.dumps(sheet(list(left_talents) if name == PROJECTS["left"] else [], cl=10)))
    combat = CombatService(ROOT, tmp_path)
    starts = {"team1": [[3, 4]], "team2": [[4, 4]]}
    if ally:
        starts["team1"].append([2, 4])
    combat.tabletop_maps.save({"display_name": "Mutual knockout yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": starts})
    modes = {LEFT: "MANUAL", RIGHT: "MANUAL", **({ALLY: "MANUAL"} if ally else {})}
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"]] + ([PROJECTS["ally"]] if ally else []),
                                      opponent_actor_ids=[RIGHT], control_modes=modes,
                                      arena_id="battlefield:map.mutual-knockout-yard",
                                      match_seed="MUTUAL-KO")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def step(table, mid):
    """End the current turn, whether the engine offers it a manual menu or not."""
    state = table.state(mid)
    menu = state["menu"]
    if menu["manual"]:
        return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    return table.auto_step(mid, state["last_sequence"])


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
    # The ending turn closes before the result is sealed.
    assert not after
    assert any(event.event_type == "TURN_ENDED" and event.actor_id == LEFT for event in loaded.engine.events)
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


def test_a_natural_20_death_save_stands_the_creature_up_while_an_ally_is_live(tmp_path, monkeypatch):
    """Regression (MUTUALKO1F13 finding 1): the downed-side rule is not the death-save rule.

    A natural 20 on a death saving throw regains 1 Hit Point whenever the fight is
    still going. Here the ally is deliberately conscious, so the dying character
    reaches its next turn start and the forced natural 20 must stand it up. The
    owner's "a natural 20 is not a way back" ruling (FD-14) ends a side; it does
    not cancel the heal while somebody on that side can still act.
    """
    from tests.test_lock_choices import install
    ext.effects()
    combat, table, mid = install_duel(tmp_path, monkeypatch, ally=True)

    def wound(engine, actor):
        if actor.entity_id == LEFT and actor.turns_started == 2:
            damage(engine, LEFT)

    monkeypatch.setitem(ext._HOOKS, "turn_start", [*ext._HOOKS.get("turn_start", []), wound])
    install(monkeypatch, "d20_result", lambda engine, roll, intent: (
        {"source_id": "test:death_save_nat20", "operation": "replace", "natural_result": 20}
        if roll.reason == "SAVE:death" and roll.actor_id == LEFT else None))
    for _ in range(20):
        if combat._load_session(mid).engine.state.actors[LEFT].turns_started >= 3:
            break
        assert step(table, mid)["status"] == "COMMITTED"
    else:
        raise AssertionError("the dying character never reached its second death save")

    loaded = combat._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert loaded.engine.state.terminal_result is None, "a conscious ally keeps its side in the fight"
    assert loaded.engine.state.actors[ALLY].active
    assert actor.active and actor.current_hp == 1 and actor.life_state != "DYING"
    checks = [event for event in loaded.engine.events if event.event_type == "CHECK_ROLLED"
              and event.source_definition_id == "system:death_save" and event.actor_id == LEFT]
    assert checks and checks[-1].payload["success"] is True
    assert checks[-1].payload["actor"]["natural_result"] == 20
    assert any(event.event_type == "HEALING_APPLIED" and event.actor_id == LEFT for event in loaded.engine.events)
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


def test_summon_on_owner_former_side_keeps_fight_running(tmp_path, monkeypatch):
    """A side with only a summon still participates after its owner changes sides."""
    from combat.relation_models import RelationChange
    from combat.relations import apply_change, relation

    combat, table, mid = install_duel(tmp_path, monkeypatch, left_talents=["TAL_DEATH_CORPSE_SERVANT"])
    before = combat._load_session(mid).engine
    summons = [a.entity_id for a in before.state.actors.values()
               if (a.summon or {}).get("owner") == LEFT and a.active]
    assert summons
    old_side = before.state.actors[LEFT].team_id

    def change_and_knock_out(engine):
        with engine.victory_deferred():
            apply_change(engine, RelationChange(kind="ACTOR_SIDE", subject=LEFT, other="team:third"))
            apply_change(engine, RelationChange(kind="TEAM_RELATION", subject=old_side,
                                                other="team:third", relation="ALLY"))
            damage(engine, LEFT, RIGHT)

    on_hold(monkeypatch, change_and_knock_out)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    assert result["state"]["presentation"]["terminal"] is False
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert engine.state.terminal_result is None
    assert engine.state.actors[LEFT].life_state == "DYING"
    assert engine.state.actors[LEFT].team_id == "team:third"
    assert all(engine.state.actors[s].team_id == old_side and engine.state.actors[s].active for s in summons)
    assert not any(a.primary_combatant and a.team_id == old_side for a in engine.state.actors.values())
    assert relation(engine, engine.state.actors[summons[0]], engine.state.actors[RIGHT]) == "ENEMY"
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_companion_only_side_defeat_awards_victory_after_side_change(tmp_path, monkeypatch):
    from combat.relation_models import RelationChange
    from combat.relations import apply_change

    combat, table, mid = install_duel(tmp_path, monkeypatch, left_talents=["TAL_DEATH_CORPSE_SERVANT"])
    before = combat._load_session(mid).engine
    summons = [a.entity_id for a in before.state.actors.values()
               if (a.summon or {}).get("owner") == LEFT and a.active]
    assert summons
    old_side = before.state.actors[LEFT].team_id
    winning_side = before.state.actors[RIGHT].team_id

    def change_sides_and_defeat_companions(engine):
        with engine.victory_deferred():
            apply_change(engine, RelationChange(kind="TEAM_RELATION", subject=old_side,
                                                other=winning_side, relation="ENEMY"))
            apply_change(engine, RelationChange(kind="ACTOR_SIDE", subject=LEFT, other=winning_side))
        assert engine.state.terminal_result is None
        assert not any(a.primary_combatant and a.team_id == old_side for a in engine.state.actors.values())
        with engine.victory_deferred():
            for summon in summons:
                damage(engine, summon, RIGHT)

    on_hold(monkeypatch, change_sides_and_defeat_companions)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    assert result["state"]["presentation"]["terminal_result"]["kind"] == "VICTORY"
    assert result["state"]["presentation"]["terminal_result"]["winning_team_id"] == winning_side
    assert result["state"]["summary"]["actors"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.terminal_result.kind == TerminalKind.VICTORY
    assert loaded.engine.state.terminal_result.winning_team_id == winning_side
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


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
    # The result is the last event.
    assert not after
    assert any(event.event_type == "TURN_ENDED" and event.actor_id == AN for event in engine.events)
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
    assert not after
    assert any(event.event_type == "TURN_ENDED" and event.actor_id == LEFT for event in loaded.engine.events)
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
    # main's DYINGTURN1 rule passes a downed side's only-End-Turn turn on its own,
    # so the reloaded fight may have no manual menu: step() handles both shapes.
    result = step(reopened, mid)
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
    assert not [event for event in engine.events if event.sequence > ended[0]]
    assert closes[-1].sequence < ended[0]
    assert cleaned[-1] == (2, ME), "the ending turn's turn_end cleanup ran for the second turn"


def test_a_legacy_active_actor_at_zero_hp_keeps_its_side_live():
    # Review RB1 finding 2: the victory rule must not reclassify a legacy
    # zero_hp fight's active primary as down. That engine marks a creature out
    # of the fight with active=False instead of a life state, so life_state=None
    # at 0 HP still means "the engine has not marked it down" (old behaviour),
    # while DYING/STABLE is the downed state the new rule understands.
    from types import SimpleNamespace

    from combat import victory

    def actor(entity_id, team, hp, life_state=None):
        return SimpleNamespace(entity_id=entity_id, team_id=team, current_hp=hp,
                               life_state=life_state, primary_combatant=True, active=True,
                               conditions={})

    legacy = actor("legacy", "team:a", 0)
    standing = actor("standing", "team:b", 9)
    engine = SimpleNamespace(state=SimpleNamespace(actors={"legacy": legacy, "standing": standing},
                                                   rules={}, terminal_result=None))
    assert victory.can_act(legacy) is True
    assert victory.decide(engine) is None

    legacy.life_state = "DYING"
    assert victory.can_act(legacy) is False
    # The defeat rule that reads a life state is a rule of the 2024 dying rules,
    # exactly as the turn-boundary caller already treats it
    # (resolve_stable_opponents only runs for rules["zero_hp"] == "dying_2024").
    # A legacy fight marks a creature out of the fight with active=False, so a
    # life state alone leaves its side in the fight; main's recovery consumers
    # (test_riders_c8_recovery) set a Dying creature up and then commit, reload
    # and let its own saving throw happen before anything decides the match.
    assert victory.decide(engine) is None

    engine.state.rules = {"zero_hp": "dying_2024"}
    decision = victory.decide(engine)
    assert decision is not None and decision[0] == TerminalKind.VICTORY


def test_the_closing_turn_end_is_dispatched_once_at_the_outer_event_depth(monkeypatch):
    # Review RB1 finding 4: the closing turn_end cleanup is delivered either by
    # gate4's outermost TURN_ENDED dispatch (depth 0) or by the nested-dispatch
    # fallback. This covers the depth-0 arm, which the turn_start tests do not:
    # the cleanup must run exactly once, never twice.
    from tests.test_auto_tabik import AN, ME, _engine

    engine, _ = _engine([])
    ext.effects()
    cleaned = []
    monkeypatch.setitem(ext._HOOKS, "turn_end",
                        [*ext._HOOKS.get("turn_end", []), lambda engine, actor: cleaned.append(actor.entity_id)])
    assert getattr(engine, "_ext_event_depth", 0) == 0
    engine._defeat(engine.state.actors[AN], "test:outer_defeat", final=True)
    engine._check_victory()
    assert engine.state.terminal_result is not None
    assert getattr(engine, "_ext_event_depth", 0) == 0
    assert cleaned == [ME], "the closing turn_end cleanup ran once at outer depth"
    closes = [event for event in engine.events if event.event_type == "TURN_ENDED" and event.actor_id == ME]
    assert len(closes) == 1


def on_start_of_turn(monkeypatch, callback):
    """A start-of-turn effect that hurts: it runs before this turn's TURN_STARTED.

    "_system_start_turn" imports "start_turn" when it runs, so patching the module
    is enough, and the turn-start snapshot is taken first so the effect cannot
    record anything after the closing TURN_ENDED.
    """
    from combat import movement_budget
    original = movement_budget.start_turn

    def run(engine, actor):
        result = original(engine, actor)
        callback(engine, actor)
        return result

    monkeypatch.setattr(movement_budget, "start_turn", run)


def tail_after_match_end(events):
    """The recorded events from MATCH_ENDED on, as (type, actor) pairs."""
    ended = next(index for index, event in enumerate(events) if event.event_type == "MATCH_ENDED")
    return [(event.event_type, event.actor_id) for event in events[ended:]]


def test_a_match_that_ends_on_start_of_turn_damage_closes_the_opening_turn(tmp_path, monkeypatch):
    # Lead 2026-10-21, review MUTUALKO1F14 finding 2: when a match ends, the turn
    # that is open closes exactly once and no other turn starts. A turn that opens
    # on lethal start-of-turn damage is that turn too, even though its own
    # TURN_STARTED is recorded only if the fight goes on.
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def lethal_dawn(engine, actor):
        if actor.entity_id == RIGHT:
            damage(engine, RIGHT)

    on_start_of_turn(monkeypatch, lethal_dawn)
    result = act(table, mid, "end")
    assert result["status"] == "COMMITTED", result
    assert result["state"]["presentation"]["terminal"] is True
    assert result["state"]["summary"]["actors"], "the summary opens with the ending"

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    closes = [e for e in loaded.engine.events if e.event_type == "TURN_ENDED" and e.actor_id == RIGHT]
    assert len(closes) == 1
    assert [(e.event_type, e.actor_id) for e in loaded.engine.events[-2:]] == [("TURN_ENDED", RIGHT), ("MATCH_ENDED", None)]
    assert loaded.engine._open_turn_actor() is None, "the closing TURN_ENDED is the record that closes the turn"
    assert loaded.verify()["status"] == "PASS"


def test_a_fight_finished_after_a_cold_reload_keeps_the_tail_and_state_of_one_played_through(tmp_path, monkeypatch):
    # Lead 2026-10-21, review MUTUALKO1F14 finding 1: the turn that is open is a
    # fact of the recorded journal, not engine state, so the same fight finished
    # after a restart ends exactly like the fight played straight through.
    def play(root, restart_before_the_end):
        root.mkdir()
        patch = pytest.MonkeyPatch()  # one start-of-turn effect per arm
        combat, table, mid = install_duel(root, patch)

        def lethal_dawn(engine, actor):
            if actor.entity_id == RIGHT:
                damage(engine, RIGHT)

        on_start_of_turn(patch, lethal_dawn)
        if restart_before_the_end:
            del combat, table  # every in-memory object goes away, as after a restart
            combat = CombatService(ROOT, root)
            table = TabletopService(combat, root)
        try:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        finally:
            patch.undo()
        del combat, table
        stored = CombatService(ROOT, root)._load_session(mid)
        assert stored.verify()["status"] == "PASS"
        state = stored.engine.state.model_dump(mode="json")
        state["match_id"] = None  # independent saves use different storage identifiers
        return [(e.event_type, e.actor_id) for e in stored.engine.events[-2:]], state

    straight = play(tmp_path / "straight", restart_before_the_end=False)
    reloaded = play(tmp_path / "reloaded", restart_before_the_end=True)
    assert straight[0] == [("TURN_ENDED", RIGHT), ("MATCH_ENDED", None)]
    assert reloaded == straight, "a reloaded fight finished is the same game, tail and state"


def test_the_open_turn_is_read_back_out_of_the_recorded_journal():
    # The reducer's derivation, on its own: the last recorded turn boundary decides,
    # MATCH_ENDED closes nothing by itself, and the closing TURN_ENDED closes it.
    from combat.gate3_reducer import open_turn_actor

    def event(sequence, event_type, actor_id=None):
        return {"sequence": sequence, "event_type": event_type, "actor_id": actor_id,
                "source_definition_id": "system:test"}

    assert open_turn_actor([]) is None
    assert open_turn_actor([event(1, "TURN_STARTED", LEFT)]) == LEFT
    assert open_turn_actor([event(1, "TURN_STARTED", LEFT), event(2, "TURN_ENDED", LEFT)]) is None
    assert open_turn_actor([event(1, "TURN_STARTED", LEFT), event(2, "TURN_ENDED", LEFT),
                            event(3, "TURN_STARTED", RIGHT)]) == RIGHT
    assert open_turn_actor([event(1, "TURN_STARTED", LEFT), event(2, "MATCH_ENDED")]) == LEFT
    assert open_turn_actor([event(1, "TURN_STARTED", LEFT), event(2, "MATCH_ENDED"),
                            event(3, "TURN_ENDED", LEFT)]) is None


def test_a_saved_fight_knows_its_open_turn_before_it_ends(tmp_path, monkeypatch):
    # The fact follows the recorded boundaries across a cold reload, so the ending
    # action always finds the same turn open that an uninterrupted fight would.
    combat, table, mid = install_duel(tmp_path, monkeypatch)
    first = CombatService(ROOT, tmp_path)._load_session(mid)
    assert first.engine._open_turn_actor() == LEFT, "the fight is saved in the middle of LEFT's turn"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    second = CombatService(ROOT, tmp_path)._load_session(mid)
    assert second.engine._open_turn_actor() == RIGHT, "LEFT's turn closed; RIGHT's turn is open"




@pytest.mark.parametrize("third_side", ["neutral", "allied"])
@pytest.mark.parametrize("boundary", [False, True])
def test_relations_and_downed_enemies_share_one_table_victory(tmp_path, monkeypatch, third_side, boundary):
    """Both damage and turn-boundary decisions ignore non-hostile survivors."""
    from combat.relation_models import RelationChange
    from combat.relations import apply_change
    from combat.ext.life_state import resolve_stable_opponents

    combat, table, mid = install_duel(tmp_path, monkeypatch, ally=True)

    def finish(engine):
        with engine.victory_deferred():
            side = "team:neutral" if third_side == "neutral" else "team:third"
            apply_change(engine, RelationChange(kind="ACTOR_SIDE", subject=ALLY, other=side))
            if third_side == "allied":
                apply_change(engine, RelationChange(kind="TEAM_RELATION", subject=side,
                    other=engine.state.actors[LEFT].team_id, relation="ALLY"))
            damage(engine, RIGHT, LEFT)
            engine._set_life_state(engine.state.actors[RIGHT], "STABLE", FORCE)
            if boundary:
                resolve_stable_opponents(engine, engine.state.actors[LEFT])

    on_hold(monkeypatch, finish)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    state = result["state"]
    assert state["presentation"]["terminal"] is True
    assert state["presentation"]["terminal_result"]["kind"] == "VICTORY"
    assert state["summary"]["actors"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    terminal = loaded.engine.state.terminal_result
    assert terminal.kind == TerminalKind.VICTORY
    assert terminal.winning_team_id == (loaded.engine.state.actors[LEFT].team_id if third_side == "neutral" else None)
    assert loaded.engine.state.actors[RIGHT].life_state == "STABLE"
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)["summary"]["actors"]
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("fallen", ["inactive", "dying", "recovering"])
def test_actor_truce_ignores_only_teammates_who_cannot_return(tmp_path, monkeypatch, fallen):
    """A defeated teammate cannot keep two allied survivors at war."""
    if fallen == "recovering":
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, "self_recovery", [self_recovery(ALLY)])
    combat, table, mid = install_duel(tmp_path, monkeypatch, ally=True)

    def knock_out_teammate(engine):
        if fallen == "inactive":
            engine._defeat(engine.state.actors[ALLY], "test:fallen", final=True)
        else:
            damage(engine, ALLY, RIGHT)

    on_hold(monkeypatch, knock_out_teammate)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED"
    before = combat._load_session(mid)
    assert before.engine.state.terminal_result is None
    combat.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": RIGHT, "relation": "ALLY"}, expected_state_version=before.engine.state.state_version)

    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    if fallen == "recovering":
        assert loaded.engine.state.terminal_result is None
    else:
        assert loaded.engine.state.terminal_result is not None
        assert loaded.engine.state.terminal_result.kind == TerminalKind.VICTORY
        assert loaded.engine.state.terminal_result.winning_team_id == loaded.engine.state.actors[RIGHT].team_id
        state = TabletopService(fresh, tmp_path).state(mid)
        assert state["presentation"]["terminal"] is True
        assert state["summary"]["actors"]
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_second_ruin_form_backlash_settles_before_victory_and_reload(tmp_path, monkeypatch):
    from tests.test_c5_review import _table, _act
    from tests import test_riders_c5 as C
    from combat import stances

    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL"])
    _act(combat, table, mid, "Second Ruin Form: Black Palm Vessel")

    def finish(engine):
        me, foe = engine.state.actors[C.ME], engine.state.actors[C.AN]
        engine._gain_resource(me, C.STRAIN, 5, "test:setup")
        form = next(c for c in stances.active(me) if (c.data or {}).get("end_of_turn_if_damaged"))
        me.turn_flags[f"stance_damaged:{form.condition_id}"] = True
        me.current_hp = 1
        engine._commit_damage(foe, foe.current_hp, "FORCE", "test:finish", C.ME, None, reaction_depth=0)

    on_hold(monkeypatch, finish)
    engine, _ = _act(combat, table, mid, "Hold position")
    assert engine.state.actors[C.ME].current_hp == 0
    assert engine.state.terminal_result.kind == TerminalKind.DRAW_SIMULTANEOUS
    assert engine.events[-1].event_type == "MATCH_ENDED"
    gain = next(e for e in engine.events if e.event_type == "RESOURCE_GAINED"
                and e.payload.get("resource_id") == C.STRAIN and e.payload.get("current") == 6)
    backlash = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                    and "ruin_backlash" in e.source_definition_id)
    assert gain.sequence < backlash.sequence < engine.events[-1].sequence
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
    assert [e.model_dump(mode="json") for e in fresh.events] == [e.model_dump(mode="json") for e in engine.events]


def test_massive_damage_seals_once_after_closing_turn_and_reload(tmp_path, monkeypatch):
    combat, table, mid = install_duel(tmp_path, monkeypatch)

    def finish(engine):
        foe = engine.state.actors[RIGHT]
        engine._commit_damage(foe, foe.current_hp + foe.maximum_hp, "FORCE", FORCE, LEFT, None, reaction_depth=0)

    on_hold(monkeypatch, finish)
    result = act(table, mid, HOLD)
    assert result["status"] == "COMMITTED", result
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    endings = [e for e in engine.events if e.event_type == "MATCH_ENDED"]
    closes = [e for e in engine.events if e.event_type == "TURN_ENDED" and e.actor_id == LEFT]
    assert len(endings) == len(closes) == 1
    assert closes[0].sequence < endings[0].sequence
    assert engine.events[-1] == endings[0]
    assert engine.state.terminal_result.event_sequence == endings[0].sequence


def test_blackwater_start_trigger_settles_before_victory(tmp_path, monkeypatch):
    from combat.gate2_runtime_content import BAI
    from combat.gate2_runtime_models import ZoneState
    from tests.test_lock_choices import install

    from combat import gate2_engine
    original_seal = gate2_engine.Gate2Engine._seal_match
    offers_at_seal = []
    def record_seal(self, *args):
        pending = self.state.pending_resolution
        offers_at_seal.append(list(pending.follow_up_candidates) if pending else None)
        original_seal(self, *args)
        assert self.state.pending_resolution is None
    monkeypatch.setattr(gate2_engine.Gate2Engine, "_seal_match", record_seal)

    folder = tmp_path / "portable_characters" / PROJECTS["left"]
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet([], cl=10)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Blackwater yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[7, 4], [8, 4], [9, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"]], opponent_actor_ids=[BAI],
        control_modes={LEFT: "MANUAL", BAI: "MANUAL"}, arena_id="battlefield:map.blackwater-yard",
        match_seed="MUTUAL-KO")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    install(monkeypatch, "d20_result", lambda engine, roll, intent: (
        {"source_id": "test:zone_save", "operation": "replace", "natural_result": 1}
        if roll.actor_id == LEFT and roll.reason.startswith("SAVE:") and roll.reason.endswith(":CON")
        else None))

    def court(engine):
        owner, target = engine.state.actors[BAI], engine.state.actors[LEFT]
        engine._gain_resource(owner, "resource:bai_meizhen.moon_sea_radiance", 1, "test:setup")
        engine._commit_damage(target, target.current_hp - 1, "FORCE", FORCE, BAI, None, reaction_depth=0)
        zone = ZoneState(zone_id="zone:test-court", source_definition_id="action:bai_meizhen.blackwater_serpent_court",
            owner_id=BAI, center=target.position, radius_cells=0, affected_cells=(target.position,),
            concentration_link=False, created_round=engine.state.round_number, trigger_profile={"kind": "BLACKWATER"})
        engine.state.zones[zone.zone_id] = zone
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=BAI,
                             payload={"zone": zone.model_dump(mode="json")})

    on_hold(monkeypatch, court)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    for _ in range(6):
        if table.state(mid)["presentation"]["terminal"]:
            break
        result = act(table, mid, "end")
        assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert engine.state.actors[LEFT].life_state == "DYING"
    ends = [e for e in engine.events if e.event_type == "MATCH_ENDED"]
    assert len(ends) == 1 and engine.events[-1] == ends[0]
    conditions = [e.payload.get("condition_id") for e in engine.events
                  if e.event_type == "CONDITION_APPLIED" and e.sequence < ends[0].sequence]
    assert "condition:bai_meizhen.dose_mark" in conditions
    assert "condition:core.reaction_denied" in conditions
    assert engine.state.pending_resolution is None, (ends[0].sequence, engine.state.pending_resolution)
    assert any(offers and "action:bai_meizhen.moon_disc_descent" in offers for offers in offers_at_seal)
    assert loaded.engine.state.pending_resolution is None
    assert engine.state.terminal_result.event_sequence == ends[0].sequence
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_two_turn_start_zones_settle_before_victory(tmp_path, monkeypatch):
    from combat.gate2_runtime_content import BAI
    from combat.gate2_runtime_models import ZoneState
    from tests.test_lock_choices import install

    folder = tmp_path / "portable_characters" / PROJECTS["left"]
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet([], cl=10)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Blackwater yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[7, 4], [8, 4], [9, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"]], opponent_actor_ids=[BAI],
        control_modes={LEFT: "MANUAL", BAI: "MANUAL"}, arena_id="battlefield:map.blackwater-yard",
        match_seed="MUTUAL-KO")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != BAI:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    install(monkeypatch, "d20_result", lambda engine, roll, intent: (
        {"source_id": "test:zone_save", "operation": "replace", "natural_result": 1}
        if roll.actor_id == LEFT and roll.reason.startswith("SAVE:") and roll.reason.endswith(":CON")
        else None))

    def court(engine):
        owner, target = engine.state.actors[BAI], engine.state.actors[LEFT]
        engine._gain_resource(owner, "resource:bai_meizhen.moon_sea_radiance", 1, "test:setup")
        engine._commit_damage(target, target.current_hp - 1, "FORCE", FORCE, BAI, None, reaction_depth=0)
        zone = ZoneState(zone_id="zone:test-court", source_definition_id="action:bai_meizhen.blackwater_serpent_court",
            owner_id=BAI, center=target.position, radius_cells=0, affected_cells=(target.position,),
            concentration_link=False, created_round=engine.state.round_number, trigger_profile={"kind": "BLACKWATER"})
        engine.state.zones[zone.zone_id] = zone
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=BAI,
                             payload={"zone": zone.model_dump(mode="json")})
        bearing = ZoneState(zone_id="zone:test-risen", source_definition_id="action:bai_meizhen.sea_risen_bearing",
            owner_id=BAI, center=target.position, radius_cells=0, affected_cells=(target.position,),
            concentration_link=False, created_round=engine.state.round_number,
            trigger_profile={"kind": "SEA_RISEN", "speed_delta": -5})
        engine.state.zones[bearing.zone_id] = bearing
        engine._append_event("ZONE_CREATED", bearing.source_definition_id, actor_id=BAI,
                             payload={"zone": bearing.model_dump(mode="json")})

    on_hold(monkeypatch, court)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    for _ in range(6):
        if table.state(mid)["presentation"]["terminal"]:
            break
        result = act(table, mid, "end")
        assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert engine.state.actors[LEFT].life_state == "DYING"
    ends = [e for e in engine.events if e.event_type == "MATCH_ENDED"]
    assert len(ends) == 1 and engine.events[-1] == ends[0]
    conditions = [e.payload.get("condition_id") for e in engine.events
                  if e.event_type == "CONDITION_APPLIED" and e.sequence < ends[0].sequence]
    assert "condition:bai_meizhen.dose_mark" in conditions
    assert "condition:core.reaction_denied" in conditions
    assert engine.state.pending_resolution is None, (ends[0].sequence, engine.state.pending_resolution)
    assert not any(e.event_type == "ZONE_REMOVED" and e.payload.get("zone_id") == "zone:test-risen"
                   and e.sequence < ends[0].sequence for e in engine.events)
    bearing = [e for e in engine.events if e.event_type == "MODIFIER_APPLIED"
               and e.source_definition_id == "action:bai_meizhen.sea_risen_bearing"]
    assert bearing and all(e.sequence < ends[0].sequence for e in bearing)
    assert engine.state.terminal_result.event_sequence == ends[0].sequence
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
