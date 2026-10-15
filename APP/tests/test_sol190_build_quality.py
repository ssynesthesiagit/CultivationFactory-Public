"""Purposeful mechanics through the production seeded walk, without a model/GUI."""
import json

import pytest

from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_menus import (
    CommittedState, _effective_ability_scores, build_point_buy_preset_menu,
    build_point_buy_assignment_menu, build_background_ability_menu, _ability_priority,
    build_insight_occurrence_menu,
)
from character_creation.creative_controller.linear_walk import commit_option
from character_creation.creative_controller.linear_assembly import build_response
from character_creation.creative_controller.linear_prompt import build_step_prompt
from character_creation.insight_build_policy import AUTOMATIC_INSIGHT_ADVICE
from tests import test_insights_are_chosen as levels
from tests.test_dcc_linear_s3 import _fixture


PATHS = [("body_refining", "CON"), ("qi_cultivation", "INT"), ("spirit_awakening", "WIS")]


@pytest.mark.parametrize("path,key", PATHS)
@pytest.mark.parametrize("cl", [1, 5, 10, 15, 20])
@pytest.mark.parametrize("seed", ["QB-AAA111", "QB-BBB222"])
def test_start_and_levels_follow_key_ability_and_survive_reload(path, key, cl, seed):
    path_id = "tianxia.path." + path
    request, envelope = _fixture()
    # Production presets are all permutable; the S3 unit fixture also has a
    # deliberately fixed array to exercise a different contract.
    from character_creation.service import _PROVIDER_POINT_BUY_LEGAL_PRESETS
    envelope["bounded_choice_summary"]["ability_scores"]["legal_score_presets"] = [
        {"scores": list(scores), "cost": 27, "permutable_across_abilities": True}
        for scores in _PROVIDER_POINT_BUY_LEGAL_PRESETS]
    state = CommittedState(by_slot={"path_choice": [path_id]})
    menu = build_point_buy_preset_menu(request, envelope, state)
    state = commit_option(menu, seeded_picker.step_receipt(seed, menu)["value"]["option_id"], state)
    menu = build_point_buy_assignment_menu(request, envelope, state)
    state = commit_option(menu, seeded_picker.step_receipt(seed, menu)["value"]["option_id"], state)
    base = dict(state.bounded["ability_scores"])
    assert base[key] == 15
    assert sorted(base.values()) == [8, 8, 8, 15, 15, 15]
    assert sum(int(envelope["bounded_choice_summary"]["ability_scores"]["cost_by_value"][str(v)]) for v in base.values()) == 27
    assert AUTOMATIC_INSIGHT_ADVICE in build_step_prompt(request, envelope, state, menu)
    # Production-shaped legal advancement envelope. Mere +1 rows in this
    # fixture advertise no cultivation benefit, so ASIs are the useful branch.
    request = levels._request(cl)
    envelope = json.loads(json.dumps(levels._envelope(cl)).replace(levels.PATH_ID, path_id))
    state = CommittedState(by_slot={"path_choice": [path_id]}, bounded={"ability_scores": base},
                           trained_choice_skips=tuple(range(1, cl + 1)))
    ids = [f"{path_id}.feature.ability_score_improvement_or_cultivation_insight.cl{n}"
           for n in levels.SELECTION_LEVELS if n <= cl]
    state = levels._walk_until(request, envelope, state,
        lambda s: all(i in s.bounded.get("ability_score_changes_by_milestone_id", {}) for i in ids),
        chooser=lambda m: seeded_picker.step_receipt(seed, m)["value"]["option_id"])
    scores = _effective_ability_scores(state, request, envelope)
    assert scores[key] == min(20, 15 + 2 * len(ids))
    assert all(v <= 20 for v in scores.values())
    assert not state.insight_occurrences
    for i in ids[:2]:
        assert state.bounded["ability_score_changes_by_milestone_id"][i]["deltas"] == {key: 2}
    restored = CommittedState(**{k: v for k, v in state.to_dict().items()
                               if k not in {"schema"}})
    assert _effective_ability_scores(restored, request, envelope) == scores
    # The actual Stage plan assembly retains the chosen milestone deltas.
    state = state.with_identity("Test Cultivator", "Test", "Purposeful cultivation")
    plan = json.loads(build_response(dict(request, delegated_choice_envelope=envelope), state))
    assert len(plan["bounded_choices"].get("ability_score_changes_by_milestone_id", {})) == len(ids)


def test_useful_owned_resource_insight_gets_key_boost_not_alphabetical_boost():
    request, envelope = levels._request(5), levels._envelope(5)
    from pathlib import Path
    catalogue = json.loads((Path(__file__).resolve().parents[1] / "catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json").read_text())
    printed = next(row for row in catalogue["records"] if row["canonical_id"] == "insight.expanded-dantian")
    insight_id = printed["canonical_id"]
    row = levels._insight_row(insight_id, printed["name"], ["CON", "INT", "CHA"],
                             [{"kind": "path", "operator": "requires", "target_id": levels.PATH_ID}])
    row["description"] = printed["full_rules_text"]
    envelope["choices_by_slot"]["insight_priorities"][insight_id] = row
    for milestone in envelope["linear_provider_payload"]["response_contract"]["required_milestone_resolutions"].values():
        option = milestone["resolution_options"]["cultivation_insight_acquisition"]
        option["allowed_insight_ids"].append(insight_id)
        option["parameters_by_insight_id"][insight_id] = {"allowed_abilities": ["CON", "INT", "CHA"], "amount": 1}
    state = levels._walk_until(request, envelope, levels._starting_state(5),
        lambda s: levels._levels_answered(s, 5),
        chooser=lambda m: seeded_picker.step_receipt("QB-AAA111", m)["value"]["option_id"])
    assert state.insight_occurrences[0]["insight_id"] == insight_id
    assert state.insight_occurrences[0]["parameters"]["ability"] == "INT"


def test_frozen_qi_charisma_authority_is_respected():
    request, envelope = levels._request(1), levels._envelope(1)
    envelope["choices_by_slot"]["path_choice"][levels.PATH_ID]["stage2_authority"] = {"key_ability": "CHA"}
    assert _ability_priority(levels._starting_state(1), request, envelope) == ("CHA", "CON", "DEX", "WIS", "STR", "INT")


def _production_start_fixture():
    from tests import test_dcc_linear_s4 as service_tests
    from character_creation.service import _PROVIDER_POINT_BUY_LEGAL_PRESETS
    request, scores = _fixture()
    envelope = service_tests._envelope()
    path = "tianxia.path.spirit_awakening"
    envelope["choices_by_slot"]["path_choice"] = [{"id": path, "name": "Spirit Awakening"}]
    envelope["allowed_choices_by_slot"]["path_choice"] = [path]
    envelope["owner_locks"] = {"by_slot": {"path_choice": [path]}}
    envelope["bounded_choice_summary"] = scores["bounded_choice_summary"]
    envelope["bounded_choice_summary"]["ability_scores"]["legal_score_presets"] = [
        {"scores": list(values), "cost": 27, "permutable_across_abilities": True}
        for values in _PROVIDER_POINT_BUY_LEGAL_PRESETS]
    envelope["response_contract"] = {
        "expected_acquisition_counts": {"sphere_free_talent_pairs": 1},
        "presented_legal_first_cycle_pairs": [{
            "sphere_id": "tianxia.sphere.wrestling", "talent_id": "TAL_WRESTLING_CHOKE_HOLD",
            "sphere_name": "Wrestling", "talent_name": "Choke Hold"}],
    }
    request = dict(service_tests._request(envelope), bounded_choice_contract={
        "fields": {"ability_scores": request["bounded_choice_contract"]["fields"]["ability_scores"]}})
    return request, envelope


@pytest.mark.parametrize("pair_count", [1, 2])
def test_production_walk_selects_free_sphere_before_starting_allocation(pair_count):
    from character_creation.creative_controller.linear_walk import next_step, ACTION_MENU, ACTION_AUTOCOMMITTED
    request, envelope = _production_start_fixture()
    envelope["response_contract"]["expected_acquisition_counts"]["sphere_free_talent_pairs"] = pair_count
    envelope["response_contract"]["presented_legal_first_cycle_pairs"].append({
        "sphere_id": "tianxia.sphere.water", "talent_id": "WATER_BASE_WATER_JET",
        "sphere_name": "Water", "talent_name": "Water Jet"})
    state = CommittedState.empty().with_identity("Test Cultivator", "Test", "A wrestler")
    visited = []
    events = []
    for _ in range(30):
        step = next_step(request, envelope, state, events)
        visited.append(step.step_id)
        if step.step_id == "point_buy_preset":
            assert len(state.pairs) == pair_count, "the production allocation must use all selected free Spheres"
        if step.action == ACTION_AUTOCOMMITTED:
            state = step.committed
        else:
            assert step.action == ACTION_MENU
            wrestling = next((option for option in step.menu.options
                              if option.choice_ids and option.choice_ids[0] == "tianxia.sphere.wrestling"), None)
            option_id = wrestling.option_id if wrestling else seeded_picker.step_receipt("SOL190r1", step.menu)["value"]["option_id"]
            state = commit_option(step.menu, option_id, step.committed)
        events.append({"event_type": "STEP_COMMITTED", "step_id": step.step_id})
        if "ability_scores" in state.bounded:
            break
    pair_step = next(value for value in visited if value.startswith("sphere_free_talent_pair"))
    assert visited.index(pair_step) < visited.index("point_buy_preset")
    assert state.bounded["ability_scores"]["STR"] == 15
    assert state.bounded["ability_scores"]["WIS"] == 15


def test_charisma_qi_allocation_and_capped_asi_use_defenses_before_unused_int():
    request, envelope = _production_start_fixture()
    path = levels.PATH_ID
    envelope["choices_by_slot"]["path_choice"] = [{"id": path, "stage2_authority": {"key_ability": "CHA"}}]
    state = CommittedState(by_slot={"path_choice": [path]})
    preset = build_point_buy_preset_menu(request, envelope, state)
    state = commit_option(preset, preset.options[0].option_id, state)
    menu = build_point_buy_assignment_menu(request, envelope, state)
    state = commit_option(menu, menu.options[0].option_id, state)
    assert state.bounded["ability_scores"] == {"STR": 8, "DEX": 15, "CON": 15, "INT": 8, "WIS": 8, "CHA": 15}
    request, envelope = levels._request(5), levels._envelope(5)
    envelope["choices_by_slot"]["path_choice"][path]["stage2_authority"] = {"key_ability": "CHA"}
    state = levels._starting_state(5).with_ability_scores(dict(state.bounded["ability_scores"], CHA=20))
    from character_creation.creative_controller.linear_menus import build_asi_milestone_menu
    menu = build_asi_milestone_menu(request, envelope, state, milestone_id=levels._milestone_id(4))
    state = commit_option(menu, menu.options[0].option_id, state)
    assert state.bounded["ability_score_changes_by_milestone_id"][levels._milestone_id(4)]["deltas"] == {"CON": 2}


@pytest.mark.parametrize("owner_scores", [None, {"STR": 8, "DEX": 10, "CON": 12, "INT": 13, "WIS": 14, "CHA": 15}])
def test_model_service_recommendation_and_owner_lock_persist_after_reload(fresh_db, monkeypatch, owner_scores):
    from tests import test_dcc_linear_s4 as service_tests
    from app.core import canonical_json
    from character_creation.creative_controller.linear_persistence import LinearWalkPersistence
    request, envelope = _production_start_fixture()
    if owner_scores:
        envelope["owner_locks"]["by_slot"]["point_buy_assignment"] = {"ability_scores": owner_scores}
    request["request_sha256"] = service_tests.CharacterCreationExecutionService.request_payload_sha256(request)
    service_tests._insert_project(fresh_db)
    service_tests._seed_run(fresh_db, request)

    class LastOptionProvider(service_tests._FakeFirstProvider):
        def complete_json(self, **kwargs):
            receipt = super().complete_json(**kwargs)
            options = kwargs["response_schema"].get("properties", {}).get("option_id", {}).get("enum")
            if options:
                receipt["value"] = {"option_id": options[-1]}
                receipt["response_text"] = canonical_json(receipt["value"])
            return receipt

    provider = LastOptionProvider()
    service = service_tests._service_for(fresh_db, provider)
    def finish_at_consumer_boundary(run_id, response_text, transport, **kwargs):
        with fresh_db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW' WHERE run_id=?",
                         (canonical_json(transport), run_id))
        return service.get(run_id)
    monkeypatch.setattr(service, "_apply_response", finish_at_consumer_boundary)
    result = service._run_dcc_linear_walk("cg1.run.s4")
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["transport"]["provider_called"] is True
    fresh = service_tests._service_for(fresh_db, LastOptionProvider())
    restored = fresh.linear_walk.verified_replay(request, envelope, "cg1.run.s4")
    snapshot = LinearWalkPersistence(fresh_db).load_snapshot("cg1.run.s4")
    assert restored["state"].committed_sha256 == snapshot["committed"].committed_sha256
    scores = restored["state"].bounded["ability_scores"]
    events = fresh.controller_routes.projection("cg1.run.s4")["events"]
    picks = [e["payload"] for e in events if e["event_type"] == "STEP_COMMITTED" and e["payload"]["step_id"] == "point_buy_assignment"]
    if owner_scores:
        assert scores == owner_scores
        assert not picks
        assert not any(e["event_type"] == "MENU_PUBLISHED" and
                       e["payload"]["step_id"].startswith("point_buy") for e in events)
    else:
        assert scores["STR"] == scores["WIS"] == 15
        assert picks and picks[0]["build_choice_reason"]
        selected = [e["payload"]["option_id"] for e in events if e["event_type"] == "OPTION_SELECTED"
                    and e["payload"]["step_id"] == "point_buy_assignment"]
        assert picks[0]["provider_proposed_option_id"] != selected[0]
    assert fresh.get("cg1.run.s4")["transport"] == result["transport"]


def test_owner_locked_scores_are_not_reallocated():
    request, envelope = _fixture()
    state = CommittedState(bounded={"ability_scores": dict(zip(("STR", "DEX", "CON", "INT", "WIS", "CHA"), (8, 10, 12, 13, 14, 15)))})
    assert build_point_buy_preset_menu(request, envelope, state) is None
    assert build_point_buy_assignment_menu(request, envelope, state) is None


def test_background_bonus_targets_the_used_path_ability():
    request, envelope = _fixture()
    request["bounded_choice_contract"]["fields"]["background_ability"] = {
        "allowed_abilities": ["CHA", "INT", "WIS"], "amount": 2, "cap": 20}
    state = CommittedState(by_slot={"path_choice": ["tianxia.path.spirit_awakening"],
                                   "background_choice": ["background.scholar"]})
    menu = build_background_ability_menu(request, envelope, state)
    option_id = seeded_picker.step_receipt("QB-AAA111", menu)["value"]["option_id"]
    assert next(option for option in menu.options if option.option_id == option_id).choice_ids[0] == "WIS"


def test_insight_with_all_listed_abilities_at_cap_is_not_offered():
    request, envelope = levels._request(5), levels._envelope(5)
    state = levels._starting_state(5).with_ability_scores({a: 20 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")})
    assert build_insight_occurrence_menu(request, envelope, state, milestone_id=levels._milestone_id(4)) is None


def test_owned_wrestling_dc_supports_strength_without_reading_enemy_save_stats():
    from character_creation.insight_build_policy import sphere_attack_abilities
    assert "STR" in sphere_attack_abilities({"tianxia.sphere.wrestling"})
    state = CommittedState(by_slot={"path_choice": ["tianxia.path.spirit_awakening"]},
                           pairs=[{"sphere_id": "tianxia.sphere.wrestling", "talent_id": "TAL_WRESTLING_CHOKE_HOLD"}])
    assert _ability_priority(state, {}, {})[:2] == ("WIS", "STR")


def test_model_and_seeded_mechanical_recommendations_are_identical():
    from character_creation.insight_build_policy import recommended_build_option, build_choice_reason
    request, envelope = levels._request(5), levels._envelope(5)
    step, state = levels._step_for(request, envelope, levels._starting_state(5),
                                   f"asi_or_insight:{levels._milestone_id(4)}")
    recommendation = recommended_build_option(step.menu)
    assert recommendation.choice_ids == ("ability_score_increase",)
    assert seeded_picker.step_receipt("QB-AAA111", step.menu)["value"]["option_id"] == recommendation.option_id
    assert "useful Insight" in build_choice_reason(step.menu, recommendation)
