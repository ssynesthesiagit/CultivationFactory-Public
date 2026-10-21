"""Native True Reflection regressions (Mirror Cultivator CL18, "### CL18 — True Reflection").

The assigned source leaf is the activation header plus the True Doppelganger file. These checks
compile a real Factory character that owns the feature (``tests/h1_support.py:sheet``), drive the
printed Reaction through the shipped table -- 8 Qi, once per scene, Concentration up to 1 minute,
manifesting the True Doppelganger -- and then cold-reload and replay the fight. No browser and no
model server are used.

The native creation pipeline is exercised separately and stays quarantined on the pre-existing
sealed ``validation_profile`` mismatch, recorded the same way as
``tests/test_mgr_t14_ling_subpath_cinder_touch.py``. Sovereign Reflection, the Recorded Echoed
Patterns, Fixate the Original and Mirrored Intercession remain GM-adjudicated riders on the
authority record (``CORE_WITH_RIDERS``); this file does not certify them.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

from app.api import create_app
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet


FEATURE = "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"
SUBPATH = FEATURE.split(".feature.")[0]
QI = "tianxia.path.qi_cultivation"
OWNER, ALLY, FOE = [FACTORY_ACTOR_PREFIX + "true-reflection-" + name
                    for name in ("owner", "ally", "foe")]
DOUBLE = OWNER + ".summon.true_doppelganger.1"
QI_POOL = "resource:core.qi"
USE_POOL = "resource:uses.reaction:typed." + FEATURE
# Reaction rows hold Concentration under "reaction:typed.<feature>" (factory_compiler _generic_reaction's action_id).
CONCENTRATION_SOURCE = "reaction:typed." + FEATURE
# Combat fixture durability/weapon only; ownership and every feature value come from the shipped
# sheet and compiler, with no injected receipts or effects.
KIT = {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1},
                 {"item_id": "tianxia.mortal.gear.explorer_s_pack", "name": "Explorer's Pack", "quantity": 1},
                 {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}

PROFILE = ROOT / "projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json"
CONTRACT = ROOT / "projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json"
KNOWN_EXPECTED = "2c752f3b48d6dd9db17860855d33402d380a706520d9a74a2f6e2e416b326419"
KNOWN_ACTUAL = "83f1c49137c64ad6dafabc1885b6c8ddaa5d93d905d769627c32d94032380541"


def _evidence(name, value):
    print(name, json.dumps(value, sort_keys=True))
    directory = os.environ.get("TRUE_REFLECTION_EVIDENCE_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")


def _owner_sheet(variant):
    """The Factory owner's own sheet: 'owner' owns the feature, the controls do not."""
    if variant == "owner":
        return sheet([FEATURE], cl=18, primary="Qi", key="CON", name="True Reflection owner")
    if variant == "below":
        return sheet([], cl=17, primary="Qi", key="CON", name="True Reflection below")
    return sheet([], cl=18, primary="Qi", key="CON", name="True Reflection wrong-owner")


def _durable(document):
    document["ability_scores_and_statistics"]["armor_class"] = {"base_value": 1}
    document["ability_scores_and_statistics"]["hit_points"] = {"maximum": 500}
    return document


def test_feature_compiles_its_reaction_and_doppelganger():
    """The printed Reaction and the True Doppelganger chassis compile from the shipped authority.

    Fails without the authority effect: an empty activation row compiles no reaction and no summon.
    """
    bundle = compile_character(sheet([FEATURE], cl=18, primary="Qi", key="CON"),
                               actor_id=OWNER, reaction_plan={"ask": True})
    rows = [row for row in bundle["typed_reactions"] if row.get("feature_id") == FEATURE]
    assert rows, "the printed Reaction did not compile"
    row = rows[0]
    assert row["kind"] == "ally_damaged" and row["includes_self"] is True
    assert row["range_ft"] == 60  # "A creature within 60 feet deals damage to you or one ally you can perceive."
    assert {"resource_id": QI_POOL, "amount": 8} in row["costs"]
    assert {"resource_id": USE_POOL, "amount": 1} in row["costs"], "once per scene is one use per fight"
    assert [e for e in row["effects"] if e.get("type") == "summon" and e.get("group") == "true_doppelganger"]
    summons = [entry for entry in bundle["summons"] if entry["summon"]["group"] == "true_doppelganger"]
    assert summons, "the True Doppelganger creature did not compile"
    creature = summons[0]
    assert creature["summon"]["owner"] == OWNER
    assert creature["summon"]["source"] == FEATURE
    assert creature["summon"]["concentration"] is True
    template = creature["actor_template"]
    assert template["armor_class"] == 15 + 4          # AC 15 + Proficiency Bonus (sheet pb = 4)
    assert template["maximum_hp"] == 6 * 18           # Hit Points 6 x Qi Cultivation CL
    assert template["speed_ft"] == 40
    passives = {p.get("kind"): set(p.get("damage_types") or []) for p in creature["typed_passives"]}
    assert {"BLUDGEONING", "PIERCING", "SLASHING", "FORCE", "PSYCHIC"} <= passives.get("resistance", set())
    assert "POISON" in passives.get("immunity", set())
    immunity = next(p for p in creature["typed_passives"] if p.get("block") == "condition_immunity")
    assert {"charmed", "frightened", "poisoned"} <= set(immunity["conditions"])
    assert any("command" in action["source_definition_id"] and "true_doppelganger" in action["source_definition_id"]
               for action in bundle["action_catalog"]), "Command True Doppelganger must be offered"
    # The controls own the feature never: no reaction row, no creature.
    control = compile_character(sheet([], cl=18, primary="Qi", key="CON"), actor_id=OWNER, reaction_plan={"ask": True})
    assert not [r for r in control["typed_reactions"] if r.get("feature_id") == FEATURE]
    assert not [s for s in control["summons"] if s["summon"]["group"] == "true_doppelganger"]


def _fight(tmp_path, variant, target, far, spread=False):
    """Advance a real three-way Factory fight to the foe's turn and hand back the table."""
    owner_doc = _durable(_owner_sheet(variant))
    ally = _durable(sheet([], cl=18, primary="Qi", key="CON", name="True Reflection ally"))
    foe = sheet([], cl=18, score=30, kit={"starting_kit": KIT}, name="True Reflection foe")
    bundles = [compile_character(doc, actor_id=actor, reaction_plan={"ask": True} if actor == OWNER else {})
               for doc, actor in zip((owner_doc, ally, foe), (OWNER, ALLY, FOE))]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.tabletop_maps.save({"display_name": "True Reflection yard", "width_squares": 32,
        "height_squares": 12, "walls": [], "starts": {"team1": [[2, 6], [16, 6]], "team2": [[17, 6]]}})
    positions = {OWNER: {"x": 2 if far else 15, "y": 6}, ALLY: {"x": 16, "y": 6},
                 FOE: {"x": 14 if target == OWNER else 17, "y": 6}}
    if spread:  # the owner 20 ft from the ally it guards, the foe 25 ft from the owner and in reach of the ally
        positions = {OWNER: {"x": 2, "y": 6}, ALLY: {"x": 9, "y": 6}, FOE: {"x": 10, "y": 6}}
    match = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE], {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        positions, combat.factory_arenas(include_retired=True)["battlefield:map.true-reflection-yard"],
        [OWNER, ALLY], [FOE], control_modes={a: "MANUAL" for a in (OWNER, ALLY, FOE)},
        match_seed="M5-TRUE-REFLECTION", display_name="True Reflection regression", maximum_rounds=10)["match_id"]
    for _ in range(12):
        view = table.state(match)
        menu = view["menu"]
        if menu["actor_id"] == FOE:
            return combat, table, match
        assert table.act(match, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         view["last_sequence"])["status"] == "COMMITTED"
    raise AssertionError("no enemy turn")


def _resolve(table, match, candidate_id, *, use_feature):
    """Commit ``candidate_id``, answering every Ask me window; the feature's own window is used."""
    view = table.state(match)
    menu = view["menu"]
    answers = []
    for _ in range(16):
        result = table.act(match, candidate_id, menu["decision_id"], menu["state_version"],
                           view["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result, answers
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        selection = "USE" if use_feature and FEATURE in json.dumps(prompt) else "DECLINE"
        answers.append({**prompt["context"], "selection": selection})
    raise AssertionError("too many unrelated reaction prompts")


@pytest.mark.parametrize("variant,target,far,expected", [
    ("owner", OWNER, False, True),
    ("owner", ALLY, False, True),
    ("below", ALLY, False, False),
    ("wrong-owner", ALLY, False, False),
    ("owner", ALLY, True, False),
])
def test_native_reaction_payment_summon_and_replay(tmp_path, variant, target, far, expected):
    combat, table, match = _fight(tmp_path, variant, target, far)
    engine = combat._load_session(match).engine
    before_hp = engine.state.actors[target].current_hp
    before_qi = engine.state.actors[OWNER].resources.get(QI_POOL)
    before_uses = engine.state.actors[OWNER].resources.get(USE_POOL)
    menu = table.state(match)["menu"]
    option = next(o for group in menu["actions"] if group["label"] == "Bi Shou (Dagger) attack"
                  for o in group["options"] if o.get("target_ids") == [target])
    result, answers = _resolve(table, match, option["candidate_id"], use_feature=expected)
    loaded = combat._load_session(match)
    replay = loaded.mechanical.replay()
    actors = loaded.engine.state.actors
    owner = actors[OWNER]
    doubles = [a for a in actors.values() if a.entity_id == DOUBLE]
    _evidence(f"table-{variant}-{target.rsplit('-', 1)[-1]}-{far}", {
        "result": result["status"], "expected_reaction": expected, "answers": len(answers),
        "before_hp": before_hp, "after_hp": actors[target].current_hp, "replay": replay["status"],
        "owner_qi_before": before_qi, "owner_qi_after": owner.resources.get(QI_POOL),
        "owner_uses_before": before_uses, "owner_uses_after": owner.resources.get(USE_POOL),
        "concentration": getattr(owner.concentration, "source_definition_id", None),
        "doppelganger": [{"id": a.entity_id, "active": a.active, "status": (a.summon or {}).get("status"),
                          "expires_on": (a.summon or {}).get("expires_on"),
                          "duration_text": (a.summon or {}).get("duration_text")} for a in doubles],
    })
    assert result["status"] == "COMMITTED", result["status"]
    assert replay["status"] == "PASS"
    assert actors[target].current_hp < before_hp, "the attack must exercise real committed damage"
    assert len(answers) == (1 if expected else 0), answers
    if expected:
        assert owner.resources.get(QI_POOL) == before_qi - 8, "the Reaction must pay 8 Qi"
        assert owner.resources.get(USE_POOL) == before_uses - 1, "once per scene must spend its one-use counter"
        assert owner.concentration is not None
        assert owner.concentration.source_definition_id == CONCENTRATION_SOURCE, "Concentration must be held on the Doppelganger"
        assert len(doubles) == 1 and doubles[0].active and doubles[0].summon["status"] == "present"
        assert doubles[0].summon["owner"] == OWNER and doubles[0].summon["source"] == FEATURE
        assert doubles[0].current_hp == doubles[0].maximum_hp
        assert doubles[0].summon.get("expires_on") and doubles[0].summon.get("duration_text") == "1 minute"
    else:
        assert owner.resources.get(QI_POOL) == before_qi, "a control must not spend Qi"
        assert not [a for a in doubles if a.active and (a.summon or {}).get("status") == "present"]


def test_doppelganger_lands_within_10_feet_of_the_triggering_creature(tmp_path):
    """Printed placement: "one unoccupied space within 10 feet of the triggering creature", not of the owner.

    The owner stands 35 ft from the ally the foe hits, and the foe is 40 ft from the owner (inside the Reaction's
    60 ft range). Anchoring on the owner would place the Doppelganger about 25 ft from the trigger and fail here.
    """
    combat, table, match = _fight(tmp_path, "owner", ALLY, False, spread=True)
    engine = combat._load_session(match).engine
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    result, answers = _resolve(table, match, next(
        o["candidate_id"] for group in table.state(match)["menu"]["actions"] if group["label"] == "Bi Shou (Dagger) attack"
        for o in group["options"] if o.get("target_ids") == [ALLY]), use_feature=True)
    assert result["status"] == "COMMITTED", result["status"]
    assert len(answers) == 1, answers
    loaded = combat._load_session(match)
    doubles = [a for a in loaded.engine.state.actors.values() if a.entity_id == DOUBLE]
    assert len(doubles) == 1 and doubles[0].active
    landed = loaded.engine.grid.distance_ft(doubles[0].position, loaded.engine.state.actors[ALLY].position)
    _evidence("trigger-anchor", {"owner": [owner.position.x, owner.position.y],
                                 "trigger": [ally.position.x, ally.position.y],
                                 "doppelganger": [doubles[0].position.x, doubles[0].position.y],
                                 "distance_from_trigger_ft": landed})
    assert landed <= 10, landed
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_controlling_parent_and_shared_source_are_pinned():
    with zipfile.ZipFile(ROOT / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip") as archive:
        parent = archive.read(next(n for n in archive.namelist() if n.endswith("Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md")))
        shared = archive.read(next(n for n in archive.namelist() if n.endswith("Tianxia_Qi_Cultivation_Shared_Subpath_Rules_R4.md")))
    assert hashlib.sha256(parent).hexdigest() == "ca25b88915a2d83324a23feed94a54409d359369dbd0452fb29d28b938262584"
    assert hashlib.sha256(shared).hexdigest() == "b0853fd30b2fb92571ce25a0b24ac5cd5c8962603c4ae33fc2b8f90ed4d48ab2"
    text = parent.decode("utf-8-sig").splitlines()
    assert "### CL18 — True Reflection" == text[10198]
    full = "\n".join(text[10198:10415])
    for clause in ("True Doppelganger Statistics", "Sovereign Reflection", "Restoration Pattern",
                   "Mirrored Intercession", "After use, the Pattern is erased."):
        assert clause in full


class KnownTrueReflectionAcquisitionBlocker(Exception):
    """Only the recorded sealed validation_profile mismatch, never an acquisition pass."""


def _check_acquisition_status(run):
    assert run["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
    if run["status"] == "NEEDS_REVIEW":
        blockers = run["blockers"]
        if (len(blockers) == 1
                and blockers[0].get("code") == "PROJECTION_AUTHORITY_IDENTITY_MISMATCH"
                and blockers[0].get("details") == {"authority": "validation_profile", "path": str(PROFILE)}
                and json.loads(CONTRACT.read_text())["validation_profile"]["sha256"] == KNOWN_EXPECTED
                and hashlib.sha256(PROFILE.read_bytes()).hexdigest() == KNOWN_ACTUAL):
            raise KnownTrueReflectionAcquisitionBlocker(
                "Recorded validation_profile identity mismatch; True Reflection acquisition unverified")
        assert [b["code"] for b in blockers] == ["COMMAND6_CHARACTER_GM_CONSUMER_FAILED"]
        assert blockers[0]["details"]["consumer_report"]["harness_run"]["skipped"] is True


def _recorded_blocked_run():
    return {"status": "NEEDS_REVIEW", "blockers": [{
        "code": "PROJECTION_AUTHORITY_IDENTITY_MISMATCH",
        "details": {"authority": "validation_profile", "path": str(PROFILE)}}]}


def test_quarantine_matches_only_the_recorded_failure(monkeypatch, tmp_path):
    """The quarantine is not a blanket pass: a repaired profile or an unrelated blocker stays red."""
    profile = tmp_path / "validation_profile.json"
    contract = tmp_path / "projection_contract.json"
    profile.write_bytes(b'{"recorded": true}')
    contract.write_text(json.dumps({"validation_profile": {"sha256": KNOWN_EXPECTED}}))
    monkeypatch.setitem(globals(), "PROFILE", profile)
    monkeypatch.setitem(globals(), "CONTRACT", contract)
    monkeypatch.setitem(globals(), "KNOWN_ACTUAL", hashlib.sha256(profile.read_bytes()).hexdigest())
    with pytest.raises(KnownTrueReflectionAcquisitionBlocker):
        _check_acquisition_status(_recorded_blocked_run())
    unrelated = _recorded_blocked_run()
    unrelated["blockers"][0]["code"] = "UNRELATED_FAILURE"
    with pytest.raises(AssertionError):
        _check_acquisition_status(unrelated)


@pytest.mark.xfail(strict=True, raises=KnownTrueReflectionAcquisitionBlocker,
                   reason="Pre-existing sealed validation_profile mismatch; remove quarantine when repaired")
def test_native_creation_acquisition_baseline(catalog_environment, monkeypatch):
    """The shipped creation producer acquires the Subpath at CL18 once the sealed profile is repaired."""
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/nonexistent/true-reflection-no-browser")
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    project = builder.create_project(
        working_name="True Reflection acquisition baseline", concept="Mirror cultivation source delivery",
        source_reference=None, target_cl=18, power_band="rival/boss", creation_mode="quick",
        generation_route="ai_bootstrap", ability_scores={}, autogen_seed="MGR-T14-TRUE-REFLECTION",
        selections={"path_choice": [QI], "subpath_choice": [SUBPATH]}, method_planning_mode="AUTO")
    builder.commit_normal_first_cycle_catalog_choices(project["project_id"])
    run = app.state.character_creation.start(
        project["project_id"], execution_mode="STANDARD_API", idempotency_key="true-reflection-acquisition",
        controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
    _check_acquisition_status(run)
    document = app.state.character_creation.load_candidate_gm_context(run["run_id"])["owner_character_sheet"]
    assert document["identity"]["cultivation_level"] == 18
    owned = list(document["path_and_subpath"].get("path_feature_record_ids", []))
    owned += [r["feature_id"] for r in document["path_and_subpath"].get("earned_feature_occurrences", [])]
    assert FEATURE in owned
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={"ask": True})
    assert [r for r in bundle["typed_reactions"] if r.get("feature_id") == FEATURE]


def test_declined_reaction_summons_no_doppelganger_and_spends_nothing(tmp_path):
    """Owner 2026-10-19 (F6R blocker 1): a player who DECLINES the printed Reaction gets no True Doppelganger.

    The owner owns the feature and is asked; the answer is DECLINE. No Doppelganger may appear, no Qi or
    once-per-scene use is spent, and Concentration is not held on the Doppelganger.
    """
    combat, table, match = _fight(tmp_path, "owner", ALLY, False)
    before = combat._load_session(match).engine
    before_qi = before.state.actors[OWNER].resources.get(QI_POOL)
    before_uses = before.state.actors[OWNER].resources.get(USE_POOL)
    option = next(o for group in table.state(match)["menu"]["actions"] if group["label"] == "Bi Shou (Dagger) attack"
                  for o in group["options"] if o.get("target_ids") == [ALLY])
    # Probe the first Ask me window itself: the Doppelganger must not exist before the owner answers.
    view = table.state(match)
    first = table.act(match, option["candidate_id"], view["menu"]["decision_id"], view["menu"]["state_version"],
                      view["last_sequence"], [])
    assert first["status"] == "REACTION_REQUIRED", first
    pending = [a for a in combat._load_session(match).engine.state.actors.values() if a.entity_id == DOUBLE]
    assert not [a for a in pending if a.active], "the Doppelganger appeared before the owner answered"
    assert all(DOUBLE not in observed for observed in before.state.observations.values()), "inactive Doppelganger leaked into observations"
    assert not any(any(DOUBLE in observed for observed in event.payload.get("observations_after", {}).values())
                   for event in before.events), "inactive Doppelganger leaked in an observation event"
    answers = [{**first["reaction"]["context"], "selection": "DECLINE"}]
    result = table.act(match, option["candidate_id"], view["menu"]["decision_id"], view["menu"]["state_version"],
                       view["last_sequence"], answers)
    loaded = combat._load_session(match)
    actors = loaded.engine.state.actors
    owner = actors[OWNER]
    doubles = [a for a in actors.values() if a.entity_id == DOUBLE]
    _evidence("declined-reaction", {"answers": len(answers), "result": result["status"],
                                    "doppelgangers": [{"active": a.active, "summon": a.summon} for a in doubles],
                                    "qi_before": before_qi, "qi_after": owner.resources.get(QI_POOL),
                                    "uses_before": before_uses, "uses_after": owner.resources.get(USE_POOL),
                                    "concentration": getattr(owner.concentration, "source_definition_id", None)})
    assert result["status"] == "COMMITTED", result["status"]
    assert len(answers) == 1, answers
    assert not [a for a in doubles if a.active], "a declined Reaction must not summon"
    assert all(DOUBLE not in observed for observed in loaded.engine.state.observations.values()), "declined Doppelganger leaked into observations"
    assert not any(any(DOUBLE in observed for observed in event.payload.get("observations_after", {}).values())
                   for event in loaded.engine.events), "declined Doppelganger leaked in an observation event"
    assert owner.resources.get(QI_POOL) == before_qi and owner.resources.get(USE_POOL) == before_uses
    assert owner.concentration is None or owner.concentration.source_definition_id != CONCENTRATION_SOURCE
    assert loaded.mechanical.replay()["status"] == "PASS"
