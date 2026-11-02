"""Training cannot consume the final mandatory ordinary Talent at a CL."""

from character_creation.creative_controller.linear_menus import (
    CommittedState,
    build_creation_training_menu,
    build_ordinary_talent_menu,
)
from character_creation.creative_controller.linear_walk import commit_option
from tests.test_creation_training_r4 import _menu_fixture


def _fixture():
    request, envelope, routes = _menu_fixture(target_cl=1, required=3)
    envelope["ordinary_talent_count"] = 1
    for record_id, authority in envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"].items():
        authority["allowed_kinds"].append("level_talent_acquisition")
        authority["allowed_channels"].append("level-choice")
        authority["sphere_id"] = routes[record_id]["owning_sphere_id"]
        authority["minimum_cl"] = routes[record_id]["minimum_cl"]
        row = envelope["choices_by_slot"]["advancement_skeleton"][record_id]
        row.update(content_type="talent", prerequisites=routes[record_id]["prerequisites"])
    state = CommittedState.empty().with_pair("sphere.a", "talent.initial")
    for slot in (1, 2):
        state = state.with_trained_choice({"cl": 1, "slot": slot, "choice_type": "known_sphere_talent", "record_id": f"talent.prior{slot}"})
    return request, envelope, state


def test_final_training_preserves_ordinary_and_allows_new_sphere_successor():
    request, envelope, state = _fixture()
    before = state.committed_sha256
    menu = build_creation_training_menu(request, envelope, state, cl=1, slot=3)
    assert menu is not None
    offered = [option for option in menu.options if not option.is_continuation]
    assert ("talent.a",) not in [option.choice_ids for option in offered]
    bundle = next(option for option in offered if option.choice_ids == ("sphere.z", "talent.zbonus"))
    after = commit_option(menu, bundle.option_id, state)
    ordinary = build_ordinary_talent_menu(request, envelope, after, cl=1)
    assert ordinary is not None
    assert ("talent.chain",) in [option.choice_ids for option in ordinary.options]
    assert state.committed_sha256 == before


def test_training_may_consume_last_ordinary_when_it_unlocks_successor():
    request, envelope, state = _fixture()
    route = envelope["creation_training_contract"]["records"]["talent.chain"]
    route.update(owning_sphere_id="sphere.a", prerequisites=[{"operator": "requires", "target_id": "talent.a"}])
    envelope["choices_by_slot"]["advancement_skeleton"]["talent.chain"]["prerequisites"] = route["prerequisites"]
    envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]["talent.chain"]["sphere_id"] = "sphere.a"
    menu = build_creation_training_menu(request, envelope, state, cl=1, slot=3)
    assert menu is not None
    choice = next(option for option in menu.options if option.choice_ids == ("talent.a",))
    after = commit_option(menu, choice.option_id, state)
    ordinary = build_ordinary_talent_menu(request, envelope, after, cl=1)
    assert ordinary is not None
    assert [option.choice_ids for option in ordinary.options] == [("talent.chain",)]


def test_earlier_training_can_build_prerequisites_before_boundary():
    request, envelope, _ = _fixture()
    state = CommittedState.empty().with_pair("sphere.a", "talent.initial")
    menu = build_creation_training_menu(request, envelope, state, cl=1, slot=1)
    assert menu is not None
    assert ("talent.a",) in [option.choice_ids for option in menu.options]
