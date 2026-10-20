"""Beast-Marrow Frame at the table; owner-approved downtime deferral."""
import copy
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from non_sphere_authority.foundation_mechanics import (
    resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests import test_a2r11_foundations as f

FRAME = f.MARROW + ".beast_marrow_frame"
DIGESTION = f.MARROW + ".safe_beast_digestion"


@pytest.mark.parametrize("stage,multiplier", [
    ("Common Expression", 0), ("Awakened", 1), ("Integrated", 2),
    ("Intermediate", 2), ("Refined", 2), ("Perfected", 2),
])
def test_frame_maximum_hp_commits_and_reloads_without_stacking(tmp_path, monkeypatch, stage, multiplier):
    combat, table, mid = f._service_fight(tmp_path, monkeypatch, f._marrow(stage), f.MARROW_BARE)
    before = f._engine(combat, mid).state.actors[f.FIGHTER]
    assert before.maximum_hp == 500 + multiplier * before.proficiency_bonus
    f._play(table, mid, table.state(mid)["menu"]["end_turn"])
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid).state.actors[f.FIGHTER]
    assert cold.maximum_hp == before.maximum_hp

    # Re-level/recompile from the unchanged owner sheet, not the previous
    # compiled actor maximum. The contribution follows PB, not levels spent.
    doc = f._doc([f._first_feature(f.MARROW_BARE)], "the fighter", foundation=f._marrow(stage))
    original = copy.deepcopy(doc)
    for level, pb in [(10, 4), (13, 5), (13, 5), (17, 6), (17, 6)]:
        doc["identity"].update(cultivation_level=level, proficiency_bonus=pb)
        first = compile_character(doc, actor_id=f.FIGHTER)
        second = compile_character(doc, actor_id=f.FIGHTER)
        assert first["actor_template"]["maximum_hp"] == 500 + multiplier * pb
        assert second["actor_template"]["maximum_hp"] == first["actor_template"]["maximum_hp"]
        assert doc["ability_scores_and_statistics"] == original["ability_scores_and_statistics"]


@pytest.mark.parametrize("stage,multiplier", [("Awakened", 1), ("Integrated", 2)])
def test_frame_does_not_duplicate_the_initial_foundation_hp_projection(tmp_path, monkeypatch, stage, multiplier):
    record = verified_foundation_records()[f.MARROW_BARE]
    initial_stage = record["stage"].split(" or ")[0]
    mechanics = resolve_initial_foundation_mechanics(
        record, [record["compatible_path_ids"][0]], stage=initial_stage)
    from stage2.formulas import evaluate_formula
    included = sum(evaluate_formula(row["formula"]["root"], {"pb": 4}).value
                   for row in mechanics["hp_maximum_modifiers"])
    foundation = {**f._marrow(stage), "mechanics": mechanics}

    def prepare(bundles):
        doc = f._doc([f._first_feature(f.MARROW_BARE)], "the fighter",
                     foundation=foundation, hp=500 + included)
        replacement = compile_character(doc, actor_id=f.FIGHTER, reaction_plan={"ask": True})
        owner = next(b for b in bundles if b["actor_id"] == f.FIGHTER)
        owner.clear()
        owner.update(replacement)

    combat, table, mid = f._service_fight(tmp_path, monkeypatch, f._marrow(stage), f.MARROW_BARE, prepare=prepare)
    f._play(table, mid, table.state(mid)["menu"]["end_turn"])
    actor = f._engine(CombatService(f.ROOT, tmp_path), mid).state.actors[f.FIGHTER]
    assert actor.maximum_hp == 500 + multiplier * actor.proficiency_bonus


def test_safe_beast_digestion_is_explicitly_deferred_not_a_combat_action():
    override = json.loads((f.ROOT / "authority/typed_mechanics/reviewed_final.d/a2r03_safe_beast_digestion.json").read_text())
    assert override["mechanics"][DIGESTION]["riders"] == [
        "out-of-combat: deferred to the main-game window"]
    authority = json.loads((f.ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert "out-of-combat: deferred to the main-game window" in authority["mechanics"][DIGESTION]["riders"]
    bundle = compile_character(f._doc([f._first_feature(f.MARROW_BARE)], "the fighter",
                                     foundation=f._marrow("Refined")), actor_id=f.FIGHTER)
    assert not any(DIGESTION in a["source_definition_id"] for a in bundle["action_catalog"])
