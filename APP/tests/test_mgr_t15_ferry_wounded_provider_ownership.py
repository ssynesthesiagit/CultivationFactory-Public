"""F2: provider ownership, source-effective passives and same-round admission."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.test_mgr_t14_sol_subpath_ferry_wounded import (
    acquired, damage_ally, FERRY, REACTION, AXE,
)
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn


def test_complete_trigger_ownership_keeps_other_generic_reactions(monkeypatch):
    authority_path = Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
    donor_id = "tianxia.subpath.body.bojutsu.feature.sweeping_strike"
    donor = json.loads(authority_path.read_text())["mechanics"][donor_id]
    ids = ["test:ferry-f2.claimed", "test:ferry-f2.unclaimed"]
    mechanics = {}
    for source in ids:
        row = deepcopy(donor)
        row.update(mechanic_id=source, name=source,
                   effects=[{"type": "temp_hp", "flat": 1, "applies_to": "self"}])
        mechanics[source] = row

    def claim(info):
        if ids[0] in info["owned_ids"]:
            info["passives"].append({"block": "test_owner", "feature_id": ids[0],
                                     "trigger_owner": "test_provider"})
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_actions",
                        [*ext._HOOKS.get("compile_actions", []), claim])
    from tests.h1_support import sheet
    doc = sheet([], cl=6)
    doc["path_and_subpath"] = {"path_feature_record_ids": ids}
    bundle = compile_character(doc, actor_id=OWNER,
                               typed_authority={"mechanics": mechanics})
    generic = [r["feature_id"] for r in bundle["typed_reactions"] if r["block"] == "generic"]
    assert ids[0] not in generic
    assert generic.count(ids[1]) == 1
    assert sum(r.get("trigger_owner") == "test_provider" for r in bundle["typed_passives"]) == 1
    assert any(r["block"] == "opportunity" for r in bundle["typed_reactions"])


def mixed_shugenja(acquired):
    doc = deepcopy(acquired)
    doc["identity"].update(cultivation_level=11, proficiency_bonus=4)
    path = next(p for p in doc["path_and_subpath"]["paths"]
                if p["path_id"] == "tianxia.path.qi_cultivation")
    path.update(effective_cl=6, attainment=6)
    # The shared fixture selects its Subpath through parent-bound subpaths[],
    # not the provenance-gated path-level acquisition fields.
    selection = next(s for s in doc["path_and_subpath"]["subpaths"]
                     if s["owning_path_id"] == path["path_id"])
    selection["subpath_id"] = "tianxia.subpath.qi.shugenja"
    return doc


def test_mixed_shugenja_selects_parent_bound_progression_without_mutating_ferry(acquired):
    from combat.ext.shugenja_terrain import TERRAIN
    from combat.subpath_acquisition import acquired_features
    from tests.h1_support import ROOT

    original = deepcopy(acquired)
    doc = mixed_shugenja(acquired)
    assert doc["identity"]["cultivation_level"] == 11
    assert doc["identity"]["proficiency_bonus"] == 4
    features = acquired_features(doc, ROOT)
    assert features[TERRAIN] == {"cl": 6, "min_cl": 6}
    assert FERRY not in features
    assert acquired == original
    assert FERRY in acquired_features(acquired, ROOT)


@pytest.mark.parametrize("benefit", ["temp_hp", "qi"])
def test_mixed_attainment_passive_uses_the_characters_pb_on_table_and_reload(tmp_path, acquired, benefit):
    from combat.ext.shugenja_terrain import TERRAIN
    from tests import r1i_service_support as s
    from tests.test_a2_qi_subpaths8 import fixture as scene, cold, seal

    bundle = compile_character(mixed_shugenja(acquired), actor_id=s.OWNER,
                               reaction_plan={"ask": True})
    passive = next(r for r in bundle["typed_passives"] if r["feature_id"] == TERRAIN)
    # Terrain Attunement prints "your Proficiency Bonus", so the CL11 character
    # pays its own 4 while CL-scaled numbers still read the CL6 attainment.
    assert passive["numbers"]["cl"] == 6
    assert passive["numbers"]["pb"] == 4
    assert bundle["actor_template"]["proficiency_bonus"] == 4
    qi = "resource:core.qi"
    next(r for r in bundle["actor_template"]["resources"] if r["resource_id"] == qi)["initial"] = 20
    seal(bundle)

    def native_owner(bundles):
        bundles[0] = deepcopy(bundle)
    combat, table, mid, send, commit = scene(tmp_path, [], terrain=benefit,
                                            bundle_transform=native_owner)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    assert owner.temporary_hp == (8 if benefit == "temp_hp" else 0)
    assert owner.resources[qi] == (24 if benefit == "qi" else 20)
    # The scene decision is paid/delivered once, including after a real turn.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != s.OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    persisted = cold(tmp_path, mid).state.actors[s.OWNER]
    assert persisted.temporary_hp == owner.temporary_hp
    assert persisted.resources[qi] == owner.resources[qi]


def test_feature_blocks_scope_numbers_and_restore_defaults(monkeypatch):
    from combat import typed_reactions as tr
    features = {
        "low:save": {"block": "save_bonus", "bonus": "pb"},
        "low:attacks": {"block": "extra_attack", "attacks_by_cl": {"1": 1, "11": 2}},
        "low:custom": {"block": "test_source_numbers"},
        "global:save": {"block": "save_bonus", "bonus": "pb"},
    }
    monkeypatch.setattr(tr, "rules", lambda: {"features": features})
    ext.effects()
    def custom(block, spec, row, info):
        if block == "test_source_numbers":
            return [{**row, "pb": info["pb"], "cl": info["cl"]}]
    monkeypatch.setitem(ext._HOOKS, "compile_block", [*ext._HOOKS.get("compile_block", []), custom])
    low = {"pb": 3, "cl": 6}
    result = tr.compile_blocks(list(features), pb=4, cl=11, key_mod=2,
        saves={}, resource_ids={}, numbers_by_source={k: low for k in features if k.startswith("low:")})
    rows = {r["feature_id"]: r for r in result["passives"]}
    assert rows["low:save"]["bonus"] == 3
    assert rows["low:attacks"]["attacks"] == 1
    assert (rows["low:custom"]["pb"], rows["low:custom"]["cl"]) == (3, 6)
    assert rows["global:save"]["bonus"] == 4


def test_source_passive_variants_keep_full_ownership_and_rows(monkeypatch):
    from combat.source_compilation import compile_passives
    ext.effects()
    def provider(rows, info):
        assert set(info["owned_ids"]) == {"low", "high", "global"}
        pb = info["numbers"]["pb"]
        # In-place changes must not contaminate the other numeric variant.
        rows[0]["value"] += pb
        return [*rows, {"feature_id": "low", "value": pb},
                {"feature_id": "high", "value": pb},
                {"value": pb}]
    monkeypatch.setitem(ext._HOOKS, "compile_passives", [provider])
    rows = [{"feature_id": "global", "value": 0}]
    info = {"owned_ids": ["low", "high", "global"], "numbers": {"pb": 4}}
    result = compile_passives(rows, info, {"low": {"pb": 3}, "high": {"pb": 5}})
    assert result == [{"feature_id": "global", "value": 4},
                      {"feature_id": "low", "value": 3},
                      {"feature_id": "high", "value": 5}, {"value": 4}]
    assert rows == [{"feature_id": "global", "value": 0}]


def test_source_passive_variants_preserve_interleaved_row_priority(monkeypatch):
    from combat.source_compilation import compile_passives
    ext.effects()
    def provider(rows, info):
        return [{"feature_id": source, "block": block, "pb": info["numbers"]["pb"]}
                for source, block in [("low", "first"), ("global", "middle"), ("low", "last")]]
    monkeypatch.setitem(ext._HOOKS, "compile_passives", [provider])
    result = compile_passives([], {"owned_ids": ["low", "global"], "numbers": {"pb": 4}},
                              {"low": {"pb": 3}})
    assert [(r["block"], r["pb"]) for r in result] == [
        ("first", 3), ("middle", 4), ("last", 3)]


def test_reaction_refresh_does_not_allow_second_ferry_in_same_round(tmp_path, acquired):
    second_foe = FOE + "1"
    owner_bundle = compile_character(acquired, actor_id=OWNER, reaction_plan={"ask": True})
    def initiative_and_reliable_attacks(bundles):
        for b in bundles:
            aid = b["actor_id"]
            b["actor_template"]["initiative_bonus"] = {
                FOE: 100, OWNER: 50, second_foe: -50, ALLY: -100}[aid]
            if aid in (FOE, second_foe):
                for action in b["action_catalog"]:
                    if action["display_name"] == "Fu (Short Axe) attack":
                        action["attack_bonus"] = 100
                        typed = action.get("parameters", {}).get("typed")
                        if typed:
                            typed["numbers"]["attack_bonus"] = 100
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [], cl=6, foe_kit=AXE, extra_foes=1,
        owner_bundle=owner_bundle, bundle_transform=initiative_and_reliable_attacks,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6},
                   FOE: {"x": 5, "y": 6}, second_foe: {"x": 5, "y": 7}},
        seed="MGR-T15-FERRY-SAME-ROUND")
    # The first foe acts before the owner, the second after it. Starting at the
    # owner's first turn means this first attack is in round two.
    turn(table, mid, FOE)
    first, _, prompts = damage_ally(combat, table, mid, tmp_path,
                                    choices={REACTION: ["cell:4,6"]})
    assert any(p["context"]["reaction_source_id"] == REACTION for p in prompts)
    first_round = first.state.round_number
    turn(table, mid, OWNER)
    refreshed = reload(tmp_path, mid)
    assert refreshed.state.round_number == first_round
    assert refreshed.state.actors[OWNER].reaction_available
    assert refreshed.state.actors[OWNER].turn_flags["once_per_round:typed." + FERRY] == first_round

    turn(table, mid, second_foe)
    before = reload(tmp_path, mid)
    start = len(before.events)
    from tests.worker2_support import candidate
    prompts = settle(table, mid,
        candidate(combat, mid, "Fu (Short Axe) attack", target=ALLY).candidate_id,
        choices={REACTION: ["cell:4,7"]})
    after = reload(tmp_path, mid)
    events = after.events[start:]
    assert after.state.round_number == first_round
    assert any(e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids
               and int(e.payload.get("hp_damage") or 0) > 0 for e in events)
    assert not any(p["context"]["reaction_source_id"] == REACTION for p in prompts)
    assert after.state.actors[OWNER].reaction_available
    assert after.state.actors[ALLY].position == before.state.actors[ALLY].position
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert not any(e.source_definition_id == FERRY and e.event_type in {
        "REACTION_WINDOW_OPENED", "MOVEMENT_COMMITTED", "RESOURCE_SPENT"} for e in events)
    # The original native next-round acceptance regression remains unchanged.
