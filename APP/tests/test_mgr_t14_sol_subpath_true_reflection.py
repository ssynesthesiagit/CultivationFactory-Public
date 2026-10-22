"""Native True Reflection delivery, settlement and cold-replay acceptance.

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
    if not ACTIVE_DCC_PUBLICATION.is_file():
        # The publication is private and excluded from public exports; the native
        # acquisition checks run only where it is installed (private/local queue).
        pytest.skip("native acquisition needs the private installed DCC publication")
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


def _act(table, match, candidate, *, settlement=None, auto=False):
    view = table.state(match)
    menu = view["menu"]
    answers, offers = [], []
    for _ in range(32):
        result = (table.auto_step(match, view["last_sequence"], answers) if auto else
                  table.act(match, candidate, menu["decision_id"], menu["state_version"], view["last_sequence"], answers))
        if result["status"] != "REACTION_REQUIRED":
            return {**result, "_reflection_offers": offers}
        reaction = result["reaction"]
        ours = FEATURE in json.dumps(reaction)
        if ours:
            assert result["status"] == "REACTION_REQUIRED"
            offers.append(deepcopy(reaction))
            assert reaction["context"]["reactor_id"] == OWNER, reaction
            if settlement is None:
                return result
            choices = (reaction.get("choice") or {}).get("options") or []
            answer = {**reaction["context"], "selection": settlement}
            if choices:
                assert settlement == "USE", "decline must settle the initial optional window"
                selected = next((o["id"] for o in choices if o["id"] == "ranged"), choices[0]["id"])
                answer["option_ids"] = [selected]
            answers.append(answer)
        else:
            # Preserve every natively acquired feature and pass genuine optional
            # earlier windows through the table's own answer transport.
            answers.append({**reaction["context"], "selection": "DECLINE"})
    raise AssertionError("too many reaction prompts")


@pytest.mark.parametrize("variant,target,far,expected,settlement,seat", [
    ("owner", OWNER, False, True, "USE", "manual"),
    ("owner", ALLY, False, True, "USE", "manual"),
    ("below", ALLY, False, False, None, "manual"),
    ("wrong-owner", ALLY, False, False, None, "manual"),
    ("owner", ALLY, True, False, None, "manual"),
    ("owner", OWNER, False, True, "DECLINE", "manual"),
    ("owner", ALLY, False, True, "USE", "owner-auto"),
    ("owner", ALLY, False, True, "USE", "attacker-auto"),
])
def test_native_damage_reaction_table_reload(acquired, tmp_path, variant, target, far, expected, settlement, seat):
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
    if seat == "owner-auto":
        # Configure the real reaction plan, keeping all acquired abilities.
        # Otherwise Qi Armor can legitimately consume the sole Reaction first.
        held = [r["feature_id"] for r in bundles[0]["typed_reactions"] if r.get("feature_id") != FEATURE]
        bundles[0] = compile_character(document, actor_id=OWNER,
            reaction_plan={"off": held, "order": [FEATURE]})
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
    initial = CombatService(ROOT, tmp_path)._load_session(match).engine
    initial_sequence = initial.state.event_sequence
    qi_before = initial.state.actors[OWNER].resources["resource:core.qi"]
    assert initial.state.actors[OWNER].reaction_available
    if seat == "owner-auto":
        combat.set_controller_mode(match, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    if seat == "attacker-auto":
        combat.set_controller_mode(match, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = _act(table, match, option["candidate_id"], settlement=settlement, auto=seat == "attacker-auto")
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
    offers = result.get("_reflection_offers", [])
    assert result["status"] == "COMMITTED", result
    if expected and seat != "owner-auto":
        assert offers, "True Reflection offered no native damage reaction"
        assert all(o["context"]["reactor_id"] == OWNER for o in offers)
    if not expected or seat == "owner-auto":
        assert not offers
    events = [e for e in loaded.engine.events if e.sequence > initial_sequence]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FOE
               and (target in e.target_ids or seat == "attacker-auto")]
    assert len(packets) == 1, "the original damage must commit exactly once"
    packet = packets[0]
    actual_target = packet.target_ids[0]
    assert actual_target in (OWNER, ALLY)
    assert packet.payload["hp_damage"] > 0
    assert initial.state.actors[actual_target].current_hp - loaded.engine.state.actors[actual_target].current_hp == packet.payload["hp_damage"]
    body = [a for a in loaded.engine.state.actors.values()
            if a.owner_id == OWNER and (a.summon or {}).get("source") == FEATURE and a.active]
    spends = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.actor_id == OWNER
              and e.source_definition_id == FEATURE]
    resolutions = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == FEATURE]
    paid = expected and settlement == "USE"
    owner = loaded.engine.state.actors[OWNER]
    if paid:
        assert qi_before - owner.resources["resource:core.qi"] == 8
        assert len(spends) == len(resolutions) == 1
        assert not owner.reaction_available
        assert resolutions[0].actor_id == OWNER
        assert len(body) == 1
        reflection = body[0]
        record = reflection.summon
        assert record["owner"] == OWNER and record["source"] == FEATURE
        assert record["original_actor"] == FOE and record["source_cl"] == 18
        assert record["status"] == "present" and record["duration_text"] == "1 minute"
        from combat.ext.effect_durations import parse_round
        assert parse_round(record["expires_on"]) is not None
        assert owner.concentration.source_definition_id == FEATURE
        assert reflection.maximum_hp == 6 * 18
        assert reflection.armor_class == 15 + owner.proficiency_bonus
        assert reflection.speed_ft == 40 and reflection.saving_throws == owner.saving_throws
        assert loaded.engine.grid.distance_ft(reflection.position, loaded.engine.state.actors[FOE].position) <= 10
        assert loaded.engine.grid.placement_legal(reflection.position,
            footprint=loaded.engine._footprint(reflection),
            occupied_cells=loaded.engine._occupied_cells_except(reflection.entity_id))
        # The Doppelganger does not copy the foe's identity or printed creature type.
        assert set(reflection.creature_types).isdisjoint(loaded.engine.state.actors[FOE].creature_types)
        assert not reflection.resources
        assert any(c.condition_id == "condition:typed.true_reflection_spent" for c in owner.conditions.values())
        assert not [e for e in events if e.event_type == "GM_RIDER" and e.source_definition_id == FEATURE]
        if seat != "owner-auto":
            assert any("true_reflection_space" in o["context"]["reaction_source_id"] for o in offers)
            assert record["mirror_strike_mode"] == "ranged"
    else:
        assert not spends and not resolutions and not body
        assert owner.resources["resource:core.qi"] == qi_before
        assert owner.reaction_available
    assert loaded.verify()["status"] == "PASS"
    cold = CombatService(ROOT, tmp_path)._load_session(match)
    assert cold.mechanical.replay()["status"] == "PASS"
    assert cold.engine.state.actors[OWNER].resources == owner.resources
    assert [(a.entity_id, a.summon) for a in cold.engine.state.actors.values() if a.active and a.owner_id == OWNER and (a.summon or {}).get("source") == FEATURE] == [(a.entity_id, a.summon) for a in body]
    _evidence("settlement-" + seat + "-" + variant + "-" + str(target) + "-" + str(far) + "-" + str(settlement),
        {"status": result["status"], "offer_count": len(offers), "paid_qi": qi_before - owner.resources["resource:core.qi"],
         "damage_packets": len(packets), "hp_damage": packet.payload["hp_damage"],
         "reaction_paid": int(not owner.reaction_available), "bodies": [a.summon for a in body],
         "replay": cold.mechanical.replay()["status"]})


def test_unimplemented_true_reflection_clauses_keep_their_gm_riders():
    """Review 143522 (blocking): riders must name each printed clause the engine does not implement."""
    record = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/sol107.json").read_text())[
        "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"]
    riders = " | ".join(record.get("riders") or [])
    assert record.get("riders"), "unimplemented printed clauses must carry GM riders"
    for clause in ("Command True Doppelganger", "Mirrored Intercession", "Echoed Pattern", "Sovereign Reflection"):
        assert clause in riders, clause
    assert record["duration"]["concentration"] is True
