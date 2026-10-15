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
BLADE_CHOICE = "condition:typed.blade_fist_choice"
SEVER_CHOICE = "condition:typed.severing_palm_choice"
ARM = "condition:typed.severing_arm"
FIRST_ATTACK = "condition:typed.sword_draws_first_attack"
BLADE_OPTIONS = {"damage": "Slashing Damage", "speed": "Speed -5", "reactions": "Deny Reactions", "draw": "Draw/Stow Blade"}
SEVER_OPTIONS = {"arm": "Arm", "leg": "Leg", "breath": "Breath", "flow": "Flow", "guard": "Guard"}


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("kind") == kind and row.get("block") in ("kensei", "path_rider")]


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
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.current_actor_id}:{current.turns_started if current else 0}"


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

    labels = {"damage": f"+{int(actor.proficiency_bonus or 2)} Slashing damage", "speed": f"{target.display_name}'s Speed -5 until your next turn",
              "reactions": f"{target.display_name} cannot take Reactions until its next turn",
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
    engine._spend_resource(actor, STAMINA, 4, f"passive:{SEVERING_PALM}")
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

    _clear_area(engine, actor, target, area)
    sub = _severing_context(ctx, target, area)
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target", "on_fail": rows(long_end, -2), "on_success": rows(short, -1),
                                      "evidence": "Severing Palm: Constitution saving throw"}])


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
    engine, actor = ctx.engine, ctx.actor
    held = next((c for c in actor.conditions.values() if c.condition_id == FIRST_ATTACK), None)
    if held is not None and target is not None and int(engine.state.round_number) == 1:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", PREFIX + "sword_draws_before_thought", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": FIRST_ATTACK, "instance_id": held.instance_id, "reason": "CONSUMED"})
        return "ADVANTAGE"
    return None


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
    paths = {cell_id(cell, include_altitude=spatial): (path, mode)
             for cell, (path, cost, mode) in granted_movement.routes(ctx.engine, mover, feet).items()}
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
        actor.turn_flags["_round_sword_saint_hit"] = _stamp(engine)
        from .. import typed_executor as te

        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}).with_source(PREFIX + SAINT + "#hit"),
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
        distance = engine._distance_actor_to_actor(actor, target)
        if rule:
            base = engine.action_catalog.get(rule.get("base"))
            if base is None or distance <= int(base.range_ft or 5):
                continue
        elif distance > int(action.range_ft or 5):
            continue
        if (distance <= current_reach(engine, actor, action)
                and engine._line_of_sight_actor_to_actor(actor, target)):
            out[action.source_definition_id] = action
    return out


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True, "attack_action": False}, [target], target, {}), [attack])


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
    if ctx.typed.get("range_ft") or ctx.typed.get("granted_attack") or not target.reaction_available or not attacker.active:
        return
    from ..typed_executor import condition_rules
    from .granted_attacks import allows_root

    if not allows_root(engine) or any(rule.get("no_reactions") for rule in condition_rules(target)):
        return
    action = _pick_strike(engine, ctx.intent, target, attacker, "choice:needle.flowing_blade_answer",
                          f"Flowing Blade Stance: {attacker.display_name} missed you. Use your Reaction to strike back?", decline=True)
    if action is None:
        return
    from .. import typed_reactions

    with activation(engine, target, PREFIX + FLOWING):
        typed_reactions._open(engine, {"feature_id": PREFIX + FLOWING}, target, (attacker.entity_id,), "ATTACK_MISSED")
        target.reaction_available = False
        _granted(engine, target, action, attacker, ctx.intent)


# ----------------------------------------------------------------------------------------- Sword Draws Before Thought
@hook("fight_setup_tasks")
def sword_draws_tasks(engine: Any) -> list[dict[str, str]] | None:
    return [{"actor_id": actor.entity_id, "source_id": PREFIX + "sword_draws_before_thought"}
            for actor in engine.state.actors.values() if actor.active and _rows(engine, actor, "sword_draws")
            and not any(str(c.condition_id).endswith(".surprised") for c in actor.conditions.values())] or None


@hook("fight_setup")
def sword_draws(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    if source_id != PREFIX + "sword_draws_before_thought" or not _rows(engine, actor, "sword_draws"):
        return None
    if actor.turn_flags.get("_round_sword_draws"):
        return True
    with activation(engine, actor, source_id):
        return _sword_draws_choice(engine, actor, intent)


def _sword_draws_choice(engine: Any, actor: Any, intent: Any) -> bool:
    actor.turn_flags["_round_sword_draws"] = 1
    from .needle import ask, checkpoint_id
    from .states import context

    labels = {"move": "Move up to half your Speed without provoking",
              "strike": "Draw or manifest one available Blade, then one unarmed or integrated Blade attack in reach",
              "ac": "+2 AC until the start of your first turn",
              "advantage": "Advantage on your first attack roll in the first round"}
    picked = ask(engine, intent, checkpoint_id(engine, "sword_draws", actor.entity_id), actor, "choice:needle.sword_draws_before_thought", list(labels),
                 labels=labels, preferred=["advantage"] if "advantage" in labels else None, allow_decline=True, target_id=actor.entity_id,
                 name="Sword Draws Before Thought", prompt="Sword Draws Before Thought: Initiative was rolled. Choose one before the first turn. No action or resource cost.")
    choice = picked[0] if picked else None
    ctx = context(engine, actor, PREFIX + "sword_draws_before_thought", [actor], {"pb": int(actor.proficiency_bonus or 2)}).with_source(PREFIX + "sword_draws_before_thought")
    ctx.intent = intent
    if choice == "move":
        _move(ctx, actor, int(engine._effective_speed(actor)) // 2, "choice:needle.sword_draws_move", "Sword Draws Before Thought")
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
        if source == PREFIX + SAINT and not any(e.get("type") == "zone" for e in typed.get("effects") or []):
            # Old immutable catalogs retain their sole historical zone provider.
            changed["kensei_native_reach"] = 1
        return action.model_copy(update={"parameters": {**action.parameters, "typed": changed}})
    if BLADE_FIST not in info["owned_ids"]:
        return None
    from .integrated_weapons import in_group
    weapon = typed.get("weapon")
    attacks = [e for e in typed.get("effects") or [] if e.get("type") == "attack"]
    if not weapon or not attacks:
        return None
    unarmed = any(e.get("attack_kind") == "unarmed" for e in attacks)
    if not unarmed and not in_group(typed, "blade"):
        return None
    changed = copy.deepcopy(typed)
    original_ability = ("CON" if "#integrated_con" in action.source_definition_id else
                        "DEX" if "#integrated_dex" in action.source_definition_id else weapon.get("ability", "STR"))
    changed["weapon"].update(ability=original_ability,
        ability_modifier=int(weapon.get("ability_modifier", info["mods"].get(original_ability, 0)))
        if "#integrated_con" not in action.source_definition_id else int(info["mods"].get("CON", 0)))
    magic = 0 if unarmed else int(typed.get("magic_bonus") or 0)
    if "#integrated_con" in action.source_definition_id:
        changed["numbers"]["attack_bonus"] = int(info["numbers"]["attack_bonus"]) + magic
    allowed = ["STR", "DEX", "CON"] if unarmed else ["DEX", "CON"]
    changed["kensei_abilities"] = {"options": {a: int(info["mods"].get(a, 0)) for a in allowed},
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
                + ("attack uses your Cultivation Attack Modifier" if a == "CON" else "add the ability once")
                for a, n in options.items()},
        preferred=[max(options, key=options.get)], target_id=target.entity_id, name="Blade Fist", feature_id=BLADE_FIST,
        prompt=f"Blade Fist: choose the ability for {ctx.action.display_name} against {target.display_name}. No additional action or Stamina cost.")
    if not choice:
        return
    selected = choice[0]
    select_strike_ability(ctx, spec, selected, options[selected], fixed_unarmed="fixed_damage" in (ctx.typed.get("weapon") or {}))
    if selected == "CON" and not held["unarmed"]:
        spec["attack_bonus"] = held["cultivation_attack_bonus"]
        spec["typed"]["numbers"]["attack_bonus"] = spec["attack_bonus"]


def _readiness(ctx: Any, *, allow_stow: bool) -> bool:
    """Use existing carried Blade instances and the shared grip transaction."""
    from .weapon_hits import available_weapons
    from .integrated_weapons import in_group, recorded_integration
    from .hand_occupancy import weapon_grips, free_hands, resting_hands
    from .equipment_hands import set_weapon_readiness
    from .needle import ask, checkpoint_id
    ready = weapon_grips(ctx.engine, ctx.actor)
    options = {}
    for key, weapon in available_weapons(ctx.engine, ctx.actor).items():
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
            or (ctx.typed.get("kensei_abilities") or {}).get("heavenly")) or not _blade_or_unarmed(ctx):
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
    from .reach_bonus import melee_reach
    if engine._distance_actor_to_actor(actor, subject) > melee_reach(engine, actor) or not engine._line_of_sight_actor_to_actor(actor, subject):
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
    typed = {**action.parameters['typed'], 'effects': []}
    ctx = Context(engine, actor, action, getattr(engine, '_active_intent', None), typed, [subject], subject, {}).with_source(PREFIX + SAINT)
    actor.turn_flags[key] = _stamp(engine)
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'sword_saint_reach_type', subject.entity_id), actor,
        'choice:needle.sword_saint_reach_type', ['force','slashing'], preferred=['force'],
        labels={kind: '3d8 ' + kind.title() + ' damage (half on a successful Dexterity save)' for kind in ('force','slashing')},
        target_id=subject.entity_id, name='Sword Saint Incarnation', feature_id=PREFIX + SAINT,
        prompt=f'Sword Saint Incarnation: {subject.display_name} entered your reach or started its turn there. Choose its damage type; no additional cost.')
    kind = chosen[0] if chosen else 'force'
    until = 'START_OF_TARGET_NEXT_TURN'
    run_effects(ctx, [{'type':'save','ability':'dex','applies_to':'target',
        'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':3,'sides':8},'damage_types':[kind]},
            {'type':'path_results','family':'sword_saint','name':'Sword Saint Incarnation','count':1,
             'prompt':'Sword Saint Incarnation: {target} failed its save; choose one.',
             'options':[{'label':'No Reactions','effects':[{'type':'reaction_denied','applies_to':'target','expires_on':until}]},
                        {'label':'Speed -10','effects':[{'type':'speed','applies_to':'target','flat':-10,'source_owned':True,'expires_on':until}]}]}],
        'on_success':[{'type':'half_damage','applies_to':'target','damage_types':[kind]},
            {'type':'speed','applies_to':'target','flat':-5,'source_owned':True,'expires_on':until}]}])


@hook('zone_arrival')
def saint_reach_entry(engine: Any, mover: Any, start: Any, end: Any, forced: bool) -> None:
    from .reach_bonus import melee_reach
    for owner in sorted(engine.state.actors.values(), key=lambda a:a.entity_id):
        if owner.entity_id == mover.entity_id or not _state(engine, owner, SAINT):
            continue
        reach = melee_reach(engine, owner)
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
    profile = ctx.typed.get('kensei_abilities') or {}
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
    profile = typed.get('kensei_abilities') or {}
    if actor is None or not _rows(engine, actor, 'blade_fist') or not (profile.get('refined') or profile.get('heavenly')):
        return None
    from .integrated_weapons import recorded_integration
    if recorded_integration(engine, actor, typed, 'blade'):
        return True
    return None


@hook('attack_damage_types')
def heavenly_blade_types(ctx: Any, attack: Any, kinds: list[str]) -> list[str] | None:
    if (ctx.typed.get('kensei_abilities') or {}).get('heavenly') and _rows(ctx.engine,ctx.actor,'blade_fist') and _blade_or_unarmed(ctx):
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
    return [{**row, "properties": (str(row.get("properties") or "") + ", Finesse").lstrip(", ")}
            if row.get("block") == "natural_weapon" and "finesse" not in str(row.get("properties") or "").lower()
            else row for row in passives]
