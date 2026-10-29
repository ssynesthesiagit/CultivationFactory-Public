"""Sun-Piercing Bow Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sun-Piercing Bow Body (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "sun_bow", "role": "bow_body" | "overdraw"}``; Bow Body also carries the integrated-weapon
row ``{"kind": "integrated_weapon", "group": "bow"}`` (combat/ext/integrated_weapons.py: the "(Constitution)" variant).

Bow Body            a hostile creature within 5 feet gives its Bow attacks no Disadvantage (hook close_ranged_ok).
Meridian Overdraw   once per turn, after a Bow attack hits (asked, 1 Stamina): + 2d8 Piercing or Force (3d8 at CL11, 4d8 at CL17),
                    then a Strength save; failure: one chosen result (push 10 feet, no Reactions until the start of its next
                    turn, Speed - 15 feet until then, or you move 10 feet without provoking); success: push 5 feet or you move 5.
Sky-Pinning Arrow   "Sky-Pinning Arrow (<Bow>)" (and its Constitution version): one attack with that Bow (its own range and
                    long range) costing 3 Stamina; on a hit + 5d8 Piercing or Force and a Strength save: Sky-Pinned (Speed 0,
                    no teleport, no willing move) until the start of your next turn, or Speed halved until then (the feature
                    itself is typed as a marker row, so it compiles no action of its own).
Sun-Chasing Line    "Sun-Chasing Line (<Bow>)": the Bow's Attack action with one attack spent on a 120-foot line (combat/ext/
                    attack_lines.py) for 2 Stamina, once per turn.
Every hook returns early for a creature without these rows or actions.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

PREFIX = "tianxia.subpath.body.sun_piercing_bow_body.feature."
SKY = PREFIX + "sky_pinning_arrow"
LINE = PREFIX + "sun_chasing_line"
PINNED = "condition:typed.sky_pinned"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "sun_bow"}


def _bow(typed: dict[str, Any]) -> bool:
    from .integrated_weapons import in_group

    return in_group(typed or {}, "bow") and int((typed or {}).get("range_ft") or 0) > 5


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


@hook("close_ranged_ok")
def bow_body_close(ctx: Any) -> bool | None:
    return True if "bow_body" in _roles(ctx.engine, ctx.actor) and _bow(ctx.typed) else None


# --------------------------------------------------------------------------------------------------- Meridian Overdraw
@hook("after_hit")
def meridian_overdraw(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    row = _roles(engine, actor).get("overdraw")
    if row is None or target is None or not target.active or target.team_id == actor.team_id or not _bow(ctx.typed):
        return
    if actor.turn_flags.get("_round_meridian_overdraw") == _stamp(engine) or int(actor.resources.get(STAMINA, 0) or 0) < 1:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "meridian_overdraw", target.entity_id), actor, "choice:needle.meridian_overdraw", ["use"],
                 labels={"use": "Spend 1 Stamina: extra Piercing or Force damage and a Strength save"}, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Meridian Overdraw", prompt=f"Meridian Overdraw: {ctx.action.display_name} hit {target.display_name}. Overdraw?")
    if not picked:
        return
    engine._spend_resource(actor, STAMINA, 1, row["feature_id"])
    actor.turn_flags["_round_meridian_overdraw"] = _stamp(engine)
    cl = int(row.get("cl") or 1)
    count = 4 if cl >= 17 else 3 if cl >= 11 else 2
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**ctx.numbers, 'save_dc': int(row.get('save_dc') or ctx.numbers.get('save_dc') or 10)}}, damage_cache={})
    push = lambda ft: {"type": "forced_movement", "applies_to": "target", "distance_ft": ft, "direction": "away", "evidence": f"Push it {ft} feet."}
    step = lambda ft: {"type": "overdraw_step", "feet": ft, "evidence": f"Move yourself {ft} feet without provoking Opportunity Attacks."}
    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": ["piercing", "force"],
                          "evidence": f"Meridian Overdraw: + {count}d8"},
                         {"type": "save", "ability": "str", "evidence": "Meridian Overdraw: Strength saving throw",
                          "on_fail": [{"type": "path_results", "family": "meridian_overdraw", "count": 1, "name": "Meridian Overdraw",
                                       "prompt": "Meridian Overdraw: {target} failed its Strength save. Choose one result.",
                                       "options": [{"label": "Push 10 Feet", "effects": [push(10)]},
                                                   {"label": "No Reactions", "effects": [{"type": "reaction_denied", "applies_to": "target",
                                                                                          "expires_on": "START_OF_TARGET_NEXT_TURN"}]},
                                                   {"label": "Speed - 15 Feet", "effects": [{"type": "speed", "applies_to": "target", "flat": -15,
                                                                                             "expires_on": "START_OF_TARGET_NEXT_TURN"}]},
                                                   {"label": "Move Yourself 10 Feet", "effects": [step(10)]}]}],
                          "on_success": [{"type": "path_results", "family": "meridian_overdraw_saved", "count": 1, "name": "Meridian Overdraw",
                                          "prompt": "Meridian Overdraw: {target} succeeded on its Strength save. Push it 5 feet or move 5 feet?",
                                          "options": [{"label": "Push 5 Feet", "effects": [push(5)]}, {"label": "Move Yourself 5 Feet", "effects": [step(5)]}]}]}])


@effect("overdraw_step")
def overdraw_step(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, actor = ctx.engine, ctx.actor
    feet = int(row.get("feet") or 5)
    paths = routes(engine, actor, feet)
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "overdraw_step", actor.entity_id), actor, "choice:needle.overdraw_step", sorted(paths),
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name="Meridian Overdraw",
                 prompt=f"Meridian Overdraw: move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(engine, actor, paths[picked[0]], PREFIX + "meridian_overdraw")


# ------------------------------------------------------------------------------------ Sky-Pinning Arrow, Sun-Chasing Line
@hook("compile_actions")
def bow_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import EconomyKind
    from .integrated_weapons import constitution_typed, integrated_groups

    owned = set(info["owned_ids"])
    if SKY not in owned and LINE not in owned:
        return None
    bows = [a for a in info["actions"] if a.economy == EconomyKind.ACTION and "#" not in a.source_definition_id and _bow((a.parameters or {}).get("typed") or {})
            and any(isinstance(e, dict) and e.get("type") == "attack" for e in ((a.parameters or {}).get("typed") or {}).get("effects") or [])]
    out = []
    if SKY in owned:
        integrated = "bow" in integrated_groups(info)
        for base in sorted(bows, key=lambda a: a.source_definition_id):
            typed = (base.parameters or {}).get("typed") or {}
            for suffix, label, spec in (("", "", typed), ("#con", ", Constitution", constitution_typed(info, typed) if integrated else None)):
                if spec is None:
                    continue
                variant = copy.deepcopy(spec)
                attack = next(e for e in variant["effects"] if isinstance(e, dict) and e.get("type") == "attack")
                attack["count"] = 1
                attack["on_hit"] = [*(attack.get("on_hit") or []),
                                    {"type": "extra_damage", "applies_to": "target", "dice": {"count": 5, "sides": 8}, "damage_types": ["piercing", "force"],
                                     "evidence": "Sky-Pinning Arrow: + 5d8"},
                                    {"type": "save", "ability": "str", "evidence": "Sky-Pinning Arrow: Strength saving throw",
                                     "on_fail": [{"type": "condition", "applies_to": "target", "condition": "sky_pinned", "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                                     "on_success": [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}]
                variant["numbers"] = {**variant.get("numbers", {}), "save_dc": info["numbers"].get("save_dc")}
                out.append(base.model_copy(update={
                    "source_definition_id": base.source_definition_id + "#sky_pinning" + suffix,
                    "display_name": f"Sky-Pinning Arrow ({base.display_name.removesuffix(' attack')}{label})",
                    "costs": (*base.costs, (STAMINA, 3)), "parameters": {**{k: v for k, v in base.parameters.items() if k != "typed"}, "typed": variant,
                                                                         "sky_pinning": True, "description": (
                        "Sky-Pinning Arrow (Action, 3 Stamina): make one attack with this Bow, out to its long range. On a hit it deals an extra "
                        "5d8 Piercing or Force damage and the target makes a Strength saving throw. On a failure, until the start of your next "
                        "turn its Speed is 0 and it cannot teleport or move of its own will (being pushed or pulled still works). On a success, "
                        "its Speed is halved until then.")}}))
    if LINE in owned:
        from .attack_lines import line_variants

        out += line_variants(info, LINE, bows, replace=1, area={"shape": "line", "size_ft": 120, "width_ft": 5}, stamina=2, name="Sun-Chasing Line")
    return out or None


@hook("teleport_check")
def sky_pinned_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    return False if any(c.condition_id == PINNED for c in actor.conditions.values()) else None  # "it cannot teleport"
