"""Build the W5 test responses from the current sealed choice contract."""

import json

from character_creation.creative_controller.linear_assembly import build_response
from character_creation.creative_controller.linear_menus import (
    MILESTONE_BRANCH_ABILITY_INCREASE,
    MILESTONE_BRANCH_INSIGHT,
    CommittedState,
    build_step_menu,
)
from character_creation.creative_controller.linear_walk import (
    ACTION_AUTOCOMMITTED,
    ACTION_COMPLETE,
    EVENT_STEP_COMMITTED,
    commit_option,
    next_step,
)


def presented_route(projection, sphere_priorities):
    """Use a whole advertised route, not example IDs from the shape template."""
    routes = projection["sphere_route_modules"]
    assert routes, "W5 fixture needs a complete presented route"
    priority = {sphere_id: index for index, sphere_id in enumerate(sphere_priorities)}
    return min(routes, key=lambda route: (
        priority.get(route["sphere_id"], len(priority)),
        route["route_id"],
    ))


def _route_context(request, projection, state, route):
    # Match the production walk's in-memory context: the sealed envelope has
    # milestone IDs but the provider projection has their decision menus.
    envelope = {**request["delegated_choice_envelope"], "linear_provider_payload": projection}
    pair = route["free_talent_pair"]
    state = state.with_pair(pair["sphere_id"], pair["talent_id"]).with_route(route["route_id"])
    # Reserve the entire ordinary sequence. The training menus distinguish
    # reserved IDs from Talents already learned at the current CL.
    for cl, talent_id in route["ordinary_talent_ids_by_cl"].items():
        state = state.with_ordinary(cl, talent_id)
    return envelope, state


def _training_pages(request, envelope, state, menu):
    page = 1
    while menu is not None:
        yield menu
        if not menu.next_page_id:
            break
        page += 1
        menu = build_step_menu(
            request, envelope, state, step_id=menu.step_id,
            step_kind=menu.step_kind, ordinal=menu.ordinal, page=page,
        )


def response_for_route(
    request, projection, state: CommittedState, route, *, sphere_grant_count, take_insights=False,
):
    """Keep the first-cycle pair, ordinary sequence, and constructed training distinct."""
    envelope, state = _route_context(request, projection, state, route)

    events = []
    while True:
        step = next_step(request, envelope, state, events)
        completed = {"event_type": EVENT_STEP_COMMITTED, "step_id": step.step_id}
        if step.step_kind.startswith("treasure_") or (
            step.step_kind in {"insight_priorities", "item_priorities"}
            and state.by_slot.get(step.step_kind)
        ):
            # No optional treasure build or further recommendations after the first.
            events.append(completed)
            continue
        state = step.committed
        if step.action == ACTION_COMPLETE:
            break
        if step.action == ACTION_AUTOCOMMITTED:
            events.append(step.event)
            continue

        menu = step.menu
        options = [option for option in menu.options if not option.is_continuation]
        if step.step_kind == "creation_training":
            # Broaden through actual training slots, not extra CL1 pairs or
            # planning priorities. After that, prefer deepening known Spheres.
            sphere_count = 1 + sum(
                row["choice_type"] == "new_sphere" for row in state.trained_choices
            )
            wanted = 2 if sphere_count < sphere_grant_count else 1
            # Prefer the desired grant type across pages; keep the menu that
            # issued the fallback option so its opaque choice ID stays valid.
            fallback = None
            for page in _training_pages(request, envelope, state, menu):
                eligible = [row for row in page.options if not row.is_continuation]
                options = [row for row in eligible if len(row.choice_ids) == wanted]
                if options:
                    menu = page
                    break
                if fallback is None and eligible:
                    fallback = (page, eligible)
            else:
                if fallback is not None:
                    menu, options = fallback
        assert options, f"No selectable option in the W5 fixture at {step.step_id}"
        option = options[0]
        if step.step_kind == "asi_or_insight":
            # Branches are chosen before the walk commits normal ASI deltas.
            # Count the selected ASI itself so the next dual-kind milestone
            # takes the Insight branch even while that ASI is unresolved.
            branches = state.bounded.get("advancement_milestone_branch_by_milestone_id") or {}
            has_asi = (
                MILESTONE_BRANCH_ABILITY_INCREASE in branches.values()
                or state.bounded.get("ability_score_changes_by_milestone_id")
            )
            branch = (
                MILESTONE_BRANCH_INSIGHT if take_insights and has_asi
                else MILESTONE_BRANCH_ABILITY_INCREASE
            )
            option = next(row for row in options if row.choice_ids == (branch,))
        elif step.step_kind == "forged_design":
            option = next((row for row in options if row.kind == "none"), option)
        state = commit_option(menu, option.option_id, state)
        events.append(completed)

    response = json.loads(build_response(request, state))
    # The file schema asks for the advertised proficiency maps even when
    # the selected character has no choices in one of those maps.
    advertised = request["bounded_choice_contract"]["fields"]
    for field in (
        "path_skill_choices_by_path_id",
        "origin_skill_choices_by_origin_id",
        "background_language_choices_by_background_id",
    ):
        if field in advertised:
            response["bounded_choices"].setdefault(field, {})
    return response


def sphere_grants(response):
    """Exact non-Background Sphere/bonus pairs the response asks to acquire."""
    acquisition = response["acquisition_intent"]
    return {
        **{pair["sphere_id"]: pair["talent_id"] for pair in acquisition["sphere_free_talent_pairs"]},
        **{
            row["record_id"]: row["bonus_talent_id"]
            for row in acquisition.get("trained_choices", ())
            if row["choice_type"] == "new_sphere"
        },
    }
