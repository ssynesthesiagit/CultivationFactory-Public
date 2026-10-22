"""Native acquisition, cold character import and package play for Training."""
import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from canonical_catalog import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from combat.ext.beastmastery_training import TRAINING, SPHERE, RIDER, TAMER, EXTRA
from combat.ext import mounts
from combat.gate2_runtime_content import AN
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
AID = "actor:factory." + PID
PIN = "b06e59272dc72b70a8a3e345a4d9cad4ea01c278e17bbba77e058fd63908642e"
RESOURCES = (ROOT / "authority/Tianxia_Sphere_Path_Access_R1.json",
             ROOT / "authority/Tianxia_Forged_Technique_Authority_R1.json")


def native(tmp_path, rank=0, spelling="Animal Handling", json_skills=False, cl=5):
    assert all(p.is_file() for p in RESOURCES)
    doc = sheet([], cl=cl, name="Beastmaster")
    doc["spheres_and_talents"] = {"sphere_record_ids": [], "learned_talent_record_ids": [],
                                 "automatic_sphere_component_record_ids": []}
    doc["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
    skills = [{"skill": spelling, "bonus": 2 + 4 * rank, "proficiency_multiplier": rank}]
    doc["ability_scores_and_statistics"]["skills"] = json.dumps(skills) if json_skills else skills
    folder = tmp_path / "portable_characters" / PID
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return services(tmp_path), doc


def services(root):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def select(table, package=RIDER):
    selected = {"package": package}
    for key in ("free", "bonus"):
        rows = table.learning_preview(PID, SPHERE, selected)["learning_choices"]
        row = next((r for r in rows if r["id"] == key), None)
        if row:
            selected[key] = next(o["id"] for o in row["options"]
                                 if o["id"] != EXTRA and o["id"] not in selected.values())
    return selected


@pytest.mark.parametrize("package", [RIDER, TAMER])
@pytest.mark.parametrize("rank", [0, 1, 2])
def test_native_training_persists_exact_grants_and_later_other_package(tmp_path, package, rank):
    (combat, table), original = native(tmp_path, rank, "animal handling" if rank else "Animal Handling")
    chosen = select(table, package)
    before = copy.deepcopy(original)
    result = table.add_advancement(PID, "sphere", SPHERE, learning_choices=chosen)
    combat, table = services(tmp_path)
    learned = combat._factory_owner_sheet(PID)
    receipt = learned["learning_receipts"][0]
    assert receipt["source"] == TRAINING
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    # The receipt is bound to the exact printed text the app loaded. The public CI export replaces
    # owner prose with a transformed copy (different bytes), so the approved install's exact pin is
    # checked only when that printed text is present; both environments still verify receipt/file
    # agreement, and the owner hash b06e... is recorded in the lane report.
    assert receipt["source_sha256"] == hashlib.sha256(rules[TRAINING].encode()).hexdigest()
    if "gain proficiency in Wisdom (Animal Handling)" in rules[TRAINING]:
        assert receipt["source_sha256"] == PIN
    assert receipt["conditional_bonus_earned"] == int(rank >= 1)
    assert receipt["skill_granted"] == int(rank == 0) and receipt["slot_cost"] == 0
    block = learned["spheres_and_talents"]
    assert set(block["automatic_sphere_component_record_ids"]) & {RIDER, TAMER} == {package}
    assert set(block["learned_talent_record_ids"]) == {v for k, v in chosen.items() if k != "package"}
    skill, = learned["ability_scores_and_statistics"]["skills"]
    assert skill["skill"] == "Animal Handling"
    assert skill["proficiency_multiplier"] == max(1, rank)
    assert skill["bonus"] == 2 + 4 * max(1, rank)
    assert original == before
    assert len(result["added"]["spheres"]) == 1 and not result["added"]["talents"]
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "sphere", SPHERE, learning_choices=chosen)
    other = TAMER if package == RIDER else RIDER
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "talent", EXTRA, learning_choices={"package": package})
    table.add_advancement(PID, "talent", EXTRA, learning_choices={"package": other})
    combat, table = services(tmp_path)
    reopened = combat._factory_owner_sheet(PID)
    assert set(reopened["spheres_and_talents"]["automatic_sphere_component_record_ids"]) & {RIDER, TAMER} == {RIDER, TAMER}
    assert reopened["spheres_and_talents"]["learned_talent_record_ids"].count(EXTRA) == 1
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "talent", EXTRA, learning_choices={"package": package})
    assert combat._factory_owner_sheet(PID) == reopened


@pytest.mark.parametrize("bad", ["missing", "unearned", "duplicate", "prerequisite", "foreign", "wrong_package"])
def test_invalid_training_choices_never_write_receipts(tmp_path, bad):
    (combat, table), _ = native(tmp_path, 1 if bad in ("duplicate", "prerequisite", "foreign") else 0)
    chosen = select(table)
    if bad == "missing":
        chosen.pop("package")
    elif bad == "unearned":
        chosen["bonus"] = chosen["free"]
    elif bad == "duplicate":
        chosen["bonus"] = chosen["free"]
    elif bad == "prerequisite":
        chosen["bonus"] = "tianxia.talent.beastmastery.permanent_control"
        assert any(row.get("canonical_talent_id") == chosen["bonus"] for row in table._catalog_talents())
    elif bad == "foreign":
        chosen["bonus"] = "TAL_MAGMA_LAVA_SPIT"
    else:
        chosen["package"] = TRAINING
    before = copy.deepcopy(combat._factory_owner_sheet(PID))
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "sphere", SPHERE, learning_choices=chosen)
    assert services(tmp_path)[0]._factory_owner_sheet(PID) == before


def test_unknown_legacy_skill_rank_does_not_block_training_or_assume_bonus(tmp_path):
    (combat, table), original = native(tmp_path)
    row = original["ability_scores_and_statistics"]["skills"][0]
    row.pop("proficiency_multiplier")
    row["proficiency"] = "legacy-unmapped"
    folder = tmp_path / "portable_characters" / PID
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(original))
    combat, table = services(tmp_path)
    choices = select(table)
    assert "bonus" not in choices
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choices)
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    receipt = reopened["learning_receipts"][0]
    assert receipt["gm_note"]
    assert receipt["conditional_bonus_earned"] == 0
    assert receipt["skill_granted"] == 0
    assert not (set(reopened["spheres_and_talents"]["learned_talent_record_ids"]) - set(choices.values()))


def test_wrong_acquisition_owner_cannot_consume_training_choices(tmp_path):
    (combat, table), _ = native(tmp_path)
    with pytest.raises(TabletopError) as exc:
        table.add_advancement(PID, "sphere", "tianxia.sphere.air", learning_choices={"package": RIDER})
    assert exc.value.code == "LEARNING_CHOICES_WRONG_OWNER"
    assert not combat._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]


def test_extra_package_can_be_the_earned_bonus_without_duplicate_grants(tmp_path):
    (combat, table), _ = native(tmp_path, 1)
    chosen = select(table, TAMER)
    chosen.update(bonus=EXTRA, extra_package=RIDER)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=chosen)
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert set(reopened["spheres_and_talents"]["automatic_sphere_component_record_ids"]) & {RIDER, TAMER} == {RIDER, TAMER}
    assert reopened["spheres_and_talents"]["learned_talent_record_ids"].count(EXTRA) == 1


def test_json_skills_are_canonicalized_and_persisted_on_cold_import(tmp_path):
    (combat, table), _ = native(tmp_path, rank=1, spelling="animal handling", json_skills=True)
    chosen = select(table)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=chosen)
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    skill, = reopened["ability_scores_and_statistics"]["skills"]
    assert skill["skill"] == "Animal Handling"
    assert skill["proficiency_multiplier"] == 1


def test_extra_package_as_first_free_talent_unlocks_dependent_bonus(tmp_path):
    # Spirit-Beast Covenant prints "Prerequisite: Tamer Package, CL 7+", so the
    # dependent-bonus character must actually be CL 7 (review F7RSC P2).
    (combat, table), _ = native(tmp_path, rank=1, cl=7)
    covenant = next(row["canonical_talent_id"] for row in table._catalog_talents()
                    if row.get("display_name") == "Spirit-Beast Covenant")
    assert covenant == "TAL_BEASTMASTERY_SPIRIT_BEAST_COVENANT"
    # Before Tamer is received the Covenant is not an eligible bonus talent.
    unqualified = {"package": RIDER, "free": EXTRA}
    preview = table.learning_preview(PID, SPHERE, unqualified)["learning_choices"]
    bonus = next(row for row in preview if row["id"] == "bonus")
    assert all(option["id"] != covenant for option in bonus["options"])
    choices = {"package": RIDER, "free": EXTRA, "extra_package": TAMER}
    preview = table.learning_preview(PID, SPHERE, choices)["learning_choices"]
    bonus = next(row for row in preview if row["id"] == "bonus")
    assert any(option["id"] == covenant for option in bonus["options"])
    choices["bonus"] = covenant
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choices)
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert covenant in reopened["spheres_and_talents"]["learned_talent_record_ids"]
    assert {RIDER, TAMER} <= set(reopened["spheres_and_talents"]["automatic_sphere_component_record_ids"])


def test_acquired_rider_action_commits_reloads_and_mechanically_replays(tmp_path):
    (combat, table), _ = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=select(table, RIDER))
    combat, table = services(tmp_path)
    mid = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={AID: "MANUAL", AN: "MANUAL"}, match_seed="TRAINING-RIDER-NATIVE")["match_id"]
    session = combat._load_session(mid)
    rider = session.engine.state.actors[AID]
    assert mounts.mount_of(session.engine, rider) is not None
    for _ in range(3):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == AID:
            break
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if g["label"] == "Dismount")
    option = group["options"][0]
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert mounts.mount_of(loaded.engine, loaded.engine.state.actors[AID]) is None
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
