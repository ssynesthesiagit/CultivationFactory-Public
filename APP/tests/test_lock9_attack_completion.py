"""Source-backed post-attack contracts; full ability eligibility remains rider-owned."""
from dataclasses import FrozenInstanceError

import pytest

from combat import ext, typed_executor as te, typed_reactions as tr
from combat.attack_completion import notify
from combat.ext import needle
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService, CombatServiceError
from tests.h1_support import ROOT, ME, FOE, ALLY as H1_ALLY, duel, script, attack
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT
from tests.r10_fixup_support import answer

REPRISAL = "TAL_GUARDIAN_GUARDIAN_S_REPRISAL"
SOVEREIGN = "TAL_SWORD_SWORD_SOVEREIGN_INCARNATION"
READY = "condition:typed.test_reprisal_ready"


def install(monkeypatch, *providers):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, "attack_completed", list(providers))


def counter(engine, owner, attacker, intent, source):
    row = tr._opportunity_row(engine, owner)
    action = engine.action_catalog[row["action_id"]].model_copy(update={"source_definition_id": source})
    typed = {**action.parameters["typed"], "reaction_attack": True}
    ctx = te.Context(engine, owner, action, intent, typed, [attacker], attacker)
    # Reprisal's ordinary attack plus its printed 2d8; the Sword response uses
    # its ordinary attack. Other ability clauses are deliberately not automated.
    hit = [{"type": "damage", "weapon_damage": True}]
    if source == REPRISAL:
        hit.append({"type": "damage", "dice": {"count": 2, "sides": 8}, "damage_types": ["bludgeoning"]})
    kind = "unarmed" if typed.get("source") == "unarmed_strike" else "weapon"
    te.block_attack(ctx, {"type": "attack", "attack_kind": kind, "count": 1, "on_hit": hit})


@pytest.mark.parametrize("feature,hit,rolls", [(REPRISAL, True, [10, 1, 12, 1, 1, 1]),
                                              (SOVEREIGN, False, [1, 12, 1, 1])])
def test_legacy_attack_then_legal_followup_without_recursive_checkpoint(monkeypatch, feature, hit, rolls):
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1}]}}
    e = duel([feature], cl=20, kit=kit if feature == SOVEREIGN else None)
    owner, attacker = e.state.actors[ME], e.state.actors[FOE]
    if feature == SOVEREIGN:
        e._apply_condition(attacker, te.mark_condition_id("Sword Intent", ME), feature, ME, expires_on="END_OF_CURRENT_TURN")
    else:
        owner.reaction_available = False  # the earlier Interpose has resolved
    seen = []
    def response(engine, notice, intent):
        seen.append(notice)
        assert notice.hit is hit and notice.attacker_id == FOE and notice.target_id == ME
        assert notice.source_id == "test:incoming" and notice.melee
        with pytest.raises(FrozenInstanceError):
            notice.hit = not hit
        if feature == SOVEREIGN:
            assert owner.reaction_available and te.bears_mark(attacker, ME, "Sword Intent")
            owner.reaction_available = False
            engine._append_event("REACTION_RESOLVED", feature, actor_id=ME, target_ids=(FOE,))
        else:
            assert not owner.reaction_available
            engine._spend_resource(owner, "resource:core.martial_focus", 1, feature)
        counter(engine, owner, attacker, intent, feature)
    install(monkeypatch, response)
    script(e, rolls)
    before = len(e.events)
    assert attack(e, FOE, ME, bonus=100 if hit else 0, source_id="test:incoming") is hit
    attacks = [ev for ev in e.events[before:] if ev.event_type == "ATTACK_ROLLED"]
    assert [ev.actor_id for ev in attacks] == [FOE, ME]
    assert len(seen) == 1 and not getattr(e, "_attack_completion_active", False)


def test_typed_damageless_attack_finishes_its_on_hit_riders_before_reply(monkeypatch):
    e = duel([REPRISAL], cl=20, ally_mids=[])
    owner, attacker = e.state.actors[ME], e.state.actors[H1_ALLY]
    seen = []
    def response(engine, notice, intent):
        assert attacker.temporary_hp == 7  # the original attack's last on-hit rider
        seen.append(notice)
        counter(engine, owner, attacker, intent, REPRISAL)
    install(monkeypatch, response)
    action = next(a for a in e.action_catalog.values() if a.owner_id == H1_ALLY)
    typed = {"source": "test:touch", "numbers": {"attack_bonus": 100}, "range_ft": None}
    ctx = te.Context(e, attacker, action, None, typed, [owner], owner)
    script(e, [10, 12, 1, 1, 1])
    start = len(e.events)
    te.block_attack(ctx, {"type": "attack", "attack_kind": "cultivation", "no_damage": True,
                         "on_hit": [{"type": "temp_hp", "flat": 7, "applies_to": "self"}]})
    events = e.events[start:]
    assert len(seen) == 1 and seen[0].hit
    grant = next(i for i, ev in enumerate(events) if ev.event_type == "TEMP_HP_GRANTED")
    reply = next(i for i, ev in enumerate(events) if ev.event_type == "ATTACK_ROLLED" and ev.actor_id == ME)
    assert grant < reply


@pytest.mark.parametrize("multiple_targets", [False, True])
def test_typed_extra_attacks_stop_if_response_incapacitates_attacker(monkeypatch, multiple_targets):
    e = duel([], ally_mids=[])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    def response(engine, notice, intent):
        engine._apply_condition(actor, "condition:typed.incapacitated", "test:reply", FOE, expires_on="UNTIL_REMOVED")
    install(monkeypatch, response)
    action = next(a for a in e.action_catalog.values() if a.owner_id == ME)
    targets = [target, e.state.actors[H1_ALLY]] if multiple_targets else [target]
    ctx = te.Context(e, actor, action, None, {"numbers": {"attack_bonus": 100}, "range_ft": None}, targets, target)
    script(e, [10] * 10)
    before = len(e.events)
    te.block_attack(ctx, {"type": "attack", "attack_kind": "cultivation", "no_damage": True, "count": 2})
    assert len([ev for ev in e.events[before:] if ev.event_type == "ATTACK_ROLLED"]) == 1


def test_terminal_response_stops_later_providers_and_restores_scope(monkeypatch):
    e = duel([])
    called = []
    def finish(engine, notice, intent):
        called.append("first")
        engine._commit_damage(engine.state.actors[FOE], 10000, "FORCE", "test:finish", ME, None, reaction_depth=1)
    install(monkeypatch, finish, lambda *a: called.append("second"))
    script(e, [10, 1])
    attack(e, FOE, ME, bonus=100)
    assert called == ["first"] and e.state.terminal_result is not None
    assert not getattr(e, "_attack_completion_active", False)
    assert notify(e, e.state.actors[ME], e.state.actors[FOE], {}, None, "test:late", True) is False


def test_notice_uses_resolved_target_and_skips_final_rider_scope(monkeypatch):
    e = duel([], ally_mids=[])
    seen = []
    install(monkeypatch, lambda engine, notice, intent: seen.append(notice))
    assert notify(e, e.state.actors[FOE], e.state.actors[ME], {"resolved_target_id": H1_ALLY}, None, "test:redirect", True)
    assert seen[0].target_id == H1_ALLY
    e._final_rider_active = True
    assert notify(e, e.state.actors[FOE], e.state.actors[ME], {}, None, "test:final", True) is False
    assert len(seen) == 1


@pytest.mark.parametrize("use", [True, False])
@pytest.mark.parametrize("portable", [False, True])
def test_reprisal_after_spent_interpose_reaction_pauses_then_reloads(monkeypatch, tmp_path, use, portable):
    combat, table, mid = table_fight(tmp_path, [REPRISAL], ally_talents=[])
    def response(engine, notice, intent):
        owner = engine.state.actors[LEFT]
        if notice.source_id != "test:incoming":
            return
        assert not owner.reaction_available  # Interpose already spent it; Reprisal spends Focus instead
        assert any(c.condition_id == READY for c in owner.conditions.values())
        picked = needle.ask(engine, intent, "ATTACK_COMPLETED", owner, "choice:needle.lock9_reprisal", ["attack"],
                            labels={"attack": "Spend Martial Focus and strike back"}, name="Guardian's Reprisal",
                            prompt="Spend Martial Focus to strike back at Right after its attack?",
                            target_id=RIGHT, automatic=False, allow_decline=True)
        if not picked:
            return
        engine._remove_condition(owner, READY, REPRISAL)
        engine._spend_resource(owner, "resource:core.martial_focus", 1, REPRISAL)
        counter(engine, owner, engine.state.actors[RIGHT], intent, REPRISAL)
    install(monkeypatch, response)
    def incoming(engine):
        owner = engine.state.actors[LEFT]
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", "test:interpose", actor_id=LEFT, target_ids=(RIGHT,))
        engine._apply_condition(owner, READY, REPRISAL, LEFT, expires_on="END_OF_CURRENT_TURN")
        script(engine, [10, 1, 12, 1, 1, 1])
        if portable:
            from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
            CharacterCombatRuntimeEngine._resolve_character_attack(engine, engine.state.actors[RIGHT], owner,
                source_id='test:incoming', attack_bonus=100, damage=DiceSpec(count=1, sides=4),
                damage_type='BLUDGEONING', intent=engine._active_intent, ranged=False)
        else:
            engine._resolve_attack_spec(engine.state.actors[RIGHT], owner,
                {"attack_bonus": 100, "reach_ft": 5, "damage": DiceSpec(count=1, sides=4), "damage_type": "BLUDGEONING"},
                engine._active_intent, source_definition_id="test:incoming")
    on_hold(monkeypatch, incoming)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    def send(answers=()):
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(paused["reaction"], use=use)])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[LEFT]
    assert owner.resources["resource:core.martial_focus"] == (0 if use else 1)
    assert not owner.reaction_available
    assert len([ev for ev in loaded.engine.events if ev.event_type == "ATTACK_ROLLED" and ev.source_definition_id == REPRISAL]) == int(use)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_invalid_completion_reply_rolls_back_original_attack(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    install(monkeypatch, lambda *a: True)
    def incoming(engine):
        engine._resolve_attack_spec(engine.state.actors[RIGHT], engine.state.actors[LEFT],
            {"attack_bonus": 100, "reach_ft": 5, "damage": DiceSpec(count=1, sides=4), "damage_type": "FORCE"},
            engine._active_intent, source_definition_id="test:invalid")
    on_hold(monkeypatch, incoming)
    from tests.test_lock2_persistence import act
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    with pytest.raises(CombatServiceError):
        act(table, mid, HOLD)
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
