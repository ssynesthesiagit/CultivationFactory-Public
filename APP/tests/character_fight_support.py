"""Character sheets, fights and intents shared by the C13 rider lane and the tables that read its sheets.

Consumers: tests/test_riders_c13.py (the C13 lane itself; its printed-rider assertions stay there),
tests/test_c13_movement_accounting.py, tests/test_c13_review_fixup.py (accept/intent),
tests/test_c13_slam_fixup.py, tests/test_c13_seal_slam_fixup.py, tests/test_a2_foundations1_shared_pool.py.
The base sheet, the engine and the starting kit come from tests/test_review_sw-athletics.py, so a character built
here is the same character those tests build.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME, AN = t.ME, t.AN
FOE = "actor:factory.c13_foe"
DRUNKEN = "tianxia.sphere.drunken_style"
AXE_ITEMS = t.AXE_KIT["starting_kit"]["items"]


def accept(request, options=()):
    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(options)), None


def intent(engine, name, actor=None, destination=None):
    c = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
             and (actor is None or c.actor_id == actor)
             and (destination is None or c.destination == destination))
    return ActionIntent(intent_id=f"review-{engine.state.event_sequence}", decision_id=c.decision_id,
                        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
                        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids)


def _sheet(spheres, talents=(), items=(), cl=10, dc=16):
    spheres = [spheres] if isinstance(spheres, str) else list(spheres)
    sheet = t._sheet(spheres[0], list(talents), {"starting_kit": {"items": list(items)}} if items else {}, cl=cl, dc=dc)
    mechanics = t._mechanics()
    for sphere in spheres[1:]:
        sheet["spheres_and_talents"]["sphere_record_ids"].append(sphere)
        sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += [
            key for key, row in mechanics.items() if row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return sheet


def _bundle(spheres, talents=(), items=(), cl=10, dc=16, features=()):
    sheet = _sheet(spheres, talents, items, cl, dc)
    if features:
        sheet["path_and_subpath"]["path_feature_record_ids"] = list(features)
    return compile_character(sheet, actor_id=ME)


def _fight(spheres, talents=(), items=(), cl=10, dc=16, foe_hp=400, sure_hit=True, foe_at=(4, 6), features=()):
    engine = t._engine(_bundle(spheres, talents, items, cl, dc, features), foe_hp=foe_hp, sure_hit=sure_hit, foe_at=foe_at)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _names(engine):
    t._ready(engine)
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}


def _use(engine, name, target=AN, destination=None, contains=False, *, ready=True):
    if ready:
        t._ready(engine)
    found = [c for c in engine.legal_candidates() if (name in c.display_name if contains else c.display_name.split(" at ")[0] == name)
             and c.actor_id == ME and (target is None or not c.target_ids or target in c.target_ids)
             and (destination is None or (c.destination is not None and (c.destination.x, c.destination.y) == destination))]
    assert found, f"{name!r} is not legal; legal: {sorted(n for n in _names(engine) if not n.startswith('Move'))}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]
