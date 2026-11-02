"""Perceived object occupancy and paid vessel movement through persisted intents."""

import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext import placed, vessel
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from tests.auto_worker1_support import LEFT, RIGHT
from tests.h1_support import ROOT, sheet

OWNED = ["PUPPETRY_BASE_RAISE_THE_VESSEL", "PUPPETRY_BASE_PUPPET_STRIKE"]


def scene(root, *, unseen_placement=False):
    bundles = []
    for aid in (LEFT, RIGHT):
        doc = sheet(OWNED, cl=15)
        doc["identity"]["display_name"] = "Puppeteer" if aid == LEFT else "Opponent"
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        folder = root / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid)
        if aid == LEFT:
            sid = "action:test.sphb1pr2.blind"
            bundle["actor_template"]["action_ids"].append(sid)
            bundle["action_catalog"].append({"source_definition_id": sid, "owner_id": aid,
                "display_name": "Become blinded", "economy": "NONE", "resolution_kind": "TYPED",
                "target_kind": "SELF", "range_ft": 0, "costs": [], "parameters": {"player_only": True, "free_primary": True, "typed": {
                    "effects": [{"type": "condition", "condition": "blinded", "applies_to": "self", "until_escape": True}],
                    "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})
        if aid == LEFT:
            sid = "action:test.sphb1pr2.blindsight"
            bundle["actor_template"]["action_ids"].append(sid)
            bundle["action_catalog"].append({"source_definition_id": sid, "owner_id": aid,
                "display_name": "Gain Blindsight", "economy": "NONE", "resolution_kind": "TYPED",
                "target_kind": "SELF", "range_ft": 0, "costs": [], "parameters": {"player_only": True, "free_primary": True, "typed": {
                    "effects": [{"type": "gain_sense", "sense": "blindsight", "range_ft": 60}],
                    "numbers": {}, "duration": {"kind": "one_minute"}, "riders": []}}})
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    if unseen_placement:
        for bundle in bundles:
            for action in bundle["action_catalog"]:
                if action.get("parameters", {}).get("vessel_raise") or action.get("parameters", {}).get("vessel_move"):
                    action["parameters"]["typed"]["requires_seen_origin"] = False
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    svc = CombatService(ROOT, root)
    mid = svc._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT: "team:a", RIGHT: "team:b"},
        {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}},
        svc.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [LEFT], [RIGHT],
        control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, match_seed="SPHB1Pr2",
        display_name="Vessel perception and movement", maximum_rounds=10)["match_id"]
    return mid


def load(root, mid):
    return CombatService(ROOT, root)._load_session(mid)


def context(session):
    return build_decision_context(session.engine, PolicyLibrary(ROOT).for_actor(
        session.engine.state.current_actor_id)[0], for_ai=True)


def decline(request):
    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
        reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None


def commit(root, mid, suffix, xy=None):
    session = load(root, mid)
    rows = session.engine.legal_candidates()
    row = next(c for c in rows if (c.kind == "END_TURN" if suffix == "end_turn" else c.source_definition_id.endswith(suffix))
               and (xy is None or c.destination and (c.destination.x, c.destination.y) == xy))
    intent = ActionIntent(intent_id=f"test:{row.candidate_id}", decision_id=row.decision_id,
        candidate_id=row.candidate_id, state_version=row.state_version, actor_id=row.actor_id,
        target_ids=row.target_ids, destination=row.destination)
    session.submit_intent(intent, primary_decision_record=None,
        reaction_provider=decline)
    return load(root, mid)


def turn(root, mid, aid):
    for _ in range(3):
        if load(root, mid).engine.state.current_actor_id == aid:
            return
        commit(root, mid, "end_turn")
    raise AssertionError("turn did not advance")


def preference(root, mid, suffix="vessel.raise"):
    rows = [c for c in context(load(root, mid)).legal_candidates if c.source_definition_id.endswith(suffix)]
    assert len(rows) == 1
    return rows[0].destination


def test_blinded_ai_does_not_follow_opposing_vessel_relocation(tmp_path):
    from combat import senses

    # An explicit sealed unseen-origin permission exercises object occupancy
    # independently of the current default requiring sight of a placement.
    mid = scene(tmp_path, unseen_placement=True)
    turn(tmp_path, mid, LEFT)
    commit(tmp_path, mid, "sphb1pr2.blind")
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "combat.movement", (6, 6))
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    before = preference(tmp_path, mid)
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "vessel.raise", (6, 7))
    commit(tmp_path, mid, "vessel.move", (before.x, before.y))
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    session = load(tmp_path, mid)
    owner = session.engine.state.actors[LEFT]
    assert not senses.perceives_cell(session.engine, owner, before)
    assert preference(tmp_path, mid) == before
    # Real execution still sees occupancy, despite an intentionally ignorant preview.
    assert not any(c.source_definition_id.endswith("vessel.raise") and c.destination == before
                   for c in session.engine.legal_candidates())
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "vessel.move", (6, 7))
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    assert preference(tmp_path, mid) == before
    commit(tmp_path, mid, "vessel.raise", (before.x, before.y))
    assert placed.of(load(tmp_path, mid).engine, "vessel", owner_id=LEFT)[0].center == before
    assert load(tmp_path, mid).verify()["status"] == "PASS"
    assert load(tmp_path, mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("blindsight", [False, True])
def test_perceiving_ai_avoids_opposing_vessel(tmp_path, blindsight):
    from combat import senses
    mid = scene(tmp_path)
    turn(tmp_path, mid, LEFT)
    if blindsight:
        commit(tmp_path, mid, "sphb1pr2.blind")
        commit(tmp_path, mid, "sphb1pr2.blindsight")
    before = preference(tmp_path, mid)
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "vessel.raise", (before.x, before.y))
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    session = load(tmp_path, mid)
    assert senses.perceives_cell(session.engine, session.engine.state.actors[LEFT], before)
    after = preference(tmp_path, mid)
    assert after != before
    commit(tmp_path, mid, "vessel.raise", (after.x, after.y))
    assert placed.of(load(tmp_path, mid).engine, "vessel", owner_id=LEFT)[0].center == after
    assert load(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_ai_pays_once_to_improve_vessel_reach_then_strikes(tmp_path):
    mid = scene(tmp_path)
    turn(tmp_path, mid, LEFT)
    commit(tmp_path, mid, "vessel.raise", (2, 6))
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    session = load(tmp_path, mid)
    engine = session.engine
    owner, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    zone = placed.of(engine, "vessel", owner_id=LEFT)[0]
    assert zone in vessel.threaded_vessels(engine, owner, vessel.kit(engine, owner))
    distance = engine._distance_actor_to_cell(enemy, zone.center)
    assert distance > 5
    menu = context(session)
    assert len([c for c in menu.legal_candidates if c.source_definition_id.endswith("vessel.move")]) == 1
    assert not any(c.source_definition_id == "system:combat.dodge" for c in menu.legal_candidates)
    initial_qi = owner.resources["resource:core.qi"]
    controller = LocalDeterministicController()
    for _ in range(12):
        session = load(tmp_path, mid)
        menu = context(session)
        decision = controller.choose_primary_action(menu)
        selected = next(c for c in menu.legal_candidates if c.candidate_id == decision.intent.candidate_id)
        assert selected.actor_id == LEFT
        assert not selected.source_definition_id.endswith("vessel.raise")
        assert selected.source_definition_id != "system:combat.dodge"
        if selected.source_definition_id.endswith("vessel.move"):
            break
        session.submit_intent(decision.intent, primary_decision_record=decision.record, reaction_provider=decline)
    else:
        raise AssertionError("AI did not select paid vessel movement in 12 decisions")
    engine = session.engine
    owner = engine.state.actors[LEFT]
    qi = owner.resources["resource:core.qi"]
    assert qi == initial_qi
    action_before = owner.action_available
    assert owner.bonus_action_available
    assert engine._distance_actor_to_cell(enemy, selected.destination) < distance
    assert not any(c.source_definition_id == "system:combat.dodge" for c in context(session).legal_candidates)
    assert selected.kind == "BONUS_ACTION"
    sequence = engine.state.event_sequence
    session.submit_intent(decision.intent, primary_decision_record=decision.record, reaction_provider=decline)
    after = load(tmp_path, mid)
    actor = after.engine.state.actors[LEFT]
    assert not actor.bonus_action_available and actor.action_available == action_before
    assert sum(e.event_type == "ZONE_CREATED" and e.payload["zone"]["zone_id"] == zone.zone_id
               for e in after.engine.events if e.sequence > sequence) == 1
    assert actor.resources["resource:core.qi"] == qi
    assert placed.of(after.engine, "vessel", owner_id=LEFT)[0].center == selected.destination
    assert not any(c.source_definition_id.endswith("vessel.move") for c in context(after).legal_candidates)
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, RIGHT)
    commit(tmp_path, mid, "end_turn")
    turn(tmp_path, mid, LEFT)
    after = load(tmp_path, mid)
    assert after.engine.state.actors[LEFT].bonus_action_available
    assert not any(c.source_definition_id.endswith("vessel.move") for c in context(after).legal_candidates)
    assert any(c.source_definition_id == "system:combat.dodge" for c in context(after).legal_candidates)
    menu = context(after)
    strike = next(c for c in menu.legal_candidates if vessel.STRIKE_BASE in c.source_definition_id)
    decision = ManualControllerAdapter(lambda _: (strike.candidate_id, ())).choose_primary_action(menu)
    assert vessel.STRIKE_BASE in strike.source_definition_id and strike.source_definition_id.endswith(".vessel")
    assert strike.metadata["effect_origin"]["id"] == "vessel:" + zone.zone_id
    after.submit_intent(decision.intent, primary_decision_record=decision.record, reaction_provider=decline)
    final = load(tmp_path, mid)
    assert placed.of(final.engine, "vessel", owner_id=LEFT)[0].center == selected.destination
    assert final.engine.state.actors[LEFT].bonus_action_available
    assert final.engine.state.actors[LEFT].resources["resource:core.qi"] == qi
    assert final.verify()["status"] == final.mechanical.replay()["status"] == "PASS"
