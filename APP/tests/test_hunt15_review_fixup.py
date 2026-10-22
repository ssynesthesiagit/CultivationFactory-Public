"""Review regressions for subscriber attribution and persisted selector lifetime."""
import pytest

from tests.hunt15_support import LEFT, RIGHT, act, action_sender, fight, reload, turn


def test_originating_event_stays_stable_across_nested_dispatch(monkeypatch):
    from tests.test_auto_tabik import _engine
    from tests.test_lock3_nested_events import subscribe

    seen = []
    def preceding(engine, kind, kwargs):
        if kind == "TEST_ROOT":
            engine._append_event("TEST_CHILD", "test:child")
    def observing(engine, kind, kwargs):
        event = kwargs["originating_event"]
        if kind in ("TEST_ROOT", "TEST_CHILD"):
            assert event.event_type == kind
            seen.append((kind, event.source_definition_id, event.sequence))
    subscribe(monkeypatch, preceding, observing)
    engine, _ = _engine([])
    engine._append_event("TEST_ROOT", "test:root")
    root, child = engine.events[-2:]
    assert seen == [("TEST_CHILD", "test:child", child.sequence),
                    ("TEST_ROOT", "test:root", root.sequence)]


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_originating_event_survives_ready_delivery_at_table(tmp_path, monkeypatch, ai, selection):
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.prepared_actions import CONDITION
    from tests.r10_fixup_support import cast_sender
    from tests.test_tabletop_hunt6 import table_fight, LEFT as keeper, RIGHT as attacker

    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian"}]}}
    combat, table, mid = table_fight(tmp_path, ["TAL_SNIPER_INTERCEPTING_SHOT"],
                                    kit=kit, ask=True, ally_talents=[])
    assert cast_sender(combat, table, mid, "Ready: Intercepting Shot (")()["status"] == "COMMITTED"
    prepared = CombatService(combat.source_root, tmp_path)._load_session(mid).engine
    assert any(c.condition_id == CONDITION for c in prepared.state.actors[keeper].conditions.values())
    turn(table, mid, attacker)
    engine = combat._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates()
                  if keeper in c.target_ids and c.source_definition_id in engine.action_catalog
                  and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("weapon")
                  and engine.action_catalog[c.source_definition_id].parameters["typed"].get("range_ft"))
    group = next(g for g in table.state(mid)["menu"]["actions"]
                 if g["source_definition_id"] == attack.source_definition_id)
    send = action_sender(combat, table, mid, group["label"], ai=ai, target_id=keeper)

    # Observe through the real dispatcher, without replacing Ready or any ability.
    # Keep assertions outside the hook, whose exceptions are intentionally logged.
    seen = []
    def observe(engine, kind, kwargs):
        if not engine._transaction_id or engine._active_intent is None:
            return
        event = kwargs["originating_event"]
        seen.append((kind, event.event_type, event.source_definition_id, event.sequence,
                     event.actor_id, kwargs.get("actor_id"), engine.events[-1].event_type,
                     engine.events[-1].sequence))
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], observe])
    monkeypatch.setitem(ext._NESTED_HOOKS, "event", {*ext._NESTED_HOOKS.get("event", ()), observe})
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "ready:sniper.intercepting_shot"
    assert attack.display_name in prompt["trigger"]
    assert "Left" in prompt["trigger"] and "Right" in prompt["trigger"]
    assert prompt["cost"] == "Reaction now; the Action to prepare was spent earlier"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answers = [{**prompt["context"], "selection": selection}]
    for _ in range(8):
        seen.clear()
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED"
    committed_seen = list(seen)
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    original = next(e for e in loaded.engine.events if e.event_type == "INTENT_ACCEPTED"
                    and e.actor_id == attacker and e.source_definition_id == attack.source_definition_id)
    delivered = [row for row in committed_seen if row[0] == "INTENT_ACCEPTED" and row[5] == attacker]
    # Table transport previews and then executes; both must report the same identity.
    assert delivered
    assert {row[:6] for row in delivered} == {(original.event_type, original.event_type, original.source_definition_id,
                                             original.sequence, attacker, attacker)}
    if selection == "USE":
        assert delivered[0][6] == "REACTION_RESOLVED" and delivered[0][7] > original.sequence
        assert not loaded.engine.state.actors[keeper].reaction_available
    else:
        assert delivered[0][7] == original.sequence
    assert any(c.condition_id == CONDITION for c in loaded.engine.state.actors[keeper].conditions.values()) == (selection == "DECLINE")
    # Every root/child delivery in the committed transaction carries the actual
    # recorded type, source, sequence and actor, including the Ready cascade.
    for kind, event_kind, source, sequence, actor, delivered_actor, _, _ in committed_seen:
        recorded = loaded.engine.events[sequence - 1]
        assert (kind, event_kind, source, actor) == (recorded.event_type, recorded.event_type,
                                                    recorded.source_definition_id, recorded.actor_id)
        assert actor == delivered_actor
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai", [False, True])
def test_record_keeps_original_action_when_charm_subscriber_appends(tmp_path, monkeypatch, ai):
    from combat import ext
    from combat.ext.charm_rules import after_event
    from combat.ext.karma_imprints import held

    # Imports elsewhere in the test process can register Karma early. Configure
    # the real Charm subscriber to precede it, as in alphabetical plug-in loading.
    ext.effects()
    subscribers = list(ext._HOOKS["event"])
    subscribers.remove(after_event)
    monkeypatch.setitem(ext._HOOKS, "event", [after_event, *subscribers])
    combat, table, mid = fight(tmp_path, ["TAL_KARMA_RECORD_THE_DEED"], effects=[
        {"type": "condition", "condition": "charmed", "applies_to": "self", "until_escape": True,
         "condition_data": {"bar": {"fragile": "any"}}},
        {"type": "damage", "damage_type": "PSYCHIC", "flat": 2, "applies_to": "target"},
    ], target="HOSTILE_ENTITY")
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup", target_id=RIGHT)["status"] == "COMMITTED"
    assert any(c.condition_id == "condition:typed.charmed"
               for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    turn(table, mid, RIGHT)
    assert any(c.condition_id == "condition:typed.charmed"
               for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    send = action_sender(combat, table, mid, "Test setup", ai=ai, target_id=LEFT)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Record the Deed"
    assert prompt["cost"] == "Reaction; no resource cost"
    assert "Visiting Fighter's Test setup" in prompt["trigger"]
    assert "meaningful damage to River Keeper" in prompt["trigger"]
    assert "the triggering effect" not in prompt["trigger"]
    assert send([{**prompt["context"], "selection": "USE"}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    damage = next(e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED"
                  and e.actor_id == RIGHT and LEFT in e.target_ids)
    removal = next(e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                   and e.source_definition_id == "system:bar.damaged" and LEFT in e.target_ids)
    assert removal.sequence > damage.sequence
    assert not any(c.condition_id == "condition:typed.charmed"
                   for c in engine.state.actors[LEFT].conditions.values())
    assert not engine.state.actors[LEFT].reaction_available
    assert held(engine.state.actors[RIGHT], LEFT, "debt")


@pytest.mark.parametrize("expression", ["Golden Bell Circulation", "Blood-Furnace Circulation", "Mountain-Rending Pulse"])
def test_core_tempering_hover_is_permanent_after_commit_reload(tmp_path, expression):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.bodya_body_refining import CHOICE_CONDITION, MR_CHOICE_CONDITION
    from tests.hunt10_support import ROOT, fight as body_fight, reload_equal

    service, session = body_fight(tmp_path)
    actor_id = session.engine.state.current_actor_id
    table = TabletopService(service, tmp_path)
    assert act(table, session.match_id, f"Core Tempering Expression: {expression}")["status"] == "COMMITTED"
    reload_equal(service, service._load_session(session.match_id))
    fresh_service = CombatService(ROOT, tmp_path)
    fresh_table = TabletopService(fresh_service, tmp_path)
    def status(condition):
        actor = next(a for a in fresh_table.state(session.match_id)["presentation"]["actors"]
                     if a["entity_id"] == actor_id)
        return next(c for c in actor["conditions"] if c["condition_id"] == condition)
    row = status(CHOICE_CONDITION)
    assert "permanent until a later Realm breakthrough" in row["detail"]
    assert "cannot change it during this fight" in row["detail"]
    assert "until you change it" not in row["detail"]
    assert expression in row["rule_text"]
    if expression == "Mountain-Rending Pulse":
        assert act(fresh_table, session.match_id, "Mountain-Rending: Push")["status"] == "COMMITTED"
        reload_equal(fresh_service, fresh_service._load_session(session.match_id))
        assert "until you change it" in status(MR_CHOICE_CONDITION)["detail"]
        assert "permanent until" not in status(MR_CHOICE_CONDITION)["detail"]
    assert fresh_service.verify(session.match_id)["status"] == "PASS"
    assert fresh_service.replay(session.match_id)["status"] == "PASS"
