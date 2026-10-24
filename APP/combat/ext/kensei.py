"""Kensei Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities ... is applied"; rider lane C7
2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Kensei. "Integrated Blade" is a weapon of the Blade group
(combat/ext/integrated_weapons.py ``in_group(typed, "blade")``: daggers, swords, sabers and the other Blade Weapon Forms, and
cutting axes); an unarmed strike stays an unarmed strike.

Blade Fist      unarmed strikes may deal Slashing (path_riders unarmed_types add) and have a "(Dexterity)" variant when Dexterity
                beats the strike's own ability; Blade weapons get "(Constitution)" and "(Dexterity)" variants
                (integrated_weapons ``blade`` row). Once per turn on an unarmed or Blade hit, one choice (asked; the standing
                "Blade Fist: ..." button is the answer offered first): + Proficiency Bonus Slashing, Speed -5 until the start of
                your next turn, no Reactions until the start of its next turn, or draw/stow one carried Blade.
Severing Palm   once per turn on an unarmed or Blade hit, 4 Stamina (asked, with the area: the standing "Severing Palm: ..."
                button is offered first): Constitution save. Failure: Arm (Disadvantage on its weapon attacks), Leg (Speed
                halved), Breath (no Reactions), Flow (Disadvantage on Concentration saves and Cultivation Checks to maintain techniques) until the end of your next turn, or
                Guard (AC -2 until the start of your next turn); success: the same until the start of your next turn (Guard -1).
                A new one replaces the same area's earlier one from you.
Flowing Blade Stance  state "flowing_blade_stance": +1 AC (typed), unarmed and Blade attacks may deal Force or Slashing, once per
                turn after a hit a 5-foot move without provoking (asked), and after a typed melee attack by a creature within
                your reach misses you, your Reaction for one unarmed or Blade attack against it (asked).
Sword Draws Before Thought  saved initiative setup choice before any turn, unless Surprised: move half Speed without
                provoking, draw and strike, +2 AC until your first turn, or first-round first-attack Advantage.
Sword Saint Incarnation  state "sword_saint_incarnation": +2 AC (typed), Force or Slashing on unarmed and Blade attacks, once per
                turn + 3d8 Force or Slashing on an unarmed or Blade hit, +5 ft melee reach (reach_bonus), Opportunity Attacks
                against you have Disadvantage, and the reach area's Dexterity save (a zone following you; its failed-save
                choice is asked).
Every hook returns early for a creature without these rows or states.
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

    return actor is not None and bool(active(engine, actor, name))


def _stamp(engine: Any) -> str:
    actor = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{int(actor.turns_started) if actor else 0}"


def _blade_or_unarmed(ctx: Any, kind: str | None = None) -> bool:
    from .integrated_weapons import in_group

    unarmed = kind == "unarmed" or ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                                                    for e in ctx.typed.get("effects") or [])
    return unarmed or in_group(ctx.typed, "blade")


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
    """"You may use Dexterity instead of Strength or Constitution for Iron Fist attack and damage rolls."""
    import copy

    from ..gate2_runtime_models import EconomyKind

    dex = int((info.get("mods") or {}).get("DEX", 0) or 0)
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        weapon = typed.get("weapon") or {}
        if base.economy != EconomyKind.ACTION or ".natural." not in base.source_definition_id or "#" in base.source_definition_id or not weapon:
            continue
        if (base.parameters or {}).get("player_only"):
            continue
        swap = copy.deepcopy(typed)
        swap["numbers"]["attack_bonus"] = int(typed["numbers"].get("attack_bonus") or 0) - int(weapon.get("ability_modifier") or 0) + dex
        swap["weapon"]["damage"]["modifier"] = int(weapon["damage"].get("modifier") or 0) - int(weapon.get("ability_modifier") or 0) + dex
        swap["weapon"]["ability_modifier"] = dex
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#blade_fist_dex",
                                           "display_name": base.display_name + " (Dexterity)", "parameters": {**base.parameters, "typed": swap}}))
    return out


def _blade_handling_options(engine: Any, actor: Any, *, draw_only: bool = False) -> dict[str, tuple[Any, bool]]:
    """Use the table's possession, grip and free-hand model for one physical Blade."""
    from ..weapon_delivery import available_weapons
    from .hand_occupancy import weapon_grips, free_hands, resting_hands
    from .integrated_weapons import in_group

    ready = weapon_grips(engine, actor)
    free = len(free_hands(engine, actor))
    available = available_weapons(engine, actor)
    options = {key: (action, draw_only or key not in ready)
               for key, action in available.items()
               if in_group((action.parameters or {}).get("typed") or {}, "blade")
               and (key in ready or free >= resting_hands(action))}
    if draw_only and _rows(engine, actor, "blade_fist"):
        from .. import carry
        # Recorded integrated weapons may be manifested, not duplicated. Only
        # physical owned inventory records qualify, never a borrowed profile.
        for item in (carry.carrying_of(engine, actor.entity_id) or {}).get("items") or []:
            key = item.get("weapon_action")
            action = engine.action_catalog.get(key)
            displaced = any((r.data or {}).get("disables_action") == key and
                            ((r.data or {}).get("dropped_at") or (r.data or {}).get("held_by"))
                            for r in actor.conditions.values())
            if (displaced and key not in available and action is not None and action.owner_id == actor.entity_id
                    and not carry.quantity_exhausted(engine, actor, item)
                    and in_group((action.parameters or {}).get("typed") or {}, "blade")
                    and free >= resting_hands(action)):
                options[key] = (action, True)
    return options


def _handle_blade(engine: Any, actor: Any, intent: Any, source: str, *, draw_only: bool = False) -> bool:
    from .needle import ask, checkpoint_id
    from .equipment_hands import set_weapon_readiness

    from ..weapon_delivery import available_weapons
    available = available_weapons(engine, actor)
    options = _blade_handling_options(engine, actor, draw_only=draw_only)
    if not options:
        return False
    picked = ask(engine, intent, checkpoint_id(engine, "kensei_weapon", actor.entity_id), actor,
                 "choice:needle.kensei_weapon", list(options),
                 labels={key: ("Manifest " if key not in available else "Draw " if held else "Stow ") + action.display_name.removesuffix(" attack")
                         for key, (action, held) in options.items()},
                 target_id=actor.entity_id, name="Sword Draws Before Thought" if draw_only else "Blade Fist",
                 prompt=("Sword Draws Before Thought: draw a carried Blade or manifest a recorded integrated Blade into a free hand before the granted attack?"
                         if draw_only else "Blade Fist after the hit: draw or stow one Blade, without an Action or object interaction."))
    if picked and picked[0] in options:
        key = picked[0]
        if key not in available:
            from .. import carry
            item = carry.item_of(carry.carrying_of(engine, actor.entity_id), weapon_action=key)
            for iid, row in list(actor.conditions.items()):
                data = row.data or {}
                if (data.get("disables_action") == key or (item and data.get("item_key") == item["key"])) and (
                        data.get("dropped_at") or data.get("held_by") or row.condition_id == "condition:typed.disarmed"):
                    del actor.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id,
                        target_ids=(actor.entity_id,), payload={"condition_id": row.condition_id, "instance_id": iid,
                                                               "reason": "MANIFESTED"})
            for holder in engine.state.actors.values():
                carry.refresh(engine, holder, source)
        set_weapon_readiness(engine, actor, key, options[key][1], source=source, source_actor_id=actor.entity_id)
        return True
    return False


@hook("compile_bundle")
def blade_finesse(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    if BLADE_FIST not in info["owned_ids"]:
        return None
    import copy
    result = copy.deepcopy(bundle)
    for action in result["action_catalog"]:
        typed = (action.get("parameters") or {}).get("typed") or {}
        if ".natural." not in action["source_definition_id"] and ".natural." not in str(typed.get("opportunity_of") or ""):
            continue
        weapon = typed.get("weapon")
        if weapon is not None and "finesse" not in str(weapon.get("properties") or "").lower():
            weapon["properties"] = (str(weapon.get("properties") or "") + ", Finesse").strip(", ")
    return result


# ------------------------------------------------------------------------------------------------ Blade Fist
@effect("blade_fist_choice")
def blade_fist_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, BLADE_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, BLADE_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Blade Fist: {BLADE_OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def blade_fist(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind not in ("unarmed", "weapon") or actor.turn_flags.get("blade_fist") == _stamp(engine) or not _rows(engine, actor, "blade_fist") or not _blade_or_unarmed(ctx, kind):
        return
    if target is None or not target.active or target.team_id == actor.team_id:
        return
    actor.turn_flags["blade_fist"] = _stamp(engine)
    from .needle import ask, checkpoint_id

    labels = {"damage": f"+{int(actor.proficiency_bonus or 2)} Slashing damage", "speed": f"{target.display_name}'s Speed -5 until your next turn",
              "reactions": f"{target.display_name} cannot take Reactions until its next turn"}
    if _blade_handling_options(engine, actor):
        labels["draw"] = "Draw or stow one Blade weapon (no Action or object interaction)"
    standing = _standing(actor, BLADE_CHOICE, "damage")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "blade_fist", target.entity_id), actor, "choice:needle.blade_fist", list(labels),
                 labels=labels, preferred=[standing] if standing in labels else None, target_id=target.entity_id, name="Blade Fist",
                 prompt=f"Blade Fist: {ctx.action.display_name} hit {target.display_name}. Choose one.")
    choice = picked[0] if picked else (standing if standing in labels else "damage")
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}, effect_source=BLADE_FIST)
    if choice == "damage":
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": 0, "formula": "pb",
                                          "damage_types": ["slashing"], "evidence": "Blade Fist: Proficiency Bonus Slashing damage"}])
    elif choice == "draw":
        _handle_blade(engine, actor, ctx.intent, BLADE_FIST)
    elif choice == "speed":
        typed_executor.run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -5,
                                          "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Blade Fist: Speed -5"}])
    elif choice == "reactions":
        typed_executor.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target",
                                          "expires_on": "START_OF_TARGET_NEXT_TURN", "evidence": "Blade Fist: deny Reactions"}])


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
    if kind not in ("unarmed", "weapon") or target is None or not target.active or target.team_id == actor.team_id:
        return
    if actor.turn_flags.get("severing_palm") == _stamp(engine) or not _rows(engine, actor, "severing_palm") or not _blade_or_unarmed(ctx, kind):
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
    actor.turn_flags["severing_palm"] = _stamp(engine)
    engine._spend_resource(actor, STAMINA, 4, f"passive:{SEVERING_PALM}")
    long_end = f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}" if engine.state.current_actor_id == actor.entity_id else token("end", actor.entity_id, int(actor.turns_started) + 1)
    short = "START_OF_SOURCE_NEXT_TURN"

    def rows(until: str, guard: int) -> list[dict[str, Any]]:
        return {"arm": [{"type": "severing_arm", "expires_on": until}],
                "leg": [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": until}],
                "breath": [{"type": "reaction_denied", "applies_to": "target", "expires_on": until}],
                "flow": [{"type": "severing_flow", "expires_on": until}],
                "guard": [{"type": "ac_bonus", "applies_to": "target", "flat": guard, "expires_on": short}]}[area]
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


@effect("severing_flow")
def severing_flow(ctx: Any, row: dict[str, Any]) -> None:
    """One impairment with two distinct roll scopes, not a prose roll selector."""
    from ..typed_executor import save_provenance

    target = ctx.target
    if target is not None and target.active:
        origin = save_provenance(ctx)
        ctx.engine._apply_condition(target, "condition:typed.concentration_mode", ctx.source, ctx.actor.entity_id,
            expires_on=str(row.get("expires_on") or "START_OF_SOURCE_NEXT_TURN"),
            data={"rule": {"concentration_mode": "DISADVANTAGE", "severing_flow": 1},
                  "label": "Severing Palm (Flow): Disadvantage on Concentration saves and Cultivation Checks to maintain techniques",
                  **({"origin_save": origin} if origin else {})})


def _flow_mode(actor: Any, kind: str, hazards: Any) -> str | None:
    if kind != "cultivation" or not any(str(tag).startswith("maintain:") for tag in hazards or ()):
        return None
    if any(c.condition_id == "condition:typed.concentration_mode"
           and c.source_definition_id == SEVERING_PALM + "#flow"
           and ((c.data or {}).get("rule") or {}).get("severing_flow") == 1
           for c in actor.conditions.values()):
        return "DISADVANTAGE"
    return None


@hook("contest_check_mode")
def severing_flow_contest(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any]) -> str | None:
    return _flow_mode(subject, str(spec.get("kind") or ""), spec.get("hazards"))


@hook("ability_check_hazard_mode")
def severing_flow_check(engine: Any, actor: Any, ability: Any, skill: Any, against: Any, hazards: Any) -> str | None:
    context = engine.d20_context() or {}
    if context.get("actor_id") != actor.entity_id:
        return None
    return _flow_mode(actor, str(context.get("check_kind") or ""), hazards)


@hook("attack_mode")
def kensei_attack_modes(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is not None and (_state(engine, target, SAINT)) and (ctx.typed.get("opportunity_of") or getattr(engine, "_typed_oa_attacker", None) == actor.entity_id):
        return "DISADVANTAGE"  # Sword Saint: Opportunity Attacks against you have Disadvantage
    if ctx.typed.get("weapon") and any(c.condition_id == ARM for c in actor.conditions.values()) and ".natural." not in ctx.source:
        return "DISADVANTAGE"  # Severing Palm (Arm): its weapon attacks
    held = next((c for c in actor.conditions.values() if c.condition_id == FIRST_ATTACK), None)
    if held is not None and target is not None:
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


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "kensei_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "kensei")


@hook("after_hit")
def stance_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or target.team_id == actor.team_id or not _blade_or_unarmed(ctx, kind):
        return
    if _state(engine, actor, SAINT) and target.active and actor.turn_flags.get("_round_sword_saint_hit") != _stamp(engine):
        actor.turn_flags["_round_sword_saint_hit"] = _stamp(engine)
        from .. import typed_executor as te

        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["force", "slashing"],
                         "evidence": "Sword Saint Incarnation: once per turn + 3d8"}])
    if _state(engine, actor, FLOWING) and actor.turn_flags.get("_round_flowing_step") != _stamp(engine):
        actor.turn_flags["_round_flowing_step"] = _stamp(engine)
        _move(ctx, actor, 5, "choice:needle.flowing_blade_step", "Flowing Blade Stance")


def _strikes(engine: Any, actor: Any, target: Any) -> dict[str, Any]:
    """The fighter's unarmed and Blade attack actions that reach ``target``."""
    from ..typed_reactions import attack_reaches
    from .integrated_weapons import in_group

    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or str(getattr(action.economy, "value", action.economy)) != "ACTION" or typed.get("range_ft"):
            continue
        from .hand_occupancy import weapon_allowed
        if (action.parameters or {}).get("player_only") or weapon_allowed(engine, actor, action) is False:
            continue
        if "#" in action.source_definition_id and not any(tag in action.source_definition_id for tag in ("#integrated", "#blade_fist_dex")):
            continue
        if not (".natural." in action.source_definition_id or in_group(typed, "blade")):
            continue
        if engine._distance_actor_to_actor(actor, target) <= int(action.range_ft or 5) or attack_reaches(engine, actor, target, {"attack_kind": "unarmed"}):
            out[action.source_definition_id] = action
    return out


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])


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
    if target is None or not target.active or attacker.team_id == target.team_id or not _state(engine, target, FLOWING):
        return
    if ctx.typed.get("range_ft") or not target.reaction_available or not attacker.active:
        return
    from ..typed_executor import condition_rules

    if any(rule.get("no_reactions") for rule in condition_rules(target)):
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
def _surprised(actor: Any) -> bool:
    return any(c.condition_id.lower().removeprefix("condition:typed.").removeprefix("condition:") == "surprised"
               for c in actor.conditions.values())


@hook("fight_setup_tasks")
def sword_draws_tasks(engine: Any) -> list[dict[str, str]]:
    return [{"actor_id": aid, "source_id": PREFIX + "sword_draws_before_thought"}
            for aid in engine.state.initiative_order
            if _rows(engine, engine.state.actors[aid], "sword_draws") and not _surprised(engine.state.actors[aid]) ]


@hook("fight_setup")
def sword_draws(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    if source_id != PREFIX + "sword_draws_before_thought" or not _rows(engine, actor, "sword_draws"):
        return None
    # Initial scene conditions can be installed by match_start after tasks are sealed.
    if _surprised(actor):
        return True
    from .needle import ask, checkpoint_id
    from .. import typed_executor
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    labels = {"move": "Move up to half your Speed without provoking",
              "strike": "Draw a Blade and make one unarmed or integrated Blade attack against a creature in reach",
              "ac": "+2 AC until the start of your first turn",
              "advantage": "Advantage on your first attack roll during the first round"}
    picked = ask(engine, intent, checkpoint_id(engine, "sword_draws", actor.entity_id), actor, "choice:needle.sword_draws_before_thought", list(labels),
                 labels=labels, preferred=["advantage"], target_id=actor.entity_id,
                 name="Sword Draws Before Thought", prompt="Sword Draws Before Thought: the fight has begun. Choose one.")
    choice = picked[0] if picked else None
    action = ActionDefinition(source_definition_id=source_id, display_name="Sword Draws Before Thought",
                              owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF")
    ctx = typed_executor.Context(engine, actor, action, intent, {"numbers": {"pb": int(actor.proficiency_bonus or 2)}},
                                 [actor], actor, {})
    if choice == "move":
        _move(ctx, actor, int(engine._effective_speed(actor)) // 2, "choice:needle.sword_draws_move", "Sword Draws Before Thought")
    elif choice == "advantage":
        engine._apply_condition(actor, FIRST_ATTACK, PREFIX + "sword_draws_before_thought", actor.entity_id, expires_on="START_OF_SLOT_AT:2:0",
                                data={"label": "Sword Draws Before Thought: Advantage on your first attack roll this round"})
    elif choice == "ac":
        typed_executor.run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": 2, "source_owned": True,
                                         "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                         "evidence": "Sword Draws Before Thought: +2 AC until your first turn"}])
    elif choice == "strike":
        if not _handle_blade(engine, actor, intent, source_id, draw_only=True):
            return True
        foes = [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if a.active and a.team_id != actor.team_id and _strikes(engine, actor, a)]
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
    if mover.active and mover.team_id != occupant.team_id and _state(engine, mover, SAINT):
        return "difficult"
    return None
