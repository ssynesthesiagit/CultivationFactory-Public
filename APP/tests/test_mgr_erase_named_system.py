"""A named Secret feature can be selected, erased and restored through the table."""
from combat import ext, typed_reactions
from combat.authority_projection import compile_project_character
from combat.canonical import canonical_sha256
from combat.ext import void_touched_cultivator as void
from tests.test_mgr_erase import (
    DAMAGE_TYPE_PROMPT, POOL_PROMPT, SYSTEM_PROMPT, PARENT,
    acquired, helpless_foe, owner_bundle, owner_doc,
)
from tests.worker2_support import ALLY, FOE, OWNER, candidate, end_turn, fixture, reload, settle, turn

FEATURE = PARENT + ".feature.hollow_field"
SIBLING = PARENT + ".feature.void_step"


def test_named_secret_feature_table_choice_survives_reload_and_restores_only_its_rows(acquired, tmp_path):
    service, project = acquired

    def named_secret_target(bundles):
        doc = owner_doc(service, project, name="Mara")
        doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": 300, "current": 300}
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 0
        target = compile_project_character(service, project, doc, actor_id=FOE,
                                           reaction_plan={"ask": True})
        field = next(row for row in target["action_catalog"]
                     if row["parameters"].get("typed", {}).get("source") == FEATURE)
        # Public compiled fixtures omit the Secret category. Seal it on the
        # actual compiled action, whose id differs from its typed mechanic id.
        field["parameters"]["typed"]["source_category"] = "Secret"
        assert field["source_definition_id"] != FEATURE
        # Inert synthetic rows exercise both retained-row stores without adding
        # any invented combat behaviour to Hollow Field or its sibling.
        for store in ("typed_passives", "typed_reactions"):
            target[store].extend(
                {"feature_id": source, "name": name, "block": "erase_test_sentinel"}
                for source, name in ((FEATURE, "Hollow Field"), (SIBLING, "Void Step"))
            )
        target.pop("bundle_sha256", None)
        target["bundle_sha256"] = canonical_sha256(target)
        bundles[2] = target
        helpless_foe(bundles)

    combat, table, mid = fixture(
        tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
        bundle_transform=named_secret_target,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
        seed="ERASE-NAMED-SECRET-TABLE",
    )
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
