"""Concept-informed score proposals survive the real controller service walk.

The provider is a deterministic stand-in, so these checks measure preservation
of legal choices rather than the quality of any particular model's reasoning.
"""

import itertools
import json
from copy import deepcopy

from app.core import canonical_json
from character_builder.service import CharacterBuilderService
from character_creation.creative_controller import (
    CommittedState, LinearWalkPersistence, build_background_ability_menu, build_point_buy_assignment_menu,
)
from character_creation.insight_build_policy import recommended_build_option
from tests import test_dcc_linear_s3 as score_fixtures
from tests import test_dcc_linear_s4 as service_fixtures


def _scores(option):
    return {parts[-2]: int(parts[-1]) for token in option.choice_ids
            if (parts := token.split(":"))}


def test_assignment_menu_reaches_every_key_first_permutation_and_shows_varied_secondaries():
    # Rule: the key ability (CON with no Path) must hold the highest score. The menu
    # therefore offers only key-first permutations, not a different leader each time.
    request, envelope = score_fixtures._fixture()
    request["generation_route"] = "ai_bootstrap"
    preset = {"abilities": list(score_fixtures.ABILITIES),
              "scores": [15, 14, 13, 12, 10, 8], "permutable_across_abilities": True}
    state = CommittedState.empty().with_point_buy_preset(preset)
    first = build_point_buy_assignment_menu(request, envelope, state)
    assert {max(_scores(option), key=_scores(option).get) for option in first.options
            if option.choice_ids} == {"CON"}
    seen = set()
    page = 1
    while True:
        menu = build_point_buy_assignment_menu(request, envelope, state, page=page)
        assert len(menu.options) <= 12
        for option in menu.options:
            if option.choice_ids:
                scores = _scores(option)
                CharacterBuilderService.validate_point_buy(scores)
                values = tuple(scores[ability] for ability in score_fixtures.ABILITIES)
                assert values not in seen
                seen.add(values)
        if menu.next_page_id is None:
            break
        page += 1
    assert page > 3
    assert seen == {values for values in itertools.permutations(preset["scores"]) if values[2] == max(values)}


def test_manual_score_menus_keep_every_printed_background_and_assignment_choice():
    request, envelope = score_fixtures._fixture()
    preset = {"abilities": list(score_fixtures.ABILITIES),
              "scores": [15, 14, 13, 12, 10, 8], "permutable_across_abilities": True}
    state = CommittedState.empty().with_point_buy_preset(preset)
    menu = build_point_buy_assignment_menu(request, envelope, state)
    assert {max(_scores(option), key=_scores(option).get) for option in menu.options
            if option.choice_ids} == set(score_fixtures.ABILITIES)

    background_request = {"request_sha256": "a" * 64, "bounded_choice_contract": {"fields": {
        "background_ability": {"allowed_values": ["STR", "DEX", "CON"], "amount": 2},
    }}}
    background_state = CommittedState.empty().with_slot("background_choice", ["background.wanderer"])
    background_menu = build_background_ability_menu(background_request, {}, background_state)
    assert {option.choice_ids[0] for option in background_menu.options} == {"STR", "DEX", "CON"}


def test_model_score_choice_is_advice_while_seeded_fallback_still_has_a_recommendation():
    request, envelope = score_fixtures._fixture()
    request["generation_route"] = "ai_bootstrap"
    state = CommittedState.empty().with_point_buy_preset({
        "abilities": list(score_fixtures.ABILITIES), "scores": [15, 14, 13, 12, 10, 8],
        "permutable_across_abilities": True,
    })
    menu = build_point_buy_assignment_menu(request, envelope, state)
    assert recommended_build_option(menu) == menu.options[0]
    assert recommended_build_option(menu, model_choice=True) is None


def test_background_bonus_options_name_the_affected_score_and_preserve_model_choice():
    request = {"generation_route": "ai_bootstrap", "request_sha256": "a" * 64, "bounded_choice_contract": {"fields": {
        "background_ability": {"allowed_values": ["STR", "DEX", "CON"], "amount": 2},
    }}}
    state = CommittedState.empty().with_slot("background_choice", ["background.wanderer"])
    menu = build_background_ability_menu(request, {}, state)
    # Rule: the Background bonus goes to the key ability (CON with no Path); only that option is offered.
    assert [option.choice_ids[0] for option in menu.options] == ["CON"]
    names = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution"}
    for option in menu.options:
        ability = option.choice_ids[0]
        assert f"{names[ability]} ({ability})" in option.cue
        assert "by 2" in option.cue
    assert recommended_build_option(menu, model_choice=True) is None


def test_two_concepts_keep_different_legal_scores_through_service_commit_and_reload(fresh_db, monkeypatch):
    service_fixtures._insert_project(fresh_db)
    from character_creation.service import next_linear_step as actual_step

    current_menu = [None]

    def observe_step(*args, **kwargs):
        step = actual_step(*args, **kwargs)
        current_menu[0] = step.menu
        return step

    monkeypatch.setattr("character_creation.service.next_linear_step", observe_step)
    cases = [
        ("A sneaky archer who scouts ahead and relies on accurate ranged attacks.",
         {"STR": 12, "DEX": 14, "CON": 15, "INT": 10, "WIS": 13, "CHA": 8}),
        ("A brawler who grapples foes and withstands punishment in close combat.",
         {"STR": 15, "DEX": 8, "CON": 15, "INT": 15, "WIS": 8, "CHA": 8}),
    ]
    results = []
    for index, (concept, desired) in enumerate(cases):
        current_menu[0] = None
        envelope = service_fixtures._envelope()
        score_request, score_envelope = score_fixtures._fixture()
        envelope["bounded_choice_summary"] = deepcopy(score_envelope["bounded_choice_summary"])
        envelope["bounded_choice_summary"]["ability_scores"]["legal_score_presets"].append({
            "scores": [15, 15, 15, 8, 8, 8], "cost": 27, "permutable_across_abilities": True,
        })
        request = service_fixtures._request(envelope)
        request["concept"] = concept
        request["bounded_choice_contract"] = {
            "fields": {"ability_scores": score_request["bounded_choice_contract"]["fields"]["ability_scores"]},
        }
        from character_creation.service import CharacterCreationExecutionService
        request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
        run_id = f"cg1.run.abilityvar.{index}"
        service_fixtures._seed_run(fresh_db, request, run_id)
        provider = service_fixtures._FakeFirstProvider()
        real_complete = provider.complete_json
        proposed = {}

        def choose(**kwargs):
            receipt = real_complete(**kwargs)
            menu = current_menu[0]
            if menu.step_kind == "identity":
                receipt["value"]["concept"] = concept
            elif menu.step_kind in {"point_buy_preset", "point_buy_assignment"}:
                assert concept in kwargs["prompt_text"]
                assert "first option is a fallback" in kwargs["prompt_text"]
                if menu.step_kind == "point_buy_preset":
                    option = next(option for option in menu.options if option.choice_ids
                                  and sorted(_scores(option).values()) == sorted(desired.values()))
                else:
                    option = next((option for option in menu.options if option.choice_ids
                                   and _scores(option) == desired), None)
                    if option is None:
                        option = next(option for option in menu.options if option.is_continuation)
                proposed[menu.step_kind] = option.option_id
                receipt["value"] = {"option_id": option.option_id}
            receipt["response_text"] = canonical_json(receipt["value"])
            return receipt

        monkeypatch.setattr(provider, "complete_json", choose)
        service = service_fixtures._service_for(fresh_db, provider)
        assembled = []

        def accept(run_id, response_text, transport, **kwargs):
            assembled.append(json.loads(response_text))
            with fresh_db.transaction() as conn:
                conn.execute("UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW' WHERE run_id=?",
                             (canonical_json(transport), run_id))
            return service.get(run_id)

        monkeypatch.setattr(service, "_apply_response", accept)
        result = service._run_dcc_linear_walk(run_id)
        assert result["status"] == "READY_FOR_REVIEW", result.get("blockers")
        assert assembled[0]["bounded_choices"]["ability_scores"] == desired
        reloaded = LinearWalkPersistence(fresh_db).load_snapshot(run_id)["committed"]
        assert reloaded.bounded["ability_scores"] == desired
        assert reloaded.bounded["identity"]["concept"] == concept
        assert CharacterBuilderService.validate_point_buy(desired)["points_spent"] == 27
        events = service.controller_routes.projection(run_id)["events"]
        commits = [event["payload"] for event in events if event["event_type"] == "STEP_COMMITTED"
                   and event["payload"]["step_id"] in proposed]
        assert len(commits) == 2
        assert all("provider_proposed_option_id" not in commit for commit in commits)
        results.append(reloaded.bounded["ability_scores"])
    assert results[0] != results[1]
