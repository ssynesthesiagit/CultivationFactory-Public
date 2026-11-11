"""The C10 rider lane's compiled characters and MANUAL-fight helpers, shared by the rider tests.

Code only: no printed rules wording, no owner data and no repository history, so a test that needs this lane's sheets
(tests/test_fight_ownership_no_leak.py, tests/test_plugin_choice_costs.py) keeps its own assertions and imports them
from here, while tests/test_riders_c10.py keeps the lane's printed-wording checks to itself.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests import rider_sheet_support as sheets

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.riders_c10"
ALLY = "actor:factory.riders_c10_ally"
JIAN = "tianxia.mortal.weapon.jian"
BOW = "tianxia.mortal.weapon.gong_jian"


@lru_cache(maxsize=1)
def authority():
    old = os.environ.get("C10_OLD_AUTHORITY")
    if old:
        return json.loads(Path(old).read_text())
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=10, dc=15, sphere=None, items=(JIAN,), pool=30, ac=14, pb=4, score=14, key="WIS", bases=True):
    """This lane's sheet, in the lane's OLD mode against the base authority (C10_OLD_AUTHORITY)."""
    return sheets.sheet(ids, cl=cl, dc=dc, sphere=sphere, items=items, pool=pool, ac=ac, pb=pb, score=score, key=key,
                        bases=bases, authority_doc=authority())


def bundle(ids, *, actor_id=ME, **kwargs):
    return compile_character(sheet(ids, **kwargs), actor_id=actor_id, typed_authority=authority())


def fight(ids, *, foe_at=(8, 6), ally=False, ally_ids=(), ally_sphere=None, foe_ids=(), foe_sphere=None, foe_items=(JIAN,), **kwargs):
    bundles = [bundle(ids, **kwargs), bundle(list(foe_ids), actor_id=AN, sphere=foe_sphere, items=foe_items)]
    teams, places = {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    if ally:
        bundles.append(bundle(list(ally_ids), actor_id=ALLY, sphere=ally_sphere))
        teams[ALLY], places[ALLY] = "team:a", {"x": 3, "y": 9}
    engine = Gate4ControllerEngine(ROOT, match_seed="C10", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams, "starting_positions": places})
    turn(engine, ME)
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 1000
    return engine


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def names(engine):
    return [c.display_name for c in engine.legal_candidates()]


def use(engine, name, *, target=None, actor_id=None, destination=None):
    actor_id = actor_id or engine.state.current_actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = True
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, actor_id)
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or target in c.target_ids)
                  and (destination is None or (c.destination is not None and (c.destination.x, c.destination.y) == destination))]
    assert candidates, (name, target, sorted(set(names(engine)))[:80])
    candidate = candidates[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c10-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[start:]


def answers(engine, selections):
    """Answer extension choices by the choice id's suffix; None declines, a missing key takes the first options."""
    asked = []

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return ReactionDecision(**{key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                                    selection="USE", option_ids=()), None
        asked.append(request["reaction_source_id"])
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:max(1, spec["minimum_selections"])])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    engine.set_reaction_provider(provider)
    return asked


def riders(key):
    return authority()["mechanics"][key]["riders"]
