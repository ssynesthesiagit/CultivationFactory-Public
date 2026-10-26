"""Sabers lines that were GM riders (rider lane C5, owner 2026-09-30: "i want everything we can automated"). The sphere's own engine
(Edge Momentum, Guard Pressured, Saber-Line Pressure, Hard Draw Cut, Saber Scare) is combat/ext/wenxue_sabers.py.

Effect types (shared: any ability's typed rows may use them; each is inert unless a row names it):
  if_target_state   {"marks": [...], "conditions": [...], "bloodied": bool, "effects": [...]}: the nested rows run only against a target
                    that bears one of the user's named marks ("Guard Pressured"), one of the typed conditions, or is Bloodied.
  if_adjacent       {"effects": [...]}: only when the user ends within 5 feet of the target (Counter-Slope Dao: "If you end adjacent
                    to it, it becomes Guard Pressured").
  cone_passage      on a failed save of an area technique: "Until the start of your next turn, allies who move through the
                    cone's area do not provoke Opportunity Attacks from creatures that failed the save" (Army-Line Chopping Field):
                    a condition on the creature naming the user's side and the area's squares, read by opportunity_allowed.
  choose_hit_target {"effects": [...]}: "After resolving all attacks, choose one creature you hit" -- the rows run on one creature this
                    activation hit (asked of a player; the AI takes the first), including zero-damage hits.
Hooks:
  opportunity_allowed   cone_passage (only Factory fighters' Opportunity Attacks reach this seam).
  compile_block / after_hit  Short Saber Infighting (block "sabers_rider", kind "short_saber_infighting"): after a hit with a duan dao,
                        butterfly saber or other short saber on a creature within 5 feet, the owner may shove it as part of the same
                        Action (Strength or Dexterity save; pushed 5 feet or knocked Prone, the owner's pick); a shoved creature is
                        Guard Pressured until the start of the owner's next turn.
  event                 Execution Platform Presence: "When you reduce a creature to 0 HP during the duration, you may end one
                        Frightened effect on yourself or one willing ally within 30 feet" (its stance data carries
                        "kill_ends_frightened_ft").
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

PASSAGE = "condition:typed.cone_passage"
SHORT_SABER_WORDS = ("duan dao", "butterfly", "hu die", "short saber", "short sabre")


@effect("if_target_state")
def if_target_state(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import mark_condition_id, run_effects

    target = ctx.target
    if target is None or not target.active:
        return
    wanted = {f"condition:typed.{name}" for name in eff.get("conditions") or []}
    wanted |= {mark_condition_id(name, ctx.actor.entity_id) for name in eff.get("marks") or []}
    bloodied = bool(eff.get("bloodied")) and target.current_hp * 2 <= target.maximum_hp
    if bloodied or any(c.condition_id in wanted for c in target.conditions.values()):
        run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("if_adjacent")
def if_adjacent(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    target = ctx.target
    if target is not None and target.active and ctx.engine._distance_actor_to_actor(ctx.actor, target) <= 5:
        run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("cone_passage")
def cone_passage(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import area_cells

    target = ctx.target
    area = ctx.typed.get("area") or {}
    aim = ctx.damage_cache.get("_checkpoint_aim")
    if target is None or not target.active or aim is None or not area.get("size_ft"):
        return
    cells = area_cells(ctx.engine, ctx.actor.position, aim, area) or ()
    extra = {}
    if eff.get("choose_allies"):
        from .needle import CHOICE, ask, checkpoint_id
        key = "_sabers_passage_allies"
        if key not in ctx.damage_cache:
            allies = sorted((a for a in ctx.engine.state.actors.values() if a.active
                             and a.entity_id != ctx.actor.entity_id and a.team_id == ctx.actor.team_id),
                            key=lambda a: a.entity_id)
            ids = [a.entity_id for a in allies]
            ctx.damage_cache[key] = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, key, ctx.source),
                ctx.actor, CHOICE + "sabers_passage_allies", ids, minimum=0, maximum=len(ids),
                labels={a.entity_id: a.display_name for a in allies}, allow_decline=True, preferred=ids,
                name=ctx.action.display_name,
                prompt=f"{ctx.action.display_name}: choose allies who can move through the line without "
                       f"Opportunity Attacks from creatures that failed the save until your next turn starts. No extra cost.") if ids else []
        extra["allies"] = list(ctx.damage_cache[key] or [])
    ctx.engine._apply_condition(target, PASSAGE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"team": ctx.actor.team_id, **extra, "cells": ";".join(f"{cell.x},{cell.y}" for cell in cells),
                                      "label": f"Makes no Opportunity Attacks against {ctx.actor.display_name}'s allies moving through the cut"})


@effect("choose_hit_target")
def choose_hit_target(ctx: Any, eff: dict[str, Any]) -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    hit = []
    for target_id in ctx.damage_cache.get("_choose_hit_targets", ()):
        creature = ctx.engine.state.actors.get(target_id)
        if creature is not None and creature.active and creature.entity_id != ctx.actor.entity_id:
            hit.append(creature)
    if not hit:
        return
    ids = [creature.entity_id for creature in hit]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "CHOOSE_HIT", ctx.source), ctx.actor, CHOICE + "choose_hit_target", ids,
                 labels={creature.entity_id: creature.display_name for creature in hit}, name=ctx.action.display_name,
                 prompt=f"{ctx.action.display_name}: {eff.get('prompt') or 'choose one creature you hit'}.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, hit[0]))
    chosen = next((creature for creature in hit if creature.entity_id == (picked or ids)[0]), hit[0])
    run_effects(replace(ctx, targets=[chosen], target=chosen), copy.deepcopy(eff.get("effects") or []))


@hook("attack_result")
def remember_choice_hits(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Resolution-local successful attacks for the opt-in choose_hit_target effect; no fight-history lookup."""
    if not hit or not any(row.get("type") == "choose_hit_target" for row in ctx.typed.get("effects") or []):
        return
    targets = ctx.damage_cache.setdefault("_choose_hit_targets", [])
    if target.entity_id not in targets:
        targets.append(target.entity_id)


@hook("opportunity_allowed")
def passage_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    for condition in reactor.conditions.values():
        if condition.condition_id != PASSAGE or (condition.data or {}).get("team") != mover.team_id:
            continue
        if "allies" in condition.data and mover.entity_id not in condition.data["allies"]:
            continue
        if f"{mover.position.x},{mover.position.y}" in str((condition.data or {}).get("cells") or "").split(";"):
            return False
    return None


@hook("compile_block")
def sabers_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "sabers_rider", "kind": spec.get("kind"),
             **({"hit_effects": copy.deepcopy(spec["hit_effects"]),
                 "source_mechanics": list(spec.get("source_mechanics") or [])}
                if spec.get("hit_effects") else {})}] if block == "sabers_rider" else None


@hook("compile_actions")
def seal_saber_hit_pool(info: dict[str, Any]) -> list[Any]:
    """Seal the owner's actual CP pool into new paid hit rows before hashing."""
    from ..factory_compiler import RESOURCE_IDS
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("resource_id") == "primary":
                value["resource_id"] = RESOURCE_IDS[info["primary"]]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for row in info["passives"]:
        if row.get("block") == "sabers_rider" and row.get("hit_effects"):
            visit(row["hit_effects"])
    return []


@hook("after_hit")
def paid_saber_hit(ctx: Any, target: Any, kind: str) -> None:
    """New sealed hit rows own the movement/size/payment/save gates; legacy rows are inert."""
    if not target.active:
        return
    from ..typed_executor import run_effects
    from dataclasses import replace
    for row in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, []):
        if row.get("block") == "sabers_rider" and row.get("hit_effects") \
                and str(ctx.typed.get("option_of") or ctx.typed.get("source") or "") in row.get("source_mechanics", []):
            run_effects(replace(ctx, targets=[target], target=target), copy.deepcopy(row["hit_effects"]))


def _owns(engine: Any, actor: Any, kind: str) -> bool:
    from ..typed_reactions import _rows

    return any(row.get("kind") == kind for row in _rows(engine, actor.entity_id, "sabers_rider"))


@hook("after_hit")
def short_saber_infighting(ctx: Any, target: Any, kind: str) -> None:
    """"When you hit a creature within 5 feet with a duan dao, butterfly saber, short saber, or similar close saber, you may make a
    shove attempt against that creature as part of the same Action. If the shove succeeds, the creature is Guard Pressured"."""
    if kind != "weapon" or not target.active or not _owns(ctx.engine, ctx.actor, "short_saber_infighting") \
            or ctx.engine._distance_actor_to_actor(ctx.actor, target) > 5 \
            or not any(word in str(ctx.action.display_name).lower() for word in SHORT_SABER_WORDS) or ctx.typed.get("reaction_attack"):
        return
    from ..typed_executor import Context, run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SHORT_SABER", ctx.source, target.entity_id), ctx.actor, CHOICE + "short_saber_infighting",
                 ["prone", "push", "skip"], labels={"prone": f"Shove {target.display_name}: knock it Prone", "push": f"Shove {target.display_name}: push it 5 feet",
                                                    "skip": "No shove"}, name="Short Saber Infighting",
                 prompt=f"Short Saber Infighting: {ctx.action.display_name} hit {target.display_name}. Shove it as part of the same Action?",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    choice = (picked or ["prone"])[0]
    if choice == "skip":
        return
    shove = ({"type": "condition", "condition": "prone", "applies_to": "target", "evidence": "knocked Prone"} if choice == "prone"
             else {"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target", "evidence": "pushed 5 feet"})
    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache), [
        {"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1, "applies_to": "target", "evidence": "a shove attempt",
         "on_fail": [shove, {"type": "mark", "mark": "Guard Pressured", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                             "evidence": "If the shove succeeds, the creature is Guard Pressured until the start of your next turn."}],
         "on_success": []}])


@hook("event")
def execution_frees_fear(engine: Any, event_type: str, kwargs: Any) -> None:
    payload = (kwargs or {}).get("payload") or {}
    if event_type != "DAMAGE_COMMITTED" or int(payload.get("remaining_hp", 1)) != 0 or int(payload.get("hp_damage") or 0) <= 0:
        return
    actor = engine.state.actors.get((kwargs or {}).get("actor_id") or "")
    if actor is None or not actor.active:
        return
    from .. import stances

    reach = max([int((c.data or {}).get("kill_ends_frightened_ft") or 0) for c in stances.active(actor)] or [0])
    if not reach:
        return
    consent = any((c.data or {}).get("kill_ally_consent") for c in stances.active(actor))
    from ..relations import relation, ALLY
    frightened = [creature for creature in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
                  if creature.active and (relation(engine, actor, creature) == ALLY if consent else creature.team_id == actor.team_id) and engine._distance_actor_to_actor(actor, creature) <= reach
                  and any(c.condition_id == "condition:typed.frightened" for c in creature.conditions.values())]
    if not frightened:
        return
    from . import ai_controlled
    if consent and ai_controlled(engine, actor):
        from ..senses import perceives
        # Perception bounds the computer's knowledge, not the printed ally
        # eligibility. A player may help a known ally even while blinded.
        frightened = [c for c in frightened if c is actor or perceives(engine, actor, c)]
        if not frightened:
            return
    frightened.sort(key=lambda creature: creature.entity_id != actor.entity_id)  # the AI frees itself first
    from .needle import CHOICE, ask, checkpoint_id

    ids = [creature.entity_id for creature in frightened]
    picked = ask(engine, None, checkpoint_id(engine, "EXECUTION_PRESENCE", actor.entity_id), actor, CHOICE + "execution_presence", ids,
                 labels={creature.entity_id: f"End Frightened on {creature.display_name}" for creature in frightened}, allow_decline=True,
                 name="Execution Platform Presence",
                 prompt="Execution Platform Presence: you dropped a creature. End one Frightened effect on yourself or a willing ally within 30 feet?")
    if not picked:
        return
    subject = engine.state.actors[picked[0]]
    # New stance rows require the willing ally's own answer. Unstamped
    # historical stances preserve their previous one-chooser transport.
    consent = any((c.data or {}).get("kill_ally_consent") for c in stances.active(actor))
    if consent and subject is not actor:
        willing = ask(engine, None, checkpoint_id(engine, "EXECUTION_CONSENT", actor.entity_id, subject.entity_id),
                      subject, CHOICE + "execution_consent", ["accept"], allow_decline=True,
                      labels={"accept": "End one Frightened effect"}, name="Execution Platform Presence",
                      prompt=f"{actor.display_name} offers to end one Frightened effect on you. Accept? No extra cost.")
        if not willing:
            return
    iid = next(key for key, c in subject.conditions.items() if c.condition_id == "condition:typed.frightened")
    condition = subject.conditions.pop(iid)
    engine._append_event("CONDITION_REMOVED", "tianxia.talent.sabers.execution_platform_presence", actor_id=actor.entity_id,
                         target_ids=(subject.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": iid})
    engine._append_event("PASSIVE_TRIGGERED", "tianxia.talent.sabers.execution_platform_presence", actor_id=actor.entity_id,
                         target_ids=(subject.entity_id,), payload={"trigger": f"Execution Platform Presence: {subject.display_name} is no longer Frightened."})


FEINT_READY = "condition:typed.sabers.feint_next"


@effect("sabers_feint_next")
def feint_next(ctx: Any, eff: dict[str, Any]) -> None:
    """A target-bound next Sabers attack roll, held only for this turn."""
    from .condition_ownership import refresh_owned
    if ctx.target is None:
        return
    refresh_owned(ctx.engine, ctx.actor, FEINT_READY, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, FEINT_READY, ctx.source, ctx.actor.entity_id,
        expires_on="END_OF_CURRENT_TURN", data={"target": ctx.target.entity_id,
        "label": f"Beheading Feint: Advantage on your next Sabers attack against {ctx.target.display_name} this turn"})


def feint_applies(ctx: Any, target: Any) -> list[tuple[str, Any]]:
    if ctx.typed.get("sphere") != "tianxia.sphere.sabers":
        return []
    return [(iid, c) for iid, c in ctx.actor.conditions.items()
            if c.condition_id == FEINT_READY and c.data.get("target") == target.entity_id]


@hook("attack_mode")
def feint_mode(ctx: Any, target: Any) -> str | None:
    return "ADVANTAGE" if feint_applies(ctx, target) else None


@hook("attack_result")
def feint_consumed(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    from .condition_ownership import remove_instance
    if ctx.attack_result is not None:
        for iid, held in feint_applies(ctx, target):
            remove_instance(ctx.engine, ctx.actor, iid, held.source_definition_id)


@hook("compile_actions")
def saber_bound_reach(info: dict[str, Any]) -> list[Any]:
    """Seal one selectable physical expression per base saber; one projected mode.

    Keep the first expression's historical id/label. Alternate expressions name
    their weapon and bind reach, delivery numbers, damage and possession to it.
    Reach/off-hand variants describe the same item, not additional sabers.
    """
    from ..gate2_runtime_models import ActionDefinition
    from ..weapon_delivery import weapon_variant_base
    from .saber_learning import saber_action
    weapons = [a for a in info["actions"] if ((a.parameters or {}).get("typed") or {}).get("weapon")
               and saber_action(a)
               and not (((a.parameters or {}).get("typed") or {}).get("long_range_ft"))
               and "#" not in a.source_definition_id and not weapon_variant_base(a.parameters)
               and not any(((a.parameters or {}).get("typed") or {}).get(key)
                           for key in ("delivered_by", "weapon_source_id", "maneuver_of", "opportunity_of"))]
    weapon = weapons[0] if weapons else None
    made = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        effects = typed.get("effects") or []
        bind = any(e.get("bind_saber_reach") for e in effects)
        if not bind:
            continue
        # No saber -> no physical expression; a projected feint remains available
        # only to a character whose sealed sheet has a Qi pool.
        action.parameters["sabers_requires_weapon"] = not bool(weapon)
        if weapon:
            action.parameters["range_from_action"] = weapon.source_definition_id
            typed["saber_weapon_source"] = weapon.source_definition_id
            typed["weapon_source_id"] = weapon.source_definition_id
            for index, alternate in enumerate(weapons[1:], start=2):
                params = copy.deepcopy(action.parameters)
                params["range_from_action"] = alternate.source_definition_id
                params["typed"]["saber_weapon_source"] = alternate.source_definition_id
                params["typed"]["weapon_source_id"] = alternate.source_definition_id
                made.append(ActionDefinition(**{**action.model_dump(),
                    "source_definition_id": action.source_definition_id + f".saber_{index}",
                    "display_name": action.display_name + f" (with {alternate.display_name})",
                    "parameters": params}))
        if any(e.get("projected_feint") for e in effects) and "qi" in info["pools"]:
            params = copy.deepcopy(action.parameters)
            params.pop("range_from_action", None)
            params.pop("sabers_requires_weapon", None)
            params["typed"].pop("weapon_source_id", None)
            params["typed"].pop("saber_weapon_source", None)
            params["typed"]["range_ft"] = 30
            made.append(ActionDefinition(**{**action.model_dump(),
                "source_definition_id": action.source_definition_id + ".projected",
                "display_name": action.display_name + " (projected saber qi; 30 feet)",
                "range_ft": 30, "parameters": params}))
    return made


@hook("candidate_allowed")
def saber_weapon_required(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "parameters", None) or {}).get("sabers_requires_weapon"):
        return False
    bound = (getattr(action, "parameters", None) or {}).get("range_from_action")
    if bound:
        from ..weapon_delivery import available_weapons
        from .hand_occupancy import weapon_allowed
        linked = available_weapons(engine, actor).get(bound)
        if linked is None or weapon_allowed(engine, actor, linked) is False:
            return False
    return None


@hook("compile_action")
def saber_creature_domain(action: Any, info: dict[str, Any]) -> Any | None:
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("bind_saber_reach") for e in effects):
        return None
    params = copy.deepcopy(action.parameters)
    params["harmful"] = True
    return action.model_copy(update={"target_kind": "ANY_CREATURE", "parameters": params})


@hook("target_eligibility")
def saber_other_creature(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if any(e.get("bind_saber_reach") for e in effects) and target is actor:
        return False
    return None



@hook("hit_snapshot")
def stance_target_snapshot(engine: Any, actor: Any, target: Any, attack_context: Any, intent: Any) -> dict[str, Any] | None:
    from ..stances import hit_target_receipt
    receipt = hit_target_receipt(engine, actor, target)
    return {"stance_targets_at_hit": receipt} if receipt else None


@hook("hit_final")
def stance_target_final(ctx: Any, target: Any, kind: str) -> None:
    if "stance_targets_at_hit" in ctx.hit_snapshots:
        ctx.damage_cache.setdefault("_stance_hit_targets", {})[target.entity_id] = copy.deepcopy(ctx.hit_snapshots["stance_targets_at_hit"])
