"""One physical inventory item stays destroyed through table replay and journeys.

All actors, inventory and actions are synthetic/public. The small fixture
actions transport the production object-damage, shield-break and Channel-break
operations through real table commits; they do not implement destruction.
"""
from copy import deepcopy

import pytest

from combat import armour, carry, ext
from combat.ext import hand_occupancy, item_lifecycle, objects, scoundrel_riders, unmaking_channels
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, RuntimeObjectState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

A, B = "actor:factory.item-owner", "actor:factory.other-owner"
SHIELD = "tianxia.mortal.armor.shield"
DAGGER = "tianxia.mortal.weapon.bi_shou"
SPOTS = {A: {"x": 3, "y": 6}, B: {"x": 8, "y": 6}}


def act(service, mid, label=None):
    table = TabletopService(service, service.userdata_root)
    menu = table.state(mid)["menu"]
    candidate = menu["end_turn"]
    if label:
        candidate = next(option["candidate_id"] for group in menu["actions"]
                         for option in group["options"] if label in option["label"] or label in group["label"])
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "COMMITTED", result


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
                                            ("shield", False), ("channel", False)])
def test_item_destruction_survives_table_reload_replay_and_next_encounter(tmp_path, monkeypatch, route, borrowed):
    item_id = DAGGER if route == "channel" else SHIELD
    kit = {"starting_kit": {"items": [{"item_id": item_id, "name": "Ordinary item", "quantity": 1}]}}
    doc = sheet([], kit=kit)
    doc["proficiencies"] = {"armor": ["Shield"]}
    bundles = {aid: compile_character(doc, actor_id=aid) for aid in (A, B)}
    carried = bundles[A]["carrying"]["items"][0]
    key, weapon = carried["key"], carried.get("weapon_action", "")
    physical = scoundrel_riders.object_id(A, key)
    holder = B if borrowed else A

    def fixture_setup(ctx, eff):
        owner = ctx.engine.state.actors[A]
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
        if route == "object":
            objects.deal(ctx.engine, ctx.actor, ctx.engine.state.objects[physical],
                         [(10, "FORCE")], ctx.source)
        elif route == "channel":
            unmaking_channels.destroy(ctx.engine, owner, weapon, ctx.source)
        else:
            # The same accepted condition as Sacrificial Shield and delayed breaks.
            from combat.typed_executor import run_effects
            run_effects(ctx, [{"type": "condition", "condition": "shield_broken",
                              "applies_to": "self", "duration": "until_removed"}])
        # A late position/custody upsert must read retirement, not revive it.
        ctx.engine._update_object(stale_object, ctx.source, A)

    monkeypatch.setitem(ext.effects(), "test_item_setup", fixture_setup)
    monkeypatch.setitem(ext.effects(), "test_item_destroy", fixture_destroy)
    for name, effect in (("Prepare item", "test_item_setup"), ("Destroy item", "test_item_destroy")):
        action = ActionDefinition(source_definition_id="action:test." + effect, display_name=name,
            owner_id=A, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"free_primary": True, "typed": {"numbers": {}, "effects": [{"type": effect}]}})
        bundles[A]["action_catalog"].append(action.model_dump(mode="json"))
        bundles[A]["actor_template"]["action_ids"].append(action.source_definition_id)
    monkeypatch.setattr(CombatService, "compile_factory_actor",
                        lambda self, pid: deepcopy(bundles["actor:factory." + pid]))
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self, **kwargs: {"scene": arena})
    cold = lambda: CombatService(ROOT, tmp_path)
    journey = cold().create_journey(project_ids=["item-owner", "other-owner"], arena_id="scene",
        positions=SPOTS, base_paces={A: 5, B: 5})
    jid = journey["journey_id"]
    mid = cold().journey_start_combat(jid, journey["revision"], {A: "team:a", B: "team:b"},
                                      maximum_rounds=1, positions=SPOTS)["match_id"]
    on_turn(cold, mid, A)
    initial = cold()._load_session(mid).engine
    if not weapon:
        assert armour.shield_bonus_earning(initial, initial.state.actors[A]) == 2
    original_weight = carry.weight(initial, initial.state.actors[A])
    act(cold(), mid, "Prepare item")
    prepared = cold()._load_session(mid).engine
    assert any(item["object"] == physical for item in
               scoundrel_riders.possessions(prepared, prepared.state.actors[holder]))
    act(cold(), mid, "Destroy item")

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
        # Same-key gear on another owner is a different physical item.
        assert carry.holds(engine, engine.state.actors[B], key)
        assert any(item["object"] == scoundrel_riders.object_id(B, key)
                   for item in scoundrel_riders.possessions(engine, engine.state.actors[B]))

    saved = cold()._load_session(mid)
    gone(saved.engine)
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
                                         positions=SPOTS)["match_id"]
    next_session = cold()._load_session(second)
    gone(next_session.engine)
    assert next_session.verify()["status"] == "PASS"
    assert next_session.mechanical.replay()["status"] == "PASS"
