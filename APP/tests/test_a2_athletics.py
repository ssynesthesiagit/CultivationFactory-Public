"""Athletics second-pass regressions through journaled table actions and cold loads."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.auto8f1_table_support import (
    AXE_KIT, FOE, OWNER, SECOND, candidate_id, fixture, reload_identical,
)

CAPOEIRA = "TAL_ATHLETICS_CAPOEIRA_SPIN"
FLANK = "TAL_ATHLETICS_SUDDEN_FLANK"
FLIP = "TAL_ATHLETICS_WHIRLWIND_FLIP"
FOCUS = "resource:core.martial_focus"


def setup_actions(bundles):
    """Seal test-only posture/vision actions before genesis; never mutate a live engine."""
    for bundle in bundles:
        if bundle["actor_id"] != OWNER:
            continue
        for name, condition in (("Lie down", "prone"), ("Close eyes", "blinded"),
                                ("Become restrained", "restrained")):
            action = ActionDefinition(
                source_definition_id="action:test.a2." + condition,
                display_name=name, owner_id=OWNER, economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"free_primary": True, "typed": {
                    "effects": [{"type": "condition", "condition": condition, "applies_to": "self"}],
                    "numbers": {}, "riders": [], "duration": {"kind": "instant"},
                }},
            )
            bundle["action_catalog"].append(action.model_dump(mode="json"))
            bundle["actor_template"]["action_ids"].append(action.source_definition_id)


def game_for(tmp_path, talents, *, kit=None):
    return fixture(tmp_path, talents, seed="A2ATH-" + tmp_path.name,
                   kit=kit, bundle_transform=setup_actions)


def commit(game, label):
    if label.startswith("Tumble ("):
        for group in game["menu"]()["actions"]:
            for option in group["options"]:
                if label in option["label"] and option.get("target_ids") == [FOE]:
                    return game["commit"](option["candidate_id"])
        raise AssertionError(f"no {label} against the named foe")
    return game["commit"](candidate_id(game["menu"](), label))


def finish(game):
    reload_identical(game["combat"], game["match_id"], game["userdata"])


def own_rolls(game):
    return [e for e in game["combat"]._load_session(game["match_id"]).engine.events
            if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]


@pytest.mark.parametrize("talents,blind,expected", [
    ([CAPOEIRA], False, "NORMAL"),
    ([CAPOEIRA], True, "DISADVANTAGE"),
    ([], False, "DISADVANTAGE"),
])
def test_prone_unarmed_strike_removes_only_capoeiras_named_penalty(tmp_path, talents, blind, expected):
    game = game_for(tmp_path, talents)
    commit(game, "Lie down")
    if blind:
        commit(game, "Close eyes")
    finish(game)
    commit(game, "Attack the square" if blind else "Unarmed Strike")
    assert own_rolls(game)[-1].payload["mode"] == expected
    assert any(c.condition_id == "condition:typed.prone" for c in game["reload_owner"]().conditions.values())
    finish(game)


def test_capoeira_does_not_remove_prone_penalty_from_weapon_attacks(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA], kit=AXE_KIT)
    commit(game, "Lie down")
    commit(game, "Fu (Short Axe) attack")
    assert own_rolls(game)[-1].payload["mode"] == "DISADVANTAGE"
    finish(game)


def test_capoeira_stand_and_one_strike_costs_only_bonus_action_and_survives_reload(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA])
    commit(game, "Lie down")
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    finish(game)
    before = game["reload_owner"]()
    count = len(own_rolls(game))
    commit(game, "Capoeira Spin: stand and make one Unarmed Strike")
    after = game["reload_owner"]()
    assert not any(c.condition_id == "condition:typed.prone" for c in after.conditions.values())
    assert len(own_rolls(game)) == count + 1
    assert after.action_available is True and after.bonus_action_available is False
    assert after.movement_remaining_ft == before.movement_remaining_ft
    finish(game)


def test_capoeira_requires_starting_prone_and_does_not_reappear_after_standing(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA])
    label = "Capoeira Spin: stand and make one Unarmed Strike"
    commit(game, "Lie down")
    with pytest.raises(AssertionError):
        candidate_id(game["menu"](), label)
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    candidate_id(game["menu"](), label)
    commit(game, "Stand up")
    with pytest.raises(AssertionError):
        candidate_id(game["menu"](), label)
    finish(game)


def tumble_game(tmp_path, talents, *, success=True, places=None):
    def transform(bundles):
        setup_actions(bundles)
        for b in bundles:
            b.setdefault("skills", {})["Acrobatics"] = (60 if success else -60) if b["actor_id"] == OWNER else 0
            b["actor_template"].setdefault("skills", {})["Acrobatics"] = b["skills"]["Acrobatics"]
            for resource in b["actor_template"]["resources"]:
                if resource["resource_id"] == FOCUS:
                    resource["initial"] = 0
    return fixture(tmp_path, talents, seed="A2ATH-TUMBLE-" + tmp_path.name,
                   bundle_transform=transform, places=places)


def explicit_move(game, path):
    menu = game["menu"]()
    table, mid = game["table"], game["match_id"]
    quote = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], OWNER, path)
    answers = []
    for _ in range(20):
        result = table.commit_move_path(mid, quote["candidate"]["candidate_id"], menu["decision_id"],
            menu["state_version"], OWNER, path, reactions=answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "DECLINE"})
    raise AssertionError("movement did not commit")


@pytest.mark.parametrize("talents,economy", [([FLIP], "Action"), ([FLANK, FLIP], "Bonus Action")])
def test_whirlwind_flip_restores_focus_on_real_tumble_check_and_permission_reloads(tmp_path, talents, economy):
    game = tumble_game(tmp_path, talents)
    before = game["reload_owner"]().movement_remaining_ft
    commit(game, f"Tumble ({economy})")
    fresh = game["stored_engine"]()
    owner = fresh.state.actors[OWNER]
    assert owner.resources[FOCUS] == 1
    assert fresh.state.actors[FOE].resources[FOCUS] == 0
    assert owner.movement_remaining_ft == before
    assert any(c.condition_id == "condition:typed.athletics_tumble" for c in owner.conditions.values())
    assert not owner.modifiers, "Sudden Flank needs passage, not just a won check"
    assert owner.action_available is (economy != "Action")
    assert owner.bonus_action_available is (economy != "Bonus Action")
    finish(game)


def test_failed_tumble_grants_no_passage_no_focus_and_no_flank(tmp_path):
    game = tumble_game(tmp_path, [FLANK, FLIP], success=False)
    commit(game, "Tumble (Bonus Action)")
    owner = game["reload_owner"]()
    assert owner.resources[FOCUS] == 0
    assert not any(c.condition_id == "condition:typed.athletics_tumble" for c in owner.conditions.values())
    assert not owner.modifiers
    finish(game)


def test_sudden_flank_uses_one_crossing_then_one_attack_against_that_enemy(tmp_path):
    from combat.tabletop_service import TabletopError
    game = tumble_game(tmp_path, [FLANK])
    commit(game, "Tumble (Bonus Action)")
    finish(game)
    before = game["reload_owner"]().movement_remaining_ft
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    owner = game["reload_owner"]()
    assert owner.movement_remaining_ft == before - 15
    assert owner.resources[FOCUS] == 0, "owning Sudden Flank does not grant Whirlwind Flip"
    grants = [m for m in owner.modifiers.values() if m.source_definition_id == FLANK]
    assert len(grants) == 1 and grants[0].value == "ADVANTAGE:" + FOE
    finish(game)
    with pytest.raises(TabletopError):
        explicit_move(game, [{"x": 5, "y": 6}, {"x": 4, "y": 6}, {"x": 3, "y": 6}])
    count = len(own_rolls(game))
    commit(game, "Unarmed Strike")
    rolls = own_rolls(game)[count:]
    assert rolls[0].payload["mode"] == "ADVANTAGE"
    assert all(r.payload["mode"] == "NORMAL" for r in rolls[1:])
    assert not any(m.source_definition_id == FLANK for m in game["reload_owner"]().modifiers.values())
    finish(game)


def test_unused_tumble_and_sudden_flank_expire_at_turn_end(tmp_path):
    game = tumble_game(tmp_path, [FLANK, FLIP])
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    game["commit"](game["menu"]()["end_turn"])
    owner = game["reload_owner"]()
    assert not any(c.condition_id == "condition:typed.athletics_tumble" for c in owner.conditions.values())
    assert not any(m.source_definition_id == FLANK for m in owner.modifiers.values())
    finish(game)


def test_interrupted_tumble_spends_passage_without_granting_flank(tmp_path, monkeypatch):
    from combat import ext
    from combat.tabletop_service import TabletopError

    def halt_inside(engine, mover, previous, nxt, intent):
        if mover.entity_id != OWNER:
            return None
        foe = engine.state.actors[FOE]
        if set(engine._actor_volume(mover)) & set(engine._actor_volume(foe)):
            return {"stop": True, "source_id": "test:a2.transit_obstacle",
                    "label": "A test obstacle stops this passage."}
        return None

    # Test-only movement hazard through the real documented checkpoint; no
    # engine/class replacement. It remains installed during cold reload/replay.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "movement_step", [*ext.subscribers("movement_step"), halt_inside])
    game = tumble_game(tmp_path, [FLANK])
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    owner = game["reload_owner"]()
    assert (owner.position.x, owner.position.y) == (3, 6)
    assert not any(m.source_definition_id == FLANK for m in owner.modifiers.values())
    finish(game)
    with pytest.raises(TabletopError):
        explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])


def test_capoeira_cannot_stand_when_restrained_at_zero_speed(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA])
    commit(game, "Lie down")
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    commit(game, "Become restrained")
    with pytest.raises(AssertionError):
        candidate_id(game["menu"](), "Capoeira Spin: stand and make one Unarmed Strike")
    finish(game)


def test_capoeira_uses_the_owners_improved_unarmed_strike(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA, "tianxia.path.body_refining.feature.iron_fist"])
    commit(game, "Lie down")
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    engine = game["stored_engine"]()
    ordinary = next(a for a in engine.action_catalog.values()
                    if a.owner_id == OWNER and a.display_name == "Iron Fist attack")
    bonus = next(a for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and a.display_name.startswith("Capoeira Spin:"))
    assert bonus.parameters["typed"]["weapon"] == ordinary.parameters["typed"]["weapon"]
    assert bonus.parameters["typed"]["weapon"]["damage"]["sides"] > 2, "must use improved dice"
    count = len(own_rolls(game))
    commit(game, "Capoeira Spin: stand and make one Unarmed Strike")
    assert len(own_rolls(game)) == count + 1
    finish(game)


def test_tumble_cannot_restore_focus_by_contesting_a_distant_creature(tmp_path):
    game = tumble_game(tmp_path, [FLIP])
    for group in game["menu"]()["actions"]:
        for option in group["options"]:
            if "Tumble (" in option["label"]:
                assert option.get("target_ids") != [SECOND]
    finish(game)


def test_canceled_attack_does_not_spend_sudden_flank(tmp_path, monkeypatch):
    from combat import ext

    def cancel(ctx, target, effect):
        return False if ctx.actor.entity_id == OWNER else None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_allowed", [*ext.subscribers("attack_allowed"), cancel])
    game = tumble_game(tmp_path, [FLANK])
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    count = len(own_rolls(game))
    commit(game, "Unarmed Strike")
    assert len(own_rolls(game)) == count
    assert any(m.source_definition_id == FLANK for m in game["reload_owner"]().modifiers.values())
    finish(game)


def test_attack_against_another_creature_does_not_spend_sudden_flank(tmp_path):
    game = tumble_game(tmp_path, [FLANK], places={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 7},
    })
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    count = len(own_rolls(game))
    option = next(o for g in game["menu"]()["actions"] for o in g["options"]
                  if g["source_definition_id"].endswith(".natural.unarmed_strike")
                  and o.get("target_ids") == [SECOND])
    game["commit"](option["candidate_id"])
    rolls = own_rolls(game)[count:]
    assert rolls and all(e.payload["mode"] == "NORMAL" for e in rolls)
    assert any(m.source_definition_id == FLANK and m.value == "ADVANTAGE:" + FOE
               for m in game["reload_owner"]().modifiers.values())
    finish(game)


def test_two_creatures_tumble_permissions_and_flanks_remain_distinct(tmp_path):
    game = tumble_game(tmp_path, [FLANK], places={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 6, "y": 6},
    })
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}])
    option = next(o for g in game["menu"]()["actions"] for o in g["options"]
                  if "Tumble (Action)" in o["label"] and o.get("target_ids") == [SECOND])
    game["commit"](option["candidate_id"])
    explicit_move(game, [{"x": 5, "y": 6}, {"x": 6, "y": 6}, {"x": 7, "y": 6}])
    owner = game["reload_owner"]()
    assert {m.value for m in owner.modifiers.values() if m.source_definition_id == FLANK} == {
        "ADVANTAGE:" + FOE, "ADVANTAGE:" + SECOND,
    }
    assert {c.data["target_id"] for c in owner.conditions.values()
            if c.condition_id == "condition:typed.athletics_tumble"} == {FOE, SECOND}
    finish(game)
