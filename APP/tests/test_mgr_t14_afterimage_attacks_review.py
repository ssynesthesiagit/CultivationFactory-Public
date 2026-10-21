"""Review findings: movement-earned images and real saved portable attacks.

No synthetic image producer, live models, UI, or runtime engine patching.
"""
from pathlib import Path

import pytest

from combat import motion
from combat.canonical import canonical_sha256, sha256_file
from combat.ext.afterimage_targeting import destroy_image
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, INTEGRATION_SCHEMA
from combat.portable_runtime_authority import runtime_actor_id
from combat.tabletop_service import TabletopService
from tests.test_auto_athletics import _sheet
from tests.test_c2_review import table_fixture
from tests.hunt15_support import act, turn, reload
from tests.auto_worker1_support import resolve
from tests.test_c3ar_runtime_executability import adapter, bundle, runtime_package

OWNER = "actor:factory.afterimage-review"
FEATURE = "TAL_ATHLETICS_AFTERIMAGE"
FOE = "actor:factory.afterimage-review-foe"
ROOT = Path(__file__).resolve().parents[1]


def walk(table, mid, points):
    """Commit the declared route, accepting only a genuine opportunity attack."""
    menu = table.state(mid)["menu"]
    path = [{"x": x, "y": y} for x, y in points]
    quote = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], OWNER, path)
    answers = []
    for _ in range(8):
        result = table.commit_move_path(mid, quote["candidate"]["candidate_id"], menu["decision_id"],
            menu["state_version"], OWNER, path, reactions=answers)
        if result["status"] == "COMMITTED":
            return
        assert result["status"] == "REACTION_REQUIRED", result
        context = result["reaction"]["context"]
        assert context["reaction_source_id"] in {
            "reaction:core.opportunity_attack", "reaction:typed.opportunity_attack",
            "system:combat.opportunity_attack"}
        answers.append({**context, "selection": "USE"})
    raise AssertionError("movement did not finish")


def earned_image(combat, table, mid):
    turn(table, mid, OWNER)
    walk(table, mid, [(x, 6) for x in range(2, 8)])
    engine = reload(combat, mid)
    owner = engine.state.actors[OWNER]
    held = next(c for c in owner.conditions.values() if c.condition_id == motion.AFTERIMAGE)
    oid = held.data.get("image_object_id")
    assert oid in engine.state.map_images, "movement-earned Afterimage must bind a native image"
    image = engine.state.map_images[oid]
    assert (image.position.x, image.position.y) == (7, 6)
    assert image.owner_id == OWNER and image.component["condition_instance_id"] == held.instance_id
    assert image.component["intent_id"] and owner.movement_remaining_ft == 5
    assert oid not in engine.state.objects
    return oid


def assert_attack(combat, mid, start, oid, attacker, expected, hp):
    engine = reload(combat, mid)
    events = engine.events[start:]
    decisions = [e for e in events if e.payload.get("kind") == "afterimage_targeting"]
    assert len(decisions) == 1
    assert decisions[0].payload["result"] == expected
    assert decisions[0].actor_id == attacker
    assert decisions[0].payload["image_object_id"] == oid
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert engine.state.map_images[oid].destroyed == (expected == 1)
    assert motion.has_afterimage(engine.state.actors[OWNER]) == (expected == 2)
    if expected == 1:
        assert not rolls and engine.state.actors[OWNER].current_hp == hp
        receipt = next(e for e in events if e.payload.get("kind") == "attack_target_intercepted")
        assert receipt.target_ids == (oid,) and receipt.payload["original_target_id"] == OWNER
    else:
        assert len(rolls) == 1 and rolls[0].target_ids == (OWNER,)
        assert engine.state.actors[OWNER].current_hp < hp
    assert combat._load_session(mid).verify()["status"] == "PASS"
    return engine


@pytest.mark.parametrize("route", ["native", "typed"])
@pytest.mark.parametrize("seed,expected", [("image-1", 1), ("image-2", 2)])
def test_movement_earned_image_protects_native_and_typed_table(tmp_path, route, seed, expected):
    def configure(bundles):
        foe = next(b for b in bundles if b["actor_id"] == FOE)
        action = {"source_definition_id": "action:test.afterimage-review", "display_name": "Review strike",
            "owner_id": FOE, "economy": "ACTION", "resolution_kind": "ATTACK", "target_kind": "HOSTILE_ENTITY",
            "costs": [["resource:core.stamina", 1]], "reach_ft": 5, "attack_bonus": 100,
            "damage": {"count": 1, "sides": 6, "modifier": 4}, "damage_type": "SLASHING"}
        if route == "typed":
            action.update(resolution_kind="TYPED", parameters={"typed": {"numbers": {"attack_bonus": 100},
                "riders": [], "effects": [{"type": "attack", "attack_kind": "melee", "on_hit": [
                    {"type": "damage", "dice": "1d6+4", "damage_types": ["slashing"]}]}]}})
        foe["actor_template"]["action_ids"].append(action["source_definition_id"])
        foe["action_catalog"].append(action)
    combat, table, mid = table_fixture(tmp_path, {OWNER: _sheet([FEATURE]), FOE: _sheet([])},
        {OWNER: (2, 6), FOE: (8, 7)}, foes=(FOE,), seed=seed, configure=configure)
    oid = earned_image(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(combat, mid)
    stamina = before.state.actors[FOE].resources["resource:core.stamina"]
    assert act(table, mid, "Review strike", target_id=OWNER)["status"] == "COMMITTED"
    after = assert_attack(combat, mid, len(before.events), oid, FOE, expected, before.state.actors[OWNER].current_hp)
    assert not after.state.actors[FOE].action_available
    assert after.state.actors[FOE].resources["resource:core.stamina"] == stamina - 1


@pytest.mark.parametrize("seed,expected", [("image-1", 1), ("image-2", 2)])
def test_movement_earned_marker_receipt_commits_opportunity_and_reloads(tmp_path, seed, expected):
    combat, table, mid = table_fixture(tmp_path, {OWNER: _sheet([FEATURE]), FOE: _sheet([])},
        {OWNER: (2, 6), FOE: (8, 6)}, foes=(FOE,), seed=seed)
    oid = earned_image(combat, table, mid)
    before = reload(combat, mid)
    assert oid in before.state.map_images and oid not in before.state.objects
    walk(table, mid, [(7, 6), (6, 6)])
    after = reload(combat, mid)
    events = after.events[len(before.events):]
    decisions = [e for e in events if e.payload.get("kind") == "afterimage_targeting"]
    assert len(decisions) == 1 and decisions[0].payload["result"] == expected
    assert not after.state.actors[FOE].reaction_available
    assert after.state.actors[FOE].action_available == before.state.actors[FOE].action_available
    assert after.state.actors[OWNER].movement_remaining_ft == 0
    assert after.state.map_images[oid].destroyed == (expected == 1)
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    if expected == 1:
        receipt = next(e for e in events if e.payload.get("kind") == "attack_target_intercepted")
        assert receipt.target_ids == (oid,)
        assert receipt.payload["original_target_id"] == OWNER
        assert not rolls and after.state.actors[OWNER].current_hp == before.state.actors[OWNER].current_hp
    else:
        assert len(rolls) == 1 and rolls[0].target_ids == (OWNER,)
    assert combat._load_session(mid).verify()["status"] == "PASS"


def portable_table(tmp_path, bundle, runtime_package, seed):
    """Seal the actual portable package and compiled defender into one table."""
    # The isolated runtime accepts these declared Flame Lash choices directly.
    # Saved tables obtain their offered choices from the sealed action options.
    # Preset this fixture to the existing NO_MOVEMENT variant so the candidate
    # has an exact, executable option domain (unknown multi-option domains are
    # deliberately rejected). Production option generation is unchanged.
    actions = tuple(action.model_copy(deep=True, update={"parameters": {
        **action.parameters, "options": ["NO_MOVEMENT"]}})
        if action.source_definition_id == "action:fire.flame_lash" else action
        for action in bundle.action_catalog)
    bundle = bundle.model_copy(update={"action_catalog": actions})
    sealed = bundle.model_dump(mode="json", by_alias=True)
    sealed.pop("bundle_sha256")
    bundle = bundle.model_copy(update={"bundle_sha256": canonical_sha256(sealed)})
    project = "afterimage-review-portable"
    package_hash = sha256_file(runtime_package)
    aid = runtime_actor_id(project, package_hash)
    raw = {"schema": "TianxiaPortableCombatRuntimeAuthority.v1", "runtime_actor_id": aid,
        "candidate_entry_id": "test:afterimage-review", "project_id": project, "package_sha256": package_hash,
        "project_revision": 1, "source_actor_id": bundle.actor_template.entity_id,
        "bundle": bundle.model_dump(mode="json", by_alias=True),
        "mechanics_lock_sha256": bundle.mechanics_lock_sha256,
        "primitive_registry_sha256": bundle.primitive_registry_sha256,
        "runtime_adapter_id": bundle.adapter_id, "runtime_adapter_version": bundle.adapter_version,
        "runtime_engine_version": bundle.engine_version,
        "source_package_relative_path": "SourceCharacterPackage.zip", "display_prose_parsed": False,
        "package_build_state_resource_values_used": False, "source_package_mutated": False}
    for key in ("event_head_hash", "replay_state_hash", "content_lock_hash", "combat_sheet_id",
                "combat_sheet_commitment_sha256", "actor_template_commitment_sha256"):
        raw[key] = canonical_sha256({"fixture": key})
    raw["authority_sha256"] = canonical_sha256(raw)
    defender = compile_character(_sheet([FEATURE]), actor_id=OWNER, reaction_plan={"ask": False})
    defender["actor_template"]["armor_class"] = 0
    defender.pop("bundle_sha256")
    defender["bundle_sha256"] = canonical_sha256(defender)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    modes = {aid: "MANUAL", OWNER: "MANUAL"}
    session = combat.persistence.create_match(match_seed=seed, maximum_rounds=5,
        runtime_authority=raw, source_package=runtime_package, typed_bundles=(defender,), battlefield=arena,
        roster_setup={"primary_actor_ids": [aid, OWNER], "team_by_actor": {aid: "b", OWNER: "a"},
            "starting_positions": {aid: {"x": 8, "y": 6}, OWNER: {"x": 2, "y": 6}},
            "participant_control_modes": modes})
    mid = session.match_id
    combat._write_metadata(mid, {"schema": INTEGRATION_SCHEMA, "integration_schema_version": "1.0.0",
        "match_id": mid, "display_name": "Afterimage portable regression",
        "encounter_id": combat._catalog_cache["encounters"][0]["stable_id"], "battlefield_id": arena["stable_id"],
        "participant_control_modes": modes, "paused": False, "local_auto_running": False,
        "ui_preferences": {}, "visual_assets": {}})
    return combat, table, mid, aid


@pytest.mark.parametrize("opportunity,prepare_weapon", [(False, False), (False, True), (True, False)])
@pytest.mark.parametrize("seed,expected", [("image-1", 1), ("image-2", 2)])
def test_portable_owned_image_payment_recipient_continuation_and_reload(
        tmp_path, bundle, runtime_package, seed, expected, opportunity, prepare_weapon):
    combat, table, mid, aid = portable_table(tmp_path, bundle, runtime_package, seed)
    oid = earned_image(combat, table, mid)
    if not opportunity:
        turn(table, mid, aid)
    if prepare_weapon:
        setup = reload(combat, mid)
        setup_qi = setup.state.actors[aid].resources["resource:core.qi"]
        setup_cost = sum(amount for resource, amount in setup.action_catalog["action:fire.burning_weapon"].costs
            if resource == "resource:core.qi")
        assert setup_cost > 0
        assert act(table, mid, "action:fire.burning_weapon")["status"] == "COMMITTED"
    before = reload(combat, mid)
    assert aid in before.runtime_actor_ids
    qi = before.state.actors[aid].resources["resource:core.qi"]
    if prepare_weapon:
        assert qi == setup_qi - setup_cost
        assert not before.state.actors[aid].bonus_action_available
        assert before.state.actors[aid].concentration is not None
    if opportunity:
        walk(table, mid, [(7, 6), (6, 6)])
    else:
        # Real portable action with its printed free Qi cost and declared options.
        def lash(answers):
            state = table.state(mid)
            candidates = [c for c in combat._load_session(mid).engine.legal_candidates()
                if c.source_definition_id == "action:fire.flame_lash" and c.target_ids == (OWNER,)]
            assert len(candidates) == 1, "the saved table must offer Flame Lash against the owner"
            candidate = candidates[0]
            assert candidate.option_ids == ("NO_MOVEMENT",)
            assert candidate.choice_authority_status == "COMPLETE"
            return table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                state["menu"]["state_version"], state["last_sequence"], answers, option_ids=["NO_MOVEMENT"])
        result, _ = resolve(lash)
        assert result["status"] == "COMMITTED"
    after = assert_attack(combat, mid, len(before.events), oid, aid, expected, before.state.actors[OWNER].current_hp)
    if opportunity:
        assert not after.state.actors[aid].reaction_available
        assert after.state.actors[aid].action_available == before.state.actors[aid].action_available
        assert after.state.actors[aid].resources["resource:core.qi"] == qi
        assert after.state.actors[OWNER].movement_remaining_ft == 0
        assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == aid for e in after.events[len(before.events):])
    else:
        action = before.action_catalog["action:fire.flame_lash"]
        cost = sum(amount for resource, amount in action.costs if resource == "resource:core.qi")
        # Printed Flame Lash: "Cost: None". The paid preparation variant above
        # separately proves an intercepted strike never refunds its setup cost.
        assert cost == 0
        assert after.state.actors[aid].resources["resource:core.qi"] == qi - cost
        assert not after.state.actors[aid].action_available
        assert after.state.actors[aid].reaction_available == before.state.actors[aid].reaction_available
        if prepare_weapon:
            assert after.state.actors[aid].resources["resource:core.qi"] == setup_qi - setup_cost
            assert not after.state.actors[aid].bonus_action_available
            assert after.state.actors[aid].concentration is not None
    # A fresh turn and real second attack continue normally after destruction/expiry.
    if opportunity:
        turn(table, mid, aid)
    turn(table, mid, OWNER)
    if opportunity:
        walk(table, mid, [(6, 6), (7, 6)])
    turn(table, mid, aid)
    before_next = reload(combat, mid)
    assert not motion.has_afterimage(before_next.state.actors[OWNER])
    assert before_next.state.map_images[oid].destroyed
    start = len(before_next.events)
    assert act(table, mid, "action:core.unarmed_strike", target_id=OWNER)["status"] == "COMMITTED"
    continued = reload(combat, mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == aid for e in continued.events[start:])
    assert not any(e.payload.get("kind") == "afterimage_targeting" for e in continued.events[start:])


def test_stale_unbound_image_cannot_destroy_bound_replacement(tmp_path, monkeypatch):
    from combat import ext
    def stale_effect(ctx, effect):
        owner = ctx.engine.state.actors[OWNER]
        held = next(c for c in owner.conditions.values() if c.condition_id == motion.AFTERIMAGE)
        obj = ctx.engine.state.map_images[held.data["image_object_id"]]
        if effect["operation"] == "copy":
            ctx.engine._update_object(obj.model_copy(deep=True, update={"object_id": "object:stale-image"}), ctx.source, OWNER)
            return
        state = ctx.engine.state.model_dump(mode="json")
        events = [e.model_dump(mode="json") for e in ctx.engine.events]
        assert not destroy_image(ctx.engine, "object:stale-image", ctx.source, FOE, "test:intent")
        assert ctx.engine.state.model_dump(mode="json") == state
        assert [e.model_dump(mode="json") for e in ctx.engine.events] == events
    monkeypatch.setitem(ext.effects(), "test_afterimage_stale", stale_effect)
    def configure(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        for operation in ("copy", "destroy"):
            source = "action:test.stale-image." + operation
            owner["actor_template"]["action_ids"].append(source)
            owner["action_catalog"].append({"source_definition_id": source, "display_name": operation,
                "owner_id": OWNER, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
                "parameters": {"free_primary": True, "typed": {"numbers": {}, "riders": [],
                    "effects": [{"type": "test_afterimage_stale", "operation": operation}]}}})
    combat, table, mid = table_fixture(tmp_path, {OWNER: _sheet([FEATURE]), FOE: _sheet([])},
        {OWNER: (2, 6), FOE: (8, 7)}, foes=(FOE,), configure=configure)
    oid = earned_image(combat, table, mid)
    assert act(table, mid, "copy")["status"] == "COMMITTED"
    before = reload(combat, mid)
    assert "object:stale-image" in before.state.map_images
    assert act(table, mid, "destroy")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert after.state.map_images == before.state.map_images
    assert not after.state.map_images[oid].destroyed and motion.has_afterimage(after.state.actors[OWNER])
