"""Scripted reaction answers for the R14 review regressions (a plain helper: no repository history)."""
from combat.gate2_runtime_models import ReactionDecision


def answers(fight, selections):
    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:spec["minimum_selections"]])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    fight.set_reaction_provider(provider)
