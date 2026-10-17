"""Punish the Escape Attempt filters targets before asking or paying."""
from types import SimpleNamespace

import pytest

from tests import test_riders_c13 as C
from tests.test_c13_review_fixup import intent
from combat.gate5_service import CombatService


@pytest.mark.parametrize("mixed", [True, False])
def test_failed_escape_filters_pin_only_slam_before_reaction_or_focus_payment(mixed):
    talents = ["TAL_WRESTLING_MERIDIAN_WRENCHING_LOCK", "TAL_WRESTLING_PIN_2"]
    if mixed:
        talents.append("TAL_WRESTLING_HAMMERLOCK")
    engine, me, foe = C._duel(talents)
    requests = C._answers(engine, {})
    C._grab(engine, me, foe, dc=60)
    focus = dict(me.resources)
    events = C._act_as(engine, C.FOE, "Escape grapple")
    assert any(e.event_type == "CHECK_ROLLED" and e.payload["success"] is False for e in events)
    menus = [r for r in requests if r["reaction_source_id"].endswith("wrestling_punish")]
    if mixed:
        assert len(menus) == 1
        assert all("meridian_wrenching" not in oid for oid in menus[0]["legal_option_ids"])
        assert [h.data.get("hold") for h in C._holds(foe)] == ["hammerlock"]
        assert not me.reaction_available
    else:
        assert not menus and me.reaction_available and not C._holds(foe)
    assert me.resources == focus


@pytest.mark.parametrize("manual", [True, False])
def test_failed_escape_on_ai_turn_asks_player_owner_only_for_eligible_slams(tmp_path, manual):
    engine, me, foe = C._duel(["TAL_WRESTLING_HAMMERLOCK", "TAL_WRESTLING_PIN_2", "TAL_WRESTLING_MERIDIAN_WRENCHING_LOCK"])
    C._grab(engine, me, foe, dc=60)
    engine.state.current_actor_id = C.FOE
    engine.state.current_slot_index = engine.state.initiative_order.index(C.FOE)
    engine.typed_ask_reactors = frozenset({C.ME}) if manual else frozenset()
    service = CombatService(C.ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    choice = SimpleNamespace(intent=intent(engine, "Escape grapple", C.FOE))
    before = engine.state.model_dump(mode="json")
    required = service._ask_during_ai_step(session, choice, {})
    if manual:
        assert required is not None and required.context.reactor_id == C.ME
        assert required.context.reaction_source_id.endswith("wrestling_punish")
        assert all("meridian_wrenching" not in oid for oid in required.context.choice_trigger["needle_options"])
    else:
        assert required is None
    assert engine.state.model_dump(mode="json") == before


def test_valid_punish_slam_and_reaction_payment_survive_commit_reload(tmp_path):
    import copy
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate4_persistence import Gate4Persistence
    from tests.test_c13_review_fixup import accept
    me = C._bundle(C.WRESTLING, ["TAL_WRESTLING_HAMMERLOCK", "TAL_WRESTLING_PIN_2", "TAL_WRESTLING_MERIDIAN_WRENCHING_LOCK"])
    seed = copy.deepcopy(next(a for a in me["action_catalog"] if a["display_name"] == "Grapple"))
    seed.update(source_definition_id="test:review.seed_grapple", display_name="Seed Grapple")
    seed["parameters"]["typed"]["effects"] = [{"type": "condition", "condition": "grappled", "applies_to": "target",
        "until_escape": True, "condition_data": {"escape_dc": 60, "reach_ft": 5}}]
    me["action_catalog"].append(seed)
    me["actor_template"]["action_ids"].append(seed["source_definition_id"])
    me["bundle_sha256"] = canonical_sha256({k: v for k, v in me.items() if k != "bundle_sha256"})
    foe = compile_character(C._sheet("tianxia.sphere.athletics"), actor_id=C.FOE)
    persistence = Gate4Persistence(C.ROOT, tmp_path)
    session = persistence.create_match(match_seed="C13-SLAM-PERSIST", typed_bundles=(me, foe),
        roster_setup={"primary_actor_ids": [C.ME, C.FOE], "team_by_actor": {C.ME: "team:a", C.FOE: "team:b"},
                      "starting_positions": {C.ME: {"x": 3, "y": 6}, C.FOE: {"x": 4, "y": 6}}})
    while session.engine.state.current_actor_id != C.ME:
        session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    session.submit_intent(intent(session.engine, "Seed Grapple", C.ME), primary_decision_record=None, reaction_provider=None)
    session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    requests = []
    def provider(request):
        requests.append(request)
        return accept(request, request["legal_option_ids"][:1])
    session.submit_intent(intent(session.engine, "Escape grapple", C.FOE), primary_decision_record=None, reaction_provider=provider)
    loaded = persistence.load_match(session.match_id)
    menus = [r for r in requests if r["reaction_source_id"].endswith("wrestling_punish")]
    assert len(menus) == 1 and all("meridian_wrenching" not in oid for oid in menus[0]["legal_option_ids"])
    assert not loaded.engine.state.actors[C.ME].reaction_available
    assert [h.data.get("hold") for h in C._holds(loaded.engine.state.actors[C.FOE])] == ["hammerlock"]
    assert loaded.verify()["status"] == "PASS"
