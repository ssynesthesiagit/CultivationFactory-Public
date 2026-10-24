"""Destruction sphere: Blast Shape talents built as their own standalone actions (w4-destruction, 2026-09-28/29).

Most Blast Shape talents (Ruin-Crossing Step's line, Calamity Pearl's cube, Calamity Curtain's and Wandering
Calamity's simplified instant bursts) need no code here: authority/typed_mechanics/reviewed_final.d/destruction.json
gives each its own `area`/`activation`/`effects`, and factory_compiler's own `_target_kind` already turns "a save
effect with an area" into a standalone CELL-targeted action -- the same generic path every other area talent in
this ruleset uses. Their on_fail routes through destruction_blast.destructive_blast_damage, which reads whichever
Blast Type the character currently has selected.

What is built here is what that generic per-mechanic path cannot express -- a second, differently-costed variant
of the same printed talent (an "Augment - 1 CP: ..." line), or a follow-up Bonus Action gated on a prior action's
own state:
  - Heaven-Piercing Ray (Multi-Ray, 1 CP): newly declared distinct rays use shared
    creature selection and one ordinary attack per creature. Old sealed rays keep
    their historical single-target sequence.
  - Leaping Ruin (Chain, 1 CP): resolves the whole leap in one activation instead of a separate later Bonus
    Action, since nothing here tracks "still eligible to leap from my last Leaping Ruin this turn" across actions.
  - Calamity Mantle: newly sealed runtime rows freeze release parameters and pulse every other creature
    within 10 feet. The base lasts one round; its minute Concentration and later 2 CP release are separate
    buttons. Markerless saved activations retain their historical enemy-only pulse.
  - Ruin-Binding Tether: Pulse: new bound-target rows freeze the struck creature,
    dice and save parameters. Old sealed pulses retain their historical selector.
    The mutual movement/drag and attackable tether clauses still need bindings.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .destruction_blast import current_type_id, prepare_release

HEAVEN_PIERCING_RAY = "tianxia.talent.destruction.heaven_piercing_ray"
LEAPING_RUIN = "tianxia.talent.destruction.leaping_ruin"
CALAMITY_FORM = "tianxia.talent.destruction.calamity_form"
CALAMITY_MANTLE = "tianxia.talent.destruction.calamity_mantle"
RUIN_BINDING_TETHER = "tianxia.talent.destruction.ruin_binding_tether"
MANTLE_ACTIVE = "condition:typed.destruction_calamity_mantle"
TETHER_TYPE = "condition:typed.destruction_tether_type"

_RAYS_BY_CL = ((17, 5), (11, 4), (5, 3), (1, 2))
_DICE_BY_CL = [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]]  # Unshaped Ruin's 1d8 by CL, a scoring proxy


def _declared(info: dict[str, Any], talent: str, marker: str) -> bool:
    """New behavior follows the reviewed data frozen into this compilation."""
    return any(row.get(marker) for row in (info.get("mechanics", {}).get(talent, {}).get("effects") or []))


def _pool(info: dict[str, Any]) -> str:
    return f"resource:core.{info['primary']}"


def _rays(cl: int) -> int:
    return next(count for threshold, count in _RAYS_BY_CL if cl >= threshold)


def _blast_hit_average(numbers: dict[str, Any], hits: int = 1) -> int:
    """The combat AI's scoring reads a compiled action's own ``expected_damage``, computed once at compile time
    (factory_compiler._expected_damage); it cannot see a runtime Blast Type choice, so this always estimates off
    Unshaped Ruin's 1d8-by-CL table (the same proxy destruction.json's own destructive_blast_damage effects carry)
    -- close enough for scoring even when the actual type is a d6. Used for the actions below that resolve their
    hits in a custom effect (so factory_compiler never sees the nested dice to sum on its own)."""
    from factory_authoring.typed_mechanics import dice_for_cl

    dice = dice_for_cl(_DICE_BY_CL, numbers.get("cl")) or {"count": 1, "sides": 8}
    return max(0, hits) * ((int(dice["count"]) * (int(dice["sides"]) + 1)) // 2)


@hook("compile_action")
def finite_shape_delivery(action: Any, info: dict[str, Any]) -> Any | None:
    """Retain the ordinary save action's delivery for our declared save wrapper."""
    typed = action.parameters.get("typed") or {}
    if not any(row.get("type") == "destruction_shape_save" for row in typed.get("effects") or []):
        return None
    parameters = {**action.parameters, "expected_damage": _blast_hit_average(typed.get("numbers") or {})}
    return action.model_copy(update={"target_kind": "CELL" if typed.get("area") else "HOSTILE_ENTITY", "parameters": parameters})


# ------------------------------------------------------------------ Calamity Form: Sphere / Cone / Line
@hook("compile_actions")
def calamity_form_actions(info: dict[str, Any]) -> list[Any] | None:
    if CALAMITY_FORM not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers, short, pool = info["numbers"], info["short"], _pool(info)
    save_fail = [{"type": "destructive_blast_damage",
                  **({"damage_required": True} if _declared(info, CALAMITY_FORM, "release_rules") else {})}]

    def action(key: str, label: str, range_ft: int, area: dict[str, Any], cost: int) -> Any:
        # The printed blast affects creatures in the shape, with a separate
        # optional self exclusion. Its extension-owned save has no built-in
        # harm classification, so declare this roster rather than inherit the
        # compiler's hostile-only fallback for opaque effects.
        area = {**area, "recipients": "all", "include_self": True, "exclude_self": False}
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.calamity_form.{key}", display_name=f"Calamity Form: {label}",
            owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=range_ft,
            costs=((pool, cost),) if cost else (),
            parameters={"typed": {"effects": [{"type": "destruction_shape_save" if _declared(info, CALAMITY_FORM, "release_rules") else "save",
                                               "may_exclude_self": True, "ability": "dex", "on_fail": save_fail, "on_success": [],
                                               "evidence": "Affected creatures make a Dexterity saving throw."}],
                                  "source": CALAMITY_FORM, "sphere": "tianxia.sphere.destruction",
                                  "numbers": numbers, "duration": {"kind": "instant"}, "area": area, "range_ft": range_ft,
                                  "riders": []}, "expected_damage": _blast_hit_average(numbers),
                        "ai_area_family": CALAMITY_FORM})

    return [
        action("sphere", "Sphere", 30, {"shape": "sphere", "size_ft": 5}, 0),
        action("cone", "Cone (1 CP)", 30, {"shape": "cone", "size_ft": 30}, 1),
        action("line", "Line (1 CP)", 120, {"shape": "line", "size_ft": 120, "width_ft": 5}, 1),
    ]


# ------------------------------------------------------------------ Heaven-Piercing Ray: Multi-Ray augment
@hook("compile_actions")
def heaven_piercing_multi_ray(info: dict[str, Any]) -> list[Any] | None:
    if HEAVEN_PIERCING_RAY not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.heaven_piercing_ray.multi_ray", display_name="Heaven-Piercing Ray (Multi-Ray, 1 CP)",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
        costs=((_pool(info), 1),),
        parameters={"typed": {"effects": [{"type": "destructive_blast_multi_ray",
                                            **({"distinct_targets": True} if _declared(info, HEAVEN_PIERCING_RAY, "distinct_rays") else {})}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "range_ft": 30, "riders": []},
                    "expected_damage": _blast_hit_average(info["numbers"], _rays(int(info["numbers"].get("cl") or 1)))})]


@hook("button_description")
def shape_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    for eff in effects:
        if eff.get("type") == "destructive_blast_multi_ray":
            return printed_rule_text("tianxia.talent.destruction.heaven_piercing_ray")
        if eff.get("type") == "destructive_blast_leap_chain":
            return printed_rule_text("tianxia.talent.destruction.leaping_ruin")
    return None


@effect("destructive_blast_multi_ray")
def multi_ray(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if eff.get("distinct_targets"):
        # Shared target selection deduplicates creature ids; the ordinary typed
        # attack makes exactly one attack per chosen creature, with full hit context.
        # The action is declared HOSTILE_ENTITY, so every ray's target is an enemy (S1).
        prepare_release(ctx)
        te.run_effects(ctx, [{"type": "rider_targets", "count": _rays(int(ctx.numbers.get("cl") or 1)),
                             "minimum": 1, "range_ft": 30, "hostile_only": True,
                             "prompt": f"Heaven-Piercing Ray (Multi-Ray): choose up to {_rays(int(ctx.numbers.get('cl') or 1))} "
                                       "different visible creatures within 30 feet. Spend 1 CP (cultivation energy) and your Action; "
                                       "make one full-damage Cultivation Attack against each. Each creature receives only one ray.",
                             "effects": [{"type": "attack", "attack_kind": "cultivation",
                             "count": 1, "on_hit": [{"type": "destructive_blast_damage", "damage_required": True}], "on_miss": []}]}])
        return
    target = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if target is None:
        return
    rays = _rays(int(ctx.numbers.get("cl") or 1))
    for index in range(rays):
        if not target.active or ctx.engine.state.terminal_result is not None:
            break
        spec = {"attack_bonus": int(ctx.numbers.get("attack_bonus") or 0), "range_ft": ctx.typed.get("range_ft"),
                "damage": None, "damage_type": "UNTYPED", "parameters": {}}
        hit = ctx.engine._resolve_attack_spec(ctx.actor, target, spec, ctx.intent, source_definition_id=ctx.source, attack_index=index + 1)
        if hit:
            recipient = ctx.engine.state.actors[spec["resolved_target_id"]]
            sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [recipient], recipient, ctx.damage_cache,
                             attack_damage_context=spec.get('resolved_attack_context'), attack_defense_spec=spec)
            te.run_effects(sub, [{"type": "destructive_blast_damage"}])
    ctx.rider("Heaven-Piercing Ray (Multi-Ray): every ray targeted the same creature or object; a spread across "
              "different targets is not offered.")


# ------------------------------------------------------------------ Leaping Ruin: Chain augment
@hook("compile_actions")
def leaping_ruin_chain(info: dict[str, Any]) -> list[Any] | None:
    if LEAPING_RUIN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.leaping_ruin.chain", display_name="Leaping Ruin (Chain, 1 CP)",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
        costs=((_pool(info), 1),),
        parameters={"typed": {"effects": [{"type": "destructive_blast_leap_chain"}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "range_ft": 30, "riders": []},
                    # The chain affects up to Proficiency Bonus targets total (itself included); a per-hit average
                    # times that count is a reasonable upper-bound estimate for scoring (most fights offer fewer).
                    "expected_damage": _blast_hit_average(info["numbers"], max(1, int(info["numbers"].get("pb") or 1)))})]


@effect("destructive_blast_leap_chain")
def leap_chain(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .. import stealth

    first = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if first is None:
        return
    pb = max(1, int(ctx.numbers.get("pb") or 1))
    chain, affected, previous = [first], {first.entity_id}, first
    while len(chain) < pb:
        candidates = [row for row in ctx.engine.state.actors.values()
                     if row.active and row.entity_id not in affected and row.team_id != ctx.actor.team_id
                     and ctx.engine._distance_actor_to_actor(previous, row) <= 30
                     and ctx.engine._distance_actor_to_actor(ctx.actor, row) <= 30
                     and stealth.sees(ctx.engine, ctx.actor, row)]
        if not candidates:
            break
        nxt = min(candidates, key=lambda row: (ctx.engine._distance_actor_to_actor(previous, row), row.entity_id))
        chain.append(nxt)
        affected.add(nxt.entity_id)
        previous = nxt
    for subject in chain:
        if ctx.engine.state.terminal_result is not None:
            break
        sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
        te.run_effects(sub, [{"type": "save", "ability": "dex", "on_fail": [{"type": "destructive_blast_damage"}], "on_success": []}])


# ------------------------------------------------------------------ Calamity Mantle: aura + Pulse
@hook("compile_actions")
def calamity_mantle_buttons(info: dict[str, Any]) -> list[Any] | None:
    if CALAMITY_MANTLE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    short, numbers = info["short"], info["numbers"]
    runtime = _declared(info, CALAMITY_MANTLE, "runtime")
    activate = ActionDefinition(
        source_definition_id=f"action:typed.{short}.calamity_mantle.activate", display_name="Calamity Mantle",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "destruction_calamity_mantle_activate", **({"runtime": 1} if runtime else {})}], "numbers": numbers,
                              "duration": {"kind": "instant"},
                              "source": CALAMITY_MANTLE, "riders": [] if runtime else ["The Concentration/no-Concentration duration augments are not modeled; the "
                                        "aura always lasts until the start of your next turn."]}, "expected_damage": 0})
    pulse = ActionDefinition(
        source_definition_id=f"action:typed.{short}.calamity_mantle.pulse", display_name="Calamity Mantle: Pulse",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "destruction_calamity_mantle_pulse"}], "numbers": numbers,
                              "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": _blast_hit_average(numbers), "player_only": not runtime, "target_requires_condition": MANTLE_ACTIVE})
    if not runtime:
        return [activate, pulse]
    prolonged = activate.model_copy(deep=True, update={
        "source_definition_id": activate.source_definition_id + ".minute",
        "display_name": "Calamity Mantle (1 CP, Concentration)", "costs": ((_pool(info), 1),)})
    prolonged.parameters["typed"]["effects"][0]["minute"] = 1
    prolonged.parameters["typed"]["duration"] = {"kind": "minutes", "amount": 1, "concentration": True}
    release = ActionDefinition(
        source_definition_id=activate.source_definition_id + ".release",
        display_name="Calamity Mantle: Remove Concentration (2 CP)", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((_pool(info), 2),),
        parameters={"typed": {"effects": [{"type": "destruction_mantle_release"}], "numbers": numbers,
                    "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0,
                    "target_requires_condition": MANTLE_ACTIVE,
                    "description": "Spend 2 cultivation points on your turn to keep your active Mantle for its remaining duration without Concentration. No Action is used."})
    activate.parameters["description"] = "Use an Action to surround yourself with a 10-foot aura for one round. Choose the Blast Type and Deepen before activation; later pulses keep those choices."
    prolonged.parameters["description"] = "Spend 1 cultivation point and an Action to keep your 10-foot aura for up to one minute with Concentration. Later pulses keep the Blast Type, dice and save chosen at activation."
    pulse.parameters["description"] = "Use a Bonus Action to blast every other creature within 10 feet, including allies. Each makes a Dexterity saving throw; a successful save negates a free blast or halves a paid blast and prevents its rider."
    return [activate, prolonged, pulse, release]


@effect("destruction_calamity_mantle_activate")
def mantle_activate(ctx: Any, eff: dict[str, Any]) -> None:
    if eff.get("runtime"):
        from factory_authoring.typed_mechanics import dice_for_cl
        from .effect_durations import round_token
        paid = prepare_release(ctx)
        old = next((c for c in ctx.actor.conditions.values() if c.condition_id == MANTLE_ACTIVE and c.data.get("runtime")), None)
        if old is not None:
            end_mantle_concentration(ctx.engine, ctx.actor, old.data.get("concentration_started_sequence"))
        data = {"runtime": 1, "label": "Calamity Mantle: every other creature within 10 feet makes a Dexterity save when you pulse",
                "type_id": current_type_id(ctx.engine, ctx.actor), "final_cp": paid,
                "dice_count": (1 + int(ctx.numbers["cl"]) // 2 if ctx.damage_cache.get("destruction_deepened")
                               else (dice_for_cl(_DICE_BY_CL, ctx.numbers.get("cl")) or {"count": 1})["count"]),
                "save_dc": int(ctx.numbers.get("save_dc") or 10),
                "expiry": round_token(ctx.engine, 10 if eff.get("minute") else 1)}
        if eff.get("minute") and ctx.actor.concentration is not None:
            data["concentration_started_sequence"] = ctx.actor.concentration.started_sequence
        ctx.engine._remove_condition(ctx.actor, MANTLE_ACTIVE, ctx.source)
        ctx.engine._apply_condition(ctx.actor, MANTLE_ACTIVE, ctx.source, ctx.actor.entity_id,
            expires_on="CONCENTRATION_END" if eff.get("minute") else data["expiry"], data=data)
        return
    ctx.engine._remove_condition(ctx.actor, MANTLE_ACTIVE, ctx.source)
    # "The Blast Type and all other parameters are selected when you activate the Calamity Mantle and cannot be
    # changed while it remains active": locked in now, read back by the Pulse below instead of the live choice.
    ctx.engine._apply_condition(ctx.actor, MANTLE_ACTIVE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Calamity Mantle active", "type_id": current_type_id(ctx.engine, ctx.actor)})


@effect("destruction_calamity_mantle_pulse")
def mantle_pulse(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..spatial_areas import actor_in_area
    from contextlib import nullcontext

    active = next(((c.data or {}) for c in ctx.actor.conditions.values() if c.condition_id == MANTLE_ACTIVE), None)
    if active is None:
        ctx.rider("Calamity Mantle is not active.")
        return
    targets = [row for row in ctx.engine.state.actors.values() if row.active and row.entity_id != ctx.actor.entity_id
              and (active.get("runtime") or row.team_id != ctx.actor.team_id)
              and ctx.engine._distance_actor_to_actor(ctx.actor, row) <= 10
              and (not active.get("runtime") or actor_in_area(ctx.engine, row, ctx.actor.position, ctx.actor.position,
                   {"shape": "sphere", "size_ft": 10}))]
    with te.simultaneous(ctx, targets) if active.get("runtime") else nullcontext():
        for subject in targets:
            if ctx.engine.state.terminal_result is not None:
                break
            sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
            if active.get("runtime"):
                from dataclasses import replace
                sub = replace(sub, typed={**ctx.typed, "destruction_frozen_type": active.get("type_id"),
                                          "numbers": {**ctx.numbers, "save_dc": active["save_dc"]}})
                te.run_effects(sub, [{"type": "destruction_shape_save", "ability": "dex", "locked_cp": active["final_cp"],
                    "on_fail": [{"type": "destructive_blast_damage", "locked_type_id": active.get("type_id"),
                                 "locked_dice_count": active["dice_count"], "damage_required": True}], "on_success": []}])
                continue
            te.run_effects(sub, [{"type": "save", "ability": "dex",
                                 "on_fail": [{"type": "destructive_blast_damage", "locked_type_id": active.get("type_id")}], "on_success": []}])


# ------------------------------------------------------------------ Ruin-Binding Tether: locked Blast Type + Pulse
@effect("destruction_tether_lock")
def tether_lock(ctx: Any, eff: dict[str, Any]) -> None:
    """"The Blast Type and all other parameters are selected when the tether is created and cannot be changed
    while it remains active": placed in the base action's own on_hit (after destructive_blast_damage), so Pulse
    (below) keeps re-releasing whichever type actually hit, not the live sticky choice."""
    ctx.engine._remove_condition(ctx.actor, TETHER_TYPE, ctx.source)
    data = {"type_id": current_type_id(ctx.engine, ctx.actor)}
    if eff.get("bind_target") and ctx.target is not None:
        from factory_authoring.typed_mechanics import dice_for_cl

        cl = int(ctx.numbers.get("cl") or 1)
        data.update(target_id=ctx.target.entity_id, dice_count=1 + cl // 2 if ctx.damage_cache.get("destruction_deepened")
                    else (dice_for_cl(_DICE_BY_CL, cl) or {"count": 1})["count"],
                    save_dc=int(ctx.numbers.get("save_dc") or 10), final_cp=prepare_release(ctx))
    ctx.engine._apply_condition(ctx.actor, TETHER_TYPE, ctx.source, ctx.actor.entity_id, expires_on="CONCENTRATION_END", data=data)


@hook("compile_actions")
def tether_pulse_button(info: dict[str, Any]) -> list[Any] | None:
    if RUIN_BINDING_TETHER not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    bound = any(e.get("bind_target") for row in (info.get("mechanics", {}).get(RUIN_BINDING_TETHER, {}).get("effects") or [])
                for e in row.get("on_hit") or [])
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.ruin_binding_tether.pulse", display_name="Ruin-Binding Tether: Pulse",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
        parameters={"typed": {"effects": [{"type": "destruction_tether_pulse",
                                          **({"bound_target": True} if bound else {})}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "range_ft": 30,
                              "riders": [] if bound else ["Use this only against the creature you tethered this fight; the table does not track or check that."]},
                    **({"description": "Spend your Bonus Action, with no additional cultivation energy, to release the stored blast "
                       "against the creature you tethered within 30 feet. It makes a Dexterity save; success halves damage only if "
                       "the original blast's final cost was at least 1 CP. Ends when your Concentration ends."} if bound else {}),
                    "expected_damage": _blast_hit_average(info["numbers"]), "player_only": not bound})]


@effect("destruction_tether_pulse")
def tether_pulse(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    active = next(((c.data or {}) for c in ctx.actor.conditions.values() if c.condition_id == TETHER_TYPE), None)
    if active is None:
        ctx.rider("Ruin-Binding Tether is not active.")
        return
    subject = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if subject is None:
        return
    if eff.get("bound_target"):
        if subject.entity_id != active.get("target_id"):
            return
        from dataclasses import replace

        sub = replace(ctx, targets=[subject], target=subject,
                      typed={**ctx.typed, "numbers": {**ctx.numbers, "save_dc": active["save_dc"]}})
        te.run_effects(sub, [{"type": "destruction_shape_save", "ability": "dex", "locked_cp": active["final_cp"],
                             "on_fail": [{"type": "destructive_blast_damage", "locked_type_id": active.get("type_id"), "damage_required": True,
                                          "locked_dice_count": active["dice_count"]}], "on_success": []}])
        return
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
    te.run_effects(sub, [{"type": "save", "ability": "dex",
                         "on_fail": [{"type": "destructive_blast_damage", "locked_type_id": active.get("type_id")}], "on_success": []}])


@hook("candidate_allowed")
def bound_tether_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not any(row.get("type") == "destruction_tether_pulse" and row.get("bound_target")
                                 for row in ((action.parameters.get("typed") or {}).get("effects") or [])):
        return None
    active = next(((c.data or {}) for c in actor.conditions.values() if c.condition_id == TETHER_TYPE), None)
    return bool(active and candidate.target_ids == (active.get("target_id"),))


# ------------------------------------------------------------------ Ruin-Crossing Step: the self-teleport half of its line
@effect("destruction_ruin_crossing_teleport")
def ruin_crossing_teleport(ctx: Any, eff: dict[str, Any]) -> None:
    """The area save half of Ruin-Crossing Step is plain reviewed_final JSON (a "line" area); this is only the
    "you appear in the final square of the line" half, which needs the aim point (``ctx.intent.destination``, not
    ``ctx.destination`` -- that field is only ever set for a SELF-target-kind action: typed_executor.resolve_typed).
    Reuses typed_executor._teleport, the same safe "place the user, no path, no opportunity attacks" helper
    block_movement's own teleport branch calls."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position

    destination = getattr(ctx.intent, "destination", None)
    if destination is None:
        return
    if eff.get("choose_landing"):
        crossing_landing(ctx, destination, bool(eff.get("anywhere")))
        return
    occupied = ctx.engine._occupied_cells_except(ctx.actor.entity_id)
    footprint = ctx.engine._footprint(ctx.actor)
    if ctx.engine.grid.placement_legal(destination, footprint=footprint, occupied_cells=occupied):
        te._teleport(ctx, destination)
        return
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            x, y = max(0, destination.x + dx), max(0, destination.y + dy)
            if not ctx.engine.grid.in_bounds((x, y)):
                continue
            candidate = Position(x=x, y=y)
            if ctx.engine.grid.placement_legal(candidate, footprint=footprint, occupied_cells=occupied):
                te._teleport(ctx, candidate)
                return
    ctx.rider("Ruin-Crossing Step: no legal space to land in near the end of the line.")


@effect("destruction_mantle_release")
def mantle_release(ctx: Any, eff: dict[str, Any]) -> None:
    from .retained_updates import record_instance_update
    row = next((c for c in ctx.actor.conditions.values() if c.condition_id == MANTLE_ACTIVE
                and c.data.get("runtime") and c.expires_on == "CONCENTRATION_END"), None)
    if row is None:
        return
    # Change the expiry first: ending this exact concentration must retain the aura.
    row.expires_on = row.data["expiry"]
    started = row.data.pop("concentration_started_sequence", None)
    record_instance_update(ctx.engine, ctx.actor, "condition", row.instance_id, row)
    end_mantle_concentration(ctx.engine, ctx.actor, started)


def end_mantle_concentration(engine: Any, actor: Any, started: Any) -> None:
    from .. import concentration
    if started is None:
        return
    if actor.concentration is not None and actor.concentration.started_sequence == started:
        engine._end_concentration(actor, "DURATION_ENDED")
    else:
        for key, held in concentration.held(actor):
            if held.started_sequence == started:
                concentration.end_held(engine, actor, key, "DURATION_ENDED")
                break


@hook("turn_start")
def mantle_deadline(engine: Any, actor: Any) -> None:
    from .effect_durations import due
    for holder in list(engine.state.actors.values()):
        for row in list(holder.conditions.values()):
            if row.condition_id == MANTLE_ACTIVE and row.data.get("runtime") and due(engine, row.data.get("expiry")):
                end_mantle_concentration(engine, holder, row.data.get("concentration_started_sequence"))
                engine._remove_condition(holder, MANTLE_ACTIVE, row.source_definition_id)


@hook("candidate_allowed")
def mantle_release_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    if any(e.get("type") == "destruction_mantle_release" for e in action.parameters.get("typed", {}).get("effects", [])):
        return any(c.condition_id == MANTLE_ACTIVE and c.data.get("runtime") and c.expires_on == "CONCENTRATION_END"
                   for c in actor.conditions.values())
    return None


RUIN_CROSSING = "tianxia.talent.destruction.ruin_crossing_step"


@hook("compile_actions")
def crossing_augments(info: dict[str, Any]) -> list[Any] | None:
    if RUIN_CROSSING not in info["owned_ids"] or not _declared(info, RUIN_CROSSING, "choose_landing"):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from copy import deepcopy
    out = []
    for length in (10, 15, 20, 25, 30, 35, 40):
        for anywhere in (False, True):
            if length == 10 and not anywhere:
                continue
            cost = int(length > 10) + int(anywhere)
            effects = deepcopy(info["mechanics"][RUIN_CROSSING]["effects"])
            effects[-1]["anywhere"] = anywhere
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.crossing.{length}.{int(anywhere)}",
                display_name=f"Ruin-Crossing Step: {length} feet" + (", Choose Landing" if anywhere else "") + f" ({cost} CP)",
                owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL",
                range_ft=length, costs=((_pool(info), cost),),
                parameters={"typed": {"effects": effects, "numbers": info["numbers"], "source": RUIN_CROSSING,
                    "sphere": "tianxia.sphere.destruction", "duration": {"kind": "instant"}, "riders": [],
                    "area": {"shape": "line", "size_ft": length, "width_ft": 5, "recipients": "hostile",
                             "include_self": False, "exclude_self": True, "harmful_recipients": "hostile"}, "range_ft": length},
                    "expected_damage": _blast_hit_average(info["numbers"]),
                    "description": f"Release a {length}-foot line of destruction, then teleport " +
                       ("to a legal square you choose along it." if anywhere else "to its final square, or a nearest legal square you choose.")}))
    return out


def crossing_landing(ctx: Any, aim: Any, anywhere: bool) -> None:
    from .. import typed_executor as te
    from . import needle
    from ..gate2_runtime_models import Position
    vertex = ctx.actor.position
    area = ctx.typed.get("area") or {}
    dx, dy, dz = aim.x - vertex.x, aim.y - vertex.y, aim.z - vertex.z
    if not (dx or dy or dz):
        return
    cells = te.area_cells(ctx.engine, vertex, aim, area, include_altitude=bool(dz))
    # The aim binds direction, not distance: project to the printed line's last square.
    end = max(cells, key=lambda c: ((c.x-vertex.x)*dx + (c.y-vertex.y)*dy + (c.z-vertex.z)*dz, c.z, c.y, c.x), default=aim)
    occupied = ctx.engine._occupied_cells_except(ctx.actor.entity_id)
    def legal(cell):
        return ctx.engine.grid.placement_legal(cell, footprint=ctx.engine._footprint(ctx.actor), occupied_cells=occupied)
    if anywhere:
        choices = [c for c in cells if legal(c)]
    elif legal(end):
        choices = [end]
    else:
        choices = [Position(x=x, y=y, z=end.z) for y in range(ctx.engine.grid.height) for x in range(ctx.engine.grid.width)
                   if legal(Position(x=x,y=y,z=end.z)) and ctx.engine._line_of_sight_actor_to_cell(ctx.actor, Position(x=x,y=y,z=end.z))]
        if choices:
            distance = min(ctx.engine.grid.distance_ft(end, c) for c in choices)
            choices = [c for c in choices if ctx.engine.grid.distance_ft(end, c) == distance]
    if not choices:
        return
    choices.sort(key=lambda c: (c.z, c.y, c.x))
    def option_id(cell):
        return needle.cell_id(cell, include_altitude=bool(dz))
    ids = [option_id(c) for c in choices]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "crossing_landing", ctx.source), ctx.actor,
        needle.CHOICE + "teleport_destination", ids,
        labels={option_id(c): f"Appear at {c.x},{c.y}" + (f", {c.z * ctx.engine.grid.square_size_ft} feet above ground" if dz or c.z else "") for c in choices}, preferred=ids[:1],
        prompt="Ruin-Crossing Step: choose your legal landing square. Teleporting uses no movement and provokes no Opportunity Attacks.",
        allow_decline=False, name="Ruin-Crossing Step landing")
    if picked:
        te._teleport(ctx, next(c for c in choices if option_id(c) == picked[0]))
