"""Compiler publication, existing controller consumption, and saved-catalog isolation."""
from copy import deepcopy
from pathlib import Path

import pytest

from combat import factory_compiler as compiler
from combat.canonical import canonical_sha256
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, CandidateKind, EconomyKind
from combat.gate3_reducer import canonical_state_sha256
from combat.gate3_storage import TYPED_BUNDLES_FILE
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from combat.rider_value import MAX_RIDER_UTILITY
from tests.test_factory_combat_compiler import ACTOR, SHEET

ROOT = Path(__file__).resolve().parents[1]


def action(*, effects=None, utility=None, **flags):
    parameters = {
        "typed": {"effects": effects if effects is not None else [
            {"type": "condition", "condition": "stunned", "applies_to": "target"}],
            "numbers": {"pb": 4, "cl": 5, "key_mod": 3}, "duration": {"kind": "round", "amount": 1}},
        "expected_damage": 0,
        **flags,
    }
    if utility is not None:
        parameters["rider_utility"] = utility
    return ActionDefinition(source_definition_id="action:test.general_rider", display_name="Typed test effect",
                            owner_id=ACTOR, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                            target_kind="HOSTILE_ENTITY", range_ft=30, costs=(("resource:core.qi", 1),),
                            parameters=parameters)


def test_publisher_changes_only_utility_and_does_not_mutate_input():
    before = action()
    original = before.model_dump(mode="json")
    after = compiler._with_rider_utility(before)
    assert 0 < after.parameters["rider_utility"] <= MAX_RIDER_UTILITY
    assert type(after.parameters["rider_utility"]) is int
    data = after.model_dump(mode="json")
    data["parameters"].pop("rider_utility")
    assert data == original == before.model_dump(mode="json")
    assert after.parameters["expected_damage"] == 0


@pytest.mark.parametrize("flag", ["inert", "player_only", "setting_only", "gm_only", "manual"])
@pytest.mark.parametrize("on_typed", [False, True])
def test_disabled_rows_never_retain_a_stale_hint(flag, on_typed):
    row = action(utility=99)
    (row.parameters["typed"] if on_typed else row.parameters)[flag] = True
    row.parameters["typed"]["replacement"] = {"reliable": True}
    assert "rider_utility" not in compiler._with_rider_utility(row).parameters
    assert row.parameters["rider_utility"] == 99


def test_unknown_and_damage_only_rows_do_not_retain_a_stale_hint():
    for effects in ([{"type": "damage", "flat": 9}], [{"type": "unimplemented_test_effect"}]):
        row = action(effects=effects, utility=99)
        assert "rider_utility" not in compiler._with_rider_utility(row).parameters
    stock = action().model_copy(update={"resolution_kind": "ATTACK"})
    assert compiler._with_rider_utility(stock) is stock


def test_reliable_replacement_keeps_its_existing_floor_without_double_counting():
    row = action(utility=compiler.RELIABLE_RIDER_VALUE)
    row.parameters["typed"]["replacement"] = {"reliable": True}
    assert compiler._with_rider_utility(row).parameters["rider_utility"] == compiler.RELIABLE_RIDER_VALUE
    # A reliable mark that the general estimator cannot value retains the prior contract.
    row.parameters["typed"]["effects"] = [{"type": "mark", "name": "test mark"}]
    assert compiler._with_rider_utility(row).parameters["rider_utility"] == compiler.RELIABLE_RIDER_VALUE


def without_hints(bundle):
    result = deepcopy(bundle)
    result.pop("bundle_sha256")
    for row in result["action_catalog"]:
        row["parameters"].pop("rider_utility", None)
    return result


def test_fresh_compilation_changes_only_hints_and_the_enclosing_bundle_hash(monkeypatch):
    with monkeypatch.context() as before:
        before.setattr(compiler, "_with_rider_utility", lambda row: row)
        old = compiler.compile_character(SHEET, actor_id=ACTOR)
    new = compiler.compile_character(SHEET, actor_id=ACTOR)
    assert without_hints(old) == without_hints(new)
    assert any(row["parameters"].get("rider_utility", 0) > 0 for row in new["action_catalog"])
    assert new["bundle_sha256"] != old["bundle_sha256"]
    assert new["bundle_sha256"] == canonical_sha256({key: value for key, value in new.items() if key != "bundle_sha256"})
    assert new == compiler.compile_character(SHEET, actor_id=ACTOR)


def test_publication_sees_effects_added_by_the_final_action_transform(monkeypatch):
    from combat import ext

    transform = ext.transform
    changed = set()

    def add_typed_control(event, row, context):
        made = transform(event, row, context)
        if event == "compile_action" and made.resolution_kind == "TYPED" and made.target_kind == "HOSTILE_ENTITY":
            parameters = deepcopy(made.parameters)
            if parameters.get("inert") or parameters.get("player_only") or parameters.get("setting_only"):
                return made
            parameters["typed"]["effects"] = [
                {"type": "condition", "condition": "stunned", "applies_to": "target"}]
            parameters.pop("rider_utility", None)
            changed.add(made.source_definition_id)
            return made.model_copy(update={"parameters": parameters})
        return made

    monkeypatch.setattr(ext, "transform", add_typed_control)
    bundle = compiler.compile_character(SHEET, actor_id=ACTOR)
    rows = {row["source_definition_id"]: row for row in bundle["action_catalog"]}
    assert changed
    assert all(rows[key]["parameters"].get("rider_utility", 0) > 0 for key in changed)


def test_existing_candidate_and_controller_use_the_hint_without_a_false_finish():
    engine = Gate4ControllerEngine(ROOT, match_seed="P16-RIDER-CONSUMPTION")
    actor = engine.state.actors[engine.state.current_actor_id]
    foe = next(row for row in engine.state.actors.values() if row.active and row.team_id != actor.team_id)
    foe.current_hp = 1
    foe.temporary_hp = 0
    published = compiler._with_rider_utility(action().model_copy(update={"owner_id": actor.entity_id}))
    engine.action_catalog[published.source_definition_id] = published
    candidate = engine._candidate(CandidateKind.ACTION, actor, published.source_definition_id,
                                  published.display_name, target_ids=(foe.entity_id,))
    assert candidate.metadata["expected_damage"] == 0
    assert candidate.metadata["rider_utility"] == published.parameters["rider_utility"]
    policy, _ = PolicyLibrary(ROOT).for_actor(actor.entity_id)
    context = build_decision_context(engine, policy)
    controller = LocalDeterministicController()
    score = controller._score_candidate(context, candidate, ())
    components = {row.component: row.value for row in score.components}
    assert components["rider_utility"] > 0
    assert components["defeat_prevention_or_finish"] == 0
    unseen = candidate.model_copy(update={"metadata": {**candidate.metadata, "target_knowledge": "LAST_OBSERVED"}})
    assert "rider_utility" not in {row.component for row in controller._score_candidate(context, unseen, ()).components}


@pytest.mark.parametrize("include_hints", [False, True], ids=["prior-catalog", "new-catalog"])
def test_saved_catalog_is_loaded_and_continued_without_recompilation(tmp_path, monkeypatch, include_hints):
    with monkeypatch.context() as before:
        if not include_hints:
            before.setattr(compiler, "_with_rider_utility", lambda row: row)
        old = compiler.compile_character(SHEET, actor_id=ACTOR)
    assert any(row["parameters"].get("rider_utility", 0) > 0
               for row in compiler.compile_character(SHEET, actor_id=ACTOR)["action_catalog"])
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="P16-OLD-CATALOG", maximum_rounds=3, typed_bundles=(old,),
                                       roster_setup={"primary_actor_ids": [ACTOR, AN],
                                                     "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    saved_path = session.store.match_dir / TYPED_BUNDLES_FILE
    saved = saved_path.read_bytes()
    source_state = canonical_state_sha256(session.engine.state)

    def forbidden(*args, **kwargs):
        raise AssertionError("A saved catalog must not be recompiled or revalued")

    monkeypatch.setattr(compiler, "compile_character", forbidden)
    monkeypatch.setattr(compiler, "_with_rider_utility", forbidden)
    from combat import rider_value
    monkeypatch.setattr(rider_value, "estimate_rider_utility", forbidden)
    loaded = Gate4Persistence(ROOT, tmp_path).load_match(session.match_id)
    assert canonical_state_sha256(loaded.engine.state) == source_state
    assert saved_path.read_bytes() == saved
    for row in old["action_catalog"]:
        assert loaded.engine.action_catalog[row["source_definition_id"]].model_dump(mode="json") == row
    candidate = next(row for row in loaded.engine.legal_candidates() if row.kind == CandidateKind.END_TURN)
    intent = ActionIntent(intent_id="test:p16-continue", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=loaded.engine.state.state_version,
                          actor_id=candidate.actor_id)
    loaded.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
    reopened = Gate4Persistence(ROOT, tmp_path).load_match(session.match_id)
    assert canonical_state_sha256(reopened.engine.state) == canonical_state_sha256(loaded.engine.state)
    assert reopened.verify()["status"] == "PASS"
    assert saved_path.read_bytes() == saved
