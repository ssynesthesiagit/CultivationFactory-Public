"""Normal published training and fitted-only table admission, without live services."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.core import sha256_json
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_character_sheet_complete_character import _service
from tests.test_sheet_worn_armour_matches_fight import _artifacts_for
from tests.test_mgr_t14_fitted_armor import (
    ACTOR, PROJECT, LAMELLAR, LEATHER, sheet, fight, fit, command, support,
)
from tests.test_mgr_t14_armor_consumers import HEAVY, heavy_sheet
from tests.test_mgr_t14_equipment_review import install
from tests.test_mgr_t14_armor_defenses import DAMAGE, damage_action

T = "tianxia.talent.equipment."
# Directory-discovered mechanical inputs must travel with the public fixture.
FIXTURE_INPUTS = (
    "combat/rules/feature_blocks.d/auto68_equipment.json",
    "combat/rules/feature_blocks.d/riders_lane9.json",
    "combat/rules/feature_blocks.d/auto_H1.json",
    "character_sheet/contracts/Tianxia_Character_Sheet_Readiness_Profile_R1.json",
    "character_sheet/contracts/Tianxia_Character_Sheet_Readiness_Profile_R1.json.sha256",
)


def published_training(root, count, route, *, ease_count=0, armor_item=None):
    """Build and read the normal on-disk snapshot from selected training records.

    Display cards are unique per record; trained_choices retain repeat purchases.
    Neither the ledger nor the snapshot fixture injects an armor proficiency list.
    """
    service = _service(root)
    source = sheet()
    if armor_item:
        source["equipment"][0]["starting_kit"]["items"] = [
            {"item_id": armor_item, "name": "Armor", "quantity": 1}]
    artifacts = _artifacts_for(source)
    ledger = artifacts["Character_Master_Ledger.json"]
    records = {"tianxia.sphere.equipment": "spheres", "SHIELD_BASE_SHIELD_TRAINING": "features"}
    if count:
        records[T + "armor_training"] = "talents"
    if ease_count:
        records[T + "armor_ease"] = "talents"
    purchases = {T + "armor_training": count, T + "armor_ease": ease_count}
    packets = artifacts["Rules_Selection_Packets.json"]["packets"]
    for index, record in enumerate(records):
        packets.append({"sequence": 100 + index, "target_cl": 1,
                        "record_id": record, "packet_id": "f7-" + str(index),
                        "advancement_kind": "talent"})
    if route == "training":
        ledger["advancement"]["levels"].append({"cl": 1, "trained_choices": [
            {"record_id": record, "slot": index} for record, total in purchases.items()
            for index in range(total)]})
    else:
        for offset, (record, total) in enumerate(purchases.items()):
            for index in range(1, total):
                sequence = 200 + offset * 10 + index
                packets.append({"sequence": sequence, "target_cl": index + 1,
                                "record_id": record, "packet_id": "f7-repeat-" + str(sequence),
                                "advancement_kind": "talent"})
    original = service._display_contract

    def contract_for(ledger, provenance):
        contract, _ = original(ledger, provenance)
        contract = deepcopy(contract)
        printed = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
        for record, section in records.items():
            rule = deepcopy(contract["rules"][0])
            text = printed.get(record, "Equipment sphere")
            rule.update(record_id=record, section=section, display_name=record.rsplit(".", 1)[-1],
                        one_line_description=text, full_description=text,
                        acquisition_source={"packet_ids": [], "target_cl": 1},
                        source={"path": "APP/authority/typed_mechanics/rules_text.json",
                                "anchor": record, "source_hash": hashlib.sha256(text.encode()).hexdigest()})
            contract["rules"].append(rule)
        return contract, sha256_json(contract)

    service._display_contract = contract_for
    _, artifact = service._build_snapshot(
        project={"project_id": PROJECT, "revision": 1, "user_locks": []},
        artifacts=artifacts, projection_status={"status": "READY", "projection_id": "f7-training"})
    doc = json.loads(Path(artifact["path"]).read_text())
    assert "armor" not in doc.get("proficiencies", {})
    return doc


@pytest.mark.parametrize("count", [0, 1, 2, 3])
@pytest.mark.parametrize("route", ["training", "advancement"])
def test_normal_published_training_reaches_native_preparation_and_cold_fight(tmp_path, count, route):
    doc = published_training(tmp_path, count, route)
    install(tmp_path, doc)
    combat = CombatService(ROOT, tmp_path)
    menu = combat.character_preparation_options(PROJECT)
    choices = {c["parameters"]["item_key"] for c in menu["commands"] if c["operation"] == "armor.fit.start"}
    expected = set() if count == 0 else {LEATHER} if count == 1 else {LEATHER, LAMELLAR}
    assert choices == expected
    if count:
        key = LEATHER if count == 1 else LAMELLAR
        command(tmp_path, doc, "armor.fit.start", item_key=key)
        command(tmp_path, doc, "time.advance", seconds=600, observation="fitting")
    match = combat.create_factory_match(project_ids=[PROJECT], match_seed="F7-TRAINING", maximum_rounds=1)
    engine = support._reload(tmp_path, match["match_id"])
    bundle = next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)
    assert bundle["armor_subject"]["proficiencies"] == sorted(["light", "medium", "heavy"][:count])
    assert bundle["armor_subject"]["ready"] == int(count > 0)


def prepared_doc(root, state, talents):
    doc = heavy_sheet(talents + ["sleep_in_armor"]) if state in {"sleep", "refit"} else sheet(talents)
    key = HEAVY if state in {"sleep", "refit"} else LAMELLAR
    if state == "other":
        fit(root, doc, LEATHER)
    elif state != "unfitted":
        fit(root, doc, key)
    if state in {"sleep", "refit"}:
        command(root, doc, "rest.start", kind="long_rest")
        command(root, doc, "time.advance", seconds=28800, observation="sleep")
        if state == "refit":
            fit(root, doc, key)
    return doc


def actor_turn(combat, table, mid):
    from tests.test_lock2_persistence import act
    while table.state(mid)["menu"]["actor_id"] != ACTOR:
        assert act(table, mid, "end")["status"] == "COMMITTED"


@pytest.mark.parametrize("talent", ["mirror_bright_armor", "circuit_armor", "walking_fortress_scripture"])
@pytest.mark.parametrize("state", ["unfitted", "other", "sleep", "refit"])
def test_fitted_action_admission_and_execution_after_cold_reload(tmp_path, talent, state):
    doc = prepared_doc(tmp_path, state, [talent])
    combat, table, mid = fight(tmp_path, doc)
    actor_turn(combat, table, mid)
    engine = support._reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == ACTOR and a.source_definition_id.endswith(T + talent))
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id == source]
    assert bool(candidates) == (state == "refit")
    menu = table.state(mid)["menu"]
    assert any(a["source_definition_id"] == source and a.get("options") for a in menu["actions"]) == (state == "refit")
    if state == "refit":
        before = engine.state.actors[ACTOR].resources["resource:core.qi"]
        support._commit(combat, table, mid, source, actor=ACTOR)
        cold = support._reload(tmp_path, mid)
        assert cold.state.actors[ACTOR].resources["resource:core.qi"] == before - (1 if talent == "mirror_bright_armor" else 2 if talent == "circuit_armor" else 4)


@pytest.mark.parametrize("state", ["unfitted", "other", "sleep", "refit"])
def test_persistent_shell_ac_obeys_fitted_subject_after_cold_reload(tmp_path, state):
    doc = prepared_doc(tmp_path, state, ["mountain_pattern_shell"])
    combat, table, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    actor = engine.state.actors[ACTOR]
    assert support._effective_ac(engine, actor) == actor.armor_class + int(state == "refit")
    assert table.state(mid)["match_id"] == mid


@pytest.mark.parametrize("talent", ["lamellar_flow", "ancestral_battle_dress", "soul_sealed_armor"])
@pytest.mark.parametrize("state", ["unfitted", "refit"])
def test_fitted_reactive_consumers_at_native_table(tmp_path, talent, state):
    doc = prepared_doc(tmp_path, state, [talent])

    def trigger(bundle):
        if talent == "lamellar_flow":
            damage_action(bundle)
            return
        if bundle["actor_id"] != support.ATTACKER:
            return
        effects = [{"type": "save", "ability": "wis", "dc": 100, "on_success": [], "on_fail": []}]
        if talent == "soul_sealed_armor":
            effects = [{"type": "damage", "applies_to": "target", "damage_types": ["force"],
                        "flat": doc["ability_scores_and_statistics"]["hit_points"]["maximum"]}]
        support._bundle_action(bundle, DAMAGE, "Armor response challenge", {"typed": {
            "numbers": {}, "riders": [], "duration": {"kind": "instant"}, "effects": effects}},
            target_kind="HOSTILE_ENTITY", range_ft=60)
        support._seal(bundle)

    combat, table, mid = fight(tmp_path, doc, prepare=trigger)
    # Ordinary reroll/reduction consent has no option IDs. Survival is the
    # existing explicit extension choice whose option is named "use".
    prompts = support._commit(combat, table, mid, DAMAGE,
                             answer=(lambda p: ["use"]) if talent == "soul_sealed_armor" else None)
    cold = support._reload(tmp_path, mid)
    relevant = [p for p in prompts if talent in str(p)]
    assert bool(relevant) == (state == "refit")
    assert cold.state.actors[ACTOR].resources["resource:core.qi"] == (59 if talent == "lamellar_flow" and state == "refit" else 60)
    if talent == "soul_sealed_armor":
        assert cold.state.actors[ACTOR].current_hp == int(state == "refit")
