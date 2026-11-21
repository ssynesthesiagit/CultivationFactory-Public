"""Bloodless Devouring must wait for paid positive damage at the table boundary."""

import pytest

from tests.test_auto_martial import SPEAR_KIT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight
from tests.h1_support import ROOT
from combat.gate5_service import CombatService
from combat import typed_executor

SOURCE = "TAL_DAEMONIC_CULTIVATION_BLOODLESS_DEVOURING"
ESSENCE = "resource:named.devoured_essence"
HOLD = "system:combat.hold_position"


def _install_hit(monkeypatch, *, hp=20, hits=1, essence=1):
    """Deliver real typed damage during an accepted table action, through the normal damage hook."""
    from combat.gate4_engine import Gate4ControllerEngine
    original = Gate4ControllerEngine._append_event
    done = set()

    def append(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "HOLD_POSITION_COMMITTED" and id(engine) not in done:
            done.add(id(engine))
            actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
            if int(actor.resources.get(ESSENCE, 0)) < 1:
                engine._gain_resource(actor, ESSENCE, essence, SOURCE)
            stamina = "resource:core.stamina"
            # Reducing Corruption needs an actual point to remove, not only an
            # eligible creature. Commit it as fixture setup before the hit.
            engine._gain_resource(actor, "resource:named.corruption", 1, SOURCE)
            if actor.resources.get(stamina, 0) > 0:
                engine._spend_resource(actor, stamina, 1, SOURCE)
            engine._commit_damage(actor, 10, "FORCE", "test:setup", RIGHT, None, reaction_depth=0)
            if target.current_hp > hp:
                engine._commit_damage(target, target.current_hp - hp, "FORCE", "test:setup", RIGHT, None,
                                      reaction_depth=0)
            action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT
                          and any(effect.get("type") == "attack"
                                  for effect in (((a.parameters or {}).get("typed") or {}).get("effects") or [])))
            ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                         {"numbers": {"pb": 5, "key_mod": 3}}, [target], target, {})
            for _ in range(hits):
                typed_executor._deal(ctx, target, 1, "FORCE")
        return result

    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", append)


def _hold(table, match_id, answers=()):
    state = table.state(match_id)
    menu = state["menu"]
    cid = next(option["candidate_id"] for group in menu["actions"] if group["source_definition_id"] == HOLD
               for option in group["options"])
    return table.act(match_id, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def _answer(table, match_id, result, choice):
    prompt = result["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [choice]}
    state, menu = result["state"], result["state"]["menu"]
    cid = next(option["candidate_id"] for group in menu["actions"] if group["source_definition_id"] == HOLD
               for option in group["options"])
    return table.act(match_id, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])


def test_bloodless_requires_eligible_damage_and_essence_through_table_reload(tmp_path):
    service, table, match_id = table_fight(tmp_path, [SOURCE], kit=SPEAR_KIT)
    session = service._load_session(match_id)
    actor = session.engine.state.actors[LEFT]
    assert actor.resources.get("resource:named.devoured_essence", 0) == 0
    assert any(row.get("block") == "bloodless_devouring"
               for row in session.engine.typed_passive_rows.get(LEFT, []))

    menu = table.state(match_id)["menu"]
    engine = service._load_session(match_id).engine
    targets = []
    for group in menu["actions"]:
        action = engine.action_catalog.get(group["source_definition_id"])
        if action is None or not any(row.get("type") == "attack" for row in (action.parameters.get("typed") or {}).get("effects", [])):
            continue
        targets.extend(option for option in group["options"] if RIGHT in option["target_ids"])
    assert targets
    option = max(targets, key=lambda row: row.get("expected_damage") or 0)
    result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       table.state(match_id)["last_sequence"], [])
    assert result["status"] == "COMMITTED"

    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert any(event.event_type == "DAMAGE_COMMITTED" and event.actor_id == LEFT and RIGHT in event.target_ids
               and int(event.payload.get("hp_damage") or 0) > 0 for event in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert not any(event.event_type == "REACTION_RESOLVED" and event.source_definition_id == SOURCE
                   for event in loaded.engine.events)


def test_bloodless_hp_choice_commits_cost_and_healing_through_reload(monkeypatch, tmp_path):
    _install_hit(monkeypatch)
    combat, table, match_id = table_fight(tmp_path, [SOURCE], primary="Stamina", foe_types=("demonic",))
    first = _hold(table, match_id)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert "Bloodless Devouring" in prompt["trigger"]
    assert "Improvised weapon attack" in prompt["trigger"] and "Right" in prompt["trigger"]
    options = {row["id"]: row["label"] for row in prompt["choice"]["options"]}
    assert set(options) == {"hp", "resource:core.stamina", "temporary_hp", "corruption", "skip"}
    assert "regain 6 HP" in options["hp"]
    assert "regain 1 Stamina" in options["resource:core.stamina"]
    assert "gain 8 Temporary HP" in options["temporary_hp"]
    assert "reduce Corruption by 1" in options["corruption"]
    committed = _answer(table, match_id, first, "hp")
    assert committed["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.resources[ESSENCE] == 0
    assert actor.current_hp == 56  # 10 setup damage, then 6 HP from its own compiled printed formula
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bloodless_once_per_turn_and_threshold_through_table_reload(monkeypatch, tmp_path):
    _install_hit(monkeypatch, hp=29, hits=2, essence=2)
    combat, table, match_id = table_fight(tmp_path, [SOURCE])
    first = _hold(table, match_id)
    assert first["status"] == "REACTION_REQUIRED"
    # Spend once; the second qualifying hit in the same accepted action cannot ask again.
    committed = _answer(table, match_id, first, "hp")
    assert committed["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.engine.state.actors[LEFT].resources[ESSENCE] == 1
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    # A new actual turn reopens the once-per-turn choice.
    assert act(table, match_id, "end")["status"] == "COMMITTED"
    for _ in range(4):
        if table.state(match_id)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    second = _hold(table, match_id)
    assert second["status"] == "REACTION_REQUIRED"
    assert _answer(table, match_id, second, "hp")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.engine.state.actors[LEFT].resources[ESSENCE] == 0
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bloodless_does_not_offer_at_half_hp(monkeypatch, tmp_path):
    _install_hit(monkeypatch, hp=30)
    combat, table, match_id = table_fight(tmp_path, [SOURCE])
    result = _hold(table, match_id)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == SOURCE
                   for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bloodless_ai_owner_automatically_uses_and_pays_once(monkeypatch, tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter

    _install_hit(monkeypatch)
    combat, table, match_id = table_fight(tmp_path, [SOURCE], foe_types=("demonic",))
    combat.set_controller_mode(match_id, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    real_controller = combat.controller

    class HoldController:
        def choose_primary_action(self, context):
            hold = next(row for row in context.legal_candidates if row.source_definition_id == HOLD)
            return ManualControllerAdapter(lambda _context: (hold.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real_controller, name)

    combat.controller = HoldController()
    state = table.state(match_id)
    result = table.auto_step(match_id, state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.resources[ESSENCE] == 0
    assert actor.current_hp == 56
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("kinds,eligible", [
    (("demonic",), True), (("undead",), True), (("fiend",), True), (("possessing",), True),
    ((), False), (("beast",), False),
])
def test_bloodless_corruption_requires_explicit_eligible_creature_type(monkeypatch, tmp_path, kinds, eligible):
    _install_hit(monkeypatch)
    combat, table, match_id = table_fight(tmp_path, [SOURCE], foe_types=kinds)
    first = _hold(table, match_id)
    assert first["status"] == "REACTION_REQUIRED"
    option_ids = {row["id"] for row in first["reaction"]["choice"]["options"]}
    assert ("corruption" in option_ids) is eligible
    committed = _answer(table, match_id, first, "corruption" if eligible else "hp")
    assert committed["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
