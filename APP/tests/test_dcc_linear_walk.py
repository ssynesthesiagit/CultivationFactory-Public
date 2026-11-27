"""Provider-free L1 checks for the deterministic linear DCC walk."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from character_creation.creative_controller import (
    ACTION_AUTOCOMMITTED,
    ACTION_MENU,
    CommittedState,
    LinearMenuError,
    StepMenu,
    StepOption,
    build_background_ability_menu,
    build_background_choice_menu,
    build_background_sphere_choice_menu,
    build_background_talent_choice_menu,
    build_foundation_choice_menu,
    build_identity_menu,
    build_item_priorities_menu,
    build_method_choice_menu,
    build_origin_insight_choice_menu,
    build_path_choice_menu,
    build_response_schema,
    build_step_prompt,
    build_subpath_choice_menu,
    commit_option,
    next_step,
)
from app.core import FoundryError
from character_creation.creative_controller.linear_prompt import (
    owner_locked_descriptive_fields,
    owner_locked_identity_name,
    owner_locked_identity_title,
    parse_identity_response,
    validate_identity_owner_lock,
)


def _fixture() -> tuple[dict, dict]:
    slots = {
        "path_choice": [{"id": "path.wood", "name": "Wood"}, {"id": "path.iron", "name": "Iron"}],
        "subpath_choice": [
            {"id": "sub.wood", "owning_path_id": "path.wood", "name": "Wood Thread"},
            {"id": "sub.iron", "owning_path_id": "path.iron", "name": "Iron Thread"},
        ],
        "method_choice": [{"id": "method.breath", "name": "Breath"}],
        "foundation_choice": [{"id": "foundation.quiet", "name": "Quiet Foundation"}],
        "background_choice": [{"id": "background.wanderer", "name": "Wanderer"}],
        "background_sphere_choice": [{"id": "sphere.unfurl", "name": "Unfurl"}],
        "background_talent_choice": [{"id": "talent.listen", "name": "Listen"}],
        "origin_insight_choice": [{"id": "insight.first-light", "name": "First Light"}],
        "item_priorities": [{"id": "item.sash", "name": "Sash"}],
    }
    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": slots,
        "allowed_choices_by_slot": {slot: [row["id"] for row in rows] for slot, rows in slots.items()},
        "selection_limits_by_slot": {
            "path_choice": {"final_min": 1, "final_max": 2, "allow_none": True},
            "item_priorities": {"final_min": 0, "final_max": 1, "allow_none": True},
        },
        "subpath_choice_required": True,
        "compatibility_envelope": {"compatible_method_ids": ["method.breath"]},
        "background_package_linkage": {
            "background.wanderer": {
                "spheres": [{"id": "sphere.unfurl", "name": "Unfurl"}],
                "sphere.unfurl": {"talents": [{"id": "talent.listen", "name": "Listen"}]},
            }
        },
    }
    request["bounded_choice_contract"] = {"fields": {"background_ability": {"allowed_values": ["INT", "WIS"]}}}
    return request, envelope


def _ids(menu) -> set[str]:
    return {choice_id for option in menu.options for choice_id in option.choice_ids}


def test_l1_builders_are_authority_subsets_and_deterministic() -> None:
    request, envelope = _fixture()
    empty = CommittedState.empty()
    path = build_path_choice_menu(request, envelope, empty)
    assert path is not None
    assert _ids(path) <= {"path.wood", "path.iron"}
    selected = commit_option(path, path.options[0].option_id, empty)
    subpath = build_subpath_choice_menu(request, envelope, selected, path_id="path.wood")
    assert subpath is not None and _ids(subpath) == {"sub.wood"}
    state = selected.with_slot("subpath_choice", ["sub.wood"])
    for menu, allowed in (
        (build_method_choice_menu(request, envelope, state), {"method.breath"}),
        (build_foundation_choice_menu(request, envelope, state), {"foundation.quiet"}),
        (build_background_choice_menu(request, envelope, state), {"background.wanderer"}),
    ):
        assert menu is not None
        assert _ids(menu) <= allowed
    state = state.with_slot("background_choice", ["background.wanderer"])
    sphere = build_background_sphere_choice_menu(request, envelope, state)
    assert sphere is not None and _ids(sphere) == {"sphere.unfurl"}
    state = state.with_slot("background_sphere_choice", ["sphere.unfurl"])
    talent = build_background_talent_choice_menu(request, envelope, state)
    assert talent is not None and _ids(talent) == {"talent.listen"}
    for menu, allowed in (
        (build_background_ability_menu(request, envelope, state), {"INT", "WIS"}),
        (build_origin_insight_choice_menu(request, envelope, state), {"insight.first-light"}),
        (build_item_priorities_menu(request, envelope, state), {"item.sash"}),
    ):
        assert menu is not None
        assert _ids(menu) <= allowed
    first = build_path_choice_menu(request, envelope, empty)
    second = build_path_choice_menu(request, envelope, empty)
    assert first is not None and second is not None
    assert first.to_dict() == second.to_dict()


def test_l1_paging_is_stable_and_bounded() -> None:
    request, envelope = _fixture()
    rows = [{"id": f"path.{index:02d}", "name": f"Path {index}"} for index in range(14)]
    envelope["choices_by_slot"]["path_choice"] = rows
    envelope["allowed_choices_by_slot"]["path_choice"] = [row["id"] for row in rows]
    first = build_path_choice_menu(request, envelope, CommittedState.empty())
    again = build_path_choice_menu(request, envelope, CommittedState.empty())
    assert first is not None and again is not None
    assert len(first.options) == 12 and first.next_page_id is not None
    assert first.to_dict() == again.to_dict()
    second = build_path_choice_menu(request, envelope, CommittedState.empty(), page=2)
    assert second is not None and second.next_page_id is None
    assert _ids(first).isdisjoint(_ids(second))


def test_l1_owner_lock_hides_menu_and_is_precommitted() -> None:
    request, envelope = _fixture()
    envelope["owner_locks"] = {"by_slot": {"background_choice": ["background.wanderer"]}}
    assert build_background_choice_menu(request, envelope, CommittedState.empty()) is None
    step = next_step(request, envelope, CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"}))
    assert step.step_id == "path_choice:1"
    assert step.committed.by_slot["background_choice"] == ["background.wanderer"]
    assert "background_choice" not in (step.menu.step_id if step.menu else "")


def test_l1_exact_enum_and_cross_menu_id_rejected_before_commit() -> None:
    request, envelope = _fixture()
    empty = CommittedState.empty()
    menu = build_path_choice_menu(request, envelope, empty)
    other = build_path_choice_menu(request, envelope, empty, ordinal=2)
    assert menu is not None and other is not None
    assert build_response_schema(menu)["properties"]["option_id"]["enum"] == list(menu.option_ids)
    with pytest.raises(LinearMenuError):
        commit_option(menu, other.options[0].option_id, empty)
    assert empty == CommittedState.empty()


def test_l1_identity_uses_bounded_two_string_schema_and_prompt() -> None:
    request, envelope = _fixture()
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu)
    assert schema["required"] == ["name", "title", "concept"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"name", "title", "concept"}
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert len(prompt) <= 6144
    assert '"name"' in prompt and '"title"' in prompt
    assert "ancient Chinese rendered in English/pinyin style" in prompt
    # No stock example name: every model copied it (all builds were "Wei Lianhua").
    assert "invent a fresh name" in prompt and "Wei Lianhua" not in prompt
    assert "theme from committed choices" in prompt
    assert "carry no mechanics" in prompt


def test_l1_identity_owner_lock_is_prompted_const_bound_and_rejected_before_commit() -> None:
    request, envelope = _fixture()
    envelope["delegated_fields"] = {
        "identity.name": {
            "state": "owner_locked",
            "owner_value": "Lin Shuyun",
        },
        "concept": {
            "state": "owner_locked",
            "owner_value": "A sealed sword guardian concept.",
        },
    }
    envelope["delegated_name_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": "Lin Shuyun",
    }
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu, request, envelope)
    assert schema["properties"]["name"] == {
        "type": "string",
        "maxLength": 60,
        "const": "Lin Shuyun",
    }
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert owner_locked_identity_name(request, envelope) == "Lin Shuyun"
    assert "Owner-locked identity name: Lin Shuyun" in prompt
    assert "copy this exact name unchanged" in prompt

    with pytest.raises(FoundryError) as failure:
        validate_identity_owner_lock(
            {"name": "Lianhua Beastforger", "title": "Guard", "concept": "A guard."},
            request,
            envelope,
        )
    assert failure.value.code == "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED"
    assert failure.value.details == {
        "field": "owner_descriptive_fields.identity.name",
        "expected": "Lin Shuyun",
        "actual": "Lianhua Beastforger",
    }
    accepted = validate_identity_owner_lock(
        {"name": "Lin Shuyun", "title": "Guard", "concept": "A sealed sword guardian concept."},
        request,
        envelope,
    )
    assert accepted["name"] == "Lin Shuyun"


@pytest.mark.parametrize(
    ("field", "response"),
    [
        (
            "owner_descriptive_fields.identity.name",
            {"name": "Changed Name", "title": "Furnace-Bound Alchemist", "concept": "Original sealed concept."},
        ),
        (
            "concept",
            {"name": "Lin Shuyun", "title": "Furnace-Bound Alchemist", "concept": "Paraphrased concept."},
        ),
        (
            "owner_descriptive_fields.identity.title",
            {"name": "Lin Shuyun", "title": "Changed Title", "concept": "Original sealed concept."},
        ),
    ],
)
def test_l1_all_owner_locked_descriptive_fields_reject_before_commit(field, response) -> None:
    request, envelope = _fixture()
    envelope["delegated_fields"] = {
        "identity.name": {"state": "owner_locked", "owner_value": "Lin Shuyun"},
        "concept": {"state": "owner_locked", "owner_value": "Original sealed concept."},
        "identity.title": {"state": "owner_locked", "owner_value": "Furnace-Bound Alchemist"},
    }
    envelope["delegated_name_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": "Lin Shuyun",
    }
    envelope["delegated_title_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": "Furnace-Bound Alchemist",
    }
    assert owner_locked_descriptive_fields(request, envelope) == {
        "owner_descriptive_fields.identity.name": "Lin Shuyun",
        "concept": "Original sealed concept.",
        "owner_descriptive_fields.identity.title": "Furnace-Bound Alchemist",
    }
    with pytest.raises(FoundryError) as failure:
        validate_identity_owner_lock(response, request, envelope)
    assert failure.value.code == "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED"
    assert failure.value.details == {
        "field": field,
        "expected": {
            "owner_descriptive_fields.identity.name": "Lin Shuyun",
            "concept": "Original sealed concept.",
            "owner_descriptive_fields.identity.title": "Furnace-Bound Alchemist",
        }[field],
        "actual": {
            "owner_descriptive_fields.identity.name": response.get("name"),
            "concept": response.get("concept"),
            "owner_descriptive_fields.identity.title": response.get("title"),
        }[field],
    }


def test_l1_all_owner_locked_descriptive_fields_are_const_bound_in_prompt_and_schema() -> None:
    request, envelope = _fixture()
    envelope["delegated_fields"] = {
        "identity.name": {"state": "owner_locked", "owner_value": "Lin Shuyun"},
        "concept": {"state": "owner_locked", "owner_value": "Original sealed concept."},
        "identity.title": {"state": "owner_locked", "owner_value": "Furnace-Bound Alchemist"},
    }
    envelope["delegated_name_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": "Lin Shuyun",
    }
    envelope["delegated_title_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": "Furnace-Bound Alchemist",
    }
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu, request, envelope)
    assert schema["properties"]["name"]["const"] == "Lin Shuyun"
    assert schema["properties"]["title"]["const"] == "Furnace-Bound Alchemist"
    assert schema["properties"]["concept"]["const"] == "Original sealed concept."
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert "Owner-locked identity name: Lin Shuyun" in prompt
    assert "Owner-locked identity title: Furnace-Bound Alchemist" in prompt
    assert "Owner-locked character concept: Original sealed concept." in prompt
    assert "do not paraphrase or replace it" in prompt
    accepted = validate_identity_owner_lock(
        {
            "name": "Lin Shuyun",
            "title": "Furnace-Bound Alchemist",
            "concept": "Original sealed concept.",
        },
        request,
        envelope,
    )
    assert accepted == {
        "name": "Lin Shuyun",
        "title": "Furnace-Bound Alchemist",
        "concept": "Original sealed concept.",
    }


def test_l1_locked_descriptive_lengths_make_full_provider_schema_satisfiable() -> None:
    request, envelope = _fixture()
    long_name = "N" * 61
    long_title = "T" * 121
    long_concept = "Sealed owner concept: " + "x" * (483 - len("Sealed owner concept: "))
    assert len(long_concept) == 483
    envelope["delegated_fields"] = {
        "identity.name": {"state": "owner_locked", "owner_value": long_name},
        "concept": {"state": "owner_locked", "owner_value": long_concept},
        "identity.title": {"state": "owner_locked", "owner_value": long_title},
    }
    envelope["delegated_name_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": long_name,
    }
    envelope["delegated_title_contract"] = {
        "state": "owner_locked",
        "owner_locked_value": long_title,
    }
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu, request, envelope)
    assert schema["properties"]["name"]["maxLength"] == len(long_name)
    assert schema["properties"]["title"]["maxLength"] == len(long_title)
    assert schema["properties"]["concept"]["maxLength"] == len(long_concept)
    response = {"name": long_name, "title": long_title, "concept": long_concept}
    Draft202012Validator(schema).validate(response)
    assert parse_identity_response(response, request, envelope) == response
    assert validate_identity_owner_lock(response, request, envelope) == response

    with pytest.raises(LinearMenuError):
        parse_identity_response(response)


def test_l1_unlocked_descriptive_limits_remain_bounded() -> None:
    request, envelope = _fixture()
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu, request, envelope)
    assert schema["properties"]["name"] == {"type": "string", "maxLength": 60}
    assert schema["properties"]["title"] == {"type": "string", "maxLength": 120}
    assert schema["properties"]["concept"] == {"type": "string", "maxLength": 240}
    validator = Draft202012Validator(schema)
    for field, value in (
        ("name", "N" * 61),
        ("title", "T" * 121),
        ("concept", "C" * 241),
    ):
        candidate = {"name": "Name", "title": "Title", "concept": "Concept"}
        candidate[field] = value
        assert validator.is_valid(candidate) is False
    with pytest.raises(LinearMenuError):
        parse_identity_response({"name": "N" * 61, "title": "Title", "concept": "Concept"})
    with pytest.raises(LinearMenuError):
        parse_identity_response({"name": "Name", "title": "T" * 121, "concept": "Concept"})
    with pytest.raises(LinearMenuError):
        parse_identity_response({"name": "Name", "title": "Title", "concept": "C" * 241})


def test_l1_identity_without_name_lock_remains_owner_named() -> None:
    request, envelope = _fixture()
    envelope["delegated_fields"] = {
        "identity.name": {"state": "delegated", "owner_value": None},
        "concept": {"state": "delegated", "owner_value": None},
        "identity.title": {"state": "delegated", "owner_value": None},
    }
    envelope["delegated_title_contract"] = {
        "state": "delegated",
        "owner_locked_value": None,
    }
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    schema = build_response_schema(menu, request, envelope)
    assert schema["properties"]["name"] == {"type": "string", "maxLength": 60}
    assert "const" not in schema["properties"]["title"]
    assert "const" not in schema["properties"]["concept"]
    assert owner_locked_identity_name(request, envelope) is None
    assert owner_locked_identity_title(request, envelope) is None
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert "No owner-locked identity name is sealed" in prompt
    assert "Also write one concise nonblank identity title" in prompt
    assert "Also write concept" in prompt
    accepted = validate_identity_owner_lock(
        {"name": "Wei Lianhua", "title": "Keeper", "concept": "A generated concept."},
        request,
        envelope,
    )
    assert accepted["concept"] == "A generated concept."


def test_l1_frozen_request_concept_and_linked_owner_notes_reach_prompt() -> None:
    request, envelope = _fixture()
    request.pop("concept")
    request["stage1_prompt"] = {
        "envelope": {
            "user_locks": [{
                "field": "concept",
                "value": "A sealed returning-current sword guardian.",
            }],
        },
    }
    request["revision_request"] = {
        "owner_notes": "Choose the required legal Forge design from the offered options when the sealed Forge step appears.",
        "brief": {
            "owner_notes": "Choose the required legal Forge design from the offered options when the sealed Forge step appears.",
        },
    }
    envelope["delegated_fields"] = {
        "concept": {
            "state": "owner_locked",
            "owner_value": "A sealed returning-current sword guardian.",
        },
    }
    menu = build_identity_menu(request, envelope, CommittedState.empty())
    assert menu is not None
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert "A sealed returning-current sword guardian." in prompt
    assert "Choose the required legal Forge design from the offered options" in prompt


def test_l1_prompts_use_typed_names_without_canonical_choice_ids() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty().with_slot("path_choice", ["path.wood"])
    menu = build_path_choice_menu(request, envelope, state, step_id="path_choice:2", selection_index=2)
    assert menu is not None
    prompt = build_step_prompt(request, envelope, state, menu)
    assert "Wood" in prompt
    assert "path.wood" not in prompt
    envelope["owner_locks"] = {"by_slot": {"background_choice": ["background.wanderer"]}}
    locked_prefix = build_step_prompt(request, envelope, state, menu)
    assert "Wanderer" in locked_prefix
    assert "background.wanderer" not in locked_prefix


def test_l1_repeated_menus_subtract_committed_ids_and_keep_one_pick_shape() -> None:
    request, envelope = _fixture()
    empty = CommittedState.empty()
    first = build_path_choice_menu(request, envelope, empty, step_id="path_choice:1")
    assert first is not None
    state = commit_option(first, first.options[0].option_id, empty)
    second = build_path_choice_menu(request, envelope, state, step_id="path_choice:2", selection_index=2)
    assert second is not None
    assert "path.iron" not in _ids(second)
    assert second.min_choices == second.max_choices == 1
    state = commit_option(second, next(option for option in second.options if option.choice_ids).option_id, state)
    assert set(state.by_slot["path_choice"]) == {"path.iron", "path.wood"}
    rows = [{"id": "item.a", "name": "A"}, {"id": "item.b", "name": "B"}]
    envelope["choices_by_slot"]["item_priorities"] = rows
    envelope["allowed_choices_by_slot"]["item_priorities"] = [row["id"] for row in rows]
    envelope["selection_limits_by_slot"]["item_priorities"] = {"final_min": 0, "final_max": 2, "allow_none": True}
    item_first = build_item_priorities_menu(request, envelope, empty, step_id="item_priorities:1")
    assert item_first is not None
    item_state = commit_option(item_first, item_first.options[0].option_id, empty)
    item_second = build_item_priorities_menu(request, envelope, item_state, step_id="item_priorities:2", selection_index=2)
    assert item_second is not None
    assert "item.a" not in _ids(item_second)
    assert item_second.min_choices == item_second.max_choices == 1
    item_state = commit_option(item_second, next(option for option in item_second.options if option.choice_ids).option_id, item_state)
    assert set(item_state.by_slot["item_priorities"]) == {"item.a", "item.b"}

    bundle = StepOption("dcc.opt." + "a" * 24, ("path.bundle-a", "path.bundle-b"), "Bundle", "bundle")
    bundle_menu = StepMenu(
        step_id="path_choice:bundle",
        step_kind="path_choice",
        ordinal=1,
        title="Path",
        min_choices=1,
        max_choices=1,
        options=(bundle,),
        page_id="path_choice:bundle:page:1",
    )
    bundled = commit_option(bundle_menu, bundle.option_id, CommittedState.empty())
    assert bundled.by_slot["path_choice"] == ["path.bundle-a", "path.bundle-b"]


def test_l1_indexed_none_event_advances_repeated_path_step() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"})
    events = []
    first = next_step(request, envelope, state, events)
    assert first.step_id == "path_choice:1" and first.action == ACTION_MENU
    selected = first.menu.options[0]
    state = commit_option(first.menu, selected.option_id, state)
    events.append({"event_type": "STEP_COMMITTED", "step_id": first.step_id, "choice_ids": list(selected.choice_ids)})
    # Owner ruling 2026-09-23: one Path by default; a second Path menu only
    # appears when the owner locks more Paths.
    second = next_step(request, envelope, state, events)
    assert not second.step_id.startswith("path_choice")
