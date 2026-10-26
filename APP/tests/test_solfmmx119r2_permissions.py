"""SOLFMMX119r2: folding retains vetoes, trigger qualification and saved use clocks.

Synthetic engine rows isolate permission/clock/source contracts. The table test selects
a real compiler-produced Pursuit Spear option and commits twice across a fresh reload.
Its test-only technique_used subscriber grants another Action to isolate same-turn
consumption; it changes no compiled effect, engine method or production rule.
"""
import copy

import pytest

import test_mmx119f1_rider_attempt_isolation as f1
from combat import ext
from combat.effect_eligibility import modifier_key
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService


def _augment():
    engine, actor, foe, action = f1._augment()
    return engine, actor, foe, action.model_copy(update={"parameters": copy.deepcopy(action.parameters)})


def test_confirmed_loadout_follows_redirection_and_spends_its_clock(monkeypatch):
    from combat.ext.attack_modifiers import CONDITION
    from combat.gate2_runtime_models import Position
    engine = f1._engine()
    actor = engine.state.actors[f1.ACTOR]
    declared, actual = engine.state.actors[f1.AN], engine.state.actors[f1.LEE]
    actual.position = next(spot for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        if (spot := Position(x=actor.position.x + dx, y=actor.position.y + dy)) != declared.position
        and engine.grid.placement_legal(spot, footprint=engine._footprint(actual),
                                       occupied_cells=engine._occupied_cells_except(actual.entity_id))
        and engine._line_of_sight_actor_to_actor(actor, actual.model_copy(update={"position": spot})))
    action = f1._action(f1.ACTOR, [f1._strike()], weapon=f1.WEAPON)
    row = copy.deepcopy(f1.AUGMENT_ROW)
    group = {"id": "test:redirect_bonus", "name": "Test bonus", "options": [
        {"id": "0", "label": "Damage bonus", "effects": [row], "payments": [[]]}]}
    action.parameters["typed"]["attack_modifier_loadout"] = [group]
    engine.action_catalog[action.source_definition_id] = action
    engine._apply_condition(actor, CONDITION, "test:setting", actor.entity_id, expires_on="UNTIL_REMOVED",
        data={"family": action.source_definition_id, "modifier": group["id"], "on": 1,
              "option": "0", "payment": "0", "damage": "ask"})
    def redirect(engine_, attacker, defender, intent, context):
        if attacker.entity_id == actor.entity_id and defender.entity_id == declared.entity_id:
            return {"source_id": "test:redirect", "target_id": actual.entity_id, "cover_bonus": 0}
    monkeypatch.setitem(ext._HOOKS, "retarget_attack", [*ext.subscribers("retarget_attack"), redirect])
    f1._pin_attack(monkeypatch, [20, 20])
    hp_before = declared.current_hp
    for expected in (f1.BASE_MODIFIER + f1.PB, f1.BASE_MODIFIER):
        start = len(engine.events)
        f1._hit(engine, actor, action, [declared])
        rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
                 and e.actor_id == actor.entity_id]
        packets = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"]
        assert len(rolls) == len(packets) == 1
        assert rolls[0].target_ids == packets[0].target_ids == (actual.entity_id,)
        assert rolls[0].payload["modifier"] == expected
        assert packets[0].payload["damage_type"] == "BLUDGEONING"
        assert declared.current_hp == hp_before
        assert actor.turn_flags[modifier_key(row)] is True


@pytest.mark.parametrize("veto", ["effect", "recipient"])
def test_vetoed_sibling_preserves_damage_and_use_gate_contract(monkeypatch, veto):
    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    row["once_per_turn"] = "test:damage"
    row["once_per_fight"] = "test:fight"
    ext.effects()
    if veto == "effect":
        from combat.ext.effect_denial import CONDITION
        engine._apply_condition(actor, CONDITION, "test:denial", actor.entity_id,
                               expires_on="END_OF_HOLDER_NEXT_TURN",
                               data={"effect_types": ["extra_damage"]})
    else:
        def deny(ctx, effect, subject):
            return False if effect is row and subject.entity_id == foe.entity_id else None
        monkeypatch.setitem(ext._HOOKS, "effect_subject_allowed",
                            [*ext.subscribers("effect_subject_allowed"), deny])
    steps = f1._hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in f1._rolls(steps, foe.entity_id)] == [0]
    assert len(f1._dealt(steps, foe.entity_id)) == 1
    # Ordinary execution consumes clocks before filtering individual recipients.
    # An effect veto stops before clocks; a subject-only veto retains that contract.
    expected = veto == "recipient"
    assert bool(actor.turn_flags.get(modifier_key(row))) is expected
    assert bool(actor.turn_flags.get("typed_once_turn:test:damage")) is expected
    assert bool(actor.turn_flags.get("typed_round_once:test:fight")) is expected


def test_conditional_deferred_sibling_is_registered_without_an_immediate_bonus():
    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    row.update(deferred=True, once_per_turn="test:cadence",
               evidence="once per turn when you hit it with an approved weapon, add Proficiency Bonus to the damage")
    action.parameters["typed"]["duration"] = {"kind": "rounds", "amount": 1}
    steps = f1._hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in f1._rolls(steps, foe.entity_id)] == [0]
    assert len(f1._dealt(steps, foe.entity_id)) == 1
    assert any(m.target_field == "typed_on_hit" for m in actor.modifiers.values())
    assert not actor.turn_flags.get("typed_once_turn:test:cadence")
    assert not actor.turn_flags.get(modifier_key(row))


@pytest.mark.parametrize("clock,prefix", [("once_per_turn", "typed_once_turn"),
                                         ("once_per_fight", "typed_round_once")])
@pytest.mark.parametrize("already_spent", [False, True])
def test_damage_use_clocks_are_checked_and_recorded(clock, prefix, already_spent):
    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    row.pop("modifier_once")
    row[clock] = "test:clock"
    key = f"{prefix}:test:clock"
    if already_spent:
        actor.turn_flags[key] = True
    first = f1._hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in f1._rolls(first, foe.entity_id)] == [0 if already_spent else f1.PB]
    assert len(f1._dealt(first, foe.entity_id)) == 1
    assert actor.turn_flags[key] is True
    second = f1._hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in f1._rolls(second, foe.entity_id)] == [0]
    assert len(f1._dealt(second, foe.entity_id)) == 1


def _custom_mark(engine, *, owner_turn=False, flat=False):
    actor = engine.state.actors[f1.ACTOR]
    modifier = next(m for m in actor.modifiers.values() if m.target_field == "typed_on_hit")
    action = engine.action_catalog[modifier.source_definition_id]
    parameters = copy.deepcopy(action.parameters)
    parameters["typed"]["numbers"]["pb"] = 7  # triggering action still has PB 4
    def change(rows):
        for row in rows or []:
            if row.get("type") == "extra_damage" and row.get("deferred"):
                row.update(formula="none" if flat else "double_pb", flat=3 if flat else 2,
                           evidence=("during each of your turns" if owner_turn else "once per turn")
                           + " when you damage it, add a bonus to the damage")
                modifier.value = f"{f1.AN}|{row['evidence']}"
            for branch in ("effects", "on_fail", "on_success", "on_hit", "on_miss"):
                change(row.get(branch))
    change(parameters["typed"]["effects"])
    engine.action_catalog[action.source_definition_id] = action.model_copy(update={"parameters": parameters})
    return actor


def test_attack_reservations_do_not_fold_two_rows_sharing_one_damage_clock(monkeypatch):
    engine, actor, foe, _ = _augment()
    row = {**f1.AUGMENT_ROW, "once_per_turn": "test:shared"}
    row.pop("modifier_once")
    action = f1._action(actor.entity_id, [f1._strike(), row, dict(row)], weapon=f1.WEAPON)
    f1._pin_attack(monkeypatch, [20])
    steps = f1._hit(engine, actor, action, [foe])
    assert [r["modifier"] - f1.BASE_MODIFIER for r in f1._rolls(steps, foe.entity_id)] == [f1.PB]
    assert len(f1._dealt(steps, foe.entity_id)) == 1
    assert actor.turn_flags["typed_once_turn:test:shared"] is True


@pytest.mark.parametrize("flat,expected", [(True, 3), (False, 16)])
def test_armed_row_uses_its_amount_and_source_numbers(monkeypatch, flat, expected):
    engine = f1._marked_engine()
    actor = _custom_mark(engine, flat=flat)
    foe = engine.state.actors[f1.AN]
    f1._pin_attack(monkeypatch, [20])
    steps = f1._hit(engine, actor, f1._action(f1.ACTOR, [f1._strike()], weapon=f1.WEAPON), [foe])
    assert [r["modifier"] - f1.BASE_MODIFIER for r in f1._rolls(steps, foe.entity_id)] == [expected]
    assert len(f1._dealt(steps, foe.entity_id)) == 1


@pytest.mark.parametrize("owners_turn,expected", [(True, 16), (False, 0)])
def test_armed_row_preserves_its_owner_turn_restriction(monkeypatch, owners_turn, expected):
    engine = f1._marked_engine()
    actor = _custom_mark(engine, owner_turn=True)
    foe = engine.state.actors[f1.AN]
    current = actor.entity_id if owners_turn else foe.entity_id
    engine.state.current_slot_index = engine.state.initiative_order.index(current)
    engine.state.current_actor_id = current
    f1._pin_attack(monkeypatch, [20])
    steps = f1._hit(engine, actor, f1._action(f1.ACTOR, [f1._strike()], weapon=f1.WEAPON), [foe])
    assert [r["modifier"] - f1.BASE_MODIFIER for r in f1._rolls(steps, foe.entity_id)] == [expected]
    assert len(f1._dealt(steps, foe.entity_id)) == 1


@pytest.mark.parametrize("first_hits", [True, False])
@pytest.mark.parametrize("preference,decline", [("0", False), ("ask", False), ("ask", True)])
def test_real_compiled_option_consumption_survives_table_commit_reload(tmp_path, monkeypatch, first_hits, preference, decline):
    original = f1.owner_sheet
    def spear_sheet():
        sheet = original()
        sheet["equipment"] = [{"starting_kit": {"items": [
            {"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1}]}}]
        sheet["spheres_and_talents"] = {
            "sphere_record_ids": ["tianxia.sphere.spear"],
            "automatic_sphere_component_record_ids": ["SPEAR_BASE_SPEAR_THRUST"],
            "learned_talent_record_ids": ["TAL_SPEAR_PURSUIT_SPEAR"]}
        return sheet
    monkeypatch.setattr(f1, "owner_sheet", spear_sheet)
    ext.effects()
    def extra_action(ctx):
        if ctx.actor.entity_id == f1.MINE:
            ctx.actor.action_available = True
    monkeypatch.setitem(ext._HOOKS, "technique_used", [*ext.subscribers("technique_used"), extra_action])
    combat, table, mid = f1.table_fight(tmp_path, monkeypatch)
    # The starting kit already readies the spear; do not stow it before attacking.
    table.state(mid)
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == f1.MINE
                  and a.display_name == "Spear Thrust: Reduce Speed + Pursuit Spear: Damage Bonus")
    row = next(r for r in action.parameters["typed"]["effects"][1]["on_hit"] if r["type"] == "extra_damage")
    assert row["modifier_once"] == "TAL_SPEAR_PURSUIT_SPEAR"
    # SOL117 captures this legacy embedded option as a setting on its parent
    # attack. Select it through real table buttons; hidden legacy variants are
    # still compiled evidence, rather than a separate player-facing attack.
    source = action.parameters["typed"]["variant_of"]
    def resist(engine, actor, selected_action):
        if selected_action.source_definition_id == source and actor.entity_id == f1.MINE:
            from combat import typed_executor as te
            target = engine.state.actors[f1.FOE]
            defense_ctx = te.Context(engine, target, selected_action, engine._active_intent,
                                     selected_action.parameters["typed"], [target], target)
            te.block_resistance(defense_ctx, {"type": "resistance", "applies_to": "self",
                                              "damage_types": ["PIERCING"]})
    monkeypatch.setitem(ext._HOOKS, "technique_start", [*ext.subscribers("technique_start"), resist])
    for field, value in (("option", preference), ("payment", preference)):
        setting = next(a for a in engine.action_catalog.values() if a.owner_id == f1.MINE
                       and (a.parameters.get("attack_modifier_setting") or {}) == {
                           "family": source, "modifier": "TAL_SPEAR_PURSUIT_SPEAR",
                           "name": "Pursuit Spear", "field": field, "value": value})
        assert f1.use_button(table, mid, f1.MINE, setting.source_definition_id)["status"] == "COMMITTED"
    from combat.ext.attack_modifiers import chosen
    current = combat._load_session(mid).engine
    if not chosen(current.state.actors[f1.MINE], source, "TAL_SPEAR_PURSUIT_SPEAR").get("on"):
        toggle = next(a for a in current.action_catalog.values() if a.owner_id == f1.MINE
                      and (a.parameters.get("attack_modifier_setting") or {}).get("family") == source
                      and a.parameters["attack_modifier_setting"].get("modifier") == "TAL_SPEAR_PURSUIT_SPEAR"
                      and a.parameters["attack_modifier_setting"].get("field") == "on")
        assert f1.use_button(table, mid, f1.MINE, toggle.source_definition_id)["status"] == "COMMITTED"
    weapon = next(a for a in engine.action_catalog.values()
                  if a.owner_id == f1.MINE and a.source_definition_id.endswith(".weapon.qiang"))
    base_modifier = int(weapon.parameters["typed"]["weapon"]["damage"].get("modifier") or 0)
    current = combat._load_session(mid).engine
    seq = current.state.event_sequence
    if not first_hits:
        # Counter identity makes the miss deterministic on replay as well as the
        # live first attempt, without changing the later attack's result.
        first_counter = current.state.roll_counter
        previous = list(ext.subscribers("d20_result"))
        def first_miss(engine, roll, intent):
            if roll.actor_id == f1.MINE and "ATTACK" in str(roll.reason).upper() and roll.counter_start == first_counter:
                return {"source_id": "test:permission.first_miss", "operation": "replace", "natural_result": 1}
            return next((result for callback in previous if (result := callback(engine, roll, intent)) is not None), None)
        monkeypatch.setitem(ext._HOOKS, "d20_result", [first_miss])
    def attack(table_, decline_):
        state = table_.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if g["source_definition_id"] == source)
        option = next(o for o in group["options"] if f1.FOE in o.get("target_ids", []))
        answers = []
        for _ in range(8):
            result = table_.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            assert "Pursuit Spear" in prompt.get("prompt", str(prompt))
            answers.append({**prompt["context"], "selection": "DECLINE" if decline_ else "USE",
                            "option_ids": [] if decline_ else [prompt["choice"]["options"][0]["id"]]})
        raise AssertionError("too many choices")
    first = attack(table, decline)
    assert first["status"] == "COMMITTED", first
    first_modifiers = f1._rolls_after(combat, mid, seq)
    used = first_hits and not decline
    assert first_modifiers == ([base_modifier + (f1.PB if used else 0)] if first_hits else []) and len(f1._packets(combat, mid, seq)) == int(first_hits), {
        "events": [(e.event_type, e.source_definition_id, e.target_ids,
                    {k: v for k, v in e.payload.items() if k in ("log", "kind", "option_ids", "source_definition_id")})
                   for e in combat._load_session(mid).engine.events if e.sequence > seq]}
    fresh = CombatService(f1.ROOT, tmp_path)
    session = fresh._load_session(mid)
    assert session.engine.state.current_actor_id == f1.MINE
    assert bool(session.engine.state.actors[f1.MINE].turn_flags.get(modifier_key(row))) is used
    first_events = [e for e in session.engine.events if e.sequence > seq]
    packets = [e for e in first_events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == f1.MINE]
    assert all(e.payload["damage_type"] == "PIERCING" for e in packets)
    rolls = [e for e in first_events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == f1.MINE]
    assert [e.payload["reduced_to"] for e in packets] == [e.payload["total"] // 2 for e in rolls]
    assert sum(e.event_type == "REACTION_WINDOW_OPENED" and e.payload.get("checkpoint") == "DAMAGE_APPLICATION"
               for e in first_events) == int(first_hits)
    seq = session.engine.state.event_sequence
    fresh_table = TabletopService(fresh, tmp_path)
    assert fresh_table.state(mid)["menu"]["actor_id"] == f1.MINE
    second = attack(fresh_table, False)
    assert second["status"] == "COMMITTED", second
    assert f1._rolls_after(fresh, mid, seq) == [base_modifier if used else base_modifier + f1.PB]
    assert len(f1._packets(fresh, mid, seq)) == 1
    assert CombatService(f1.ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
