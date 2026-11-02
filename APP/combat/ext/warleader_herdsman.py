"""Warleader riders (rider lane C11, 2026-09-30): the Deadly Herdsman Standard and Focusing Tactics.

Source (owner text, authority/typed_mechanics/rules_text.json tianxia.talent.warleader.*):
  Deadly Herdsman (Standard, Command): "When this Standard is active, once per turn when a Commanded ally damages a hostile creature
    with an attack, the ally may Shove the target as a Bonus Action. If the forced movement moves the target out of another Commanded
    ally's reach, that other ally may make one Opportunity Attack against the target."
  Focusing Tactics (Focus): "A Commanded ally affected by your active Standard or one of your beneficial Shouts may use its Action to
    restore your Martial Focus if absent. A creature can restore your Martial Focus with this talent once per short rest."

How it runs (the Warleader system is combat/ext/warleader.py; this module uses its public helpers only).
  Deadly Herdsman is typed as the other Standard talents are: a Bonus Action "Set the Standard: Deadly Herdsman"
  (reviewed_final.d/riders_c11.json). While it is a leader's Standard (primary or secondary), after a Commanded ally's typed attack
  damages a hostile creature within 5 feet of it (``damage_dealt``), once per turn per leader, the ally -- with its Bonus Action free --
  is asked (a player; the AI pushes) to Shove it: push 5 feet or knock Prone, the ally's own Shove (its save and DC). A push that takes
  the target out of another Commanded ally's reach offers that ally its Opportunity Attack (its own reaction plan: Ask me asks). The
  shove is a benefit of the Standard (the leader's Momentum Mark, warleader.benefit).
  Focusing Tactics: a shared Action "Restore Martial Focus" (installed at ``match_start``, offered through ``additional_actions``) for a
  creature that is Commanded under the active Standard of a leader who knows Focusing Tactics (feature block ``warleader_known``), or
  that carries an effect of one of that leader's Shouts, while the leader's Martial Focus is absent; once per fight per creature and
  leader ("once per short rest": there is no rest inside a fight).
Default-inert: nothing for leaders without the Standard or the talent.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import warleader

FOCUS = warleader.FOCUS
RESTORE = "action:shared.warleader.focusing_tactics"
USED = "typed_round_focusing_tactics"  # "_round_" keeps it through turn resets and in a saved fight
HERD_USED = "typed_round_deadly_herdsman"


# ------------------------------------------------------------------------------------------------------ Deadly Herdsman
def _shove_action(engine: Any, actor: Any, kind: str) -> Any | None:
    suffix = {"push": ".unarmed.shove_push", "prone": ".unarmed.shove_prone"}[kind]
    return next((engine.action_catalog[a] for a in actor.action_ids if a.endswith(suffix) and a in engine.action_catalog), None)


def _reaches(engine: Any, other: Any, target: Any) -> bool:
    from .. import typed_reactions

    reach = typed_reactions.opportunity_reach(engine, other)
    return reach is not None and engine._distance_actor_to_actor(other, target) <= reach


@hook("damage_dealt")
def herd(ctx: Any, target: Any, amount: int) -> None:
    engine, ally = ctx.engine, ctx.actor
    if amount <= 0 or ctx.attack_effect is None or target is None or not target.active or target.team_id == ally.team_id:
        return
    leaders = warleader.commanders(engine, ally, "deadly_herdsman")
    token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    leaders = [(leader, data) for leader, data in leaders if leader.turn_flags.get(HERD_USED) != token]
    if not leaders or not ally.bonus_action_available or engine._distance_actor_to_actor(ally, target) > 5:
        return
    options = [kind for kind in ("push", "prone") if _shove_action(engine, ally, kind) is not None]
    if not options:
        return
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "deadly_herdsman", ally.entity_id, target.entity_id), ally,
                 CHOICE + "deadly_herdsman", options, allow_decline=True, preferred=["push"], target_id=target.entity_id,
                 name="Deadly Herdsman",
                 prompt_context=action_context(engine, ally, ctx.source, target),
                 labels={"push": f"Shove {target.display_name} 5 feet away", "prone": f"Shove {target.display_name} Prone"},
                 prompt=f"Deadly Herdsman ({leaders[0][0].display_name}'s Standard): {ctx.action.display_name} damaged {target.display_name}. Shove it as a "
                        "Bonus Action (it makes a Strength or Dexterity save against your Shove)?")
    if not picked:
        return
    leader, _data = leaders[0]
    leader.turn_flags[HERD_USED] = token
    ally.bonus_action_available = False
    watchers = [other for other in engine.state.actors.values()
                if other.active and other.entity_id not in (ally.entity_id, target.entity_id) and other.team_id == ally.team_id
                and warleader.commanded(engine, leader, _data, other) and _reaches(engine, other, target)]
    from ..typed_executor import Context, run_effects

    action = _shove_action(engine, ally, picked[0])
    typed = dict(action.parameters.get("typed") or {})
    note(engine, action.source_definition_id, ally, f"Deadly Herdsman: {ally.display_name} shoves {target.display_name} as a Bonus Action.", (target,))
    run_effects(Context(engine, ally, action, ctx.intent, typed, [target], target), typed.get("effects") or [])
    warleader.benefit(engine, ally, "deadly_herdsman", "Deadly Herdsman shove")
    if picked[0] != "push" or not target.active:
        return
    from .. import typed_reactions

    for other in sorted(watchers, key=lambda row: row.entity_id):
        if not target.active or _reaches(engine, other, target) or not typed_reactions.wants_opportunity_attack(engine, other, target):
            continue
        opportunity = typed_reactions._opportunity_row(engine, other)
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, other, opportunity["action_id"], independent=True):
            engine._append_event("REACTION_WINDOW_OPENED", "tianxia.talent.warleader.deadly_herdsman", actor_id=target.entity_id,
                                 target_ids=(other.entity_id,), payload={"checkpoint": "LEAVE_REACH"})
            other.reaction_available = False
            note(engine, "tianxia.talent.warleader.deadly_herdsman", other,
                 f"Deadly Herdsman: the shove drives {target.display_name} out of {other.display_name}'s reach -- an Opportunity Attack.", (target,))
            typed_reactions.opportunity_attack(engine, other, target, ctx.intent, reach_ft=engine._distance_actor_to_actor(other, target))
            engine._append_event("REACTION_RESOLVED", "tianxia.talent.warleader.deadly_herdsman", actor_id=other.entity_id,
                                 target_ids=(target.entity_id,))
            break  # "that other ally may make one Opportunity Attack"


# ------------------------------------------------------------------------------------------------------ Focusing Tactics
def _shouted(engine: Any, leader: Any, creature: Any) -> bool:
    """It carries an effect of one of the leader's Shouts (an action whose typed effects hold a warleader_shout row)."""
    for item in [*creature.conditions.values(), *creature.modifiers.values()]:
        if getattr(item, "source_actor_id", None) != leader.entity_id:
            continue
        action = engine.action_catalog.get(str(getattr(item, "source_definition_id", "") or ""))
        rows = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []) if action is not None else []
        if any(isinstance(row, dict) and row.get("type") == "warleader_shout" for row in rows):
            return True
    return False


def leaders_to_focus(engine: Any, creature: Any) -> list[Any]:
    """The leaders whose Martial Focus this creature may restore now."""
    out = []
    for leader in engine.state.actors.values():
        if leader.entity_id == creature.entity_id or not leader.active or leader.team_id != creature.team_id:
            continue
        if not warleader.knows(engine, leader, "focusing_tactics") or FOCUS not in leader.resource_maximums or leader.resources.get(FOCUS, 0) >= 1:
            continue
        if f"{leader.entity_id}" in str(creature.turn_flags.get(USED) or "").split(","):
            continue
        data = warleader.standard_of(leader)
        if (data and warleader.commanded(engine, leader, data, creature)) or _shouted(engine, leader, creature):
            out.append(leader)
    return sorted(out, key=lambda row: row.entity_id)


@hook("match_start")
def install(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[RESTORE] = ActionDefinition(
        source_definition_id=RESTORE, display_name="Restore Martial Focus (Focusing Tactics)", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "focusing_tactics_restore"}], "numbers": {}, "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "focusing_tactics": True})


@hook("additional_actions")
def offer(engine: Any, actor: Any) -> list[str]:
    return [RESTORE] if RESTORE in engine.action_catalog and leaders_to_focus(engine, actor) else []


@hook("candidate_allowed")
def only_when_absent(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("focusing_tactics"):
        return None
    return bool(leaders_to_focus(engine, actor))


@effect("focusing_tactics_restore")
def restore(ctx: Any, row: dict[str, Any]) -> None:
    leaders = leaders_to_focus(ctx.engine, ctx.actor)
    if not leaders:
        ctx.rider("No leader of yours has lost Martial Focus.")
        return
    leader = leaders[0]
    if len(leaders) > 1:
        from .needle import CHOICE, ask, checkpoint_id

        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "focusing_tactics", ctx.actor.entity_id), ctx.actor,
                     CHOICE + "focusing_tactics", [row.entity_id for row in leaders], labels={row.entity_id: row.display_name for row in leaders},
                     name="Focusing Tactics", prompt="Focusing Tactics: whose Martial Focus do you restore?")
        leader = next((row for row in leaders if picked and row.entity_id == picked[0]), leader)
    ctx.engine._gain_resource(leader, FOCUS, 1, RESTORE)
    ctx.actor.turn_flags[USED] = ",".join(part for part in [*str(ctx.actor.turn_flags.get(USED) or "").split(","), leader.entity_id] if part)
    note(ctx.engine, RESTORE, ctx.actor, f"Focusing Tactics: {ctx.actor.display_name} spends an Action to restore {leader.display_name}'s "
         "Martial Focus (once this fight).", (leader,))
