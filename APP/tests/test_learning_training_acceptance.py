"""Whole-row native Learning acceptance; helpers stay import-compatible."""
import copy
import hashlib
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from tests.test_learning_training_native import (
    ROOT, PID, AID, PINS, native, offered, picks, acquire, replay,
)


@pytest.mark.parametrize("sphere,kwargs", [
    ("alchemy", {}), ("alchemy", {"tools": ["alchemist's supplies"]}),
    ("jester", {}), ("jester", {"skills": ["Performance", "Deception", "Acrobatics"]}),
    ("source", {}), ("spear", {}), ("spear", {"weapons": ["spear", "pike", "lance", "trident"]}),
    ("life", {}),
])
def test_native_learning_receipts_survive_table_and_fight_replay(tmp_path, sphere, kwargs):
    combat, table = native(tmp_path, **kwargs)
    options = offered(table, sphere)
    selected = picks(options)
    result = acquire(table, sphere, selected)
    cold = CombatService(ROOT, tmp_path)
    doc = cold._factory_owner_sheet(PID)
    receipt = doc["learning_receipts"][0]
    assert receipt["slot_cost"] == 0
    assert receipt["choices"] == selected
    assert receipt["conditional_bonus_earned"] == int("bonus" in selected)
    assert receipt["sphere_id"] == "tianxia.sphere." + sphere
    assert receipt["source"] in doc["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert set(receipt["talents"]) <= set(doc["spheres_and_talents"]["learned_talent_record_ids"])
    assert set(receipt["talents"]) == {v for k, v in selected.items() if k != "skill"}
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert receipt["source_sha256"] == hashlib.sha256(rules[receipt["source"]].encode()).hexdigest()
    assert receipt["source_sha256"] == PINS[receipt["source"]]
    learned_row = next(r for r in result["added"]["spheres"] if r["id"] == "tianxia.sphere." + sphere)
    assert learned_row["learning_benefit_labels"]
    if sphere == "alchemy":
        assert "alchemist's supplies" in doc["ability_scores_and_statistics"]["tool_proficiencies"]
        assert ("bonus" in selected) == bool(kwargs)
    if sphere == "spear":
        assert set(receipt["weapons"]) == {"spear", "pike", "lance", "trident"}
        assert ("bonus" in selected) == bool(kwargs)
    if sphere == "jester" and not kwargs:
        assert any(r["skill"] == selected["skill"] and r["proficiency_multiplier"] == 1
                   for r in doc["ability_scores_and_statistics"]["skills"])
    loaded = replay(combat, table, tmp_path)
    if sphere == "jester" and "skill" in selected:
        bundle = next(b for b in loaded.engine.typed_bundle_documents if b["actor_id"] == AID)
        assert bundle["skill_proficiency"][selected["skill"]] == 1
        expected = next(r["bonus"] for r in doc["ability_scores_and_statistics"]["skills"] if r["skill"] == selected["skill"])
        assert bundle["skills"][selected["skill"]] == expected
    if sphere == "spear":
        from combat.factory_compiler import weapon_group_proficient
        assert weapon_group_proficient(doc, doc["spheres_and_talents"]["automatic_sphere_component_record_ids"], "spear")


def test_missing_wrong_owner_realm_and_duplicate_choices_do_not_commit(tmp_path):
    combat, table = native(tmp_path, tools=["alchemist's supplies"])
    before = copy.deepcopy(table.buttons.get(PID))
    for choice in ({}, {"bonus": "TAL_SPEAR_COILING_SOFT_SPEAR"}, {"bonus": "not-a-talent"}):
        with pytest.raises(TabletopError):
            acquire(table, "alchemy", choice)
        assert table.buttons.get(PID) == before
    for row in offered(table, "alchemy"):
        if row["id"] == "bonus":
            assert all(table.canonical_catalog.get_talent(o["id"])["realm_band"] == "Mortal" for o in row["options"])
    acquire(table, "alchemy")
    with pytest.raises(TabletopError):
        acquire(table, "alchemy", {})
    assert len(combat._factory_owner_sheet(PID)["learning_receipts"]) == 1


def test_jester_duplicate_grants_and_unrelated_sphere_are_inert(tmp_path):
    combat, table = native(tmp_path, skills=["Performance", "Deception", "Acrobatics"])
    choices = offered(table, "jester")
    punchline = next(r for r in choices if r["id"] == "punchline")["options"][0]["id"]
    with pytest.raises(TabletopError):
        acquire(table, "jester", {"bonus": punchline, "punchline": punchline})
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "sphere", "tianxia.sphere.air", learning_choices={"bonus": punchline})
    table.add_advancement(PID, "sphere", "tianxia.sphere.air")
    assert "learning_receipts" not in combat._factory_owner_sheet(PID)


def test_prelearning_boundary_and_source_structural_prerequisite(tmp_path):
    combat, table = native(tmp_path, weapons=["spear", "pike", "lance"], cl=20)
    assert {c["id"] for c in offered(table, "spear")} == {"free"}
    source_options = offered(table, "source")[0]["options"]
    # Source Seal is an actual automatic base grant, not a guessed story flag.
    rows = {r["canonical_talent_id"]: r for r in table.canonical_catalog.list_talents(sphere_id="Source")["records"]}
    seal_candidates = [r for r in rows.values() if any(p.get("display_name") == "Source Seal" for p in r["typed_prerequisites"])
                       and all(p["kind"] in ("minimum_cl", "owning_sphere", "structural_authority", "realm") for p in r["typed_prerequisites"])]
    assert seal_candidates
    assert {r["canonical_talent_id"] for r in seal_candidates} <= {r["id"] for r in source_options}
    acquire(table, "spear")
    doc = CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)
    assert len(doc["learning_receipts"][0]["talents"]) == 1


def test_native_transaction_prevents_duplicate_training_grants(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    combat, table = native(tmp_path)
    selected = picks(offered(table, "source"))
    def learn():
        try:
            acquire(table, "source", selected)
            return "committed"
        except TabletopError:
            return "already-known"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: learn(), range(2))) == ["already-known", "committed"]
    assert len(combat._factory_owner_sheet(PID)["learning_receipts"]) == 1


def test_level_zero_does_not_become_level_one_for_training_choices(tmp_path):
    combat, table = native(tmp_path, cl=0)
    assert offered(table, "source")[0]["options"] == []
    with pytest.raises(TabletopError):
        acquire(table, "source", {"free": "tianxia.talent.source.buried_light_lantern"})
    assert "learning_receipts" not in combat._factory_owner_sheet(PID)
