"""One physical inventory item stays destroyed through table replay and journeys.

All actors, inventory and actions are synthetic/public. The small fixture
actions transport the production object-damage, shield-break and Channel-break
operations through real table commits; they do not implement destruction.
"""
from copy import deepcopy

import pytest

from combat import armour, carry, ext
from combat.ext import hand_occupancy, item_lifecycle, objects, scoundrel_riders, shield_wielding, unmaking_channels
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind, RuntimeObjectState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

A, B = "actor:factory.item-owner", "actor:factory.other-owner"
SHIELD = "tianxia.mortal.armor.shield"
DAGGER = "tianxia.mortal.weapon.bi_shou"
SPOTS = {A: {"x": 3, "y": 6}, B: {"x": 8, "y": 6}}


def act(service, mid, label=None, choose=None):
    table = TabletopService(service, service.userdata_root)
    menu = table.state(mid)["menu"]
    candidate = menu["end_turn"]
    if label:
        candidate = next(option["candidate_id"] for group in menu["actions"]
                         for option in group["options"] if label in option["label"] or label in group["label"])
    answers = []
    for _ in range(20):
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        options = choose(prompt) if choose else None
        answers.append({**prompt["context"], "selection": "DECLINE" if options is None else "USE",
                        "option_ids": options or []})
    pytest.fail("fixture choices did not finish")


def on_turn(cold, mid, aid):
    for _ in range(10):
        if cold()._load_session(mid).engine.state.current_actor_id == aid:
            return
        act(cold(), mid)
    pytest.fail("fixture actor turn missing")


def finish(cold, mid):
    for _ in range(10):
        if cold()._load_session(mid).engine.state.terminal_result is not None:
            return
        act(cold(), mid)
    pytest.fail("round-capped fixture did not finish")


@pytest.mark.parametrize("route,borrowed", [("object", False), ("object", True),
                                            ("shield", False), ("channel", False),
                                            ("orbit", False), ("guarded", False), ("guarded_stowed", False)])
def test_item_destruction_survives_table_reload_replay_and_next_encounter(tmp_path, monkeypatch, route, borrowed):
    guarded = route.startswith("guarded")
    item_id = DAGGER if route == "channel" or guarded else SHIELD
    items = [{"item_id": item_id, "name": "Ordinary item", "quantity": 1}]
    if route == "guarded_stowed":
        items.append({"item_id": SHIELD, "name": "Unrelated stowed shield", "quantity": 1})
    kit = {"starting_kit": {"items": items}}
    talents = (["TAL_SHIELD_GUARDED_STANCE", "tianxia.talent.shield.sacrificial_shield"] if guarded else
               ["TAL_SHIELD_ORBITING_SHIELD_DISC"] if route == "orbit" else [])
    doc = sheet(talents, kit=kit)
    doc["proficiencies"] = {"armor": ["Shield"]}
    bundles = {aid: compile_character(doc, actor_id=aid) for aid in (A, B)}
    carried = carry.item_of(bundles[A]["carrying"], key=item_id)
    assert carried is not None
    spots = {**SPOTS, B: {"x": 4, "y": 6}} if guarded else SPOTS
    key, weapon = carried["key"], carried.get("weapon_action", "")
    physical = scoundrel_riders.object_id(A, key)
    holder = B if borrowed else A

    def fixture_setup(ctx, eff):
        owner = ctx.engine.state.actors[A]
        from combat.typed_executor import run_effects
        if route == "guarded_stowed":
            stowed = armour.shield_item_key(ctx.engine, owner)
            carry.clear_owned_item_location(ctx.engine, owner, stowed, ctx.source)
            ctx.engine._apply_condition(owner, "condition:typed.held_object", ctx.source, A,
                expires_on="UNTIL_REMOVED", data={"item_key": stowed, "held_by": A,
                    "object_id": scoundrel_riders.object_id(A, stowed), "object_location": "carried"})
        if guarded:
            run_effects(ctx, [{"type": "guarded_stance"}])
        if route == "orbit":
            run_effects(ctx, [{"type": "orbiting_shield_disc", "duration": "until_removed"}])
        # An explicit relocation is the formerly resurrecting hand record.
        ctx.engine._apply_condition(owner, "condition:typed.held_object", ctx.source, A,
            expires_on="UNTIL_REMOVED", data={"item_key": key, "item_name": carried["name"],
                "object_id": physical, "owner": A, "held_by": holder,
                "hand": "hand:right", "object_location": "hand:hand:right"})
        ctx.engine._update_object(RuntimeObjectState(object_id=physical, object_kind="ITEM",
            owner_id=A, position=owner.position, ac=10, current_hp=1, maximum_hp=1,
            unattended=False, flammable=False, component={"name": carried["name"]}), ctx.source, A)

    def fixture_destroy(ctx, eff):
        owner = ctx.engine.state.actors[A]
        stale_object = ctx.engine.state.objects[physical]
        if route in ("object", "orbit"):
            objects.deal(ctx.engine, ctx.actor, ctx.engine.state.objects[physical],
                         [(10, "FORCE")], ctx.source)
        elif route == "channel":
            unmaking_channels.destroy(ctx.engine, owner, weapon, ctx.source)
        elif guarded:
            # A real critical attack triggers Active Defense and Sacrificial Shield.
            ctx.engine._resolve_attack_spec(ctx.engine.state.actors[B], owner,
                {"attack_bonus": 100, "damage": DiceSpec(count=1, sides=4),
                 "damage_type": "PIERCING", "reach_ft": 30}, ctx.intent,
                source_definition_id=ctx.source, attack_index=1)
        else:
            # The same accepted condition as Sacrificial Shield and delayed breaks.
            from combat.typed_executor import run_effects
            run_effects(ctx, [{"type": "condition", "condition": "shield_broken",
                              "applies_to": "self", "duration": "until_removed"}])
        # A late position/custody upsert must read retirement, not revive it.
        ctx.engine._update_object(stale_object, ctx.source, A)

    def critical(engine, roll, intent):
        if guarded and roll.actor_id == B and roll.reason.startswith("ATTACK:"):
            return {"source_id": "test:critical", "operation": "replace", "natural_result": 20}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), critical])
    monkeypatch.setitem(ext.effects(), "test_item_setup", fixture_setup)
    monkeypatch.setitem(ext.effects(), "test_item_destroy", fixture_destroy)
    for name, effect in (("Prepare item", "test_item_setup"), ("Destroy item", "test_item_destroy")):
        action = ActionDefinition(source_definition_id="action:test." + effect, display_name=name,
            owner_id=A, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"free_primary": True, "typed": {"manual_inline_choice": True,
                "numbers": {}, "effects": [{"type": effect}]}})
        bundles[A]["action_catalog"].append(action.model_dump(mode="json"))
        bundles[A]["actor_template"]["action_ids"].append(action.source_definition_id)
    monkeypatch.setattr(CombatService, "compile_factory_actor",
                        lambda self, pid: deepcopy(bundles["actor:factory." + pid]))
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self, **kwargs: {"scene": arena})
    cold = lambda: CombatService(ROOT, tmp_path)
    journey = cold().create_journey(project_ids=["item-owner", "other-owner"], arena_id="scene",
        positions=spots, base_paces={A: 5, B: 5})
    jid = journey["journey_id"]
    mid = cold().journey_start_combat(jid, journey["revision"], {A: "team:a", B: "team:b"},
                                      maximum_rounds=1, positions=spots)["match_id"]
    on_turn(cold, mid, A)
    initial = cold()._load_session(mid).engine
    if not weapon:
        assert armour.shield_bonus_earning(initial, initial.state.actors[A]) == 2
    original_weight = carry.weight(initial, initial.state.actors[A])
    act(cold(), mid, "Prepare item", lambda p: [key])
    prepared = cold()._load_session(mid).engine
    assert any(item["object"] == physical for item in
               scoundrel_riders.possessions(prepared, prepared.state.actors[holder]))
    prepared_owner = prepared.state.actors[A]
    prepared_ac = prepared_owner.armor_class + prepared._ac_modifier(prepared_owner)
    if route == "orbit" or guarded:
        assert shield_wielding.wielding_a_shield(prepared, prepared_owner)
        assert not ext.any_false("row_allowed", prepared, prepared_owner,
                                 {"feature_id": shield_wielding.ACTIVE_DEFENSE})
    if route == "orbit":
        assert shield_wielding.shield_bonus(prepared, prepared_owner) == 2
    if guarded:
        assert shield_wielding.guarded_weapon(prepared, prepared_owner) == key
        assert weapon in prepared_owner.equipment_readiness
        assert any(c.source_definition_id == weapon for c in prepared.legal_candidates())

    def choose_defense(prompt):
        source = prompt["context"]["reaction_source_id"]
        if ("active_defense_payment" in source
                or (source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE" and prompt.get("choice"))):
            return ["reaction"]
        if "ACTIVE_DEFENSE" in source:
            return []
        if "sacrificial_shield" in source:
            return ["break"]
        return None

    act(cold(), mid, "Destroy item", choose_defense)

    def gone(engine):
        owner = engine.state.actors[A]
        assert item_lifecycle.is_destroyed(owner, key=key)
        assert len([c for c in owner.conditions.values()
                    if c.condition_id == item_lifecycle.DESTROYED and c.data.get("item_key") == key]) == 1
        assert not carry.holds(engine, owner, key)
        assert carry.item_of(carry.carrying_of(engine, A), key=key) is None
        assert carry.weight(engine, owner) == max(0, original_weight - float(carried["weight_lb"]))
        for actor in engine.state.actors.values():
            assert all("object:" + key not in occupants
                       for occupants in hand_occupancy.occupancy(engine, actor).values())
            assert all(item["object"] != physical for item in scoundrel_riders.possessions(engine, actor))
            assert all(physical != c.data.get("object_id") for c in actor.conditions.values()
                       if c.data.get("held_by") or c.data.get("dropped_at"))
        assert not any("shield:" + key in occupants for occupants in hand_occupancy.occupancy(engine, owner).values())
        assert weapon not in hand_occupancy.weapon_grips(engine, owner)
        if weapon:
            assert weapon not in owner.equipment_readiness
        else:
            assert armour.shield_bonus_earning(engine, owner) == 0
        if route == "orbit":
            assert shield_wielding.shield_bonus(engine, owner) == 0
            assert owner.armor_class + engine._ac_modifier(owner) == prepared_ac - 2
        if route == "orbit" or guarded:
            assert not shield_wielding.wielding_a_shield(engine, owner)
            assert ext.any_false("row_allowed", engine, owner,
                                 {"feature_id": shield_wielding.ACTIVE_DEFENSE})
        if guarded:
            assert shield_wielding.guarded_weapon(engine, owner) is None
            assert not any(c.source_definition_id == weapon for c in engine.legal_candidates())
        if route == "guarded_stowed":
            assert carry.item_of(carry.carrying_of(engine, A), key=SHIELD) is not None
            assert not item_lifecycle.is_destroyed(owner, key=SHIELD)
        # Same-key gear on another owner is a different physical item.
        assert carry.holds(engine, engine.state.actors[B], key)
        assert any(item["object"] == scoundrel_riders.object_id(B, key)
                   for item in scoundrel_riders.possessions(engine, engine.state.actors[B]))

    saved = cold()._load_session(mid)
    gone(saved.engine)
    if guarded:
        assert any(e.event_type == "PASSIVE_TRIGGERED" and "Sacrificial Shield: the Shield breaks" in str(e.payload)
                   for e in saved.engine.events)
    assert saved.engine.state.objects[physical].destroyed
    sequence = saved.engine.state.event_sequence
    assert not item_lifecycle.destroy(saved.engine, saved.engine.state.actors[A], key=key, source="test:repeat")
    assert saved.engine.state.event_sequence == sequence
    assert saved.verify()["status"] == "PASS"
    assert saved.mechanical.replay()["status"] == "PASS"
    finish(cold, mid)
    terminal = cold()._load_session(mid)
    gone(terminal.engine)
    resumed = cold().journey_resume(jid, cold().journey_state(jid)["revision"])
    assert not any(item["key"] == key for item in resumed["actors"][A]["bundle"]["carrying"]["items"])
    assert cold().journey_replay(jid)["status"] == "PASS"
    second = cold().journey_start_combat(jid, resumed["revision"], {A: "team:a", B: "team:b"},
                                         positions=spots)["match_id"]
    next_session = cold()._load_session(second)
    gone(next_session.engine)
    assert next_session.verify()["status"] == "PASS"
    assert next_session.mechanical.replay()["status"] == "PASS"
