"""Ally damage transfers resolve only after the shared Reaction commitment boundary."""

import pytest

from combat import ext
from combat.ext import drum_body
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests.test_internal_echo_dispatch import echo
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, RIGHT, on_hold, table_fight

REDIRECT = "test:redirect_reaction"
INCOMING = "test:incoming_damage"
QI = "resource:core.qi"


@pytest.mark.parametrize("cost", [0, 1], ids=["costless", "paid"])
@pytest.mark.parametrize("echoing,hp", [(False, 1), (True, 1), (True, 40), (True, 12)],
                         ids=["lethal-transfer", "lethal-echo", "surviving-echo", "lethal-transfer-after-echo"])
def test_redirection_commits_before_damage_and_survives_cold_reload(tmp_path, monkeypatch, cost, echoing, hp):
    combat, table, mid = table_fight(tmp_path, [])

    def prepare(engine):
        protector = engine.state.actors[LEFT]
        engine._commit_damage(protector, protector.current_hp - hp, "FORCE", "test:injury",
                              RIGHT, None, reaction_depth=99)
        if echoing:
            echo(engine, protector, engine.state.actors[RIGHT])

    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"

    # Both the injury and Echo are persisted before the triggering table action.
    cold = CombatService(ROOT, tmp_path)
    table = TabletopService(cold, tmp_path)
    # Hold position is once per turn. Trigger damage on the next actor\'s turn,
    # before Echo can reach the end of its source\'s next turn.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    before = cold._load_session(mid).engine
    assert before.state.actors[LEFT].current_hp == hp
    assert any(c.condition_id == drum_body.ECHOING
               for c in before.state.actors[LEFT].conditions.values()) is echoing
    ally_hp = before.state.actors[ALLY].current_hp
    qi = before.state.actors[LEFT].resources[QI]
    start = len(before.events)
    at_echo = []
    row = {"block": "generic", "feature_id": REDIRECT, "name": "Take an ally's damage",
           "kind": "ally_damaged", "range_ft": 60,
           "costs": [{"resource_id": QI, "amount": cost}] if cost else [],
           "effects": [{"type": "redirect_damage_to_self"}]}

    def rows(engine, actor_id, block, existing):
        if actor_id == LEFT and block == "generic":
            return [*existing, row]
        return None

    def observe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and kwargs.get("source_definition_id") == drum_body.PREFIX + "internal_echo":
            owner = engine.state.actors[LEFT]
            transferred = [e for e in engine.events[start:]
                           if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == REDIRECT]
            at_echo.append((owner.reaction_available, owner.resources[QI], len(transferred)))

    ext._load()
    monkeypatch.setitem(ext._HOOKS, "reaction_rows", [*ext._HOOKS.get("reaction_rows", []), rows])
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])

    def damage(engine):
        script(engine, [1] * 40)  # Echo is exactly 3 Thunder damage.
        engine._commit_damage(engine.state.actors[ALLY], 9, "FORCE", INCOMING,
                              RIGHT, engine._active_intent, reaction_depth=0)

    on_hold(monkeypatch, damage)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    protector, ally = engine.state.actors[LEFT], engine.state.actors[ALLY]
    interrupted = echoing and hp == 1
    assert protector.current_hp == max(0, hp - (3 if echoing else 0) - (0 if interrupted else 9))
    assert ally.current_hp == ally_hp - (9 if interrupted else 0)
    assert protector.resources[QI] == qi - cost
    assert protector.reaction_available is False
    assert not any(c.condition_id == drum_body.ECHOING for c in protector.conditions.values())
    assert at_echo == ([(False, qi - cost, 0)] if echoing else [])

    events = engine.events[start:]
    transfers = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == REDIRECT]
    ally_damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == INCOMING]
    resolved = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == REDIRECT]
    assert len(transfers) == len(resolved) == (0 if interrupted else 1)
    assert sum(e.payload["hp_damage"] for e in ally_damage) == (9 if interrupted else 0)
    if transfers:
        assert transfers[0].target_ids == (LEFT,)
        assert transfers[0].payload["rolled_or_pending_damage"] == 9
        assert resolved[0].payload["pending_after"] == 0
    assert not any(e.event_type == "GM_RIDER" and e.source_definition_id == REDIRECT for e in events)
    assert loaded.mechanical.replay()["status"] == "PASS"
