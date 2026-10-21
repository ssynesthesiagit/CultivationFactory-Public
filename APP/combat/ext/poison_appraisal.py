"""Appraise the Venom's conditional creature reach.

Uses existing compile_action/candidate_allowed hooks, without replacing the
diagnosis or inventing toxin facts. The printed touch route is unconditional;
the longer route requires clear perception and reaches at most 30 feet.
Object/sample/terrain appraisal and private findings still need native producers.
"""
import copy

from . import hook
from .ability_source import mechanic_of

APPRAISE = "POISON_BASE_APPRAISE_THE_VENOM"


@hook("compile_action")
def appraisal_reach(action, info):
    """Extend the existing owned action; retain its costs, effects and options."""
    typed = (action.parameters or {}).get("typed") or {}
    if (APPRAISE not in info.get("owned_ids", ()) or mechanic_of(action) != APPRAISE
            or typed.get("modifier")):
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters["typed"]["range_ft"] = 30
    parameters["typed"]["touch_range_ft"] = 5
    parameters["typed"]["requires_perception"] = True
    # An empty diagnostic effect list is classified as beneficial by the
    # generic compiler. The printed examination also permits hostile creatures.
    return action.model_copy(update={"range_ft": 30, "target_kind": "ANY_CREATURE",
                                     "parameters": parameters})


@hook("candidate_allowed")
def appraisal_perception(engine, actor, candidate, action):
    """Default inert for every other action; touch never requires perception."""
    if (action is None or mechanic_of(action) != APPRAISE
            or ((action.parameters or {}).get("typed") or {}).get("modifier")):
        return None
    from ..target_knowledge import located

    for target_id in candidate.target_ids:
        target = engine.state.actors.get(target_id)
        if target is None:
            continue  # Noncreature delivery is not supplied by this provider.
        distance = engine._distance_actor_to_actor(actor, target)
        if distance > 30 or (distance > 5 and not located(engine, actor, target)):
            return False
    return None
