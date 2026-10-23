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
    assert {b["variant"]["base_key"] for b in buttons} == {action.variant.base_key}
    before = engine.state.actors[OWNER].resources[QI]
    selected = next(c for c in engine.legal_candidates() if c.source_definition_id == source and c.target_ids == (OWNER,))
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


def test_mandate_augment_mass_and_army_axes_are_composed_from_data():
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


def test_signed_resource_substitution_is_not_mislabelled_as_qi():
    assert cost_delta([("resource:core.stamina", 2)], [(QI, 2)]) == ((QI, -2), ("resource:core.stamina", 2))
    value = variant("base", "Ability", [choice("payment", "stamina", "Pay Stamina", cost_delta([("resource:core.stamina", 2)], [(QI, 2)]))])
    assert value.model_dump(mode="json")["choices"][0]["costs"] == [[QI, -2], ["resource:core.stamina", 2]]


def test_shared_variant_renderer_and_all_three_surfaces():
    subprocess.run(["node", "--test", "tests/action_variants.test.mjs"], cwd=ROOT, check=True)
