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
        later.append(engine.state.actors[LEFT].active)
        return "later hook"

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

    def trigger(engine):
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if consumer == "qi":
            replies = ext.run_strict(point, engine, SimpleNamespace(natural_result=10), None)
            expected = {"source_id": feature, "bonus": 4}
        else:
            from combat import stealth
            assert stealth.hidden(actor)
            replies = ext.run(point, engine, enemy, actor, "system:combat.search")
            expected = "DISADVANTAGE"
        assert replies == (["later hook"] if lethal else [expected, "later hook"])

    on_hold(monkeypatch, trigger)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert asked == [feature]
    assert paid_at_echo == [(False, initial - cost)]
    assert later == [not lethal]
    assert actor.active is not lethal and not actor.reaction_available
    assert actor.resources[pool] == initial - cost
    assert not any(c.condition_id.endswith("echoing") for c in actor.conditions.values())
    effects = [e for e in loaded.engine.events if e.source_definition_id == receipt_source
               and e.event_type == ("PASSIVE_TRIGGERED" if consumer == "qi" else "REACTION_RESOLVED")
               and (consumer != "qi" or "adds their Proficiency Bonus" in str(e.payload))]
    assert len(effects) == (0 if lethal else 1)
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
