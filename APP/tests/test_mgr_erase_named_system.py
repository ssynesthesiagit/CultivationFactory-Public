"""Public, synthetic table coverage for named Secret feature erasure.

No acquisition database, private fixture or repository history is required.
The sheets explicitly own the family features and their recorded Void Scar;
compilation and every subsequent table transaction use the real services.
"""
import ast
import json
from pathlib import Path
import zipfile

from combat import ext, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.canonical import canonical_sha256
from combat.ext import void_touched_cultivator as void
from tests.h1_support import ROOT, sheet

PARENT = "tianxia.subpath.qi.void_touched_cultivator"
FEATURE = PARENT + ".feature.hollow_field"
SIBLING = PARENT + ".feature.void_step"
OWNER = "actor:factory.worker2-owner"
ALLY = "actor:factory.worker2-ally"
FOE = "actor:factory.worker2-foe"
DAMAGE_TYPE_PROMPT = "choice:needle.empty_palm_damage_type"
POOL_PROMPT = "choice:needle.erase_pool"
SYSTEM_PROMPT = "choice:needle.erase_system"


def family_sheet(name):
    document = sheet([PARENT + ".feature." + feature for feature in
                      ("void_step", "empty_palm", "hollow_field", "erase")],
                     cl=14, dc=1, name=name)
    document["path_and_subpath"]["acquisition_choices"] = {
        PARENT: {"void_scar": "My reflection no longer appears."}}
    document["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.void"]}
    return document


def fixture(tmp_path):
    documents = [family_sheet("Wren"), sheet([], cl=14, name="Tobin"), family_sheet("Mara")]
    target_stats = documents[2]["ability_scores_and_statistics"]
    target_stats["hit_points"] = {"maximum": 300, "current": 300}
    target_stats["armor_class"]["base_value"] = 0
    ids = [OWNER, ALLY, FOE]
    bundles = []
    for actor_id, document in zip(ids, documents):
        folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundles.append(compile_character(document, actor_id=actor_id, reaction_plan={"ask": True}))
    target = bundles[2]
    field = next(row for row in target["action_catalog"]
                 if row["parameters"].get("typed", {}).get("source") == FEATURE)
    # Production compilation carries the family's Secret classification; the table
    # needs no injected category. The compiled id stays distinct from the mechanic id.
    assert field["parameters"]["typed"]["source_category"] == "Secret"
    assert field["source_definition_id"] != FEATURE
    # Inert sentinels exercise both retained-row stores, not invented effects.
    for store in ("typed_passives", "typed_reactions"):
        target[store].extend(
            {"feature_id": source, "name": name, "block": "erase_test_sentinel"}
            for source, name in ((FEATURE, "Hollow Field"), (SIBLING, "Void Step")))
    for bundle in bundles[1:]:
        bundle["actor_template"]["saving_throws"] = {
            ability: -50 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    for bundle in bundles:
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [OWNER, ALLY], [FOE], control_modes={actor_id: "MANUAL" for actor_id in ids},
        match_seed="ERASE-NAMED-SECRET-TABLE", display_name="Named feature erasure",
        maximum_rounds=15)["match_id"]
    turn(table, mid, OWNER)
    return combat, table, mid


def settle(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        rid = prompt["context"]["reaction_source_id"]
        choice = (picks or {}).get(rid, "first" if rid.startswith("choice:") else None)
        answer = {**prompt["context"], "selection": "USE" if choice is not None else "DECLINE"}
        if choice is not None and prompt.get("choice"):
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]] if choice == "first" else choice
        answers.append(answer)
    raise AssertionError("Too many prompts")


def end_turn(table, mid):
    settle(table, mid, table.state(mid)["menu"]["end_turn"])


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        end_turn(table, mid)
    raise AssertionError("No turn for " + actor)


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def candidate(combat, mid, name, *, target=None, at=None):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id) is not None
                and engine.action_catalog[c.source_definition_id].display_name == name
                and (target is None or c.target_ids == (target,))
                and (at is None or c.destination and (c.destination.x, c.destination.y) == at))


def test_named_feature_regression_has_no_private_fixture_dependencies():
    # Guard against reintroducing the transitive private acquisition/worker
    # fixtures that previously prevented this regression from exporting alone.
    imports = [node.module for node in ast.walk(ast.parse(Path(__file__).read_text()))
               if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests.")]
    assert imports == ["tests.h1_support"]


def test_named_secret_feature_table_choice_survives_reload_and_restores_only_its_rows(tmp_path):
    combat, table, mid = fixture(tmp_path)
    before = reload(tmp_path, mid)
    original = {
        store: [row for row in getattr(before, store)[FOE]
                if row.get("block") == "erase_test_sentinel"]
        for store in ("typed_passive_rows", "typed_reaction_rows")
    }
    assert all(len(rows) == 2 for rows in original.values())

    # Earn the two marks through real actions, not injected condition state.
    settle(table, mid, candidate(combat, mid, "Empty Palm: Unravel Manifestation", target=FOE).candidate_id,
           picks={DAMAGE_TYPE_PROMPT: ["FORCE"]})
    settle(table, mid, candidate(combat, mid, "Void Step", at=(2, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:2,6"], "choice:needle.void_step_trace": [FOE]})
    end_turn(table, mid)
    turn(table, mid, OWNER)
    assert void.mark_count(reload(tmp_path, mid).state.actors[FOE], OWNER) == 2

    key = "secret_feature|" + FEATURE
    prompts = settle(
        table, mid, candidate(combat, mid, "Erase: Erase Cultivation", target=FOE).candidate_id,
        picks={SYSTEM_PROMPT: [key], POOL_PROMPT: ["resource:core.qi"]},
    )
    system_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == SYSTEM_PROMPT)
    assert any(option["id"] == key for option in system_prompt["choice"]["options"])
    after = reload(tmp_path, mid)
    target = after.state.actors[FOE]
    condition = next(c for c in target.conditions.values() if c.condition_id == void.SYSTEM)
    assert condition.data["kind"] == "secret_feature"
    assert condition.data["value"] == FEATURE
    assert condition.data["band"] == "minute" and condition.data["erase"] == 1
    assert condition.expires_on.startswith("START_OF_SLOT_AT:")
    deadline = tuple(int(part) for part in condition.expires_on.split(":")[1:])
    assert deadline == (after.state.round_number + 10, after.state.current_slot_index)
    assert void.mark_count(target, OWNER) == 0
    for store, key in (("typed_passive_rows", "passive"), ("typed_reaction_rows", "reaction")):
        selected = [row for row in original[store] if row["feature_id"] == FEATURE]
        assert condition.data["rows"][key] == selected
        for row in original[store]:
            assert ext.any_false("row_allowed", after, target, row) is (row["feature_id"] == FEATURE)
    selected_reaction = next(row for row in original["typed_reaction_rows"] if row["feature_id"] == FEATURE)
    sibling_reaction = next(row for row in original["typed_reaction_rows"] if row["feature_id"] == SIBLING)
    assert not typed_reactions.can_react(after, target, selected_reaction)
    assert typed_reactions.can_react(after, target, sibling_reaction)

    # A committed turn after cold reload must still hide only the selected
    # feature, leaving another action of the very same Secret Law reachable.
    end_turn(table, mid)
    turn(table, mid, FOE)
    blocked = reload(tmp_path, mid)
    sources = {blocked.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source")
               for c in blocked.legal_candidates() if c.source_definition_id in blocked.action_catalog}
    assert FEATURE not in sources and SIBLING in sources

    # Let the printed minute expire through table commits, then cold-reload
    # again: both the action and retained passive/reaction rows must return.
    for _ in range(10):
        end_turn(table, mid)
        turn(table, mid, FOE)
        restored = reload(tmp_path, mid)
        still_erased = any(c.condition_id == void.SYSTEM
                           for c in restored.state.actors[FOE].conditions.values())
        now = (restored.state.round_number, restored.state.current_slot_index)
        assert still_erased is (now < deadline), "Erasure must last exactly the printed minute"
        if not still_erased:
            break
    else:
        raise AssertionError("Named Secret feature did not return after 1 minute")
    for store, rows in original.items():
        current = getattr(restored, store)[FOE]
        for row in rows:
            assert current.count(row) == 1
            assert not ext.any_false("row_allowed", restored, restored.state.actors[FOE], row)
    sources = {restored.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source")
               for c in restored.legal_candidates() if c.source_definition_id in restored.action_catalog}
    assert FEATURE in sources and SIBLING in sources
