"""Ryūjin Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Ryūjin (Dragon's Breath, Storm Step, Dragon's Roar, Ryūjin Ascendant Form and their
Normalized Procedures). Storm Step's action runs ``storm_step``; the form is the named state "ryujin_ascendant_form".

Storm Step       teleport to the aimed space (or, when a creature stands there, the open space nearest to it within 30 feet of
                 you), then each hostile creature within 5 feet of where you arrive makes a Dexterity save: 2d6 Lightning or
                 Thunder and no Reactions until the start of its next turn, or half. A blocked teleport has no burst.
Ascendant Form   Lightning Immunity and Thunder Resistance (typed), +5 ft unarmed reach (reach_bonus), once per turn + 3d6
                 Lightning or Thunder on an unarmed hit, a hostile creature starting its turn within 10 feet makes a Constitution
                 save or is pushed 5 feet and loses its Reactions (a zone following you, typed); while it lasts Dragon's Breath is
                 its "(Ascendant)" profile (30-foot cone, 8d6) and Storm Step costs 1 Stamina once per turn ("(Ascendant)").
The form also grants native Fly Speed 60 feet and Hover; optional Large size uses the recorded growth procedure only when the current anchor fits. Storm Step uses the shared visible landing picker, then chooses only perceived hostile recipients. Every hook returns early without its owned state or effect.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.ryujin.feature."
FORM = "ryujin_ascendant_form"


@hook("compile_action")
def classify_storm_step_movement(action: Any, info: dict[str, Any]) -> Any | None:
    """Ryūjin-owned classification consumed by the shared movement policy."""
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    changed = False
    for row in typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "storm_step" and row.get("self_movement") is not True:
            row["self_movement"] = True
            changed = True
    if not changed:
        return None
    parameters["typed"] = typed
    return action.model_copy(update={"parameters": parameters})


def _form(engine: Any, actor: Any) -> bool:
    from .states import active

    return actor is not None and bool(active(engine, actor, FORM))


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


@effect("ryujin_choose_damage")
def choose_damage(ctx: Any, row: dict[str, Any]) -> None:
    damage_choice(ctx, ["LIGHTNING", "THUNDER"], ctx.targets)


@hook("damage_type_choice")
def damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    source = str(ctx.typed.get("source") or "")
    if source not in {PREFIX + "dragon_s_breath", PREFIX + "storm_step", PREFIX + FORM}:
        return None
    if "ryujin_damage_type" in ctx.damage_cache:
        return ctx.damage_cache["ryujin_damage_type"]
    from .needle import ask, checkpoint_id
    from .. import senses, typed_reactions

    known = [target for target in targets if senses.perceives(ctx.engine, ctx.actor, target)]
    preferred = max(kinds, key=lambda kind: sum(typed_reactions.damage_factor(
        ctx.engine, target, kind, source, ctx.actor.entity_id) for target in known))
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ryujin_damage", ctx.actor.entity_id), ctx.actor,
                 "choice:needle.ryujin_damage", kinds, labels={kind:kind.title() + " damage" for kind in kinds},
                 preferred=[preferred], prompt="Ryūjin: choose Lightning or Thunder damage for this use.")
    ctx.damage_cache["ryujin_damage_type"] = chosen[0] if chosen else preferred
    return ctx.damage_cache["ryujin_damage_type"]


# Dragon's Breath commits its damage type before any recipient's save. The
# same cached activation choice is reused by every save outcome and object.


@hook("flight")
def ascendant_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    return {"fly_speed_ft": 60, "flight_hover": 1} if _form(engine, actor) else None


@effect("ryujin_form_size")
def form_size(ctx: Any, row: dict[str, Any]) -> None:
    from .. import dynamic_size
    from .needle import ask, checkpoint_id
    from ..typed_executor import effect_expiry

    engine, actor = ctx.engine, ctx.actor
    if dynamic_size.CATEGORIES.index(dynamic_size.current_category(engine, actor)) >= 3:
        return
    footprint = dynamic_size.shape(engine.actor_footprints[actor.entity_id], "Large")
    if not engine.grid.volume_legal(actor.position, footprint=footprint,
                                    occupied_cells=engine._occupied_volumes_except(actor.entity_id)):
        return
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "ryujin_size", actor.entity_id), actor,
                 "choice:needle.ryujin_size", ["large"], allow_decline=True,
                 labels={"large": "Become Large until the form ends"},
                 prompt=f"Ryūjin Ascendant Form: {actor.display_name} may become Large, or keep its current size.",
                 target_id=actor.entity_id)
    if chosen:
        dynamic_size.apply_growth(engine, actor, "Large", ctx.source, source_actor_id=actor.entity_id,
                                  expires_on=effect_expiry(ctx, row, actor, condition=True))


@effect("storm_step")
def storm_step(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position

    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.destination
    if aim is None:
        return
    from .teleport_steps import destinations
    from .needle import ask, checkpoint_id
    from .. import senses

    choose_damage(ctx, {})
    start = actor.position
    legal = destinations(engine, actor, int(row.get("range_ft") or 30), action=ctx.action)
    if not legal:
        return
    destination = aim if aim in legal else min(legal, key=lambda c: (engine.grid.distance_ft(c, aim), c.y, c.x))
    if (row.get("once_per_turn")):
        actor.turn_flags["_round_storm_step"] = _stamp(engine)
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [], None, ctx.damage_cache, destination=destination)
    te.run_effects(sub, [{"type": "teleport", "applies_to": "self", "distance_ft": int(row.get("range_ft") or 30)}])
    if actor.position == start:
        return  # the teleport failed: no arrival burst
    foes = [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= 5 and senses.perceives(engine, actor, c)]
    if not foes:
        return
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "storm_recipients", actor.entity_id), actor,
                   "choice:needle.storm_recipients", [c.entity_id for c in foes], maximum=len(foes),
                   allow_decline=True, default="all", preferred=[c.entity_id for c in foes],
                   labels={c.entity_id: c.display_name for c in foes},
                   prompt=f"Storm Step: choose the hostile creatures within 5 feet of {actor.display_name}'s arrival to affect.")
    foes = [c for c in foes if c.entity_id in selected]
    if not foes:
        return
    burst = te.Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "_area_centre": (actor.position.x, actor.position.y)},
                       foes, foes[0] if len(foes) == 1 else None,
                       {"ryujin_damage_type": ctx.damage_cache.get("ryujin_damage_type", "LIGHTNING")})
    te.run_effects(burst, [{"type": "save", "ability": "dex", "evidence": "Storm Step: Dexterity saving throw",
                            "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}, "damage_types": ["lightning", "thunder"]},
                                        {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                            "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["lightning", "thunder"]}]}])


@hook("compile_actions")
def ascendant_profiles(info: dict[str, Any]) -> list[Any] | None:
    """The form's Dragon's Breath (30-foot cone, 8d6) and Storm Step (1 Stamina, once per turn), offered while it lasts."""
    if PREFIX + FORM not in info["owned_ids"]:
        return None
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        source = str(typed.get("source") or "")
        if source == PREFIX + "dragon_s_breath" and "#" not in base.source_definition_id:
            variant = copy.deepcopy(typed)
            for row in variant.get("effects") or []:
                for fail in (row.get("on_fail") or []) if isinstance(row, dict) else []:
                    if isinstance(fail, dict) and fail.get("type") == "damage":
                        fail.pop("dice_by_cl", None)
                        fail["dice"] = {"count": 8, "sides": 6}
            variant["area"] = {**(variant.get("area") or {}), "size_ft": 30}
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#ascendant", "display_name": base.display_name + " (Ascendant)",
                                               "range_ft": 30, "radius_ft": 30,
                                               "parameters": {**base.parameters, "ryujin_ascendant": True, "typed": variant}}))
        elif source == PREFIX + "storm_step" and "#" not in base.source_definition_id:
            variant = copy.deepcopy(typed)
            for row in variant.get("effects") or []:
                if isinstance(row, dict) and row.get("type") == "storm_step":
                    row["once_per_turn"] = True
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#ascendant", "display_name": base.display_name + " (Ascendant)",
                                               "costs": tuple((r, 1 if r == "resource:core.stamina" else a) for r, a in base.costs),
                                               "parameters": {**base.parameters, "ryujin_ascendant": True, "ryujin_step": True, "typed": variant}}))
    return out or None


@hook("candidate_allowed")
def ascendant_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    source = str((params.get("typed") or {}).get("source") or "")
    if params.get("ryujin_ascendant"):
        if not _form(engine, actor):
            return False
        if params.get("ryujin_step") and actor.turn_flags.get("_round_storm_step") == _stamp(engine):
            return False
        return None
    if source == PREFIX + "dragon_s_breath" and _form(engine, actor):
        return False  # the form replaces the breath's profile
    if source == PREFIX + "storm_step" and _form(engine, actor):
        return False  # the form replaces the step's price and turn limit
    return None


@hook("after_hit")
def ascendant_rider(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id or not _form(engine, actor):
        return
    if actor.turn_flags.get("_round_ryujin_hit") == _stamp(engine):
        return
    actor.turn_flags["_round_ryujin_hit"] = _stamp(engine)
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, "source": PREFIX + FORM}, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 6}, "damage_types": ["lightning", "thunder"],
                     "evidence": "Ryūjin Ascendant Form: once per turn + 3d6"}])
