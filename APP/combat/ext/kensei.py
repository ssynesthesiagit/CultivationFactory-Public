"""Kensei's source-owned hit, initiative, stance and impairment consumers.

Sealed compilation retains each attack's legal ability options. Native fight
setup resolves Sword Draws before turn one. Equipment uses the public possession
and grip contracts; hit riders never create another weapon or object interaction.
Free movement resolves at attack completion, after attached damage and riders.
No row/state/compiled attack provenance leaves these hooks inert.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.kensei.feature."
BLADE_FIST = PREFIX + "blade_fist"
SEVERING_PALM = PREFIX + "severing_palm"
FLOWING, SAINT = "flowing_blade_stance", "sword_saint_incarnation"
STAMINA = "resource:core.stamina"
FAMILY = PREFIX.removesuffix(".feature.")
LEVELS = {PREFIX + key: level for key, level in (
    ("blade_fist", 3), ("sword_draws_before_thought", 6),
    (FLOWING, 10), ("severing_palm", 14), (SAINT, 18))}
BLADE_CHOICE = "condition:typed.blade_fist_choice"
SEVER_CHOICE = "condition:typed.severing_palm_choice"
ARM = "condition:typed.severing_arm"
FIRST_ATTACK = "condition:typed.sword_draws_first_attack"
BLADE_OPTIONS = {"damage": "Slashing Damage", "speed": "Speed -5", "reactions": "Deny Reactions", "draw": "Draw/Stow Blade"}
SEVER_OPTIONS = {"arm": "Arm", "leg": "Leg", "breath": "Breath", "flow": "Flow", "guard": "Guard"}


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    from .body_modes_scene_resources import available
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("kind") == kind and row.get("block") in ("kensei", "path_rider")
            and available(engine, actor, row.get("feature_id", ""), LEVELS.get(row.get("feature_id"), 0))]


def _state(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    if actor is None:
        return False
    held = active(engine, actor, name)
    action = engine.action_catalog.get(held.source_definition_id) if held is not None else None
    return bool(held is not None and held.source_actor_id == actor.entity_id and action is not None
                and action.owner_id == actor.entity_id
                and (action.parameters.get("typed") or {}).get("source") == PREFIX + name)


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


def _blade_or_unarmed(ctx: Any, kind: str | None = None) -> bool:
    from .integrated_weapons import recorded_integration
    from ..weapon_delivery import delivery_kind

    attack = getattr(ctx, "attack_effect", None) or next(
        (e for e in ctx.typed.get("effects") or [] if e.get("type") == "attack"), {})
    delivered = kind or delivery_kind(ctx.typed, attack, ctx.action.parameters)
    return delivered == "unarmed" or (delivered == "weapon" and
        recorded_integration(ctx.engine, ctx.actor, ctx.typed, "blade"))


def _standing(actor: Any, condition_id: str, default: str) -> str:
    return next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == condition_id), default)


@hook("compile_block")
def kensei_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "kensei":
        return None
    return [{**row, "block": "kensei", "kind": spec.get("kind")}]


@hook("compile_actions")
def kensei_choices(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, short = info["owned_ids"], info["short"]
    out = []
    if BLADE_FIST in owned:
        for key, label in BLADE_OPTIONS.items():
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.blade_fist.{key}", display_name=f"Blade Fist: {label}",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "blade_fist_choice", "choice": key}], "numbers": info["numbers"],
                                      "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}))
        out.extend(_dexterity_fist(info))
    if SEVERING_PALM in owned:
        for key, label in SEVER_OPTIONS.items():
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.severing_palm.{key}", display_name=f"Severing Palm: {label}",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "severing_palm_choice", "choice": key}], "numbers": info["numbers"],
                                      "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}))
    return out or None


def _dexterity_fist(info: dict[str, Any]) -> list[Any]:
    """Keep the Dexterity menu alias; actual attacks retain every legal ability choice."""
    import copy

    from ..gate2_runtime_models import EconomyKind

    dex = int((info.get("mods") or {}).get("DEX", 0) or 0)
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        weapon = typed.get("weapon") or {}
        if base.economy != EconomyKind.ACTION or ".natural." not in base.source_definition_id or "#" in base.source_definition_id or not weapon:
            continue
        if (base.parameters or {}).get("player_only") or not any(
                e.get("type") == "attack" and e.get("attack_kind") == "unarmed" for e in typed.get("effects") or []):
            continue
        original = int(weapon.get("ability_modifier", (info.get("mods") or {}).get(weapon.get("ability"), 0)))
        swap = copy.deepcopy(typed)
        swap["numbers"]["attack_bonus"] = int(typed["numbers"].get("attack_bonus") or 0) - original + dex
        swap["weapon"]["damage"]["modifier"] = int(weapon["damage"].get("modifier") or 0) - original + dex
        swap["weapon"].update(ability="DEX", ability_modifier=dex)
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#blade_fist_dex",
                                           "display_name": base.display_name + " (Dexterity)", "parameters": {**base.parameters, "typed": swap}}))
    return out


# ------------------------------------------------------------------------------------------------ Blade Fist
@effect("blade_fist_choice")
def blade_fist_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, BLADE_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, BLADE_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Blade Fist: {BLADE_OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def blade_fist(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind not in ("unarmed", "weapon") or actor.turn_flags.get("_round_blade_fist") == _stamp(engine) or not _rows(engine, actor, "blade_fist") or not _blade_or_unarmed(ctx, kind):
        return
    if target is None:
        return
    actor.turn_flags["_round_blade_fist"] = _stamp(engine)
    actor.turn_flags["blade_fist"] = True
    from .needle import ask, checkpoint_id

    labels = {"damage": f"+{int(ctx.numbers.get("pb") or actor.proficiency_bonus)} Slashing damage", "speed": f"{target.display_name}'s Speed -5 until the start of your next turn",
              "reactions": f"{target.display_name} cannot take Reactions until the start of its next turn",
              "draw": "Draw or stow one available Blade weapon; no extra interaction"}
    standing = _standing(actor, BLADE_CHOICE, "damage")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "blade_fist", target.entity_id), actor, "choice:needle.blade_fist", list(labels),
                 labels=labels, preferred=[standing] if standing in labels else None, target_id=target.entity_id, name="Blade Fist",
                 prompt=f"Blade Fist: {ctx.action.display_name} hit {target.display_name}. Choose one.")
    choice = picked[0] if picked else (standing if standing in labels else "damage")
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}).with_source(BLADE_FIST)
    if choice == "damage":
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": 0, "formula": "pb",
                                          "damage_types": ["slashing"], "evidence": "Blade Fist: Proficiency Bonus Slashing damage"}])
    elif choice == "speed":
        typed_executor.run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -5, "source_owned": True,
                                          "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Blade Fist: Speed -5"}])
    elif choice == "reactions":
        typed_executor.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target",
                                          "expires_on": "START_OF_TARGET_NEXT_TURN", "evidence": "Blade Fist: deny Reactions"}])

    elif choice == "draw":
        _readiness(sub, allow_stow=True)


# ------------------------------------------------------------------------------------------------ Severing Palm
@effect("severing_palm_choice")
def severing_palm_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, SEVER_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SEVER_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Severing Palm: {SEVER_OPTIONS.get(str(eff.get('choice')), '')}"})


def _severing_context(ctx: Any, target: Any, area: str) -> Any:
    """A Context whose conditions and modifiers carry ``<Severing Palm>#<area>`` (exact refresh of the same area later)."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=f"{SEVERING_PALM}#{area}", display_name=f"Severing Palm ({SEVER_OPTIONS[area]})",
                              owner_id=ctx.actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    return te.Context(ctx.engine, ctx.actor, action, ctx.intent, {**ctx.typed, "effects": []}, [target], target, {})


def _clear_area(engine: Any, owner: Any, target: Any, area: str) -> None:
    source = f"{SEVERING_PALM}#{area}"
    before=engine._effective_speed(target)
    from .benefit_suppression import SUPPRESSED,cancel
    for marker in list(target.conditions.values()):
        model=marker.data.get("model") or {}
        if marker.condition_id==SUPPRESSED and marker.source_definition_id==FAMILY+"#realm_dormancy" and model.get("source_definition_id")==source and model.get("source_actor_id")==owner.entity_id:
            cancel(engine,target,"condition:"+marker.instance_id,source)
    for iid, held in list(target.conditions.items()):
        if held.source_definition_id == source and held.source_actor_id == owner.entity_id:
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REFRESHED"})
    for mid, held in list(target.modifiers.items()):
        if held.source_definition_id == source and held.source_actor_id == owner.entity_id:
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REFRESHED"})
    delta=engine._effective_speed(target)-before
    if delta:
        from ..movement_budget import speed_changed
        speed_changed(engine,target,delta,source,reason="named impairment refresh")


@hook("after_hit_choice")
def severing_palm(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind not in ("unarmed", "weapon") or target is None or not target.active:
        return
    if actor.turn_flags.get("_round_severing_palm") == _stamp(engine) or not _rows(engine, actor, "severing_palm") or not _blade_or_unarmed(ctx, kind):
        return
    if actor.resources.get(STAMINA, 0) < 4:
        return
    from .effect_durations import token
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    standing = _standing(actor, SEVER_CHOICE, "arm")
    labels = {"arm": "Arm: Disadvantage on its weapon attacks", "leg": "Leg: its Speed is halved", "breath": "Breath: no Reactions",
              "flow": "Flow: Disadvantage on Concentration saves and Cultivation Checks to maintain techniques", "guard": "Guard: AC -2 (-1 on a success)"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "severing_palm", target.entity_id), actor, "choice:needle.severing_palm", list(labels),
                 labels=labels, preferred=[standing] if standing in labels else None, allow_decline=True, target_id=target.entity_id,
                 name="Severing Palm", feature_id=SEVERING_PALM,
                 prompt=f"Severing Palm after {ctx.action.display_name} hits {target.display_name}: spend 4 Stamina "
                        "and choose an effect. The target makes a Constitution save. On success it lasts until the "
                        "start of your next turn; on failure Arm, Leg, Breath and Flow last until the end of your "
                        "next turn, and Guard until its start.",
                 prompt_context={**action_context(engine, actor, ctx.source, target), "cost": "4", "paying_pool": STAMINA})
    if not picked or picked[0] not in labels:
        return
    area = picked[0]
    actor.turn_flags["_round_severing_palm"] = _stamp(engine)
    actor.turn_flags["severing_palm"] = True
    paid_start=len(engine.events)
    engine._spend_resource(actor, STAMINA, 4, SEVERING_PALM)
    from ..activation_payments import reaction_completed
    from .body_modes_scene_resources import available
    if not reaction_completed(engine,actor,SEVERING_PALM,consumes_reaction=False) or not available(engine,actor,SEVERING_PALM,14):return
    long_end = f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}" if engine.state.current_actor_id == actor.entity_id else token("end", actor.entity_id, int(actor.turns_started) + 1)
    short = "START_OF_SOURCE_NEXT_TURN"

    def rows(until: str, guard: int) -> list[dict[str, Any]]:
        return {"arm": [{"type": "severing_arm", "expires_on": until}],
                "leg": [{"type": "speed", "applies_to": "target", "halved": True, "source_owned": True, "expires_on": until}],
                "breath": [{"type": "reaction_denied", "applies_to": "target", "expires_on": until}],
                "flow": [{"type": "disadvantage", "applies_to": "target", "on": "Concentration saving throws", "expires_on": until},
                         {"type": "severing_flow", "expires_on": until}],
                "guard": [{"type": "ac_bonus", "applies_to": "target", "flat": guard, "source_owned": True, "expires_on": short}]}[area]
    from .. import typed_executor

    sub = _severing_context(ctx, target, area)
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target", "on_fail": [{"type":"severing_impairment","area":area,"effects":rows(long_end,-2)}],
                                      "on_success": [{"type":"severing_impairment","area":area,"effects":rows(short,-1)}],
                                      "evidence": "Severing Palm: Constitution saving throw"}])
    from .body_modes_scene_resources import complete_native_activation
    complete_native_activation(engine,actor,SEVERING_PALM,paid_start)



@effect("severing_arm")
def severing_arm(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is not None and target.active:
        ctx.engine._apply_condition(target, ARM, ctx.source, ctx.actor.entity_id, expires_on=str(row.get("expires_on") or "START_OF_SOURCE_NEXT_TURN"),
                                    data={"label": "Severing Palm (Arm): Disadvantage on weapon attacks"})


@hook("attack_mode")
def kensei_attack_modes(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is not None and (_state(engine, target, SAINT)) and (ctx.typed.get("opportunity_of") or getattr(engine, "_typed_oa_attacker", None) == actor.entity_id):
        return "DISADVANTAGE"  # Sword Saint: Opportunity Attacks against you have Disadvantage
    from .weapon_hits import is_weapon_hit
    attack = getattr(ctx, "attack_effect", None) or next((e for e in ctx.typed.get("effects") or [] if e.get("type") == "attack"), {})
    if is_weapon_hit(ctx, attack) and any(c.condition_id == ARM for c in actor.conditions.values()):
        return "DISADVANTAGE"  # Severing Palm (Arm): its weapon attacks
    return None


@hook("attack_mode")
def sword_draws_first_attack(ctx: Any, target: Any) -> str | None:
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == FIRST_ATTACK), None)
    if held is not None and target is not None and int(ctx.engine.state.round_number) == 1:
        return "ADVANTAGE"
    return None


@hook("attack_roll_finished")
def sword_draws_consume_first_attack(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    if not roll_id:
        return
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == FIRST_ATTACK), None)
    if held is not None:
        ctx.actor.conditions.pop(held.instance_id, None)
        ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "sword_draws_before_thought", actor_id=ctx.actor.entity_id,
            target_ids=(ctx.actor.entity_id,), payload={"condition_id": FIRST_ATTACK, "instance_id": held.instance_id, "reason": "CONSUMED"})


# ------------------------------------------------------------------------------------ Flowing Blade Stance, Sword Saint
@hook("attack_damage_types")
def stance_types(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    if not (_state(ctx.engine, ctx.actor, FLOWING) or _state(ctx.engine, ctx.actor, SAINT)) or not _blade_or_unarmed(ctx):
        return None
    return list(dict.fromkeys([*(str(k).upper() for k in kinds or []), "FORCE", "SLASHING"]))


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> bool:
    from .needle import ask, checkpoint_id, cell_id
    from .. import granted_movement, flight

    spatial = bool(mover.position.z or flight.profile(ctx.engine, mover).speed_ft)
    allowances = feet if isinstance(feet, dict) else {None: feet}
    paths = {}
    for movement_mode, allowance in allowances.items():
        for cell, (path, cost, mode) in granted_movement.routes(ctx.engine, mover, allowance, mode=movement_mode).items():
            key = cell_id(cell, include_altitude=spatial)
            paths[key] = (path, mode)
    if not paths:
        return False
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "kensei_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        path, mode = paths[picked[0]]
        source = PREFIX + (FLOWING if choice_id.endswith("flowing_blade_step") else "sword_draws_before_thought")
        return bool(granted_movement.resolve_path(ctx.engine, mover, path, source, feet=feet, intent=ctx.intent,
                                     provokes=False, mode=mode))
    return False


@hook("after_hit")
def stance_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _blade_or_unarmed(ctx, kind):
        return
    if _state(engine, actor, SAINT) and target.active and actor.turn_flags.get("_round_sword_saint_hit") != _stamp(engine):
        from .needle import ask,checkpoint_id
        selected=ask(engine,ctx.intent,checkpoint_id(engine,'sword_saint_hit_type',target.entity_id),actor,
            'choice:needle.sword_saint_hit_type',['FORCE','SLASHING'],allow_decline=True,
            labels={kind:'Additional 3d8 '+kind.title()+' damage' for kind in ('FORCE','SLASHING')},
            name='Sword Saint Incarnation',feature_id=PREFIX+SAINT,target_id=target.entity_id,
            prompt='Add 3d8 Force or Slashing to this eligible hit, once this turn, with no extra cost? Declining keeps this turn’s use.')
        if not selected:return
        actor.turn_flags["_round_sword_saint_hit"] = _stamp(engine)
        from .. import typed_executor as te

        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed,"kensei_persistent_numbers":1,"kensei_hit_damage_type":selected[0],
            "numbers":_saint_numbers(engine,actor,ctx.numbers)}, damage_cache={}).with_source(PREFIX + SAINT + "#hit"),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["force", "slashing"],
                         "evidence": "Sword Saint Incarnation: once per turn + 3d8"}])


@hook("attack_damage_final")
def flowing_step(engine: Any, actor: Any, target: Any, provenance: Any, intent: Any) -> None:
    if actor is None or target is None or not actor.active or not _state(engine, actor, FLOWING):
        return
    from ..typed_executor import Context
    action = engine.action_catalog.get(provenance.source_id)
    if action is None:
        return
    ctx = Context(engine, actor, action, intent, action.parameters.get("typed") or {}, [target], target, {})
    kind = provenance.kind if provenance.kind in ("unarmed", "weapon") else None
    if not _blade_or_unarmed(ctx, kind) or actor.turn_flags.get("_round_flowing_step") == _stamp(engine):
        return
    if _move(ctx, actor, 5, "choice:needle.flowing_blade_step", "Flowing Blade Stance"):
        actor.turn_flags["_round_flowing_step"] = _stamp(engine)


def _strikes(engine: Any, actor: Any, target: Any) -> dict[str, Any]:
    """The fighter's unarmed and Blade attack actions that reach ``target``."""
    from .integrated_weapons import recorded_integration
    from .hand_occupancy import weapon_allowed
    from .reach_bonus import current_reach
    from ..attack_notifications import can_strike
    from ..target_knowledge import knowledge
    from ..targeting import line_of_effect

    if not can_strike(actor):
        return {}

    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or str(getattr(action.economy, "value", action.economy)) != "ACTION" or typed.get("range_ft"):
            continue
        if action.costs or action.concentration:
            continue
        rule = (action.parameters or {}).get("reach_bonus") or {}
        if rule and rule.get("menu_variant") is not True:
            continue
        if (action.parameters or {}).get("player_only") or ("#" in action.source_definition_id
                and "#integrated" not in action.source_definition_id and not rule.get("menu_variant")):
            continue
        attacks = [e for e in typed.get("effects") or [] if e.get("type") == "attack"]
        if not attacks or not (any(e.get("attack_kind") == "unarmed" for e in attacks)
                               or recorded_integration(engine, actor, typed, "blade")):
            continue
        if weapon_allowed(engine, actor, action) is False:
            continue
        known=knowledge(engine,actor,target,action)
        if known is None:continue
        aim=target.model_copy(update={"position":known.position})
        distance = engine._distance_actor_to_actor(actor, aim)
        if rule:
            base = engine.action_catalog.get(rule.get("base"))
            if base is None or distance <= int(base.range_ft or 5):
                continue
        elif distance > int(action.range_ft or 5):
            continue
        if (distance <= current_reach(engine, actor, action)
                and line_of_effect(engine,actor,target=aim)):
            out[action.source_definition_id] = action
    return out


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, *, reaction_window: int | None = None) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    from ..target_knowledge import attack_aim
    from .granted_attacks import depth
    metadata={} if reaction_window is None else {'kensei_flowing_reaction':{
        'window':reaction_window,'depth':depth(engine)+1,'actor_id':actor.entity_id,
        'action':action.source_definition_id,'attacker':target.entity_id}}
    with attack_aim(engine,actor,target,action):
        te.run_effects(te.Context(engine, actor, action, intent, {**typed, **metadata, "effects": [attack], "granted_attack": True, "attack_action": False}, [target], target, {}), [attack])


def _pick_strike(engine: Any, intent: Any, actor: Any, target: Any, choice_id: str, prompt: str, *, decline: bool) -> Any:
    from .needle import ask, checkpoint_id

    strikes = _strikes(engine, actor, target)
    if not strikes:
        return None
    picked = ask(engine, intent, checkpoint_id(engine, "kensei_strike", target.entity_id), actor, choice_id, list(strikes),
                 labels={k: a.display_name for k, a in strikes.items()}, allow_decline=decline, target_id=target.entity_id, prompt=prompt)
    return strikes.get(picked[0]) if picked else None


@hook("after_miss")
def flowing_answer(ctx: Any, target: Any) -> None:
    """Flowing Blade Stance: a melee attack by a creature within your reach misses you -> your Reaction for one attack (asked)."""
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or not _state(engine, target, FLOWING):
        return
    if ctx.typed.get("range_ft") or ctx.typed.get("granted_attack") or not attacker.active:
        return
    from ..typed_executor import condition_rules
    from .granted_attacks import allows_root
    from ..typed_reactions import can_use_reaction
    row={"feature_id":PREFIX+FLOWING,"name":"Flowing Blade Stance","reaction":True}
    if not can_use_reaction(engine,target,attacker,row):return

    if not allows_root(engine) or any(rule.get("no_reactions") for rule in condition_rules(target)):
        return
    from ..observer_information import perceived_actor
    known=perceived_actor(engine,target,attacker)
    label=known["name"] if known is not None else "a melee attacker"
    action = _pick_strike(engine, ctx.intent, target, attacker, "choice:needle.flowing_blade_answer",
                          f"Flowing Blade Stance: {label} missed you. Use your Reaction to strike back?", decline=True)
    if action is None:
        return
    from .. import typed_reactions

    with activation(engine, target, PREFIX + FLOWING):
        boundary=len(engine.events)
        typed_reactions.open_reaction(engine,row,target,(attacker.entity_id,),"ATTACK_MISSED")
        typed_reactions.spend_reaction(engine,target,row)
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine,target,PREFIX+FLOWING):return
        if not attacker.active or not _state(engine,target,FLOWING) or action.source_definition_id not in _strikes(engine,target,attacker):
            engine._append_event("PASSIVE_TRIGGERED",PREFIX+FLOWING,actor_id=target.entity_id,
                payload={"log":"Flowing Blade Stance cannot complete its chosen attack after the reaction was used; the attacker or chosen attack is no longer available."})
            return
        window=next(e.sequence for e in engine.events[boundary:] if e.event_type=='REACTION_WINDOW_OPENED'
            and e.actor_id==target.entity_id and e.source_definition_id==PREFIX+FLOWING)
        _granted(engine,target,action,attacker,ctx.intent,reaction_window=window)


# ----------------------------------------------------------------------------------------- Sword Draws Before Thought
@hook("fight_setup_tasks")
def sword_draws_tasks(engine: Any) -> list[dict[str, str]] | None:
    return [{"actor_id": actor.entity_id, "source_id": PREFIX + "sword_draws_before_thought"}
            for actor in engine.state.actors.values() if actor.active and _rows(engine, actor, "sword_draws")
            and not any(str(c.condition_id).endswith(".surprised") for c in actor.conditions.values())
            and not _initiative_consumed(engine, actor)] or None


@hook("fight_setup")
def sword_draws(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    if source_id != PREFIX + "sword_draws_before_thought" or not _rows(engine, actor, "sword_draws"):
        return None
    if actor.turn_flags.get("_round_sword_draws"):
        return True
    with activation(engine, actor, source_id):
        before=_effect_instances(engine)
        result=_sword_draws_choice(engine,actor,intent)
        from .states import context
        from .body_modes_scene_resources import effective_body_cl,effective_body_pb
        ctx=context(engine,actor,source_id,[actor],{'cl':effective_body_cl(engine,actor),'pb':effective_body_pb(engine,actor)}).with_source(source_id)
        _record_created_profiles(ctx,before)
        return result


def _sword_draws_choice(engine: Any, actor: Any, intent: Any) -> bool:
    actor.turn_flags["_round_sword_draws"] = 1
    from .needle import ask, checkpoint_id
    from .states import context

    labels = {"move": "Move up to half your Speed without provoking",
              "strike": "Draw or manifest one available Blade, then one unarmed or integrated Blade attack in reach",
              "ac": "+2 AC until the start of your first turn",
              "advantage": "Advantage on your first attack roll in the first round"}
    picked = ask(engine, intent, checkpoint_id(engine, "sword_draws", actor.entity_id), actor, "choice:needle.sword_draws_before_thought", list(labels),
                 labels=labels, preferred=["advantage"] if "advantage" in labels else None, allow_decline=False, target_id=actor.entity_id,
                 name="Sword Draws Before Thought", prompt="Sword Draws Before Thought: Initiative was rolled. Choose one before the first turn. No action or resource cost.")
    choice = picked[0] if picked else None
    ctx = context(engine, actor, PREFIX + "sword_draws_before_thought", [actor], {"pb": int(actor.proficiency_bonus or 2)}).with_source(PREFIX + "sword_draws_before_thought")
    ctx.intent = intent
    if choice == "move":
        from .. import flight
        profile = flight.profile(engine, actor)
        _move(ctx, actor, {"walk": int(engine._effective_speed(actor)) // 2,
                           "fly": int(profile.speed_ft) // 2,
                           "climb": int(getattr(actor, "climb_speed_ft", 0) or 0) // 2},
              "choice:needle.sword_draws_move", "Sword Draws Before Thought")
    elif choice == "advantage":
        engine._apply_condition(actor, FIRST_ATTACK, PREFIX + "sword_draws_before_thought", actor.entity_id, expires_on="START_OF_SLOT_AT:2:0",
                                data={"label": "Sword Draws Before Thought: Advantage on your first attack roll this round"})
    elif choice == "ac":
        engine._add_modifier(actor, PREFIX + "sword_draws_before_thought", "armor_class", "ADD", 2,
                             "ALL_ATTACKS", expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=actor.entity_id)
    elif choice == "strike":
        if not _readiness(ctx, allow_stow=False):
            return True
        from ..target_knowledge import actors_for
        foes = [a for a in sorted(actors_for(engine, actor), key=lambda a: a.entity_id)
                if a.active and a.entity_id != actor.entity_id and _strikes(engine, actor, a)]
        target = None
        if foes:
            pick = ask(engine, intent, checkpoint_id(engine, "sword_draws_target", actor.entity_id), actor, "choice:needle.sword_draws_target",
                       [a.entity_id for a in foes], labels={a.entity_id: a.display_name for a in foes}, target_id=actor.entity_id,
                       prompt="Sword Draws Before Thought: attack which creature?")
            target = engine.state.actors.get(pick[0]) if pick else None
        if target is not None:
            action = _pick_strike(engine, intent, actor, target, "choice:needle.sword_draws_strike", "Sword Draws Before Thought: which attack?", decline=False)
            if action is not None:
                _granted(engine, actor, action, target, intent)

    return True


@hook("flight")
def saint_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The transformation grants native flight and Hover, independent of walking Speed."""
    if actor.active and _state(engine, actor, SAINT):
        return {"fly_speed_ft": 40, "flight_hover": True}
    return None


@hook("pass_through")
def saint_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    from ..relations import relation, ENEMY
    if mover.active and relation(engine, mover, occupant) == ENEMY and _state(engine, mover, SAINT):
        return "difficult"
    return None


@hook("compile_action")
def blade_fist_ability_profile(action: Any, info: dict[str, Any]) -> Any:
    """Seal legal modifiers once; the ordinary per-strike choice owns selection."""
    import copy
    typed = action.parameters.get("typed") or {}
    source = typed.get("source")
    if source in (PREFIX + SAINT, PREFIX + FLOWING) and source in info["owned_ids"]:
        # Off-turn decisions still belong to the player who owns this state.
        changed = {**typed, "manual_inline_choice": True}
        if not any(e.get("type") == "ac_bonus" for e in typed.get("effects") or []):
            changed["kensei_dynamic_ac"] = 1
        if source == PREFIX + SAINT and not any(e.get("type") == "zone" for e in typed.get("effects") or []):
            # Old immutable catalogs retain their sole historical zone provider.
            changed["kensei_native_reach"] = 1
        return action.model_copy(update={"parameters": {**action.parameters, "typed": changed}})
    if BLADE_FIST not in info["owned_ids"]:
        return None
    from .integrated_weapons import in_group
    weapon = typed.get("weapon")
    attacks = [e for e in typed.get("effects") or [] if e.get("type") == "attack"
               or (e.get("type") == "object_attack" and action.parameters.get("kensei_object_origin"))]
    if not weapon or not attacks:
        return None
    unarmed = any(e.get("attack_kind") == "unarmed" for e in attacks)
    if not unarmed and not in_group(typed, "blade"):
        return None
    changed = copy.deepcopy(typed)
    from .integrated_weapons import integration_sources
    if not unarmed:changed["integration_sources"]=integration_sources(info,typed)
    original_ability = ("CON" if "#integrated_con" in action.source_definition_id else
                        "DEX" if "#integrated_dex" in action.source_definition_id else weapon.get("ability", "STR"))
    changed["weapon"].update(ability=original_ability,
        ability_modifier=int(weapon.get("ability_modifier", info["mods"].get(original_ability, 0)))
        if "#integrated_con" not in action.source_definition_id else int(info["mods"].get("CON", 0)))
    magic = 0 if unarmed else int(typed.get("magic_bonus") or 0)
    if "#integrated_con" in action.source_definition_id:
        changed["numbers"]["attack_bonus"] = int(info["numbers"]["attack_bonus"]) + magic
    allowed = ["STR", "DEX", "CON"] if unarmed else ["DEX", "CON"]
    from ..typed_reactions import rules as block_rules
    extra_tables={feature:dict(block_rules()["features"][feature].get("attacks_by_cl") or {}) for feature in info["owned_ids"]
        if block_rules().get("features",{}).get(feature,{}).get("block")=="extra_attack"}
    changed["kensei_abilities"] = {"finesse_from_blade_fist":int(unarmed and any(row.get("feature_id")==source and row.get("kensei_finesse_source")==BLADE_FIST for row in info.get("passives",[]))),"extra_attack_sources":extra_tables,"options": {a: int(info["mods"].get(a, 0)) for a in allowed},
                                   "cultivation_attack_bonus": int(info["numbers"]["attack_bonus"]) + magic,
                                   "unarmed": int(unarmed),
                                   "source_cl": int(info["numbers"].get("cl") or 1),
                                   "refined": int("tianxia.path.body_refining.feature.refined_iron_fist" in info["owned_ids"]),
                                   "heavenly": int("tianxia.path.body_refining.feature.heavenly_fist" in info["owned_ids"])}
    return action.model_copy(update={"parameters": {**action.parameters, "typed": changed}})


@hook("attack_spec_choice")
def blade_fist_ability_choice(ctx: Any, target: Any, attack: dict[str, Any], spec: dict[str, Any], index: int) -> None:
    held = ctx.typed.get("kensei_abilities")
    if not held or not _rows(ctx.engine, ctx.actor, "blade_fist") or not _blade_or_unarmed(ctx):
        return
    from .attack_abilities import select_strike_ability, resolved_strike_ability
    if resolved_strike_ability(ctx):
        return
    from .needle import ask, checkpoint_id
    names = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution"}
    options = held["options"]
    choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "kensei_ability", target.entity_id, index),
        ctx.actor, "choice:needle.kensei_ability", list(options),
        labels={a: f"{names[a]} for this attack and damage ({n:+d}); "
                + ("attack uses your Cultivation Attack Modifier" if a == "CON" and not held["unarmed"] else "add the ability once")
                for a, n in options.items()},
        preferred=[max(options, key=options.get)], target_id=target.entity_id, name="Blade Fist", feature_id=BLADE_FIST,
        prompt=f"Blade Fist: choose the ability for {ctx.action.display_name} against {target.display_name}. No additional action or Stamina cost.")
    if not choice:
        return
    selected = choice[0]
    select_strike_ability(ctx, spec, selected, options[selected], fixed_unarmed="fixed_damage" in (ctx.typed.get("weapon") or {}))
    if selected == "CON" and not held["unarmed"]:
        spec["attack_bonus"] = held["cultivation_attack_bonus"] + int(ctx.numbers.get("pb") or ctx.actor.proficiency_bonus) - int(ctx.actor.proficiency_bonus)
        spec["typed"]["numbers"]["attack_bonus"] = spec["attack_bonus"]


def _readiness(ctx: Any, *, allow_stow: bool) -> bool:
    """Use existing carried Blade instances and the shared grip transaction."""
    from .weapon_hits import available_weapons
    from .integrated_weapons import in_group, recorded_integration
    from .hand_occupancy import weapon_grips, free_hands, resting_hands
    from .equipment_hands import set_weapon_readiness
    from .needle import ask, checkpoint_id
    ready = weapon_grips(ctx.engine, ctx.actor)
    available = available_weapons(ctx.engine, ctx.actor, include_busy=True)
    options = {}
    if not allow_stow and free_hands(ctx.engine, ctx.actor):
        from .. import carry
        inventory = carry.carrying_of(ctx.engine, ctx.actor.entity_id)
        for weapon in ctx.engine.action_catalog.values():
            key = weapon.source_definition_id
            item = carry.item_of(inventory, weapon_action=key)
            if (weapon.owner_id == ctx.actor.entity_id and key not in available and "#" not in key
                    and item is not None and recorded_integration(ctx.engine, ctx.actor, weapon.parameters.get("typed") or {}, "blade")
                    and len(free_hands(ctx.engine, ctx.actor)) >= resting_hands(weapon)
                    and carry.operation_allowed(ctx.engine, ctx.actor, ctx.actor, item, "recall", ctx.source, require_grant=True)):
                options["manifest:" + key] = (key, True, weapon, free_hands(ctx.engine, ctx.actor)[0])
    from .. import carry
    inventory=carry.carrying_of(ctx.engine,ctx.actor.entity_id)
    for key, weapon in available.items():
        item=carry.item_of(inventory,weapon_action=key)
        operation="stow" if key in ready and allow_stow else "draw"
        if item is None or not carry.operation_allowed(ctx.engine,ctx.actor,ctx.actor,item,operation,ctx.source):continue
        if not in_group(weapon.parameters.get("typed") or {}, "blade"):
            continue
        if key in ready:
            if allow_stow:
                options["stow:" + key] = (key, False, weapon, None)
            elif (free_hands(ctx.engine, ctx.actor) and resting_hands(weapon) == 1
                    and recorded_integration(ctx.engine, ctx.actor, weapon.parameters.get("typed") or {}, "blade")):
                # Sword Draws expressly manifests the same recorded weapon into
                # a free hand. A new grip replaces the old grip; no item is made.
                options["manifest:" + key] = (key, True, weapon, free_hands(ctx.engine, ctx.actor)[0])
        elif len(free_hands(ctx.engine, ctx.actor)) >= resting_hands(weapon):
            options["draw:" + key] = (key, True, weapon, free_hands(ctx.engine, ctx.actor)[0])
    if not options:
        return False
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "kensei_readiness", ctx.actor.entity_id),
        ctx.actor, "choice:needle.kensei_readiness", list(options), allow_decline=allow_stow,
        labels={key: ("Manifest the same " if key.startswith("manifest:") else "Draw " if value[1] else "Stow ") + value[2].display_name.removesuffix(" attack")
                for key, value in options.items()}, name="Blade weapon", target_id=ctx.actor.entity_id,
        prompt=("Choose one carried Blade to draw or stow. This costs no additional object interaction." if allow_stow else
                "Draw one carried Blade or manifest the same recorded Blade into a free hand. This creates no copy and costs no action or resource."))
    if picked:
        weapon, held, _, hand = options[picked[0]]
        item=carry.item_of(carry.carrying_of(ctx.engine,ctx.actor.entity_id),weapon_action=weapon)
        if item is None or not carry.operation_allowed(ctx.engine,ctx.actor,ctx.actor,item,"draw" if held else "stow",ctx.source):return False
        if picked[0].startswith("manifest:") and weapon not in available:
            from ..carry import recall_owned_weapon
            if not recall_owned_weapon(ctx.engine, ctx.actor, weapon, source=ctx.source):
                return False
        set_weapon_readiness(ctx.engine, ctx.actor, weapon, held, source=ctx.source, source_actor_id=ctx.actor.entity_id, hand=hand)
        return True
    return False


@effect("severing_flow")
def severing_flow(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        ctx.engine._apply_condition(ctx.target, "condition:typed.severing_flow", ctx.source, ctx.actor.entity_id,
            expires_on=row["expires_on"], data={"label": "Severing Palm (Flow): Disadvantage only on Cultivation Checks to maintain existing techniques"})


@hook("contest_check_mode")
def severing_maintenance_mode(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any]) -> str | None:
    """An explicit check purpose is required; ordinary cultivation is unchanged."""
    if (spec.get("kind") == "cultivation" and spec.get("purpose") == "maintain_technique"
            and any(c.condition_id == "condition:typed.severing_flow" for c in subject.conditions.values())):
        return "DISADVANTAGE"
    return None


@hook("attack_damage_type_choice")
def kensei_stance_damage_choice(ctx: Any, attack: dict[str, Any], target: Any, kinds: list[str], index: int) -> str | None:
    if not (_state(ctx.engine, ctx.actor, FLOWING) or _state(ctx.engine, ctx.actor, SAINT)
            or _available_authority(ctx.engine,ctx.actor,ctx.typed).get("heavenly")) or not _blade_or_unarmed(ctx):
        return None
    # Iron Fist's public owner already asks over the complete merged palette.
    if (ctx.typed.get("weapon") or {}).get("natural_source") == "tianxia.path.body_refining.feature.iron_fist":
        return None
    from .needle import ask, checkpoint_id
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "kensei_damage_type", target.entity_id, index),
        ctx.actor, "choice:needle.kensei_damage_type", list(kinds),
        labels={kind: kind.title() + " damage; same dice and modifier" for kind in kinds}, preferred=[kinds[0]],
        target_id=target.entity_id, name="Kensei stance",
        prompt=f"Choose the damage type of {ctx.action.display_name} against {target.display_name}. This changes its type without adding damage or cost.")
    return chosen[0] if chosen else None


def _saint_reach_trigger(engine: Any, actor: Any, subject: Any) -> None:
    """One actual entry/start delivery; never an attack or a hit-rider source."""
    from ..relations import relation, ENEMY
    if not actor.active or not subject.active or relation(engine, actor, subject) != ENEMY or not _state(engine, actor, SAINT):
        return
    from ..targeting import line_of_effect
    if engine._distance_actor_to_actor(actor, subject) > _usable_melee_reach(engine, actor) or not line_of_effect(engine,actor,target=subject):
        return
    key = "_round_sword_saint_reach:" + subject.entity_id
    if actor.turn_flags.get(key) == _stamp(engine):
        return
    from .states import active
    held = active(engine, actor, SAINT)
    action = engine.action_catalog.get(held.source_definition_id) if held is not None else None
    if (action is None or action.owner_id != actor.entity_id
            or not (action.parameters.get('typed') or {}).get('kensei_native_reach')):
        return
    from ..typed_executor import Context, run_effects
    from .needle import ask, checkpoint_id
    typed = {**action.parameters['typed'], 'effects': [], 'kensei_persistent_numbers':1,
        'numbers':dict((held.data.get('kensei_source') or {}).get('numbers') or held.data.get('numbers') or {})}
    ctx = Context(engine, actor, action, getattr(engine, '_active_intent', None), typed, [subject], subject, {}).with_source(PREFIX + SAINT)
    actor.turn_flags[key] = _stamp(engine)
    from ..observer_information import perceived_actor
    known=perceived_actor(engine,actor,subject)
    preferences=(held.data.get('kensei_source') or {})
    if known is not None:
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'sword_saint_reach_type', subject.entity_id), actor,
            'choice:needle.sword_saint_reach_type', ['force','slashing'], preferred=['force'],
            labels={kind: '3d8 ' + kind.title() + ' damage (half on a successful Dexterity save)' for kind in ('force','slashing')},
            target_id=subject.entity_id, name='Sword Saint Incarnation', feature_id=PREFIX + SAINT,
            prompt=f'Sword Saint Incarnation: {known["name"]} entered your reach or started its turn there. Choose its damage type; no additional cost.')
        kind=chosen[0] if chosen else 'force'
    else:
        # The player chooses these blind preferences at activation, not from a
        # hidden creature's resistances, identity or save. No trigger prompt
        # reveals that an unperceived recipient exists.
        kind=preferences.get('unseen_damage_type','force')
    until = 'START_OF_TARGET_NEXT_TURN'
    denied={'type':'reaction_denied','applies_to':'target','expires_on':until}
    slowed={'type':'speed','applies_to':'target','flat':-10,'source_owned':True,'expires_on':until}
    control = ({'type':'path_results','family':'sword_saint','name':'Sword Saint Incarnation','count':1,
        'prompt':'Sword Saint Incarnation: {target} failed its save; choose one.',
        'options':[{'label':'No Reactions','effects':[denied]},{'label':'Speed -10','effects':[slowed]}]}
        if known is not None else slowed if preferences.get('unseen_failed_rider')=='speed' else denied)
    run_effects(ctx, [{'type':'save','ability':'dex','applies_to':'target',
        'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':3,'sides':8},'damage_types':[kind]},control],
        'on_success':[{'type':'half_damage','applies_to':'target','damage_types':[kind]},
            {'type':'speed','applies_to':'target','flat':-5,'source_owned':True,'expires_on':until}]}])


def _usable_melee_reach(engine: Any, actor: Any) -> int:
    """Reach from attacks currently available to this actor, not catalog-only gear."""
    from .reach_bonus import current_reach
    from .hand_occupancy import weapon_allowed
    reaches = [5]
    for action in engine.action_catalog.values():
        typed = action.parameters.get("typed") or {}
        attacks = [row for row in typed.get("effects", []) if row.get("type") == "attack"]
        if (action.owner_id != actor.entity_id or not attacks
                or any("ranged" in str(row.get("attack_kind") or "").lower()
                       or "thrown" in str(row.get("attack_kind") or "").lower() for row in attacks)
                or typed.get("range_ft")):
            continue
        typed = action.parameters.get("typed") or {}
        if typed.get("weapon") and weapon_allowed(engine, actor, action) is False:
            continue
        reaches.append(current_reach(engine, actor, action))
    return max(reaches)


@hook('zone_arrival')
def saint_reach_entry(engine: Any, mover: Any, start: Any, end: Any, forced: bool) -> None:
    for owner in sorted(engine.state.actors.values(), key=lambda a:a.entity_id):
        if owner.entity_id == mover.entity_id or not _state(engine, owner, SAINT):
            continue
        reach = _usable_melee_reach(engine, owner)
        # Moving/expanding the owner's reach around a stationary subject is
        # deliberately not entry. Native movement supplies this mover's actual
        # committed segment; ordinary queries never produce a trigger.
        if (engine._distance_actor_to_actor(owner, mover, target_position=start) > reach
                and engine._distance_actor_to_actor(owner, mover, target_position=end) <= reach):
            _saint_reach_trigger(engine, owner, mover)


@hook('turn_start_choice')
def saint_reach_start(engine: Any, actor: Any) -> None:
    for owner in sorted(engine.state.actors.values(), key=lambda a:a.entity_id):
        if owner.entity_id != actor.entity_id and _state(engine, owner, SAINT):
            _saint_reach_trigger(engine, owner, actor)


@hook('damage_type_choice')
def saint_hit_damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    if ctx.source != PREFIX + SAINT + '#hit' or not _state(ctx.engine, ctx.actor, SAINT):
        return None
    if ctx.typed.get('kensei_hit_damage_type') in kinds:return ctx.typed['kensei_hit_damage_type']
    from .needle import ask, checkpoint_id
    target = targets[0] if targets else None
    target_id = target.entity_id if target else ctx.actor.entity_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sword_saint_hit_type', target_id), ctx.actor,
        'choice:needle.sword_saint_hit_type', list(kinds), preferred=[kinds[0]],
        labels={kind: 'Additional 3d8 ' + kind.title() + ' damage' for kind in kinds},
        name='Sword Saint Incarnation', feature_id=PREFIX+SAINT, target_id=target_id,
        prompt='Sword Saint Incarnation: choose Force or Slashing for this turn’s additional hit damage. No additional cost.')
    return picked[0] if picked else kinds[0]


@hook('attack_sequence_start')
def integrated_body_authority(ctx: Any) -> None:
    profile = _available_authority(ctx.engine,ctx.actor,ctx.typed)
    if not (profile.get('refined') or profile.get('heavenly')) or not _rows(ctx.engine, ctx.actor, 'blade_fist') or not _blade_or_unarmed(ctx):
        return
    import copy
    ctx.typed = copy.deepcopy(ctx.typed)
    ctx.typed['mundane'] = False
    ctx.typed['weapon']['cultivation_powered'] = True
    if profile.get('heavenly') and 'adamantine' not in str(ctx.typed['weapon'].get('properties') or '').lower():
        ctx.typed['weapon']['properties'] = str(ctx.typed['weapon'].get('properties') or '') + ', Adamantine'


@hook('attack_magical')
def integrated_blade_magical(engine: Any, actor_id: str, typed: dict[str, Any]) -> bool | None:
    actor = engine.state.actors.get(actor_id)
    profile = _available_authority(engine,actor,typed) if actor is not None else {}
    if actor is None or not _rows(engine, actor, 'blade_fist') or not (profile.get('refined') or profile.get('heavenly')):
        return None
    from .integrated_weapons import recorded_integration
    if recorded_integration(engine, actor, typed, 'blade'):
        return True
    return None


@hook('attack_damage_types')
def heavenly_blade_types(ctx: Any, attack: Any, kinds: list[str]) -> list[str] | None:
    if _available_authority(ctx.engine,ctx.actor,ctx.typed).get('heavenly') and _rows(ctx.engine,ctx.actor,'blade_fist') and _blade_or_unarmed(ctx):
        return list(dict.fromkeys([*kinds,'FORCE']))
    return None


@hook('armor_class_floor')
def severing_guard_floor(engine: Any, target: Any) -> int | None:
    if any(m.source_definition_id == SEVERING_PALM + '#guard' and m.target_field == 'armor_class'
           and m.operation == 'ADD' and m.value in (-1,-2) for m in target.modifiers.values()):
        return 0
    return None


@hook("compile_passives")
def blade_fist_natural_properties(passives: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Produce Finesse before natural attacks and their legal derivatives compile."""
    if BLADE_FIST not in info["owned_ids"]:
        return None
    return [{**row, "kensei_finesse_source":BLADE_FIST, "properties": (str(row.get("properties") or "") + ", Finesse").lstrip(", ")}
            if row.get("block") == "natural_weapon" and "finesse" not in str(row.get("properties") or "").lower()
            else row for row in passives]


@hook("body_mode_profiles")
def kensei_body_profile(bundle: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Join the shared Body clock/scene contract using actual acquired rows."""
    from .body_modes_scene_resources import feature_owned
    if not any(feature_owned(bundle, feature) for feature in LEVELS):
        return None
    limits = [cost[0] for action in bundle.get("action_catalog", [])
              if (action.get("parameters", {}).get("typed") or {}).get("source") == PREFIX + SAINT
              for cost in action.get("costs", []) if str(cost[0]).startswith("resource:uses.")]
    return [{"source": FAMILY, "name": "Kensei", "feature_levels": dict(LEVELS), "scene_limits": limits}]


def _initiative_consumed(engine: Any, actor: Any) -> bool:
    from .body_modes_scene_resources import scene_record, bundle_of
    record = scene_record(engine, actor, FAMILY)
    data = record.data if record is not None else (
        bundle_of(engine, actor).get("body_modes_scene_resources", {}).get("records", {}).get(FAMILY, {}))
    transfer=bundle_of(engine,actor).get('kensei_initiative',{})
    return bool(data.get("initiative") or transfer.get('sword_draws_available')==0)


@hook("match_start", priority=-100)
def kensei_scene_initiative(engine: Any) -> None:
    """Record first Initiative even when Surprised or temporarily suppressed."""
    from .body_modes_scene_resources import scene_record, set_record
    for actor in engine.state.actors.values():
        record = scene_record(engine, actor, FAMILY)
        if record is not None and not record.data.get("initiative"):
            set_record(engine, actor, FAMILY, {**record.data, "initiative": 1})


@hook("state_available")
def kensei_state_available(engine: Any, actor: Any, condition: Any) -> bool | None:
    name = condition.condition_id.removeprefix("condition:typed.state.")
    if name not in (FLOWING, SAINT):
        return None
    action=engine.action_catalog.get(condition.source_definition_id)
    if condition.source_actor_id!=actor.entity_id or action is None or action.owner_id!=actor.entity_id or (action.parameters.get('typed') or {}).get('source')!=PREFIX+name:
        return False
    from .body_modes_scene_resources import available
    # A dormant state keeps its original clock, cost and scene expenditure.
    from .states import preserved_on_unconscious
    return available(engine, actor, PREFIX + name, LEVELS[PREFIX + name],
                     requires_conscious=name == SAINT and not preserved_on_unconscious(engine,actor,condition))


@hook("ac")
def kensei_state_ac(engine: Any, actor: Any) -> int:
    from .states import active
    total = 0
    for name, bonus in ((FLOWING, 1), (SAINT, 2)):
        held = active(engine, actor, name)
        action = engine.action_catalog.get(held.source_definition_id) if held else None
        if _state(engine, actor, name) and action is not None and (action.parameters.get("typed") or {}).get("kensei_dynamic_ac"):
            total += bonus
    return total


def _journey_state(session: Any, aid: str, name: str) -> dict[str, Any] | None:
    import json
    from .body_modes_scene_resources import AUTHORITY,journey_available
    from .states import journey_preserved_on_unconscious
    actor=session.state['actors'][aid]
    catalog={a['source_definition_id']:a for a in actor['bundle'].get('action_catalog',[])}
    for row in actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[]):
        if row['kind']!='condition':continue
        model=json.loads(row['model']);action=catalog.get(model.get('source_definition_id'))
        if model.get('condition_id')!='condition:typed.state.'+name or model.get('source_actor_id')!=aid or action is None or action['owner_id']!=aid or (action.get('parameters',{}).get('typed') or {}).get('source')!=PREFIX+name:
            continue
        conscious=name==SAINT and not journey_preserved_on_unconscious(session,aid,model)
        if conscious and _journey_unconscious(actor):continue
        if journey_available(session,aid,PREFIX+name,LEVELS[PREFIX+name],requires_conscious=False):return row
    return None


@hook("journey_options")
def kensei_journey_options(session: Any, aid: str) -> list[dict[str, Any]] | None:
    from .body_modes_scene_resources import feature_owned, journey_available
    actor = session.state["actors"][aid]
    choices = []
    for name, label, cost in ((FLOWING, "Flowing Blade Stance", 4), (SAINT, "Sword Saint Incarnation", 7)):
        if not feature_owned(actor["bundle"], PREFIX + name) or not journey_available(session, aid, PREFIX + name, LEVELS[PREFIX + name]):
            continue
        if actor["resources"].get(STAMINA, 0) < cost:
            continue
        profile = kensei_body_profile(actor["bundle"])[0]
        if name == SAINT and any(actor["resources"].get(pool, 1) < 1 for pool in profile["scene_limits"]):
            continue
        profiles=[{}] if name!=SAINT else [{'unseen_damage_type':kind,'unseen_failed_rider':rider}
            for kind in ('force','slashing') for rider in ('reactions','speed')]
        for preferences in profiles:
            choices.append({"id":"kensei_"+name+(':'+preferences['unseen_damage_type']+':'+preferences['unseen_failed_rider'] if preferences else ''),
                "kind":"kensei_state","payload":{"state":name,**preferences},
                "label":f"{label}: spend {cost} Stamina; {'Fly 40 feet with Hover, +2 AC, +5 melee reach' if name==SAINT else '+1 AC and flowing attacks'} for 1 minute"
                    + (", once this scene; unseen recipients use "+preferences['unseen_damage_type'].title()+" and "+('no Reactions' if preferences['unseen_failed_rider']=='reactions' else 'Speed -10')+" on a failed save." if name==SAINT else ".")})
    return choices or None


@hook("journey_command")
def kensei_journey_activate(session: Any, aid: str, kind: str, payload: dict[str, Any]) -> bool | None:
    if kind != "kensei_state":
        return None
    import json
    from ..journey import require
    from .body_modes_scene_resources import AUTHORITY, journey_body_cl, complete_journey_activation
    if payload=={"state":SAINT}:
        payload={**payload,"unseen_damage_type":"force","unseen_failed_rider":"reactions"}
    options = kensei_journey_options(session, aid) or []
    require(any(row["payload"] == payload for row in options), "This Kensei state is unavailable or cannot be paid.")
    name = payload["state"]
    actor = session.state["actors"][aid]
    cost = 7 if name == SAINT else 4
    action = next(a for a in actor["bundle"]["action_catalog"] if (a.get("parameters", {}).get("typed") or {}).get("source") == PREFIX + name)
    start = len(session.state["events"])
    actor["resources"][STAMINA] -= cost
    session.emit("RESOURCE_SPENT", aid, source=PREFIX + name, resource_id=STAMINA, amount=cost)
    managed = actor.setdefault("source_states", {}).setdefault(AUTHORITY, {})
    record = managed.setdefault("records", {}).get(FAMILY, {})
    if name == SAINT:
        balances = {}
        for pool in kensei_body_profile(actor["bundle"])[0]["scene_limits"]:
            actor["resources"][pool] = 0
            balances[pool] = 0
            session.emit("RESOURCE_SPENT", aid, source=PREFIX + name, resource_id=pool, amount=1)
        record["scene_limits"] = balances
    preferences={key:payload[key] for key in ('unseen_damage_type','unseen_failed_rider') if key in payload}
    model = {"condition_id": "condition:typed.state." + name, "source_definition_id": action["source_definition_id"],
             "source_actor_id": aid, "data": {"kensei_source":_journey_creation_profile(session,aid,name,action,preferences),"name": name, "label": name.replace("_", " ").title(),
                "ends_if_unconscious": name == SAINT, "numbers": {"cl": journey_body_cl(session, aid)}}}
    effects = managed.setdefault("effects", [])
    effects[:] = [r for r in effects if not (r["kind"] == "condition" and json.loads(r["model"]).get("condition_id") == model["condition_id"])]
    model.update(instance_id="journey:kensei:"+str(len(session.state["events"])),target_id=aid,applied_sequence=0,expires_on="UNTIL_REMOVED")
    effects.append({"kind": "condition", "model": json.dumps(model, sort_keys=True), "remaining_num": 60, "remaining_den": 1,"early_bind":1})
    session.emit("BODY_TRANSFORMATION_STARTED", aid, source=PREFIX + name, duration_seconds=60)
    complete_journey_activation(session, aid, PREFIX + name, start)
    return True


@hook("journey_properties")
def kensei_journey_flight(session: Any, aid: str) -> dict[str, Any] | None:
    from fractions import Fraction
    row = _journey_state(session, aid, SAINT)
    if row is not None:
        expiry = session.clock() + Fraction(row["remaining_num"], row["remaining_den"])
        return {"fly_speed_ft": 40, "flight_hover": 1, "expiry_num": expiry.numerator, "expiry_den": expiry.denominator}


@hook("journey_state_changed")
def kensei_journey_unconscious(session: Any, aid: str) -> None:
    import json
    from .body_modes_scene_resources import AUTHORITY
    actor = session.state["actors"][aid]
    # Native journey incapacity includes ordinary incapacitation; only actual
    # Unconscious/death ends this transformation, not Stunned or Disarmed.
    snapshot = actor.get("encounter_snapshot") or {}
    conditions = [json.loads(c) if isinstance(c, str) else c for c in snapshot.get("conditions", {}).values()]
    unconscious = (snapshot.get("life_state") in ("DYING", "STABLE") or snapshot.get("current_hp", 1) <= 0
                   or not snapshot.get("active", 1) or any(c.get("condition_id", "").endswith("unconscious") for c in conditions))
    if not unconscious:
        return
    state = actor.get("source_states", {}).get(AUTHORITY, {})
    from .states import journey_preserved_on_unconscious
    state["effects"] = [r for r in state.get("effects", []) if not (r["kind"] == "condition" and json.loads(r["model"]).get("condition_id") == "condition:typed.state." + SAINT
        and not journey_preserved_on_unconscious(session,aid,json.loads(r['model'])))]


@hook("movement_mode_speed")
def kensei_nonwalking_speed(engine: Any, actor: Any, mode: str, speed: int) -> int | None:
    """Printed all-Speed impairments affect existing flight/climbing as well."""
    sources = {BLADE_FIST, SEVERING_PALM + "#leg", PREFIX + SAINT}
    modifiers = [m for m in actor.modifiers.values() if not m.consumed and m.source_definition_id in sources]
    fixed = {}
    for modifier in modifiers:
        if modifier.target_field == "speed_ft" and modifier.operation == "ADD" and int(modifier.value) < 0:
            fixed[modifier.source_definition_id] = min(fixed.get(modifier.source_definition_id, 0), int(modifier.value))
    half = any(m.target_field == "speed_halved" for m in modifiers)
    if not fixed and not half:
        return None
    result = speed + sum(fixed.values())
    return max(0, result // 2 if half else result)


@hook("possession_operation_allowed")
def sword_draws_recall_permission(engine, actor, holder, item, operation, source):
    if operation != "recall" or source != PREFIX + "sword_draws_before_thought":
        return None
    if holder is not actor or not _rows(engine, actor, "sword_draws"):
        return False
    from .hand_occupancy import free_hands
    from .integrated_weapons import recorded_integration
    action = engine.action_catalog.get(item.get("weapon_action"))
    return bool(action is not None and action.owner_id == actor.entity_id and free_hands(engine, actor)
                and recorded_integration(engine, actor, action.parameters.get("typed") or {}, "blade"))


@hook('compile_actions')
def kensei_object_profiles(info):
    """One physical attack profile per actual unarmed/Blade item, not a name guess."""
    if BLADE_FIST not in info['owned_ids']:
        return None
    import copy
    from .integrated_weapons import in_group
    from factory_authoring.starting_kits import item_definition
    out = []
    for origin in info['actions']:
        typed = origin.parameters.get('typed') or {}
        attacks = [e for e in typed.get('effects', []) if e.get('type') == 'attack']
        if (str(getattr(origin.economy,'value',origin.economy)) != 'ACTION' or not typed.get('weapon')
                or not attacks or '#' in origin.source_definition_id or typed.get('unarmed_option')
                or origin.costs or origin.concentration or origin.parameters.get('player_only')):
            continue
        unarmed = attacks[0].get('attack_kind') == 'unarmed'
        if not unarmed and not in_group(typed, 'blade'):
            continue
        changed = copy.deepcopy(typed)
        group = 'unarmed' if unarmed else 'axe' if 'axe' in str(item_definition(typed.get('source')).get('weapon_family','')).lower() else 'weapon'
        changed.update(object_weapon=copy.deepcopy(typed['weapon']), object_weapon_group=group,
                       object_melee=not bool(typed.get('range_ft')),
                       effects=[{'type':'object_attack','count':int(attacks[0].get('count') or 1),
                                 'attack_kind':attacks[0].get('attack_kind')}])
        params = {**origin.parameters, 'typed':changed, 'object_attack':True, 'player_only':True,
                  'attack_kind':attacks[0].get('attack_kind'), 'kensei_object_origin':origin.source_definition_id,
                  'description':'Attack one reachable object with this actual unarmed or integrated Blade profile; choose its legal ability and damage type for each attack. Uses your Action and normal attacks.'}
        if not typed.get('range_ft'):
            params['range_from_action'] = origin.source_definition_id
        out.append(origin.model_copy(update={'source_definition_id':origin.source_definition_id+'#kensei_object',
            'display_name':origin.display_name+' (object)', 'target_kind':'OBJECT','parameters':params}))
    return out or None


@hook('candidate_allowed')
def kensei_object_candidates(engine, actor, candidate, action):
    if action is None:
        return None
    params = action.parameters
    if params.get('kensei_object_origin'):
        from .hand_occupancy import weapon_allowed
        origin = engine.action_catalog.get(params['kensei_object_origin'])
        return bool(origin is not None and _rows(engine,actor,'blade_fist') and weapon_allowed(engine,actor,origin) is not False)
    return None


@hook('object_attack_prepared')
def kensei_object_prepare(ctx, obj, spec, index):
    from types import SimpleNamespace
    if spec['attack_kind'] != 'unarmed' and any(c.condition_id==ARM for c in ctx.actor.conditions.values()):
        spec['modes'].append('DISADVANTAGE')
    if not ctx.action.parameters.get('kensei_object_origin') or not _rows(ctx.engine,ctx.actor,'blade_fist'):
        return
    label = SimpleNamespace(entity_id=obj.object_id,display_name=(obj.component or {}).get('name') or 'Object')
    attack = ctx.typed['effects'][0]
    # These are the actual item's weapon dice, so the shared ability selector
    # replaces its damage ability as well as its attack ability.
    ctx.weapon_damage_dice=True
    spec['roll_context']={'kind':'attack','actor_id':ctx.actor.entity_id,'target_id':obj.object_id,
        'source_id':ctx.source,'source_actor_id':ctx.actor.entity_id,'attack_index':index,
        'target_kind':'object','target_dc':int(obj.ac),'reason':f'ATTACK:{ctx.source}:object:{index}'}
    blade_fist_ability_choice(ctx,label,attack,spec,index)
    ctx.typed = spec['typed']
    mode = sword_draws_first_attack(ctx,label)
    if mode:
        spec['modes'].append('ADVANTAGE')
    kinds = [spec['damage_type']]
    if spec['attack_kind']=='unarmed' and 'SLASHING' not in kinds:
        kinds.append('SLASHING')
    if _state(ctx.engine,ctx.actor,FLOWING) or _state(ctx.engine,ctx.actor,SAINT):
        kinds = list(dict.fromkeys([*kinds,'FORCE','SLASHING']))
    from .body_modes_scene_resources import available
    heavenly = bool((ctx.typed.get('kensei_abilities') or {}).get('heavenly') and
        available(ctx.engine,ctx.actor,'tianxia.path.body_refining.feature.heavenly_fist',17))
    if heavenly and 'FORCE' not in kinds:
        kinds.append('FORCE')
    from .needle import ask,checkpoint_id
    if len(kinds)>1:
        selected = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'kensei_object_type',obj.object_id,index),ctx.actor,
            'choice:needle.kensei_object_type',kinds,labels={k:k.title()+' damage; same dice and modifier' for k in kinds},
            target_id=obj.object_id,name='Kensei object attack',feature_id=BLADE_FIST,
            prompt=f'Choose the damage type of {ctx.action.display_name} against {label.display_name}; no extra cost.')
        spec['damage_type'] = selected[0] if selected else kinds[0]
    if _state(ctx.engine,ctx.actor,SAINT):
        spec['critical_range'] = min(spec['critical_range'],19)
    authority = _object_authority(ctx.engine,ctx.actor,obj)
    if authority and 'physical_prohibition' in authority['protections']:
        spec['physical_damage_prohibited']=1
    if heavenly and authority and authority['source_cl'] <= int(ctx.numbers.get('cl') or 0) and obj.unattended:
        # Doubling is after defenses. It does not erase a protected property's
        # Immunity, Resistance or threshold. Only ordinary defenses are bypassed.
        spec['multiplier']=2
        if not authority['protections']:
            spec.update(ignore_threshold=True,ignore_resistance_types=('BLUDGEONING','PIERCING','SLASHING','FORCE'))


def _object_authority(engine,actor,obj):
    """Read actual source-scoped native GM admission; unknown stays unknown."""
    from ..combat_world_facts import records,clock
    matches = [r for r in records(engine) if r['source']==FAMILY and r['subject']==actor.entity_id
               and r['kind']=='object_authority' and r['scope']==obj.object_id and r['expires_at']>clock(engine)]
    return max(matches,key=lambda r:r['sequence'])['value'] if matches else None


@hook('fact_admission_schema')
def kensei_object_authority_schema(session,source,subject,kind):
    from .body_modes_scene_resources import feature_owned
    if source!=FAMILY or kind!='object_authority' or not hasattr(session,'engine'):
        return None
    if not feature_owned(session.state['actors'][subject]['bundle'],BLADE_FIST):
        return None
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
            'description':'Record the actual Source CL and explicit protections of this object for this acquired source; no damage permission is created.'}


@hook('fact_admission_validate')
def kensei_object_authority_validate(session,source,subject,kind,scope,value):
    if source!=FAMILY or kind!='object_authority':
        return None
    from ..journey import require,integer
    obj=session.engine.state.objects.get(scope)
    require(obj is not None and not obj.destroyed and set(value)=={'source_cl','source_rule','protections'}
            and integer(value['source_cl']) and type(value['source_rule']) is str and bool(value['source_rule'].strip())
            and isinstance(value['protections'],list) and all(p in {'artifact','immortal','void','physical_prohibition'} for p in value['protections']),
            'Record a present object, its actual Source CL, printed Source Rule and explicit protection categories.')
    # Actual native object protection cannot be contradicted by a declaration.
    require(not (obj.component or {}).get('artifact') or 'artifact' in value['protections'],
            'The native Artifact protection must remain recorded.')
    return True


@hook('object_attack_packets')
def kensei_object_packets(ctx,obj,spec,index,packets):
    if not ctx.action.parameters.get('kensei_object_origin') or not _rows(ctx.engine,ctx.actor,'blade_fist'):
        return
    engine,actor=ctx.engine,ctx.actor
    from .needle import ask,checkpoint_id
    if actor.turn_flags.get('_round_blade_fist')!=_stamp(engine):
        picked=ask(engine,ctx.intent,checkpoint_id(engine,'blade_fist_object',obj.object_id,index),actor,
            'choice:needle.blade_fist_object',['damage','draw'],
            labels={'damage':f'+{int(ctx.numbers.get("pb") or actor.proficiency_bonus)} Slashing damage','draw':'Draw or stow one Blade; no additional interaction'},
            target_id=obj.object_id,name='Blade Fist',feature_id=BLADE_FIST,
            prompt=f'Blade Fist hit {(obj.component or {}).get("name") or "this object"}. Choose damage or draw/stow; inanimate objects have no Speed or Reactions to impair.')
        if picked:
            actor.turn_flags['_round_blade_fist']=_stamp(engine)
            if picked[0]=='damage':packets.append((int(ctx.numbers.get('pb') or actor.proficiency_bonus),'SLASHING'))
            else:_readiness(ctx.with_source(BLADE_FIST),allow_stow=True)
    if _state(engine,actor,SAINT) and actor.turn_flags.get('_round_sword_saint_hit')!=_stamp(engine):
        selected=ask(engine,ctx.intent,checkpoint_id(engine,'sword_saint_object',obj.object_id,index),actor,
            'choice:needle.sword_saint_hit_type',['force','slashing'],allow_decline=True,
            labels={k:'Add 3d8 '+k.title()+' damage once this turn' for k in ('force','slashing')},
            target_id=obj.object_id,name='Sword Saint Incarnation',feature_id=PREFIX+SAINT,
            prompt='Sword Saint Incarnation: add 3d8 Force or Slashing to this eligible hit, once this turn, with no extra cost?')
        if selected:
            from ..gate2_runtime_models import DiceSpec
            actor.turn_flags['_round_sword_saint_hit']=_stamp(engine)
            roll=engine.roller.roll(DiceSpec(count=3,sides=8,modifier=0),actor_id=actor.entity_id,
                reason='DAMAGE:'+PREFIX+SAINT+'#hit',critical=bool(spec.get('critical')))
            engine._record_roll(roll)
            packets.append((roll.total,selected[0].upper()))
    if spec.get('physical_damage_prohibited'):
        packets[:]=[(0,kind) for _,kind in packets]


@hook('object_attack_completed',priority=10000)
def kensei_object_completion(ctx,obj,spec,index,hit):
    if not hit or not ctx.action.parameters.get('kensei_object_origin'):
        return
    engine, actor = ctx.engine, ctx.actor
    if _state(engine,actor,FLOWING) and actor.turn_flags.get('_round_flowing_step')!=_stamp(engine):
        if _move(ctx,actor,5,'choice:needle.flowing_blade_step','Flowing Blade Stance'):
            actor.turn_flags['_round_flowing_step']=_stamp(engine)


@hook('resolution_numbers',priority=200)
def kensei_integrated_resolution_numbers(ctx,numbers):
    if ctx.typed.get('kensei_persistent_numbers') and ctx.source in {PREFIX+SAINT,PREFIX+SAINT+'#hit'} and _state(ctx.engine,ctx.actor,SAINT):
        from .states import active
        held=active(ctx.engine,ctx.actor,SAINT)
        captured=(held.data.get('kensei_source') or {}).get('numbers') or {}
        if captured:return {**numbers,**captured}
    if not ctx.typed.get('kensei_abilities') or not _rows(ctx.engine,ctx.actor,'blade_fist'):
        return None
    from .body_modes_scene_resources import effective_body_cl,effective_body_pb
    level=effective_body_cl(ctx.engine,ctx.actor);pb=effective_body_pb(ctx.engine,ctx.actor)
    compiled_pb=int(numbers.get('pb') or ctx.actor.proficiency_bonus)
    if level==int(numbers.get('cl') or level) and pb==compiled_pb:
        return None
    result={**numbers,'cl':level,'pb':pb}
    for key in ('attack_bonus','save_dc'):
        if key in result:result[key]=int(result[key])-compiled_pb+pb
    return result


@effect('severing_impairment')
def severing_exact_impairment(ctx,row):
    from ..typed_executor import condition_immune,run_effects
    if ctx.target is not None and row.get('area') in SEVER_OPTIONS and not condition_immune(ctx.engine,ctx.target,'severing_'+row['area']):
        _clear_area(ctx.engine,ctx.actor,ctx.target,row['area'])
        run_effects(ctx,row['effects'])


@hook('fact_admission_schema')
def kensei_external_weapon_schema(session,source,subject,kind):
    from .body_modes_scene_resources import feature_owned
    if source!=FAMILY or kind!='weapon_impairment' or not hasattr(session,'engine'):
        return None
    if not feature_owned(session.state['actors'][subject]['bundle'],BLADE_FIST):
        return None
    return {'value_type':'document','maximum_seconds':60,'authority':'table_owner',
        'description':'Record an actual external source rendering a particular existing weapon unusable; an actor cannot declare this authority.'}


@hook('fact_admission_validate')
def kensei_external_weapon_validate(session,source,subject,kind,scope,value):
    if source!=FAMILY or kind!='weapon_impairment':
        return None
    from ..journey import require,integer
    from .. import carry
    actor=session.engine.state.actors[subject]
    action=session.engine.action_catalog.get(scope)
    require(action is not None and action.owner_id==subject
            and carry.item_of(carry.carrying_of(session.engine,subject),weapon_action=scope) is not None
            and set(value)=={'operation','source_kind','source_rule','source_cl'}
            and value['operation'] in {'disarm','rust','dull','break'}
            and value['source_kind'] in {'mundane','cultivation'} and integer(value['source_cl'])
            and (value['source_kind']!='mundane' or value['source_cl']==0)
            and type(value['source_rule']) is str and bool(value['source_rule'].strip()),
            'Name your exact recorded weapon and the actual external impairment, source kind, Source CL and Source Rule.')
    return True


@hook('state_event')
def kensei_external_weapon_application(engine,event):
    if event.event_type!='WORLD_FACT_DECLARED' or event.source_definition_id!=FAMILY:
        return
    from ..combat_world_facts import records
    record=next((r for r in records(engine) if r['receipt_id']==event.payload['receipt_id']),None)
    if record is None or record['kind']!='weapon_impairment':
        return
    actor=engine.state.actors[record['subject']]
    from .. import carry
    item=carry.item_of(carry.carrying_of(engine,actor.entity_id),weapon_action=record['scope'])
    data={'disables_action':record['scope'],'source_receipt_id':record['receipt_id'],
          'operation':record['value']['operation'],'item_key':item['key'],'owner':actor.entity_id,
          'object_id':actor.entity_id+'|'+item['key'], 'label':'Recorded weapon impairment: '+record['value']['operation']}
    condition='condition:typed.weapon_impairment'
    if record['value']['operation']=='disarm':
        condition='condition:typed.disarmed'
        data['dropped_at']=actor.position.model_dump(mode='json')
    engine._apply_condition(actor,condition,FAMILY+'#weapon_impairment',actor.entity_id,
        expires_on='UNTIL_REMOVED',data=data)
    carry.refresh(engine,actor,FAMILY+'#weapon_impairment')


@hook('condition_data_application_attempt')
def heavenly_blade_impairment_guard(engine,target,condition_id,source,source_actor,data):
    if not _rows(engine,target,'blade_fist'):
        return None
    weapon=data.get('disables_action')
    action=engine.action_catalog.get(weapon)
    if action is None or action.owner_id!=target.entity_id:
        return None
    from .body_modes_scene_resources import available
    from .hand_occupancy import weapon_grips
    from .integrated_weapons import recorded_integration
    if (weapon not in weapon_grips(engine,target) or not (action.parameters.get('typed') or {}).get('kensei_abilities',{}).get('heavenly')
            or not available(engine,target,'tianxia.path.body_refining.feature.heavenly_fist',17)
            or not recorded_integration(engine,target,action.parameters.get('typed') or {},'blade')):
        return None
    mundane=False
    if source==FAMILY+'#weapon_impairment' and data.get('source_receipt_id'):
        from ..combat_world_facts import records
        record=next((r for r in records(engine) if r['receipt_id']==data['source_receipt_id']
            and r['source']==FAMILY and r['kind']=='weapon_impairment' and r['subject']==target.entity_id and r['scope']==weapon),None)
        mundane=bool(record and record['value']['source_kind']=='mundane')
    else:
        # Ordinary mechanical disarm/rust consumers carry their actual selected
        # item and explicit source classification; absence is never mundane.
        from .source_eligibility import catalog_action
        origin=catalog_action(engine,source)
        mundane=bool(origin is not None and (origin.parameters.get('typed') or {}).get('mundane') is True)
    if mundane and condition_id in {'condition:typed.disarmed','condition:typed.weapon_impairment','condition:typed.rusted_weapon','condition:typed.dulled_weapon','condition:typed.broken_weapon'}:
        engine._append_event('PASSIVE_TRIGGERED','tianxia.path.body_refining.feature.heavenly_fist',actor_id=target.entity_id,
            target_ids=(target.entity_id,),payload={'log':'Heavenly Fist protects the wielded integrated Blade from this mundane weapon impairment.'})
        return False
    return None


def _held_blades(engine,actor):
    from .hand_occupancy import weapon_grips
    from .integrated_weapons import recorded_integration
    return sorted(key for key in weapon_grips(engine,actor) if key in engine.action_catalog
        and recorded_integration(engine,actor,engine.action_catalog[key].parameters.get('typed') or {},'blade'))


@hook('state_data')
def kensei_creation_profile(ctx,row):
    name=row.get('name')
    if name not in (FLOWING,SAINT) or ctx.typed.get('source')!=PREFIX+name or ctx.action.owner_id!=ctx.actor.entity_id:
        return None
    from .body_modes_scene_resources import available
    if not available(ctx.engine,ctx.actor,PREFIX+name,LEVELS[PREFIX+name]):
        return None
    preferences={}
    if name==SAINT:
        from .needle import ask,checkpoint_id
        for suffix,options,labels in (
            ('type',['force','slashing'],{'force':'Force damage','slashing':'Slashing damage'}),
            ('rider',['reactions','speed'],{'reactions':'No Reactions on a failed save','speed':'Speed -10 on a failed save'})):
            selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'sword_saint_unseen',suffix),ctx.actor,
                'choice:needle.sword_saint_unseen_'+suffix,options,labels=labels,preferred=[options[0]],
                name='Sword Saint Incarnation',feature_id=PREFIX+SAINT,
                prompt='Sword Saint Incarnation: choose a standing result for any creature you cannot perceive. This reveals no unseen creature and costs nothing extra; visible recipients retain their separate choices.')
            preferences['unseen_damage_type' if suffix=='type' else 'unseen_failed_rider']=selected[0] if selected else options[0]
    return {'kensei_source':{**preferences,'activation':ctx.action.source_definition_id,'source_cl':int(ctx.numbers['cl']),
        'numbers':{k:int(ctx.numbers[k]) for k in ('cl','pb','save_dc','attack_bonus','key_mod','con_mod') if k in ctx.numbers},
        'integrated_blades':_held_blades(ctx.engine,ctx.actor),'damage_types':['FORCE','SLASHING'],
        'fly_speed_ft':40 if name==SAINT else 0,'hover':int(name==SAINT),'reach_bonus_ft':5 if name==SAINT else 0}}


@hook('paid_activation_resolved')
def kensei_native_activation_profile(engine,actor,receipt):
    source=receipt['source']
    if source not in LEVELS:return None
    from .body_modes_scene_resources import scene_record,set_record
    record=scene_record(engine,actor,FAMILY)
    if record is not None:set_record(engine,actor,FAMILY,{**record.data,'last_paid_activation':dict(receipt)})
    if source not in (PREFIX+FLOWING,PREFIX+SAINT):
        return None
    held=next((c for c in actor.conditions.values()
        if c.condition_id=='condition:typed.state.'+source.removeprefix(PREFIX) and c.source_actor_id==actor.entity_id
        and c.source_definition_id in engine.action_catalog
        and engine.action_catalog[c.source_definition_id].owner_id==actor.entity_id
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==source),None)
    if held is None or held.source_actor_id!=actor.entity_id or not held.data.get('kensei_source'):
        return None
    profile={**held.data['kensei_source'],'paid_stamina':int(receipt['paid']),
        'payment_sequences':list(receipt['payment_sequences']),'completion_sequence':int(receipt['completion_sequence'])}
    engine._update_condition_data(actor,held,{**held.data,'kensei_source':profile},held.source_definition_id)


@hook('state_event')
def kensei_current_implement(engine,event):
    if event.event_type not in {'CONDITION_APPLIED','CONDITION_REMOVED'}:
        return
    for actor in engine.state.actors.values():
        for held in list(actor.conditions.values()):
            profile=held.data.get('kensei_source')
            if not profile or held.source_actor_id!=actor.entity_id:
                continue
            action=engine.action_catalog.get(held.source_definition_id)
            if action is None or action.owner_id!=actor.entity_id or (action.parameters.get('typed') or {}).get('source') not in (PREFIX+FLOWING,PREFIX+SAINT):
                continue
            current=_held_blades(engine,actor)
            if current!=profile.get('integrated_blades'):
                engine._update_condition_data(actor,held,{**held.data,'kensei_source':{**profile,'integrated_blades':current}},held.source_definition_id)


@hook('state_event')
def kensei_flight_support_changed(engine,event):
    ids=set(event.target_ids)|{event.actor_id}
    if not any(aid in ids and kensei_body_profile(bundle) for bundle in getattr(engine,'typed_bundle_documents',())
               for aid in (bundle.get('actor_id'),)):
        return
    condition=event.payload.get('condition_id','')
    if (event.event_type in {'CONDITION_APPLIED','CONDITION_REMOVED'} and condition in {
            'condition:typed.cultivation_suppression','condition:typed.state.sword_saint_incarnation',
            'condition:typed.life_unconscious','condition:typed.unconscious','condition:core.unconscious','unconscious'}
            or event.event_type=='LIFE_STATE_CHANGED'):
        from ..falling import settle
        settle(engine,event.source_definition_id,getattr(engine,'_active_intent',None))


@hook('fact_admission_schema')
def kensei_scene_start_schema(session,source,subject,kind):
    from .body_modes_scene_resources import feature_owned
    if source!=FAMILY or kind!='initiative_surprise' or hasattr(session,'engine'):
        return None
    if not feature_owned(session.state['actors'][subject]['bundle'],PREFIX+'sword_draws_before_thought'):
        return None
    return {'value_type':'document','maximum_seconds':3600,'authority':'table_owner',
            'description':'Record actual Surprise for this new scene before Initiative; entering combat cannot supply consent or a new scene.'}


@hook('fact_admission_validate')
def kensei_scene_start_validate(session,source,subject,kind,scope,value):
    if source!=FAMILY or kind!='initiative_surprise':
        return None
    from ..journey import require,integer
    scene=session.state.get('scene_id',session.state['journey_id'])
    require(session.state['phase']=='travel' and scope==scene
            and set(value)=={'surprised','source_rule','source_cl'} and type(value['surprised']) is int and value['surprised'] in (0,1)
            and integer(value['source_cl']) and type(value['source_rule']) is str and bool(value['source_rule'].strip()),
            'Record actual Surprise as 0 or 1, with its source, for this current scene before Initiative.')
    return True


@hook('journey_combat_bundle')
def kensei_scene_start_export(bundle,session,aid):
    from .body_modes_scene_resources import feature_owned,journey_available
    if not feature_owned(bundle,PREFIX+'sword_draws_before_thought'):
        return None
    from ..fact_consent_admission import read
    scene=session.state.get('scene_id',session.state['journey_id'])
    record=read(session,FAMILY,aid,'initiative_surprise',scene,aid)
    from .body_modes_scene_resources import AUTHORITY
    prior=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{}).get('records',{}).get(FAMILY,{})
    bundle['kensei_initiative']={'scene_id':scene,'actor_id':aid,'source':FAMILY,
        'first_initiative':int(not prior.get('initiative')),
        'sword_draws_available':int(journey_available(session,aid,PREFIX+'sword_draws_before_thought',6))}
    if record:
        bundle['kensei_initiative'].update(surprised=int(record['value']['surprised']),receipt_id=record['receipt_id'])
    return bundle


@hook('initiative_modes')
def kensei_scene_start_mode(engine,actor):
    from .body_modes_scene_resources import bundle_of,feature_owned
    if not feature_owned(bundle_of(engine,actor),PREFIX+'sword_draws_before_thought'):return None
    record=bundle_of(engine,actor).get('kensei_initiative',{})
    if record.get('actor_id')==actor.entity_id and record.get('source')==FAMILY and record.get('first_initiative')==1 and record.get('surprised')==1 and record.get('receipt_id'):
        return 'DISADVANTAGE'
    return None


@hook('match_initialize')
def kensei_scene_start_bind(engine):
    """Bind the actual admitted initial state before setup discovery and turn one."""
    from .body_modes_scene_resources import bundle_of,feature_owned
    from ..gate2_runtime_models import ConditionInstance
    initialized=False
    for actor in engine.state.actors.values():
        if not feature_owned(bundle_of(engine,actor),PREFIX+'sword_draws_before_thought'):continue
        record=bundle_of(engine,actor).get('kensei_initiative',{})
        if record.get('actor_id')!=actor.entity_id or record.get('source')!=FAMILY or record.get('first_initiative')!=1 or record.get('surprised')!=1 or not record.get('receipt_id'):
            continue
        iid='condition:kensei.surprise:'+record['receipt_id']
        actor.conditions[iid]=ConditionInstance(instance_id=iid,condition_id='condition:core.surprised',
            source_definition_id=FAMILY,source_actor_id=actor.entity_id,target_id=actor.entity_id,
            applied_sequence=0,expires_on='START_OF_SOURCE_NEXT_TURN',
            data={'label':'Surprised at Initiative','receipt_id':record['receipt_id'],'scene_id':record['scene_id']})
        initialized=True
    return True if initialized else None


@hook('journey_equipment_enabled')
def kensei_journey_equipment(bundle):
    from .body_modes_scene_resources import feature_owned
    return True if feature_owned(bundle,BLADE_FIST) else None


def _journey_blades(session,aid):
    from .journey_equipment import grips,weapons
    from .integrated_weapons import in_group
    available=weapons(session,aid)
    return sorted(key for key in grips(session,aid) if key in available
        and in_group(available[key].parameters.get('typed') or {},'blade'))


def _journey_creation_profile(session,aid,name,action,preferences):
    from .body_modes_scene_resources import journey_body_cl,journey_body_pb
    numbers=dict(action.get('parameters',{}).get('typed',{}).get('numbers') or {})
    pb=journey_body_pb(session,aid);compiled=int(numbers.get('pb') or pb)
    for key in ('save_dc','attack_bonus'):
        if key in numbers:numbers[key]=int(numbers[key])-compiled+pb
    numbers.update(cl=journey_body_cl(session,aid),pb=pb)
    return {**preferences,'activation':action['source_definition_id'],'source_cl':numbers['cl'],
        'numbers':{k:int(numbers[k]) for k in ('cl','pb','save_dc','attack_bonus','key_mod','con_mod') if k in numbers},
        'integrated_blades':_journey_blades(session,aid),'damage_types':['FORCE','SLASHING'],
        'fly_speed_ft':40 if name==SAINT else 0,'hover':int(name==SAINT),'reach_bonus_ft':5 if name==SAINT else 0}


@hook('journey_paid_activation_resolved')
def kensei_journey_payment_profile(session,aid,receipt):
    if receipt['source'] not in (PREFIX+FLOWING,PREFIX+SAINT):return None
    import json
    from .body_modes_scene_resources import AUTHORITY
    state=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{})
    for row in state.get('effects',[]):
        if row['kind']!='condition':continue
        model=json.loads(row['model']);profile=model.get('data',{}).get('kensei_source')
        if not profile or model['source_actor_id']!=aid:continue
        if profile['activation']!=next((a['source_definition_id'] for a in session.state['actors'][aid]['bundle']['action_catalog']
                if (a.get('parameters',{}).get('typed') or {}).get('source')==receipt['source']),None):continue
        profile.update(paid_stamina=int(receipt['paid']),payment_sequences=list(receipt['payment_sequences']),
            completion_sequence=int(receipt['completion_sequence']))
        row['model']=json.dumps(model,sort_keys=True)


def _created_feature(source):
    plain=str(source).split('#',1)[0]
    return next((feature for feature in LEVELS if plain==feature or plain.endswith('.'+feature)),None)


def _dormancy_sweep(engine,ending_id=None):
    """Reuse shared suppression markers and absolute clocks for incoming effects."""
    if engine.__dict__.get('_kensei_dormancy_sweeping'):
        return
    from .body_modes_scene_resources import available,bundle_of,feature_owned
    from .benefit_suppression import suppress,restore_suppressed,SUPPRESSED
    from .suppressed_effects import marker_alive
    if not any(kensei_body_profile(b) for b in getattr(engine,'typed_bundle_documents',())) and not any(c.source_definition_id==FAMILY+'#realm_dormancy' for a in engine.state.actors.values() for c in a.conditions.values()):
        return
    from ..movement_budget import speed_changed
    scope=FAMILY+'#realm_dormancy'
    engine._kensei_dormancy_sweeping=True
    try:
        before={a.entity_id:engine._effective_speed(a) for a in engine.state.actors.values()}
        for holder in engine.state.actors.values():
            for marker in list(holder.conditions.values()):
                if marker.condition_id!=SUPPRESSED or marker.source_definition_id!=scope:
                    continue
                model=marker.data.get('model') or {};feature=_created_feature(model.get('source_definition_id'))
                owner=engine.state.actors.get(model.get('source_actor_id'))
                if not marker_alive(engine,holder,marker,ending_id=ending_id) or (feature and owner and available(engine,owner,feature,LEVELS[feature],requires_conscious=False)):
                    restore_suppressed(engine,holder,marker.instance_id,reason='SOURCE_AVAILABLE_OR_EXPIRED')
            for kind,collection in (('modifier',holder.modifiers),('condition',holder.conditions)):
                for iid,effect_row in list(collection.items()):
                    if kind=='condition' and (effect_row.condition_id.startswith('condition:typed.state.') or effect_row.condition_id==SUPPRESSED):
                        continue
                    feature=_created_feature(effect_row.source_definition_id)
                    owner=engine.state.actors.get(effect_row.source_actor_id)
                    if not feature or owner is None or not feature_owned(bundle_of(engine,owner),feature):
                        continue
                    if available(engine,owner,feature,LEVELS[feature],requires_conscious=False):
                        continue
                    suppress(engine,owner,holder,kind+':'+iid,'source_unavailable',scope,
                        label='Dormant Kensei effect: its source is unavailable; its original duration continues.')
        for holder in engine.state.actors.values():
            delta=engine._effective_speed(holder)-before[holder.entity_id]
            if delta:speed_changed(engine,holder,delta,scope,reason='source availability')
    finally:
        engine.__dict__.pop('_kensei_dormancy_sweeping',None)


@hook('state_event')
def kensei_dormancy_boundaries(engine,event):
    if (event.event_type in {'CONDITION_APPLIED','CONDITION_REMOVED'} and event.payload.get('condition_id')=='condition:typed.cultivation_suppression'
            or event.event_type in {'TURN_STARTED','TURN_ENDED'}):
        _dormancy_sweep(engine,ending_id=event.actor_id if event.event_type=="TURN_ENDED" else None)


@hook('effect_resolution_scope')
def kensei_created_effect_scope(ctx,row):
    if not _created_feature(ctx.source) or row.get('type') not in {'state','speed','ac_bonus','reaction_denied','disadvantage','severing_arm','severing_flow'}:
        return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        ctx.typed={**ctx.typed,'numbers':dict(ctx.numbers)}
        before=_effect_instances(ctx.engine)
        yield
        _record_created_profiles(ctx,before)
        _dormancy_sweep(ctx.engine)
    return scope()


@hook('ac')
def severing_guard_nonstacking(engine,target):
    guards=[int(m.value) for m in target.modifiers.values() if m.source_definition_id==SEVERING_PALM+'#guard'
        and m.target_field=='armor_class' and m.operation=='ADD' and m.value in (-1,-2)]
    return min(guards)-sum(guards) if guards else 0


@hook('managed_effect_transfer')
def kensei_managed_effect(engine,holder,kind,item):
    """Continue actual source-created effects on recipients without reacquisition."""
    from .body_modes_scene_resources import bundle_of,feature_owned
    if kind=='condition' and item.source_definition_id==FAMILY+'#realm_dormancy':
        model=item.data.get('model') or {}
        feature=_created_feature(model.get('source_definition_id'))
        if not feature:return None
        owner=engine.state.actors.get(model.get('source_actor_id'))
    else:
        feature=_created_feature(item.source_definition_id)
        if not feature:return None
        owner=engine.state.actors.get(item.source_actor_id)
    if feature and owner is not None and feature_owned(bundle_of(engine,owner),feature):
        return True
    return None


@hook('journey_state_changed',priority=50)
def kensei_journey_dormancy(session,aid):
    import json
    from .body_modes_scene_resources import AUTHORITY,journey_available,feature_owned
    for actor in session.state['actors'].values():
        for row in actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[]):
            if row['kind']!='condition':continue
            marker=json.loads(row['model'])
            if marker.get('source_definition_id')!=FAMILY+'#realm_dormancy':continue
            data=marker.get('data',{});model=data.get('model') or {}
            feature=_created_feature(model.get('source_definition_id'));owner=model.get('source_actor_id')
            if not feature or owner not in session.state['actors']:continue
            if not feature_owned(session.state['actors'][owner]['bundle'],feature):continue
            if not journey_available(session,owner,feature,LEVELS[feature],requires_conscious=False):continue
            row.update(kind=data['kind'],model=json.dumps(model,sort_keys=True))


@hook('journey_property_values')
def kensei_journey_speed(props,session,aid):
    import json
    from fractions import Fraction
    from .body_modes_scene_resources import AUTHORITY,journey_available
    fixed={};half=False;expiries=[]
    for row in session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{}).get('effects',[]):
        if row['kind']!='modifier':continue
        model=json.loads(row['model']);feature=_created_feature(model.get('source_definition_id'))
        owner=model.get('source_actor_id')
        if not feature or owner not in session.state['actors'] or not journey_available(session,owner,feature,LEVELS[feature],requires_conscious=False):continue
        field=model.get('target_field');value=model.get('value')
        if field=='speed_ft' and model.get('operation')=='ADD' and type(value) is int and value<0:
            fixed[model['source_definition_id']]=min(fixed.get(model['source_definition_id'],0),value)
        elif field=='speed_halved':half=True
        else:continue
        if 'remaining_num' in row:expiries.append(session.clock()+Fraction(row['remaining_num'],row['remaining_den']))
    if not fixed and not half:return None
    result=dict(props)
    def adjusted(speed):
        total=int(speed)+sum(fixed.values())
        return max(0,total//2 if half else total)
    result['walk_speed_ft']=adjusted(result.get('walk_speed_ft',session.state['actors'][aid]['bundle']['actor_template']['speed_ft']))
    if result.get('fly_speed_ft') is not None:result['fly_speed_ft']=adjusted(result['fly_speed_ft'])
    if result.get('expiry_num') is not None:expiries.append(Fraction(result['expiry_num'],result['expiry_den']))
    if expiries:
        expiry=min(expiries);result.update(expiry_num=expiry.numerator,expiry_den=expiry.denominator)
    return result


def _available_authority(engine,actor,typed):
    from .body_modes_scene_resources import available
    profile=typed.get('kensei_abilities') or {}
    return {key:bool(profile.get(key) and available(engine,actor,'tianxia.path.body_refining.feature.'+feature,level))
        for key,feature,level in [('refined','refined_iron_fist',5),('heavenly','heavenly_fist',17)]}


@hook('integrated_feature_available')
def kensei_integration_availability(engine,actor,feature):
    if feature!=BLADE_FIST:return None
    return bool(_rows(engine,actor,'blade_fist'))


@hook('attack_count')
def kensei_normal_attack_count(ctx,effect,count):
    if ctx.typed.get('granted_attack') or effect.get('granted_attack_root') or count<=1:return None
    from .body_modes_scene_resources import bundle_of,available,effective_body_cl
    from ..typed_reactions import attacks_for_cl
    level=effective_body_cl(ctx.engine,ctx.actor)
    compiled=int(bundle_of(ctx.engine,ctx.actor).get('body_mode_level',bundle_of(ctx.engine,ctx.actor).get('cl') or 1))
    if level>=compiled:return None
    allowed=[1]
    for row in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id,[]):
        if row.get('block')!='extra_attack':continue
        source=row.get('feature_id','')
        if source.startswith('tianxia.path.body_refining.'):
            required=int(bundle_of(ctx.engine,ctx.actor).get('body_feature_levels',{}).get(source,5))
            if not available(ctx.engine,ctx.actor,source,required):continue
            table=(ctx.typed.get('kensei_abilities') or {}).get('extra_attack_sources',{}).get(source)
            allowed.append(attacks_for_cl(table or {'1':row['attacks']},level))
        else:allowed.append(int(row['attacks']))
    return min(count,max(allowed))


@hook('journey_state_changed',priority=60)
def kensei_journey_current_implement(session,aid):
    import json
    from .body_modes_scene_resources import AUTHORITY,feature_owned
    actor=session.state['actors'][aid]
    if not feature_owned(actor['bundle'],BLADE_FIST):return None
    current=_journey_blades(session,aid)
    owned={a['source_definition_id']:(a.get('parameters',{}).get('typed') or {}).get('source') for a in actor['bundle'].get('action_catalog',[])}
    for row in actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[]):
        if row['kind']!='condition':continue
        model=json.loads(row['model']);profile=model.get('data',{}).get('kensei_source')
        if not profile or model.get('source_actor_id')!=aid or owned.get(model.get('source_definition_id')) not in (PREFIX+FLOWING,PREFIX+SAINT):continue
        if current!=profile.get('integrated_blades'):
            profile['integrated_blades']=current
            row['model']=json.dumps(model,sort_keys=True)


def _journey_unconscious(actor):
    import json
    snapshot=actor.get('encounter_snapshot') or {}
    conditions=[json.loads(c) if isinstance(c,str) else c for c in snapshot.get('conditions',{}).values()]
    return bool(snapshot.get('life_state') in ('DYING','STABLE') or snapshot.get('current_hp',1)<=0
        or not snapshot.get('active',1) or any(c.get('condition_id','').endswith('unconscious') for c in conditions))


@hook('journey_airborne_support')
def kensei_hover_support(session,aid,properties):
    # Incapacitated alone cannot erase Hover. Actual Unconscious ends this state.
    return True if _journey_state(session,aid,SAINT) is not None and properties.get('flight_hover') else None


def _effect_instances(engine):
    return {(actor.entity_id,kind,key) for actor in engine.state.actors.values()
        for kind,collection in (('condition',actor.conditions),('modifier',actor.modifiers)) for key in collection}


def _record_created_profiles(ctx,before):
    """Native creation numbers, with actual instance/replay ancestry and no extra effect."""
    if not _created_feature(ctx.source):return
    from .retained_updates import record_instance_update
    for actor in ctx.engine.state.actors.values():
        for kind,collection in (('condition',actor.conditions),('modifier',actor.modifiers)):
            for key,item in list(collection.items()):
                if ((actor.entity_id,kind,key) in before or item.source_actor_id!=ctx.actor.entity_id
                    or item.source_definition_id!=ctx.source):continue
                item.source_cl=int(ctx.numbers['cl'])
                dc=ctx.save_dc if type(ctx.save_dc) is int else ctx.numbers.get('save_dc')
                if type(dc) is int:item.source_save_dc=dc
                record_instance_update(ctx.engine,actor,kind,key,item)


@hook('effect_source_profile')
def kensei_effect_source_profile(engine,item):
    from .body_modes_scene_resources import bundle_of,feature_owned
    feature=_created_feature(item.source_definition_id)
    if feature is None:return None
    owner=engine.state.actors.get(item.source_actor_id)
    if owner is None or not feature_owned(bundle_of(engine,owner),feature):return None
    profile=(getattr(item,'data',{}) or {}).get('kensei_source') or {}
    if 'source_cl' in profile:
        numbers=profile.get('numbers') or {}
        return {'source_cl':int(profile['source_cl']),**({'save_dc':int(numbers['save_dc'])} if 'save_dc' in numbers else {})}
    return None


def _derived_kensei_allowed(engine,actor,action):
    if action is not None and '#blade_fist_dex' in action.source_definition_id and not _rows(engine,actor,'blade_fist'):
        return False
    return None


@hook('candidate_allowed')
def kensei_derived_candidates(engine,actor,candidate,action):
    return _derived_kensei_allowed(engine,actor,action)


@hook('attack_allowed')
def kensei_derived_attack(ctx,target,effect):
    return _derived_kensei_allowed(ctx.engine,ctx.actor,ctx.action)


@hook('attack_sequence_start',priority=-100)
def kensei_dormant_finesse(ctx):
    if not (ctx.typed.get('kensei_abilities') or {}).get('finesse_from_blade_fist') or _rows(ctx.engine,ctx.actor,'blade_fist'):return None
    from . import run_strict
    replies=run_strict('weapon_property_available',ctx.engine,ctx.actor,ctx.typed,'Finesse')
    if any(type(v) is not bool for v in replies):raise ValueError('Weapon property availability requires boolean replies')
    if True in replies and False not in replies:return None
    import copy,re
    ctx.typed=copy.deepcopy(ctx.typed)
    weapon=ctx.typed.get('weapon') or {}
    weapon['properties']=', '.join(p.strip() for p in re.split('[,;|]',str(weapon.get('properties') or '')) if p.strip().casefold()!='finesse')


@hook('attack_sequence_start',priority=-200)
def kensei_actual_attack_numbers(ctx):
    if ctx.typed.get('kensei_abilities'):
        # The private packet/profile must carry the same actual numbers used by
        # rolls, formulas, Source-CL defenses and creation provenance.
        ctx.typed={**ctx.typed,'numbers':dict(ctx.numbers)}


def _saint_numbers(engine,actor,fallback):
    from .states import active
    held=active(engine,actor,SAINT)
    if held is None:return dict(fallback)
    return {**fallback,**(held.data.get('numbers') or {}),**((held.data.get('kensei_source') or {}).get('numbers') or {})}


@hook('attack_resolved_commit',priority=10000)
def kensei_flowing_reaction_completion(ctx,target,hit,effect):
    tag=ctx.typed.get('kensei_flowing_reaction') or {}
    if not tag or tag.get('actor_id')!=ctx.actor.entity_id or tag.get('action')!=ctx.source:return None
    from .granted_attacks import depth
    if depth(ctx.engine)!=tag['depth'] or not effect.get('granted_attack_root'):return None
    txn=getattr(ctx.engine,'_transaction_id',None)
    window=next((e for e in ctx.engine.events if e.sequence==tag['window'] and e.event_type=='REACTION_WINDOW_OPENED'
        and e.actor_id==ctx.actor.entity_id and e.source_definition_id==PREFIX+FLOWING and e.transaction_id==txn),None)
    if txn is None or window is None:return None
    if any(e.event_type=='REACTION_RESOLVED' and e.payload.get('reaction_window')==window.sequence for e in ctx.engine.events):return None
    rolls=[e.payload.get('roll_id') for e in ctx.engine.events if e.sequence>window.sequence
        and e.event_type=='ATTACK_ROLLED' and e.actor_id==ctx.actor.entity_id and e.source_definition_id==ctx.source]
    ctx.engine._append_event('REACTION_RESOLVED',PREFIX+FLOWING,actor_id=ctx.actor.entity_id,target_ids=(target.entity_id,),
        payload={'checkpoint':'ATTACK_MISSED','reaction_window':window.sequence,'attack_source':ctx.source,
            'attack_roll_ids':[r for r in rolls if r],'triggering_attacker':tag['attacker'],
            'log':'Flowing Blade Stance: its one granted attack has resolved; no Stamina cost.'})
