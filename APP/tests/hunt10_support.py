"""Public synthetic table fixtures shared by the three hunt-10 regressions."""
import copy
from pathlib import Path

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.test_auto_bodya import BODY_REFINING_SHEET

ROOT = Path(__file__).resolve().parents[1]


def fight(tmp_path, *, effects=None, sheet=None, ask=False, setup_target="SELF", opponent_sheet=None):
    bundles = []
    actors = ["actor:factory.left", "actor:factory.right"]
    for actor_id in actors:
        actor_sheet = opponent_sheet if opponent_sheet is not None and actor_id == actors[1] else sheet
        bundle = compile_character(copy.deepcopy(actor_sheet or BODY_REFINING_SHEET), actor_id=actor_id,
                                   reaction_plan={"ask": ask})
        if effects is not None:
            action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
            action.update(source_definition_id=f"action:test.setup.{actor_id}", display_name="Test setup",
                          economy="ACTION", target_kind=setup_target, costs=[], range_ft=60)
            action["parameters"] = {"player_only": True, "typed": {"effects": effects, "numbers": {"cl": 12, "pb": 4},
                                               "duration": {"kind": "instant"}, "riders": []}}
            zone = next((e for e in effects if e.get("type") == "zone"), None)
            if zone:
                action["parameters"]["typed"]["zone_spec"] = {k: v for k, v in zone.items() if k != "type"}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="HUNT10-REGRESSION", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": actors, "team_by_actor": dict(zip(actors, ["team:a", "team:b"])),
                      "starting_positions": {actors[0]: {"x": 3, "y": 6}, actors[1]: {"x": 4, "y": 6}}})
    return service, session


def use(session, name, *, provider=None):
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name or
                     (name == "End Turn" and c.kind.value == "END_TURN"))
    session.submit_intent(ActionIntent(intent_id=f"h10:{session.engine.state.state_version}",
        actor_id=candidate.actor_id, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, target_ids=candidate.target_ids, destination=candidate.destination),
        primary_decision_record=None, reaction_provider=provider)


def reload_equal(service, session):
    before = session.engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, service.userdata_root).persistence.load_match(session.match_id)
    assert loaded.engine.state.model_dump(mode="json") == before
    return loaded
