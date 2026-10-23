"""Thrown equipment through accepted table actions, disk reload and replay."""
import pytest

from combat import carry
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_attack_abilities import install, sheet, ROOT
from tests.test_lock2_persistence import act

AXE = "tianxia.mortal.weapon.fu"


def fixture(tmp_path, *, quantity=1, automatic=False, weapon=AXE, extra_attack=False, returning=False, ac=1, wide=False, barrage=False, moon=False, revelation=False):
    owner = sheet(strength=18, training=False)
    owner["path_and_subpath"] = {}
    owner["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon, "name": "Test weapon", "quantity": quantity}]}}]
    if extra_attack:
        owner["path_and_subpath"] = {"path_feature_record_ids": ["tianxia.path.body_refining.feature.extra_attack"]}
    if barrage:
        owner["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.barrage"], "learned_talent_record_ids": []}
    if moon:
        owner["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.axes"],
                                      "learned_talent_record_ids": ["TAL_AXES_MOON_CLEAVER_RETURN"]}
    if revelation:
        owner["path_and_subpath"] = {"path_feature_record_ids": ["tianxia.subpath.body.thousand_eyed_calamity_body.feature.thousand_eyed_revelation"]}
    if returning:
        from factory_authoring.starting_kits import _authorities
        import json

        authority = json.loads((ROOT / "authority/Tianxia_Treasure_Weapon_Authority_R1.json").read_text())
        enchantment = next(row for row in authority["enchantments"] if row["enchantment_id"].endswith(".returning_inscription"))
        owner["equipment"][0]["starting_kit"] = {"resolved_treasure_weapon": {
            "name": "Returning axe", "chassis": _authorities()[1][AXE], "refinement_bonus": 1,
            "enchantments": [enchantment]}, "items": [{"item_id": AXE, "quantity": 1}]}
    foe_sheet = sheet(strength=8, dexterity=8, training=False)
    foe_sheet["path_and_subpath"] = {}
    foe_sheet["ability_scores_and_statistics"]["armor_class"] = {"base_value": ac}
    foe_sheet["ability_scores_and_statistics"]["hit_points"] = {"maximum": 1000}
    install(tmp_path, "thrower", owner)
    install(tmp_path, "foe", foe_sheet)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Throw yard", "width_squares": 30 if wide else 12, "height_squares": 8,
        "starts": {"team1": [[3, 4]], "team2": [[6, 4]]}, "walls": []})
    actor, foe = FACTORY_ACTOR_PREFIX + "thrower", FACTORY_ACTOR_PREFIX + "foe"
    mid = combat.create_factory_match(project_ids=["thrower"], opponent_actor_ids=[foe],
        control_modes={actor: "LOCAL_AUTO" if automatic else "MANUAL", foe: "MANUAL"},
        arena_id="battlefield:map.throw-yard", match_seed="THROWN-POSSESSION")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == actor:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid, actor, foe


@pytest.mark.parametrize("weapon,suffix", [("tianxia.mortal.weapon.fu", ".weapon.fu#thrown"),
                                           ("tianxia.mortal.weapon.bi_shou", ".weapon.bi_shou#thrown"),
                                           ("tianxia.mortal.weapon.tong_zhu", ".weapon.tong_zhu")])
def test_extra_attack_cannot_throw_the_same_copy_again(tmp_path, weapon, suffix):
    combat, table, mid, actor, foe = fixture(tmp_path, weapon=weapon, extra_attack=True)
    base = throw(table, mid, suffix)
    loaded = reload(tmp_path, mid)
    action = next(a for a in loaded.engine.action_catalog.values() if a.source_definition_id.endswith(suffix))
    assert action.parameters["typed"]["effects"][0]["count"] > 1
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor]
    assert len(rolls) == 1
    assert len(table._dropped_items(mid)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_missed_throw_also_leaves_the_hand(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, ac=100)
    base = throw(table, mid)
    loaded = reload(tmp_path, mid)
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor]
    assert rolls and all(e.payload["total"] < 100 and e.payload["natural_result"] != 20 for e in rolls)
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor for e in loaded.engine.events)
    assert any(c.data.get("disables_action") == base for c in loaded.engine.state.actors[actor].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_throw_stows_the_wielding_grip_and_frees_the_hand(tmp_path):
    """SHEETHANDS1: after a throw the weapon is no longer in hand; the other hand can draw a spare."""
    from combat.ext.hand_occupancy import GRIP, free_hands, weapon_grips

    combat, table, mid, actor, foe = fixture(tmp_path)
    base = throw(table, mid)
    loaded = reload(tmp_path, mid)
    holder = loaded.engine.state.actors[actor]
    assert base not in weapon_grips(loaded.engine, holder)
    assert free_hands(loaded.engine, holder)
    grip = next(c for c in holder.conditions.values()
                if c.condition_id == GRIP and c.data.get("weapon") == base)
    assert grip.data["held"] == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_returning_inscription_reuses_the_copy_for_extra_attacks(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, extra_attack=True, returning=True)
    base = throw(table, mid, ".weapon.fu.treasure#thrown")
    loaded = reload(tmp_path, mid)
    action = loaded.engine.action_catalog[base + "#thrown"]
    count = action.parameters["typed"]["effects"][0]["count"]
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor]
    assert count > 1 and len(rolls) == count
    assert not table._dropped_items(mid)
    assert not any(c.data.get("disables_action") == base for c in loaded.engine.state.actors[actor].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_bundle_reload_replay_preserves_existing_journal(tmp_path, monkeypatch):
    from combat import ext
    from combat.ext import thrown_equipment
    ext.effects()
    # Simulate a pre-fix frozen bundle via compile hooks, without editing any lock.
    with monkeypatch.context() as legacy:
        legacy.setitem(ext._HOOKS, "compile_weapon_traits", [f for f in ext._HOOKS["compile_weapon_traits"]
                                                            if f is not thrown_equipment.traits])
        combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
        for _ in range(12):
            state = table.state(mid)
            if state["menu"]["actor_id"] == foe:
                act(table, mid, "end")
            else:
                table.auto_step(mid, state["last_sequence"], [])
            if any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor for e in reload(tmp_path, mid).engine.events):
                break
        before = table.events(mid, 0)
        journal = table._match_dir(mid) / "Journal.ndjson"
        before_bytes = journal.read_bytes()
    loaded = reload(tmp_path, mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).events(mid, 0) == before
    assert journal.read_bytes() == before_bytes
    assert not any(c.data.get("disables_action") for c in loaded.engine.state.actors[actor].conditions.values())


def test_second_copy_can_be_left_behind_without_renumbering_the_first():
    from combat.factory_compiler import compile_character, equipment_list
    owner = sheet(training=False)
    owner["equipment"] = [{"starting_kit": {"items": [{"item_id": AXE, "quantity": 2}]}}]
    listing = equipment_list(owner)
    assert [i["key"] for i in listing["items"]] == [AXE, AXE + ".2"]
    bundle = compile_character(owner, actor_id="actor:factory.copies", left_behind=[AXE])
    assert [i["key"] for i in bundle["carrying"]["items"]] == [AXE + ".2"]
    assert bundle["carrying"]["items"][0]["weapon_action"].endswith(".fu.copy2")


def test_copy_normalization_is_idempotent_and_empty_stock_has_no_attack():
    from combat.ext.thrown_equipment import copies
    from combat.factory_compiler import compile_character
    normalized = copies([{"item_id": AXE, "quantity": 2}])
    assert copies(normalized) == normalized
    assert copies([normalized[1]]) == [normalized[1]]
    owner = sheet(training=False)
    owner["equipment"] = [{"starting_kit": {"items": [{"item_id": AXE, "quantity": 0}]}}]
    bundle = compile_character(owner, actor_id="actor:factory.empty")
    assert not any(".weapon.fu" in a["source_definition_id"] for a in bundle["action_catalog"])


def test_another_actor_can_take_throw_and_return_the_physical_axe(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path)
    base = throw(table, mid)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    take = next(a.source_definition_id for a in loaded.engine.action_catalog.values()
                if a.owner_id == foe and a.source_definition_id.endswith(".take_weapon"))
    assert act(table, mid, take)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    condition = next(c for c in loaded.engine.state.actors[actor].conditions.values() if c.data.get("disables_action") == base)
    assert condition.data["held_by"] == foe and "dropped_at" not in condition.data
    throw(table, mid, ".weapon.held.")
    loaded = reload(tmp_path, mid)
    conditions = [c for c in loaded.engine.state.actors[actor].conditions.values() if c.data.get("disables_action") == base]
    assert len(conditions) == 1 and "held_by" not in conditions[0].data
    assert conditions[0].data["dropped_at"] == loaded.engine.state.actors[actor].position.model_dump(mode="json")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, base + ".pickup")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert not any(c.data.get("disables_action") == base for c in loaded.engine.state.actors[actor].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_explicit_area_prohibition_stops_returning_inscription(tmp_path, monkeypatch):
    from combat import ext
    from combat.ext import placed

    combat, table, mid, actor, foe = fixture(tmp_path, returning=True, extra_attack=True)
    ext.effects()
    def block(engine, event_type, kwargs):
        if event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == actor:
            placed.place(engine, engine.state.actors[foe], source="test:return-block", tag="return-block",
                name="An area that prevents teleportation", cells=engine.state.actors[foe].position,
                extra={"rule": {"no_teleport": True}})
    with monkeypatch.context() as fixture_hook:
        fixture_hook.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), block])
        base = throw(table, mid, ".weapon.fu.treasure#thrown")
    loaded = reload(tmp_path, mid)
    assert len(table._dropped_items(mid)) == 1
    assert len([e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor]) == 1
    assert any(c.data.get("disables_action") == base for c in loaded.engine.state.actors[actor].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("reason", ["out_of_range", "disarmed"])
def test_checkpoint_cancelled_attack_makes_no_throw(tmp_path, monkeypatch, reason):
    from combat import ext
    from combat.gate2_runtime_models import Position

    combat, table, mid, actor, foe = fixture(tmp_path, wide=True)
    ext.effects()
    def flee(engine, attacker, defender, intent, context):
        if attacker.entity_id != actor:
            return None
        if reason == "disarmed":
            engine._apply_condition(attacker, carry.DROPPED, context["source_id"], defender.entity_id,
                expires_on="UNTIL_REMOVED", data={"item_key": AXE, "item_name": "Test axe",
                    "disables_action": context["source_id"].split("#")[0],
                    "dropped_at": attacker.position.model_dump(mode="json")})
            return {}
        start = defender.position
        defender.position = Position(x=25, y=4)
        engine._append_event("MOVEMENT_COMMITTED", context["source_id"], actor_id=defender.entity_id,
            payload={"destination": {"x": 25, "y": 4}, "path": [start.model_dump(mode="json"), {"x": 25, "y": 4}],
                     "cost_ft": 0, "teleport": True})
        return {}
    with monkeypatch.context() as checkpoint:
        checkpoint.setitem(ext._HOOKS, "before_attack", [*ext._HOOKS.get("before_attack", []), flee])
        throw(table, mid)
    loaded = reload(tmp_path, mid)
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor for e in loaded.engine.events)
    assert len(table._dropped_items(mid)) == (1 if reason == "disarmed" else 0)
    assert carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE) == (reason != "disarmed")
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_thrown_delivery_buttons_wait_for_actual_pickup(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, barrage=True)
    def barrage_offered():
        return any("Barrage" in c.display_name for c in reload(tmp_path, mid).engine.legal_candidates())
    assert barrage_offered()
    base = throw(table, mid)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert not barrage_offered()
    state = table.state(mid)
    move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 5, "y": 4})
    assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    assert act(table, mid, base + ".pickup")["status"] == "COMMITTED"
    assert barrage_offered()
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_nested_off_turn_throw_consumes_its_copy(tmp_path, monkeypatch):
    from combat import ext, typed_executor

    combat, table, mid, actor, foe = fixture(tmp_path)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    ext.effects()
    def respond(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED" or kwargs.get("actor_id") != foe:
            return
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == actor and a.source_definition_id.endswith(".weapon.fu#thrown"))
        typed = {**action.parameters["typed"], "reaction_attack": True, "reaction_range_ft": action.range_ft}
        ctx = typed_executor.Context(engine, engine.state.actors[actor], action, engine._active_intent,
                                     typed, [engine.state.actors[foe]], engine.state.actors[foe], {})
        typed_executor.block_attack(ctx, {**typed["effects"][0], "attack_kind": "cultivation_ranged"})
    with monkeypatch.context() as nested:
        nested.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), respond])
        assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len([e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor]) == 1
    assert not carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE)
    assert len(table._dropped_items(mid)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("choice", ["return", "lodge"])
def test_moon_cleaver_owner_choice_commits_and_reloads(tmp_path, choice):
    combat, table, mid, actor, foe = fixture(tmp_path, moon=True)
    state = table.state(mid)
    action = next(g for g in state["menu"]["actions"] if "TAL_AXES_MOON_CLEAVER_RETURN" in g["source_definition_id"])
    result = table.act(mid, action["options"][0]["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"])
    assert result["status"] == "REACTION_REQUIRED"
    assert not table._dropped_items(mid)  # preview is transactional
    prompt = result["reaction"]
    assert prompt["action"] == "Moon-Cleaver Return"
    assert prompt["affected"] == "Ability test fighter"
    assert "until someone picks it up" in prompt["summary"]
    assert prompt["cost"] == "No action, Reaction, or additional resource cost"
    answer = {**prompt["context"], "selection": "USE", "option_ids": [choice]}
    # Answer after a new service instance loads the same committed boundary.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    state = table.state(mid)
    action = next(g for g in state["menu"]["actions"] if "TAL_AXES_MOON_CLEAVER_RETURN" in g["source_definition_id"])
    result = table.act(mid, action["options"][0]["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"], [answer])
    assert result["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor for e in loaded.engine.events)
    assert carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE) == (choice == "return")
    assert len(table._dropped_items(mid)) == (0 if choice == "return" else 1)
    message = "Moon-Cleaver Return: the weapon returns" if choice == "return" else "leaves the axe lodged"
    assert any(message in str(e.payload) for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("choice", ["return", "lodge"])
@pytest.mark.parametrize("ai_turn", [False, True], ids=["manual-turn", "ai-turn"])
def test_moon_cleaver_off_turn_owner_choice(tmp_path, monkeypatch, choice, ai_turn):
    from combat import ext, typed_executor

    combat, table, mid, actor, foe = fixture(tmp_path, moon=True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    if ai_turn:
        combat.set_controller_mode(mid, actor_id=foe, controller_mode="LOCAL_AUTO")
    ext.effects()
    def respond(engine, event_type, kwargs):
        if event_type != "INTENT_ACCEPTED" or kwargs.get("actor_id") != foe:
            return
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == actor and "TAL_AXES_MOON_CLEAVER_RETURN" in a.source_definition_id)
        typed = {**action.parameters["typed"], "reaction_attack": True, "reaction_range_ft": action.range_ft}
        ctx = typed_executor.Context(engine, engine.state.actors[actor], action, engine._active_intent,
                                     typed, [engine.state.actors[foe]], engine.state.actors[foe], {})
        typed_executor.block_attack(ctx, {**typed["effects"][0], "attack_kind": "cultivation_ranged"})
        ext.run("technique_used", ctx)
    with monkeypatch.context() as nested:
        nested.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), respond])
        def submit(answers):
            if ai_turn:
                return table.auto_step(mid, table.state(mid)["last_sequence"], answers)
            state = table.state(mid)
            row = next(g for g in state["menu"]["actions"] if g["source_definition_id"] == "system:combat.hold_position")
            return table.act(mid, row["options"][0]["candidate_id"], state["menu"]["decision_id"],
                             state["menu"]["state_version"], state["last_sequence"], answers)
        result = submit([])
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["context"]["reactor_id"] == actor
        assert not table._dropped_items(mid)
        answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": [choice]}
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        assert submit([answer])["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE) == (choice == "return")
    assert len(table._dropped_items(mid)) == (0 if choice == "return" else 1)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_moon_cleaver_ai_owner_returns_automatically(tmp_path, monkeypatch):
    from combat import ext, typed_executor

    combat, table, mid, actor, foe = fixture(tmp_path, moon=True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    ext.effects()
    def respond(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED" or kwargs.get("actor_id") != foe:
            return
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == actor and "TAL_AXES_MOON_CLEAVER_RETURN" in a.source_definition_id)
        typed = {**action.parameters["typed"], "reaction_attack": True, "reaction_range_ft": action.range_ft}
        ctx = typed_executor.Context(engine, engine.state.actors[actor], action, engine._active_intent,
                                     typed, [engine.state.actors[foe]], engine.state.actors[foe], {})
        typed_executor.block_attack(ctx, {**typed["effects"][0], "attack_kind": "cultivation_ranged"})
        ext.run("technique_used", ctx)
    with monkeypatch.context() as nested:
        nested.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), respond])
        assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor for e in loaded.engine.events)
    assert carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE)
    assert not table._dropped_items(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


def reload(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def throw(table, mid, suffix=".weapon.fu#thrown"):
    state = table.state(mid)
    row = next(g for g in state["menu"]["actions"] if suffix in g["source_definition_id"])
    result = table.act(mid, row["options"][0]["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    return row["source_definition_id"].split("#")[0]


@pytest.mark.parametrize("automatic", [False, True], ids=["manual", "ai"])
def test_single_axe_lands_at_target_and_stays_unavailable_after_reload(tmp_path, automatic):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=automatic)
    original = reload(tmp_path, mid)
    before = carry.weight(original.engine, original.engine.state.actors[actor])
    target_position = original.engine.state.actors[foe].position.model_dump(mode="json")
    if automatic:
        for _ in range(12):
            state = table.state(mid)
            if state["menu"]["actor_id"] == foe:
                assert act(table, mid, "end")["status"] == "COMMITTED"
            else:
                assert table.auto_step(mid, state["last_sequence"], [])["status"] == "COMMITTED"
            loaded = reload(tmp_path, mid)
            rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor
                     and e.source_definition_id.endswith(".weapon.fu#thrown")]
            if rolls:
                break
        assert rolls, "the AI must actually throw its axe"
        base = rolls[0].source_definition_id.split("#")[0]
    else:
        base = throw(table, mid)
    loaded = reload(tmp_path, mid)
    conditions = [c for c in loaded.engine.state.actors[actor].conditions.values() if c.data.get("disables_action") == base]
    assert len(conditions) == 1
    assert conditions[0].data["dropped_at"] == target_position
    assert conditions[0].expires_on == "UNTIL_REMOVED"
    assert carry.weight(loaded.engine, loaded.engine.state.actors[actor]) < before
    assert any(i["x"] == target_position["x"] and i["y"] == target_position["y"] for i in table._dropped_items(mid))
    assert not carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE)
    assert loaded.mechanical.replay()["status"] == "PASS"
    if automatic:
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    offered = [g["source_definition_id"] for g in table.state(mid)["menu"]["actions"]]
    assert not any(source.split("#")[0] == base for source in offered)
    assert not any(source == base + ".pickup" for source in offered)  # still 15 ft away
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_stack_has_distinct_copies_and_recovery_restores_only_one(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, quantity=2)
    initial = reload(tmp_path, mid)
    weapons = [i for i in carry.carrying_of(initial.engine, actor)["items"] if i["item_id"] == AXE]
    assert len(weapons) == 2 and all(i["quantity"] == 1 for i in weapons)
    assert len({i["weapon_action"] for i in weapons}) == 2
    base = throw(table, mid)
    loaded = reload(tmp_path, mid)
    assert not carry.holds(loaded.engine, loaded.engine.state.actors[actor], weapons[0]["key"])
    assert carry.holds(loaded.engine, loaded.engine.state.actors[actor], weapons[1]["key"])
    # End both turns, throw the other copy, then walk to the actual ground items.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    second = throw(table, mid, ".weapon.fu.copy2#thrown")
    state = table.state(mid)
    assert not any(g["source_definition_id"] == base + ".pickup" for g in state["menu"]["actions"])
    moves = [m for m in state["menu"]["moves"] if m["destination"] == {"x": 5, "y": 4}]
    assert moves
    assert table.act(mid, moves[0]["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    assert act(table, mid, base + ".pickup")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    disabled = {c.data.get("disables_action") for c in loaded.engine.state.actors[actor].conditions.values()}
    assert base not in disabled and second in disabled
    assert len(table._dropped_items(mid)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
