"""Structured choices must survive real table commits without changing their rules."""
import subprocess
from pathlib import Path

import pytest

from combat import senses
from combat.action_variants import choice, cost_delta, variant
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.tabletop import auto_buttons
from tests.h1_support import sheet
from tests.worker2_support import OWNER, fixture, reload, settle

QI = "resource:core.qi"
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("persistent,stronger", [(False, False), (False, True), (True, False), (True, True)])
def test_darkvision_family_all_four_choices_commit_reload_and_pay(tmp_path, persistent, stronger):
    combat, table, mid = fixture(tmp_path, ["TAL_DARK_DARKVISION", "TAL_DARK_PERSISTENT_MELD"])
    engine = reload(tmp_path, mid)
    rows = [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.variant and a.variant.base_label == "Meld: Darkvision"]
    assert len(rows) == 4
    assert len({a.variant.base_key for a in rows}) == 1
    source = rows[0].variant.base_key + (".persistent" if persistent else "") + (".enhanced" if stronger else "")
    action = engine.action_catalog[source]
    assert {p.axis for p in action.variant.choices} == ({"duration"} if persistent else set()) | ({"strength"} if stronger else set())
    assert all(p.costs == ((QI, 2),) for p in action.variant.choices)
    assert all("CP" not in p.label for p in action.variant.choices)
    assert action.concentration == (not persistent)
    assert dict(action.costs).get(QI, 0) == 2 * (persistent + stronger)
    menu = table.state(mid)["menu"]
    offered = [g for g in menu["actions"] if g.get("variant", {}).get("base_label") == "Meld: Darkvision"]
    assert {g["source_definition_id"] for g in offered} == {a.source_definition_id for a in rows}
    assert all(g["variant"]["base_key"] == action.variant.base_key for g in offered)
    # The same choices reach the sheet, not just the fight menu.
    buttons = auto_buttons({"action_catalog": [a.model_dump(mode="json") for a in rows]}, {"cultivation_level": 15})
    variant_buttons = [b for b in buttons if b.get("variant")]
    assert {b["combat"]["source_definition_id"] for b in variant_buttons} == {a.source_definition_id for a in rows}
    assert {b["variant"]["base_key"] for b in variant_buttons} == {action.variant.base_key}
    before = engine.state.actors[OWNER].resources[QI]
    selected = next(c for c in engine.legal_candidates() if c.source_definition_id == source and c.target_ids == (OWNER,))
    assert selected.metadata["variant"] == action.variant.model_dump(mode="json")
    # Adding presentation data cannot manufacture or remove legal candidates.
    original = {c.candidate_id for c in engine.legal_candidates()}
    saved = dict(engine.action_catalog)
    try:
        engine.action_catalog.update({key: a.model_copy(update={"variant": None}) for key, a in saved.items()})
        assert {c.candidate_id for c in engine.legal_candidates()} == original
    finally:
        engine.action_catalog.update(saved)
    settle(table, mid, selected.candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[QI] == before - 2 * (persistent + stronger)
    assert senses.of(after, after.state.actors[OWNER])["darkvision"]["range_ft"] == (120 if stronger else 60)
    held = next(c for c in after.state.actors[OWNER].conditions.values()
                if c.condition_id == senses.MELD and c.data.get("source") == source)
    assert held.data["concentration"] == (not persistent)
    assert after.action_catalog[source].variant == action.variant


@pytest.mark.parametrize("persistent", [False, True])
def test_protection_family_keeps_both_real_actions(tmp_path, persistent):
    from combat.ext import protection
    combat, table, mid = fixture(tmp_path, ["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS"])
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values()
               if a.owner_id == OWNER and a.variant and a.variant.base_label == "Aegis: Armored Aegis"]
    assert len(actions) == 2
    action = next(a for a in actions if bool(a.variant.choices) == persistent)
    before = engine.state.actors[OWNER].resources[QI]
    selected = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    settle(table, mid, selected.candidate_id)
    after = reload(tmp_path, mid)
    assert protection.aegises(after.state.actors[OWNER])
    assert after.state.actors[OWNER].resources[QI] == before - (2 if persistent else 0)
    assert after.action_catalog[action.source_definition_id].variant == action.variant


def test_owner_screenshot_prefight_options_carry_the_same_family_and_costs():
    bundle = compile_character(sheet(["TAL_DARK_DARKVISION", "TAL_DARK_PERSISTENT_MELD"]), actor_id=OWNER)
    choices = [row for row in bundle["prefight"]["options"]
               if row.get("variant", {}).get("base_label") == "Meld: Darkvision"]
    assert len(choices) == 4
    assert len({row["variant"]["base_key"] for row in choices}) == 1
    assert sorted(sum(cost for pool, cost in row["costs"] if pool == QI) for row in choices) == [0, 2, 2, 4]
    catalog = {row["source_definition_id"]: row for row in bundle["action_catalog"]}
    for row in choices:
        assert row["variant"] == catalog[row["action_id"]]["variant"]


def test_compiler_modifier_combinations_carry_identity_and_actual_pool_deltas():
    bundle = compile_character(sheet(["TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PURE_DARKNESS"], cl=17), actor_id=OWNER)
    rows = [a for a in bundle["action_catalog"] if a.get("variant")]
    compiler = [a for a in rows if a["parameters"].get("augment_of")]
    assert compiler
    catalog = {a["source_definition_id"]: a for a in bundle["action_catalog"]}
    for row in compiler:
        identity = row["variant"]
        assert identity["choices"]
        base = catalog[identity["base_key"]]
        deltas = [cost for p in identity["choices"] for cost in p["costs"]]
        assert cost_delta(deltas) == cost_delta(row["costs"], base["costs"])
        assert ActionDefinition.model_validate(row).model_dump(mode="json")["variant"] == identity


def test_mandate_augment_axis_keeps_its_own_effects_and_cost():
    from combat.ext.imbuement_mandates import _action
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    info = {"short": "variant", "actor_id": OWNER, "numbers": {"cl": 10, "pb": 4, "save_dc": 16}}
    option = {"label": "Slow", "side": "fray", "effects": [{"type": "speed", "value": -10}],
              "augment": "Cannot Disengage", "cost": [["cp", 1]],
              "augment_effects": [{"type": "condition", "condition": "no_disengage"}]}
    actions = [_action(info, "test:mandate", option, aug, 30, QI, ActionDefinition, EconomyKind) for aug in (False, True)]
    assert actions[0].variant.base_key == actions[1].variant.base_key
    assert actions[0].variant.choices == ()
    assert actions[1].variant.choices[0].costs == ((QI, 1),)
    assert actions[1].parameters["typed"]["effects"] != actions[0].parameters["typed"]["effects"]


@pytest.mark.parametrize("mode", ["single", "mass", "army"])
def test_mandate_target_count_choices_commit_the_same_equipment_effect(tmp_path, mode):
    from combat.ext import imbuement_mandates as mandates

    prefix = "tianxia.talent.imbuement."
    kit = {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, [
        "IMBUEMENT_BASE_PLACE_MANDATE", prefix + "tempered_equipment",
        prefix + "mass_mandate", prefix + "name_the_army_s_gear",
        prefix + "layered_mandate", prefix + "qi_written_mandate"], owner_kit=kit)
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == OWNER
               and a.variant and a.variant.base_label == "Place Mandate: Temper (armor)"]
    assert len(actions) == 3
    assert len({a.variant.base_key for a in actions}) == 1
    action = next(a for a in actions if
                  (next((p.key for p in a.variant.choices if p.axis == "targets"), "single") == mode))
    assert cost_delta([cost for p in action.variant.choices for cost in p.costs]) == cost_delta(action.costs)
    before = engine.state.actors[OWNER].resources[QI]
    selected = next(c for c in engine.legal_candidates()
                    if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    # Choose the equipped owner, not the fixture helper's first recipient;
    # Army also needs the printed three points of Mandate Load capacity.
    settle(table, mid, selected.candidate_id, picks={"choice:needle.mass_mandate": [OWNER]})
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[QI] == before - (0 if mode == "single" else 2)
    assert mandates.vessel_armor(after, after.state.actors[OWNER]) > 0
    assert after.action_catalog[action.source_definition_id].variant == action.variant


def test_recipe_payment_composition_extends_identity_without_stale_costs():
    from combat.recipe_options import compose_payment_variants

    plain = {"action_id": "base", "name": "Formula", "costs": [(QI, 2)], "typed": {"recipe_id": "recipe"}}
    other = {"action_id": "other", "name": "Longer Range", "costs": [(QI, 3)],
             "typed": {"modifier": {"id": "range"}},
             "variant": variant("base", "Formula", [choice("modifier:range", "range", "Longer Range", [(QI, 1)])]),
             "_compose": {"key": "range", "modifier": {}}}
    replacement = {"action_id": "replacement", "name": "Use Stamina", "costs": [("resource:core.stamina", 2)],
                   "typed": {"modifier": {"id": "substitute"}},
                   "_compose": {"key": "substitute", "name": "Use Stamina", "spend": [],
                                "modifier": {"replace_cost": [{"from": "qi", "to": "stamina", "amount": 2}]}}}
    plain["variants"] = [other, replacement]
    compose_payment_variants(plain,
        lambda modifier, costs: [(0, [("resource:core.stamina", 3)], "3 Stamina")],
        lambda action, part: {"typed": {"modifier": {"id": "range"}}})
    composed = plain["variants"][-1]
    assert composed["variant"].base_key == "base"
    assert {p.axis for p in composed["variant"].choices} == {"modifier:range", "modifier:substitute"}
    assert cost_delta([cost for p in composed["variant"].choices for cost in p.costs]) == cost_delta(composed["costs"], plain["costs"])


def test_signed_resource_substitution_is_not_mislabelled_as_qi():
    assert cost_delta([("resource:core.stamina", 2)], [(QI, 2)]) == ((QI, -2), ("resource:core.stamina", 2))
    value = variant("base", "Ability", [choice("payment", "stamina", "Pay Stamina", cost_delta([("resource:core.stamina", 2)], [(QI, 2)]))])
    assert value.model_dump(mode="json")["choices"][0]["costs"] == [[QI, -2], ["resource:core.stamina", 2]]


def test_shared_variant_renderer_and_all_three_surfaces():
    result = subprocess.run(["node", "--test", "tests/action_variants.test.mjs", "static/tabletop/ranked-menu.test.mjs",
                             "tests/mobile_play.test.mjs", "tests/mobile_play_desktop_guard.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
