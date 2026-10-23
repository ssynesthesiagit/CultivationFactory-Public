"""Regression: a key-ability build ends with its key ability highest (CL10 CON example).

Provider-free and uses only the committed menus, so it runs in public CI.
"""

from character_creation.creative_controller import CommittedState, build_point_buy_assignment_menu, commit_option
from tests import test_dcc_linear_s3 as score_fixtures


def _scores(option):
    return {parts[-2]: int(parts[-1]) for token in option.choice_ids
            if (parts := token.split(":"))}


def test_con_key_build_never_offers_or_commits_a_higher_secondary_score():
    request, envelope = score_fixtures._fixture()
    # Key-first ordering applies to generated builds only; manual menus keep every assignment.
    request = {**request, "generation_route": "generated"}
    # The Xiahou Chong spread: 15 + 14 + 14 + 12 + 8 + 8 = 27 points.
    preset = {"abilities": list(score_fixtures.ABILITIES),
              "scores": [15, 14, 14, 12, 8, 8], "permutable_across_abilities": True}
    state = CommittedState.empty().with_point_buy_preset(preset).with_slot(
        "path_choice", ["tianxia.path.body_refining"])
    seen_leaders = set()
    page = 1
    while True:
        menu = build_point_buy_assignment_menu(request, envelope, state, page=page)
        for option in menu.options:
            if not option.choice_ids:
                continue
            scores = _scores(option)
            assert scores["CON"] == max(scores.values()), scores
            seen_leaders.add(max(scores, key=scores.get))
        if menu.next_page_id is None:
            break
        page += 1
    assert seen_leaders == {"CON"}
    # The first offered legal option (what an un-configured fallback commits) keeps CON highest at CL10.
    first = build_point_buy_assignment_menu(request, envelope, state)
    committed = commit_option(first, first.options[0].option_id, state)
    final = committed.bounded["ability_scores"]
    assert final["CON"] == max(final.values())
    assert sorted(final.values(), reverse=True) == sorted(preset["scores"], reverse=True)
