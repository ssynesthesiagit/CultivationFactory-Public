"""Native True Reflection delivery regressions, deliberately red until delivered.

The assigned source leaf is only the activation header. These checks acquire
the actual Subpath through the deterministic creation pipeline, never inject
ownership or effect receipts, and exercise real table damage and cold replay.
No browser or model server is used. This file does not certify the untested
Doppelganger commands or Sovereign Reflection procedure.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

from app.api import create_app
from app.core import FoundryError
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT


FEATURE = "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"
SUBPATH = FEATURE.split(".feature.")[0]
QI = "tianxia.path.qi_cultivation"
# Native seeded acquisition binds this installed publication. It is deliberately
# excluded from public exports; declaring the real dependency lets routing use
# private CI/local queue instead of reporting public setup errors as combat evidence.
ACTIVE_DCC_PUBLICATION = ROOT / "authority/Tianxia_DCC_Semantic_Publication_Active_v1.json"
OWNER, ALLY, FOE = [FACTORY_ACTOR_PREFIX + "true-reflection-" + name
                   for name in ("owner", "ally", "foe")]


def _evidence(name, value):
    print(name, json.dumps(value, sort_keys=True))
    directory = os.environ.get("TRUE_REFLECTION_EVIDENCE_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture(scope="module")
def acquired(catalog_environment):
    """Use the shipped creation producer, with its browser consumer disabled."""
    assert ACTIVE_DCC_PUBLICATION.is_file(), "native acquisition requires the installed DCC publication"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/nonexistent/true-reflection-no-browser")
        app = create_app(catalog_environment["settings"])
        documents = {}
        for name, cl, selected in (("owner", 18, True), ("below", 17, True),
                                   ("wrong-owner", 18, False)):
            project = app.state.character_builder.create_project(
                working_name="True Reflection " + name, concept="Mirror cultivation source delivery",
                source_reference=None, target_cl=cl, power_band="rival/boss",
                creation_mode="quick", generation_route="ai_bootstrap", ability_scores={},
                autogen_seed="MGR-T14-TRUE-REFLECTION-" + name,
                selections={"path_choice": [QI], **({"subpath_choice": [SUBPATH]} if selected else {})},
                method_planning_mode="AUTO")
            app.state.character_builder.commit_normal_first_cycle_catalog_choices(project["project_id"])
            try:
                run = app.state.character_creation.start(
                    project["project_id"], execution_mode="STANDARD_API",
                    idempotency_key="true-reflection-" + name,
                    controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
            except FoundryError as exc:
                raise AssertionError(f"Native acquisition blocked: {exc.code}: {exc.details}") from exc
            _evidence("creation-" + name, {"status": run["status"], "blockers": run.get("blockers", [])})
            if run["status"] != "READY_FOR_REVIEW":
                assert run["status"] == "NEEDS_REVIEW", run
                assert [b["code"] for b in run["blockers"]] == ["COMMAND6_CHARACTER_GM_CONSUMER_FAILED"], run["blockers"]
                harness = run["blockers"][0]["details"]["consumer_report"]["harness_run"]
                assert harness["skipped"] is True and harness["exit_code"] is None
                assert "Explicit TIANXIA_BROWSER_EXECUTABLE is missing" in harness["stderr"]
            document = app.state.character_creation.load_candidate_gm_context(run["run_id"])["owner_character_sheet"]
            assert document["identity"]["cultivation_level"] == cl
            compiled = compile_character(document, actor_id=OWNER, reaction_plan={"ask": True})
            owned = list(document["path_and_subpath"].get("path_feature_record_ids", []))
            owned += document['path_and_subpath'].get('source_granted_subpath_feature_record_ids', [])
            owned += [r["feature_id"] for r in document["path_and_subpath"].get("earned_feature_occurrences", [])]
            assert (FEATURE in owned) == (cl >= 18 and selected)
            _evidence("acquisition-" + name, {
                "creation_status": run["status"], "cl": cl, "subpath_selected": selected,
                "owned_features": sorted(set(owned)), "diagnostics": compiled["diagnostics"],
                "feature_reactions": [r for r in compiled["typed_reactions"] if r.get("feature_id") == FEATURE],
                "feature_actions": [a for a in compiled["action_catalog"] if FEATURE in a["source_definition_id"]],
                "summon_count": len(compiled.get("summons") or []),
            })
            documents[name] = document
        yield documents


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


def _act(table, match, candidate):
    view = table.state(match)
    menu = view["menu"]
    answers = []
    for _ in range(16):
        result = table.act(match, candidate, menu["decision_id"], menu["state_version"], view["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED" or FEATURE in json.dumps(result["reaction"]):
            return result
        # Native acquisition also grants earlier Qi features. Decline those
        # genuine optional windows instead of deleting their ownership rows.
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    raise AssertionError("too many unrelated reaction prompts")


@pytest.mark.parametrize("variant,target,far,expected", [
    ("owner", OWNER, False, True),
    ("owner", ALLY, False, True),
    ("below", ALLY, False, False),
    ("wrong-owner", ALLY, False, False),
    ("owner", ALLY, True, False),
])
def test_native_damage_reaction_table_reload(acquired, tmp_path, variant, target, far, expected):
    document = deepcopy(acquired[variant])
    # Combat fixture durability/AC only; ownership and all feature data remain
    # the output of the native producer, with no added receipts or effects.
    document["ability_scores_and_statistics"]["armor_class"] = {"base_value": 1}
    document["ability_scores_and_statistics"]["hit_points"] = {"maximum": 500}
    ally = sheet([], cl=18)
    ally["ability_scores_and_statistics"]["armor_class"] = {"base_value": 1}
    ally["ability_scores_and_statistics"]["hit_points"] = {"maximum": 500}
    foe = sheet([], cl=18, score=30, kit={"starting_kit": KIT})
    bundles = [compile_character(doc, actor_id=actor, reaction_plan={"ask": True} if actor == OWNER else {})
               for doc, actor in zip((document, ally, foe), (OWNER, ALLY, FOE))]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.tabletop_maps.save({"display_name": "True Reflection yard", "width_squares": 32,
        "height_squares": 12, "walls": [], "starts": {"team1": [[2, 6], [16, 6]], "team2": [[17, 6]]}})
    positions = {OWNER: {"x": 2 if far else 15, "y": 6}, ALLY: {"x": 16, "y": 6},
                 FOE: {"x": 16 if target == OWNER else 17, "y": 6}}
    match = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE], {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        positions, combat.factory_arenas(include_retired=True)["battlefield:map.true-reflection-yard"],
        [OWNER, ALLY], [FOE], control_modes={a: "MANUAL" for a in (OWNER, ALLY, FOE)},
        match_seed="H5-CHOICES", display_name="True Reflection regression", maximum_rounds=10)["match_id"]
    for _ in range(12):
        view = table.state(match)
        if view["menu"]["actor_id"] == FOE:
            break
        assert _act(table, match, view["menu"]["end_turn"])["status"] == "COMMITTED"
    assert table.state(match)["menu"]["actor_id"] == FOE
    before = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[target].current_hp
    menu = table.state(match)["menu"]
    option = next(o for group in menu["actions"] if group["label"] == "Bi Shou (Dagger) attack"
                  for o in group["options"] if o.get("target_ids") == [target])
    result = _act(table, match, option["candidate_id"])
    loaded = CombatService(ROOT, tmp_path)._load_session(match)
    replay = loaded.mechanical.replay()
    after = loaded.engine.state.actors[target].current_hp
    _evidence(f"table-{variant}-{target.rsplit('-', 1)[-1]}-{far}", {
        "result": result["status"], "expected_reaction": expected, "before_hp": before,
        "after_hp": after, "replay": replay["status"],
        "owner_resources": loaded.engine.state.actors[OWNER].resources,
        "owned_summons": [a.entity_id for a in loaded.engine.state.actors.values() if a.owner_id == OWNER],
    })
    assert replay["status"] == "PASS"
    if expected:
        # First unfixed operational clause. In the base this attack commits
        # damage with no opportunity to spend 8 Qi or manifest the Asset.
        assert result["status"] == "REACTION_REQUIRED", "True Reflection offered no native damage reaction"
        assert FEATURE in json.dumps(result["reaction"])
    else:
        assert result["status"] == "COMMITTED"
        assert after < before, "control must exercise real committed damage"
        assert not [a for a in loaded.engine.state.actors.values()
                    if a.owner_id == OWNER and FEATURE in json.dumps(a.summon or {})]
