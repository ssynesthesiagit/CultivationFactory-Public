"""The hook runner, not the Reaction scope, discards interrupted replies."""
from types import SimpleNamespace

import pytest

from combat import ext, typed_reactions
from combat.ext import eye_second_pass, qi_tempered, riders14_eye, needle
from combat.ext.eye_common import FOCUS
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_internal_echo_dispatch import echo
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, on_hold, table_fight


@pytest.mark.parametrize("lethal", [True, False])
@pytest.mark.parametrize("consumer", ["qi", "lurker"])
def test_echo_discards_the_entire_hook_reply_after_payment_and_cold_reload(tmp_path, monkeypatch, consumer, lethal):
    combat, table, mid = table_fight(tmp_path, [])
    asked, paid_at_echo, later = [], [], []
    feature = qi_tempered.FEATURE if consumer == "qi" else eye_second_pass.LURKER
    receipt_source = feature if consumer == "qi" else eye_second_pass.SOURCE
    pool, cost = (qi_tempered.QI, 2) if consumer == "qi" else (FOCUS, 1)
    row = {"feature_id": feature, "pb": 4}

    def accept(*args, **kwargs):
        asked.append(kwargs["feature_id"])
        return ["maintain" if consumer == "qi" else "lurker"]

    if consumer == "qi":
        monkeypatch.setattr(qi_tempered, "holder_row", lambda engine, actor: row if actor.entity_id == LEFT else None)
        monkeypatch.setattr(qi_tempered, "qi_powered_feature", lambda *args: "Test Qi feature")
        monkeypatch.setattr(qi_tempered, "context_of", lambda engine, roll: SimpleNamespace(
            kind="save", ability="CON", source_id=qi_tempered.CONCENTRATION,
            roller=engine.state.actors[LEFT], dc=15, total=12, succeeded=lambda: False))
        monkeypatch.setattr(qi_tempered, "ask", accept)
        point, handler = "d20_bonus", qi_tempered.tempered_save
    else:
        monkeypatch.setattr(riders14_eye, "rule", lambda engine, actor, kind:
                            row if actor.entity_id == LEFT and kind == "lurker" else None)
        monkeypatch.setattr(needle, "ask", accept)
        point, handler = "stealth_search_before_roll", eye_second_pass.lurker

    def observe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            actor = engine.state.actors[LEFT]
            paid_at_echo.append((actor.reaction_available, actor.resources[pool]))

    def later_hook(engine, *args):
        later.append(engine.state.actors[LEFT].current_hp > 0)
        return {"source_id": "test:later_bonus", "bonus": 2} if consumer == "qi" else "ADVANTAGE"

    ext._load()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])
    monkeypatch.setitem(ext._HOOKS, point, [handler, later_hook])
    initial = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT].resources[pool]
    assert initial >= cost

    # Commit the Echo/HP/hidden fixture first, then trigger from a cold session.
    def prepare(engine):
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if lethal:
            engine._commit_damage(actor, actor.current_hp - 1, "FORCE", "test:injury", RIGHT, None, reaction_depth=99)
        if consumer == "lurker":
            engine._apply_condition(actor, "condition:typed.hidden", "test:hide", LEFT,
                                    expires_on="UNTIL_REMOVED", data={"label": "Hidden"})
        echo(engine, actor, enemy)

    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    # Explicit cold load also verifies the evented setup before accepting the response.
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert any(c.condition_id.endswith("echoing") for c in cold.state.actors[LEFT].conditions.values())
    # Hold position already used the Action; the next fighter triggers the
    # response before Echo reaches the end of its source's next turn.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    asked.clear()
    paid_at_echo.clear()
    later.clear()

    def trigger(engine):
        asked_before, echo_before, later_before = len(asked), len(paid_at_echo), len(later)
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if consumer == "qi":
            from combat.roll_checkpoints import rewrite_d20

            original = engine.roller.raw_d20(modifier=0, actor_id=LEFT,
                                              reason="SAVE:system:combat.concentration:CON")
            result = rewrite_d20(engine, original)
            engine._record_roll(result)
            # Exercise the native checkpoint, which must dispatch each provider,
            # not just ext.run_strict. Later providers still modify this roll.
            assert result.natural_result == original.natural_result
            assert result.total == original.total + (2 if lethal else 6)
        else:
            from combat import stealth
            assert stealth.hidden(actor)
            modes = stealth.pending_search_modes(engine, enemy, actor, "system:combat.search")
            assert modes == ({"ADVANTAGE"} if lethal else {"DISADVANTAGE", "ADVANTAGE"})
        # The service predicts and then commits. Check each attempt separately;
        # the persisted journal below must contain exactly one actual benefit.
        assert asked[asked_before:] == [feature]
        assert paid_at_echo[echo_before:] == [(False, initial - cost)]
        assert later[later_before:] == [not lethal]

    on_hold(monkeypatch, trigger)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert asked and paid_at_echo and later
    assert (actor.current_hp == 0) is lethal
    assert actor.life_state == ("DYING" if lethal else None)
    assert not actor.reaction_available
    assert actor.resources[pool] == initial - cost
    assert not any(c.condition_id.endswith("echoing") for c in actor.conditions.values())
    effects = [e for e in loaded.engine.events if e.source_definition_id == receipt_source
               and e.event_type == ("PASSIVE_TRIGGERED" if consumer == "qi" else "REACTION_RESOLVED")
               and (consumer != "qi" or "adds their Proficiency Bonus" in str(e.payload))]
    assert len(effects) == (0 if lethal else 1)
    if consumer == "qi":
        bonuses = [e.source_definition_id for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
        assert bonuses == (["test:later_bonus"] if lethal else [feature, "test:later_bonus"])
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("runner", ["run", "run_strict", "iter_strict", "iter_strict_all"])
def test_scope_unwinds_through_nested_hook_to_its_own_dispatcher(monkeypatch, runner):
    from tests.test_internal_echo_interruption_consumers import _engine

    engine, _source, actor = _engine()
    reached = []
    ext._load()

    def interrupt(*args):
        typed_reactions.interrupt_reaction(engine, actor)

    def consumer(*args):
        with typed_reactions.reaction_resolution(engine, actor, "test:interrupted"):
            ext.run_strict("test:nested", engine)
        reached.append("fall-through bonus")
        return 99

    def later(*args):
        reached.append("later")
        return 2

    monkeypatch.setitem(ext._HOOKS, "test:nested", [interrupt])
    monkeypatch.setitem(ext._HOOKS, "test:outer", [consumer, later])
    replies = list(getattr(ext, runner)("test:outer", engine))
    assert replies == ([None, 2] if runner == "iter_strict_all" else [2])
    assert reached == ["later"]
