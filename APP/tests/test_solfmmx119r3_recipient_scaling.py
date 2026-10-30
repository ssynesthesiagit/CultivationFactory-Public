"""Bound roll modifiers share their recipient's save/Evasion reduction, once.

Engine fixtures use seeded 1d2 damage and a real compiled Demon Mark.
Service fixtures use compiled Fireball Art and real table selection, commit and reload.
Only the Evasion decision provider is substituted; the executor resolves the reduction.
"""
import pytest

import test_mmx119f1_rider_attempt_isolation as f1
from combat import ext, typed_executor as ex
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService


@pytest.mark.parametrize("raw", [5, 6])
@pytest.mark.parametrize("pb", [3, 4])
@pytest.mark.parametrize("order", ["alone", "marked-first", "marked-last"])
@pytest.mark.parametrize("evasion", [False, True], ids=["half-save-success", "evasion-failure"])
def test_bound_bonus_is_reduced_with_its_recipient(monkeypatch, raw, pb, order, evasion):
    original_sheet = f1.owner_sheet
    def sheet():
        value = original_sheet()
        value["identity"]["proficiency_bonus"] = pb
        return value
    monkeypatch.setattr(f1, "owner_sheet", sheet)
    engine = f1._marked_engine()
    actor = engine.state.actors[f1.ACTOR]
    marked, other = engine.state.actors[f1.AN], engine.state.actors[f1.LEE]
    subjects = {"alone": [marked], "marked-first": [marked, other],
                "marked-last": [other, marked]}[order]
    damage = {**f1.AREA_DAMAGE, "dice": {"count": 1, "sides": 2}, "flat": raw - 1}
    save = {**f1.AREA_SAVE, "on_fail": [damage], "on_success": [{"type": "half_damage"}]}
    action = f1._action(f1.ACTOR, [save], area={"size_ft": 20, "shape": "circle"})
    f1._pin_saves(monkeypatch, 1 if evasion else 20)
    monkeypatch.setitem(ext._HOOKS, "evasion", [
        lambda ctx, subject, *args: True if evasion and subject.entity_id == marked.entity_id else None])
    for bonus in (pb, 0):
        start = len(engine.events)
        ctx = ex.Context(engine, actor, action, None, action.parameters["typed"], subjects, subjects[0])
        with ex.simultaneous(ctx, subjects):
            ex._save_each(ctx, save, subjects)
        events = engine.events[start:]
        rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
        assert len(rolls) == 1, [(e.event_type, e.payload) for e in events]
        full = rolls[0].payload["total"] - (bonus if order == "alone" else 0)
        assert full in (raw, raw + 1)
        packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
        assert len(packets) == len(subjects)
        dealt = {e.target_ids[0]: e.payload["hp_damage"] + e.payload["temporary_hp_absorbed"]
                 for e in packets}
        assert dealt[marked.entity_id] == (full + bonus) // 2
        if other in subjects:
            assert dealt[other.entity_id] == (full if evasion else full // 2)


@pytest.mark.parametrize("multiple", [False, True], ids=["one-foe", "two-foes"])
@pytest.mark.parametrize("evasion", [False, True], ids=["half-save-success", "evasion-failure"])
def test_table_area_recipient_scaling_survives_commit_reload(tmp_path, monkeypatch, multiple, evasion):
    original_sheet = f1.owner_sheet
    def sheet():
        value = original_sheet()
        value["spheres_and_talents"]["learned_talent_record_ids"].append("FIRE_TAL_FIREBALL_ART")
        return value
    monkeypatch.setattr(f1, "owner_sheet", sheet)
    create = CombatService.create_factory_match
    def create_match(self, **kwargs):
        if multiple:
            kwargs["opponent_actor_ids"].append(f1.AN)
            kwargs["control_modes"][f1.AN] = "MANUAL"
        return create(self, **kwargs)
    monkeypatch.setattr(CombatService, "create_factory_match", create_match)
    combat, table, mid = f1.table_fight(tmp_path, monkeypatch)
    assert f1.use_button(table, mid, f1.MINE, "DEMON_MARK")["status"] == "COMMITTED"
    # Reload the real mark before the next table transaction.
    combat = CombatService(f1.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    def saves(engine, roll, intent):
        if "SAVE" in str(roll.reason).upper():
            return {"source_id": "test:mmx119r3.save", "operation": "replace",
                    "natural_result": 1 if evasion else 20}
    monkeypatch.setitem(ext._HOOKS, "d20_result", [saves])
    monkeypatch.setitem(ext._HOOKS, "evasion", [
        lambda ctx, subject, *args: True if evasion and subject.entity_id == f1.FOE else None])
    seq = combat._load_session(mid).engine.state.event_sequence
    def select_fireball(state):
        menu = state["menu"]
        group = next(g for g in menu["actions"] if "FIREBALL_ART" in g["source_definition_id"])
        # Aim the sphere at the marked creature, rather than the first legal map cell.
        option = next(o for o in group["options"] if (o.get("destination") or {}).get("x") == 4
                      and (o.get("destination") or {}).get("y") == 4)
        return menu, option
    state = table.state(mid)
    menu, option = select_fireball(state)
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    answers = []
    for _ in range(10):
        if result["status"] != "REACTION_REQUIRED":
            break
        context = result["reaction"]["context"]
        answers.append({**context, "selection": "DECLINE", "spend": 0, "option_ids": []})
        state = table.state(mid)
        menu, option = select_fireball(state)
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    session = CombatService(f1.ROOT, tmp_path)._load_session(mid)
    events = [e for e in session.engine.events if e.sequence > seq]
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == f1.MINE]
    assert len(rolls) == 1
    total = rolls[0].payload["total"]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == f1.MINE]
    dealt = {e.target_ids[0]: e.payload["hp_damage"] + e.payload["temporary_hp_absorbed"]
             for e in packets}
    # Fireball also reaches the caster on this close-quarters map, so its roll is shared.
    assert f1.FOE in dealt, {"dealt": dealt, "positions": {k: v.position for k, v in session.engine.state.actors.items()}}
    assert dealt[f1.FOE] == (total + f1.PB) // 2
    if multiple:
        assert dealt[f1.AN] == (total if evasion else total // 2)
    assert len([e for e in packets if f1.FOE in e.target_ids]) == 1
    actor = session.engine.state.actors[f1.MINE]
    rider = next(m for m in actor.modifiers.values() if m.target_field == "typed_on_hit")
    evidence = str(rider.value).split("|", 2)[1]
    key, turn = ex.on_hit_turn_key(session.engine, actor, rider.source_definition_id, evidence)
    assert actor.turn_flags[key] == turn, "the spent bound-rider use must survive the table reload"
    assert session.mechanical.replay()["status"] == "PASS"
