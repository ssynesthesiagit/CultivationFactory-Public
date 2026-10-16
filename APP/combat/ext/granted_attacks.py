"""Ordinary granted-strike choices for Returning-Heaven and other printed grants.

Reuse native action prerequisites/recipient knowledge and the candidate/attack
permission hooks, but not the Action/attack-slot budget paid by the granting
ability. Queries neither pay nor change the actor. Only owned ordinary Attack
action deliveries qualify: a paid technique/reaction cannot become a free strike.
The returned menu is complete; preferences rank it, never truncate it.
"""
from . import any_false
from .hand_occupancy import weapon_allowed


def ordinary_choices(engine, actor, target, *, kind, intent=None):
    """Return source -> action for legal ordinary deliveries of `kind`.

    Native candidates retain stance/resource/turn prerequisites, disabled
    equipment, target permissions, perception and reach. The sole projection is
    an available Action on a copied actor: the grant owns that expenditure.
    Execution must still use the granted-attack root and recheck live geometry.
    """
    from ..gate2_runtime_models import EconomyKind
    from ..typed_executor import Context
    from ..typed_reactions import attack_reaches
    from ..attack_notifications import can_strike

    if not can_strike(actor) or not target.active or engine.state.terminal_result is not None:
        return {}
    ready = actor.model_copy(update={"action_available": True})
    choices = {}
    for source in sorted(actor.action_ids):
        action = engine.action_catalog.get(source)
        if action is None or action.owner_id != actor.entity_id or action.economy != EconomyKind.ACTION:
            continue
        typed = (action.parameters or {}).get("typed") or {}
        if (not typed.get("attack_action") or action.costs
                or any(typed.get(key) for key in ("delivered_by", "forged_from", "base_form",
                                                 "use_limit", "reaction_attack", "opportunity_of", "granted_attack"))):
            continue
        # Ordinary compiled melee deliveries store their base reach in
        # range_ft; reaction execution reads reach_ft. Normalize a copy only,
        # leaving condition-bound reach additions to the shared reach query.
        action = action.model_copy(update={"reach_ft": action.reach_ft or action.range_ft or 5})
        attack = next((row for row in typed.get("effects") or []
                       if row.get("type") == "attack" and row.get("attack_kind") == kind), None)
        if attack is None or weapon_allowed(engine, actor, action) is False:
            continue
        ctx = Context(engine, actor, action, intent, {**typed, "granted_attack": True, "reaction_attack": True},
                      [target], target, {})
        if (not attack_reaches(engine, actor, target, attack, action=action)
                or any_false("attack_allowed", ctx, target, attack)):
            continue
        candidates = engine._action_candidates(ready, action)
        if any(candidate.target_ids == (target.entity_id,)
               and not any_false("candidate_allowed", engine, actor, candidate, action)
               for candidate in candidates):
            choices[source] = action
    return choices


def choose(engine, actor, target, intent, choices, *, name, choice_id):
    """Ask for any offered delivery; automatic seats use the same complete menu."""
    from .needle import ask, checkpoint_id
    if len(choices) <= 1:
        return next(iter(choices.values()), None)
    preferred = sorted(choices, key=lambda key: (-int(choices[key].parameters.get("expected_damage") or 0), key))
    picked = ask(engine, intent, checkpoint_id(engine, "granted_strike", actor.entity_id, target.entity_id),
                 actor, choice_id, list(choices), preferred=preferred[:1],
                 labels={key: action.display_name for key, action in choices.items()},
                 target_id=target.entity_id, name=name,
                 prompt=f"{name}: choose one unarmed strike against {target.display_name}; no additional cost.")
    return choices.get(picked[0]) if picked else None
