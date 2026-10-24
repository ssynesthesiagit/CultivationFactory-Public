"""Shinobi and Ninpo Adept Subpath features (owner 2026-09-28: "make sure all the talents and class abilities ... is
applied"; Tabik Damu's kit).

  Shadow Step       Bonus Action, 1 Qi, once per turn: teleport up to 15 feet from darkness, smoke or an obscured
                    area to a visible unoccupied square in one (effect "where": "darkness", combat/gate4_engine.py).
                    After it: the first Opportunity Attack against it before its next turn has Disadvantage, and Hidden
                    Strike qualifies for the rest of the turn; its next Stealth check has Advantage, and its owner
                    may draw or stow one possessed weapon, tool, talisman or implement through the shared gear model.
  Smoke Veil        its own smoke: it and its allies see through it (the PB creatures it chooses; on the table, its
                    side); "Smoke Veil: move" moves it up to 15 feet once each turn, no action, staying within 60 feet.
  Pressure-Point    asked on each qualifying hit (1 Stamina), the failed-save effect asked after the failure. Shared helper:
                    shinobi.py's Assassination calls ``pressure_point`` to apply it without Stamina.
  Shadow Afterimage the decoy is a creature of its own (combat/rules/summons.json: AC 13 + PB, 1 HP, no attacks);
                    "Shadow Exchange" (Bonus Action, 1 Stamina) swaps places with it within 60 feet.
  Hidden Strike     once per turn on a hit while the target can't see it (darkness, smoke, hidden, invisible) or after a
                    Shadow Step this turn: +2d6 (CL17 3d6) of the attack's damage type, then the chosen rider
                    (all five printed riders; manual owners choose after damage, AI uses its standing preference).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

STEP_OA = "condition:typed.shadow_step_oa"
SHADOW_STEP = "tianxia.subpath.qi.ninpo_adept.feature.shadow_step"
STEP_STEALTH = "condition:typed.shadow_step_stealth"
CHOICE = "condition:typed.hidden_strike_choice"
STAMINA = "resource:core.stamina"
HIDDEN = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"
AFTERIMAGE = "tianxia.subpath.body.shinobi.feature.shadow_afterimage"
STEALTH = "condition:typed.hidden_strike_stealth"
SMOKE_MARK = "condition:typed.hidden_strike_smoke_mark"
VANISHING = "tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique"
VANISH_STATE = "condition:typed.vanishing_state"
INVISIBLE = "condition:typed.invisible"
HIDDEN_RIDERS = {
    "withdraw": "Silent Withdrawal: move 5 feet without provoking Opportunity Attacks",
    "sever": "Sever Awareness: target cannot take Reactions until the start of your next turn",
    "vanish": "Vanishing Posture: Advantage on your next Stealth check before this turn ends",
    "mislead": "Misleading Impact: push or pull the target 5 feet",
    "smoke": "Smoke Mark: until the start of your next turn, the target cannot benefit from Invisible against you; know its direction inside your Smoke Veil",
}


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "ninpo" and row.get("kind") == kind]


@hook("compile_block")
def ninpo_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "ninpo":
        return None
    compiled = {**row, "block": "ninpo", "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1)}
    if spec.get("kind") in ("pressure_point", "hidden_strike"):
        compiled["choice_owner"] = True  # Manual owners choose even during another actor's turn.
    return [compiled]


# ------------------------------------------------------------------------------------------------ Shadow Step
@hook("teleport_settled")
def step_landed(ctx: Any, subject: Any, previous: Any, destination: Any, unwilling: bool) -> None:
    """Only a real landing in this use authorizes its after-teleport benefits.

    This is resolution-local evidence from the existing native landing seam;
    blocked/declined attempts never reach it. Nothing is installed by the hook.
    """
    from .ability_source import mechanic_of

    if subject is ctx.actor and mechanic_of(ctx.action) == SHADOW_STEP:
        ctx.damage_cache["shadow_step_landed"] = True


@effect("shadow_step_after")
def shadow_step_after(ctx: Any, eff: dict[str, Any]) -> None:
    if not ctx.damage_cache.get("shadow_step_landed"):
        return
    from .effect_durations import token

    ctx.actor.turn_flags["shadow_stepped"] = True
    ctx.engine._apply_condition(ctx.actor, STEP_OA, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "The first Opportunity Attack against it has Disadvantage (Shadow Step)"})
    # Sound next-check fragment from e0fc906e: use a distinct condition so
    # Hidden Strike's independently earned allowance retains its attribution.
    ctx.engine._apply_condition(ctx.actor, STEP_STEALTH, ctx.source, ctx.actor.entity_id,
                                expires_on=token("end", ctx.actor.entity_id, ctx.actor.turns_started),
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"}},
                                      "label": "Shadow Step: Advantage on your next Stealth check before this turn ends"})
    _step_item(ctx)


def _step_item_definition(item_id: str) -> dict[str, Any]:
    """Resolve printed gear eligibility, not words in an inventory display name.

    Mundane instruments have tool_rules. Treasure families classify tools,
    while Ch. 4 entry 85 explicitly supplies a talisman despite its functional
    family being Emergency Teleportation. Rods are implements. The pinned
    authorities remain the source of names and physical item identities.
    """
    from factory_authoring.starting_kits import item_definition
    from factory_authoring.treasure_catalog import authority

    mundane = item_definition(item_id)
    if (mundane.get("category") in {"weapon", "tool", "focus", "talisman", "implement"}
            or mundane.get("tool_rules")):
        return mundane
    treasure = next((row for row in authority()["wondrous"]
                     if row["treasure_id"] == item_id), {})
    if (treasure.get("family") in {"Appraisal Tool", "Crafting Tool", "Harvesting Tool", "Survey Tool"}
            or treasure.get("item_type") == "Rod"
            or item_id == "tianxia.treasure.wondrous.085.thunder_script_escape_talisman"):
        return treasure
    return {}


def _step_item(ctx: Any) -> None:
    """One optional real object, using public possession and hand identities."""
    from .scoundrel_riders import possessions, held_possessions, transfer_object
    from .hand_occupancy import free_hands, holding_hands
    from .needle import ask, checkpoint_id
    from dataclasses import replace

    engine, actor = ctx.engine, ctx.actor
    held = {item["object"] for item in held_possessions(engine, actor)}
    hands = free_hands(engine, actor)
    options, labels = {}, {}
    for item in possessions(engine, actor):
        definition = _step_item_definition(str(item.get("item_id") or ""))
        if item.get("worn") or not definition:
            continue
        identity = str(item["object"])
        locations = ["carried"] if identity in held else (
            [f"hand:{part}" for part in hands]
            if len(hands) >= holding_hands(engine, str(item.get("weapon_action") or "")) else [])
        for location in locations:
            key = f"{identity}|{location}"
            options[key] = (item, location)
            labels[key] = f"{'Stow' if location == 'carried' else 'Draw'} {item.get('name') or definition['name']}"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "shadow_step_item", actor.entity_id), actor,
                 "choice:needle.shadow_step_item", list(options), labels=labels,
                 allow_decline=True, default="decline", name="Shadow Step", feature_id=SHADOW_STEP,
                 target_id=actor.entity_id,
                 prompt=f"Shadow Step: after {actor.display_name} teleports, draw or stow one weapon, tool, talisman or implement, "
                        "or leave your gear as it is. This costs no extra action or resource, does not use the item, "
                        "and grants no proficiency.")
    if picked and picked[0] in options:
        item, location = options[picked[0]]
        transfer_object(replace(ctx, target=actor), {"item": item["key"], "object": item["object"],
            "as": "reposition", "from": "thief", "ability": "Shadow Step", "object_location": location})


@hook("attack_mode")
def step_oa(ctx: Any, target: Any) -> str | None:
    if getattr(ctx.engine, "_typed_oa_attacker", None) != ctx.actor.entity_id:
        return None
    if any(c.condition_id == STEP_OA for c in target.conditions.values()):
        ctx.engine._remove_condition(target, STEP_OA, ctx.source)
        return "DISADVANTAGE"
    return None


# ------------------------------------------------------------------------------------------------ Smoke Veil
@effect("zone_sight")
def zone_sight(ctx: Any, eff: dict[str, Any]) -> None:
    """Its own area does not hide anything from it (and its side, when ``team``)."""
    from .tabik_dark import republish, zone_made_now

    zone = zone_made_now(ctx)
    if zone is None:
        return
    zone.trigger_profile = {**zone.trigger_profile, "owner_sees": True, "team_sees": bool(eff.get("team"))}
    republish(ctx.engine, zone, ctx.source)


@hook("compile_actions")
def ninpo_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, short = info["owned_ids"], info["short"]
    out = []

    def make(key: str, name: str, economy: Any, effects: list[dict[str, Any]], *, target: str = "SELF", range_ft: int | None = None,
             costs: tuple = (), **parameters: Any) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.ninpo.{key}", display_name=name, owner_id=info["actor_id"],
                                economy=economy, resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=costs,
                                parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [],
                                                      "source": key}, "expected_damage": 0, **parameters})
    if "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil" in owned:
        out.append(make("smoke_veil_move", "Smoke Veil: move", EconomyKind.NONE,
                        [{"type": "move_zone", "zone_name": "Smoke Veil", "max_ft": 15, "range_ft": 60,
                          "evidence": "may move 15 feet once during each turn while remaining within 60 feet of you"}],
                        target="CELL", range_ft=60, player_only=True, any_cell=True, zone_mover="Smoke Veil"))
        out.append(make("veil_escape", "Veil Escape", EconomyKind.NONE,
                        [{"type": "veil_escape_move", "self_movement": True, "evidence": "move 5 feet without provoking"}],
                        target="SELF", player_only=True, veil_escape=True))
    if AFTERIMAGE in owned:
        out.append(make("shadow_exchange", "Shadow Exchange", EconomyKind.BONUS_ACTION, [{"type": "shadow_exchange", "self_movement": True}],
                        costs=((STAMINA, 1),), shadow_exchange=True))
    if VANISHING in owned:
        # Copy the native Step, including its costs, destination permissions and
        # after-teleport effects. Vanishing changes only its printed distance.
        for action in info["actions"]:
            if not action.source_definition_id.endswith(".feature.shadow_step"):
                continue
            typed = action.parameters.get("typed") or {}
            effects = [{**row, "distance_ft": 30} if row.get("type") == "teleport" else dict(row)
                       for row in typed.get("effects") or []]
            out.append(action.model_copy(update={
                "source_definition_id": action.source_definition_id + ".vanishing",
                "display_name": action.display_name + " (Vanishing: 30 feet)",
                "range_ft": 30,
                "parameters": {**action.parameters, "vanishing_step": True,
                               "typed": {**typed, "effects": effects}},
            }))
        if "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil" in owned:
            out.append(make("smoke_veil_move_vanishing", "Smoke Veil: move (Vanishing: 30 feet)", EconomyKind.NONE,
                            [{"type": "move_zone", "zone_name": "Smoke Veil", "max_ft": 30, "range_ft": 60}],
                            target="CELL", range_ft=60, any_cell=True,
                            zone_mover="Smoke Veil", vanishing_move=True))
    if HIDDEN in owned:
        for key, label in HIDDEN_RIDERS.items():
            out.append(make(f"hidden_strike.{key}", f"Hidden Strike: {label.split(':', 1)[0]}", EconomyKind.NONE,
                            [{"type": "hidden_strike_choice", "choice": key}], player_only=True, setting_only=True,
                            setting_description=f"Prefer {label} after Hidden Strike damage. No action or resource cost; manual owners still choose on each hit."))
    return out or None


def _in_own_smoke_veil(engine: Any, actor: Any) -> bool:
    """Veil Escape's trigger ("after entering your Smoke Veil or using Shadow Step into it") collapses to one
    check: the actor is now standing inside a Smoke Veil zone it owns, however it got there (walking in or
    Shadow Step's teleport both end with the actor's position inside the veil)."""
    from .. import zones
    from .tabik_dark import movable

    return any(zones._inside(engine, actor, zone) for zone in movable(engine, actor, "Smoke Veil"))


@hook("candidate_allowed")
def ninpo_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    mover = parameters.get("zone_mover")
    if mover == "Smoke Veil":
        from .tabik_dark import movable

        if bool(parameters.get("vanishing_move")) != vanishing_active(engine, actor):
            return False
        zones_ = movable(engine, actor, mover)
        aim = getattr(candidate, "destination", None)
        return bool(zones_) and not actor.turn_flags.get(f"moved_zone:{mover}") and aim is not None \
            and engine.grid.distance_ft(actor.position, aim) <= 60 and any(
                engine.grid.distance_ft(zone.center, aim) <= (30 if parameters.get("vanishing_move") else 15) for zone in zones_)
    if parameters.get("vanishing_step"):
        return None if vanishing_active(engine, actor) else False
    if action is not None and action.source_definition_id.endswith(".feature.shadow_step") and vanishing_active(engine, actor):
        return False
    if parameters.get("shadow_exchange"):
        return _afterimage(engine, actor) is not None
    if parameters.get("veil_escape"):
        return not actor.turn_flags.get("veil_escape_used") and _in_own_smoke_veil(engine, actor)
    return None


@effect("veil_escape_move")
def veil_escape_move(ctx: Any, eff: dict[str, Any]) -> None:
    """Once per turn after entering your Smoke Veil or using Shadow Step into it: move 5 feet without provoking
    Opportunity Attacks (a free player toggle offered only while candidate_allowed's check above holds)."""
    from ..typed_executor import block_movement

    ctx.actor.turn_flags["veil_escape_used"] = True
    block_movement(ctx, {"distance_ft": 5, "no_opportunity_attacks": True})


# ------------------------------------------------------------------------------------------------ Shadow Afterimage
def _afterimage(engine: Any, actor: Any) -> Any:
    from .. import summons

    return next((row for row in summons.owned_by(engine, actor.entity_id) if row.active and "shadow_afterimage" in row.entity_id
                 and engine._distance_actor_to_actor(actor, row) <= 60), None)


@effect("shadow_exchange")
def shadow_exchange(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    image = _afterimage(engine, actor)
    if image is None:
        return
    mine, theirs = actor.position, image.position
    actor.position, image.position = theirs, mine
    # The same shape as a teleport's (typed_executor block_movement): the replay reducer reads "destination".
    engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=actor.entity_id,
                         payload={"destination": theirs.model_dump(mode="json"), "path": [mine.model_dump(mode="json"), theirs.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True, "swap_with": image.entity_id})
    engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=image.entity_id,
                         payload={"destination": mine.model_dump(mode="json"), "path": [theirs.model_dump(mode="json"), mine.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True, "swap_with": actor.entity_id})
    from .. import zones

    zones.on_moved(engine, actor, mine, theirs, forced=True)
    zones.on_moved(engine, image, theirs, mine, forced=True)


# ------------------------------------------------------------------------------------------------ Hidden Strike
def unseen_for_hidden_strike(engine: Any, actor: Any, target: Any) -> bool:
    """Concealment qualifies; senses that actually see the attacker cancel it."""
    from ..target_knowledge import can_see

    return not can_see(engine, target, actor)


@hook("event")
def hidden_strike_visibility(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Remember sight at the roll, before damage can end an invisibility glamer."""
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not _rows(engine, actor, "hidden_strike"):
        return
    from .attack_scope import capture_roll

    frame = capture_roll(engine, kwargs)
    if frame is not None:
        target = engine.state.actors[frame["target_id"]]
        frame["ninpo_unseen"] = unseen_for_hidden_strike(engine, actor, target)


@hook("attack_roll_finished")
def hidden_strike_finished(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    """Copy only this completed roll's sight reading into its own rider context."""
    if not _rows(ctx.engine, ctx.actor, "hidden_strike"):
        return
    from .attack_scope import current

    frame = current(ctx.engine)
    ctx.damage_cache["ninpo_visibility"] = (roll_id, target.entity_id, bool(frame and frame.get("ninpo_unseen")))


@effect("hidden_strike_choice")
def hidden_strike_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Hidden Strike preference — {HIDDEN_RIDERS.get(str(eff.get('choice')), HIDDEN_RIDERS['sever'])}; no cost, choose again on each hit"})


@hook("after_hit_choice")
def hidden_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    rows = _rows(engine, actor, "hidden_strike")
    if not rows or not target.active:
        return
    current = engine.state.actors[engine.state.current_actor_id]
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    # _round_ keys survive the owner's turn reset; the value names the actual
    # current turn, including other creatures' turns and future rounds.
    if actor.turn_flags.get("_round_hidden_strike_turn") == turn:
        return
    if actor.turn_flags.get("hidden_strike") and "_round_hidden_strike_turn" not in actor.turn_flags:
        # A retained fight may carry the old boolean. Respect a use in this
        # turn only, rather than extending it over the owner's whole round.
        for event in reversed(engine.events):
            if event.event_type == "TURN_STARTED":
                break
            if event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == actor.entity_id and event.source_definition_id == f"passive:{HIDDEN}":
                return
    snapshot = ctx.damage_cache.get("ninpo_visibility")
    matching = bool(snapshot and snapshot[0] and snapshot[:2] ==
                    ((ctx.attack_result or {}).get("roll_id"), target.entity_id))
    unseen = snapshot[2] if matching else unseen_for_hidden_strike(engine, actor, target)
    # Shadow Step is a Bonus Action on the owner's turn; its qualification is
    # "during the current turn", unlike Hidden Strike's once-per-turn refresh.
    stepped_this_turn = bool(actor.turn_flags.get("shadow_stepped")) and engine.state.current_actor_id == actor.entity_id
    if not unseen and not stepped_this_turn:
        return
    actor.turn_flags["_round_hidden_strike_turn"] = turn
    count = 3 if int(rows[0].get("cl") or 1) >= 17 else 2
    dealt = next((event for event in reversed(engine.events[-30:]) if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    kind_ = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    from .. import typed_executor

    sub = ctx.on_hit_context(target, damage_cache={}).with_source(f"passive:{HIDDEN}")
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{HIDDEN}", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"trigger": "Hidden Strike"})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "damage_label": "Hidden Strike", "applies_to": "target", "dice": {"count": count, "sides": 6},
                                      **({"damage_types": [kind_.lower()]} if kind_ and kind_ != "UNTYPED" else {}), "evidence": "Hidden Strike"}])
    if not target.active:
        return
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    preferred = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "sever")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_rider", target.entity_id), actor,
                 "choice:needle.hidden_strike_rider", list(HIDDEN_RIDERS), labels=HIDDEN_RIDERS,
                 preferred=[preferred] if preferred in HIDDEN_RIDERS else ["sever"], target_id=target.entity_id,
                 name="Hidden Strike", feature_id=HIDDEN,
                 prompt=f"Hidden Strike: {ctx.action.display_name} hit {target.display_name}; bonus damage has been applied. "
                        "Choose one rider (no action, no resource cost).",
                 prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
    choice = picked[0] if picked and picked[0] in HIDDEN_RIDERS else "sever"
    if choice == "mislead":
        direction = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_direction", target.entity_id), actor,
                        "choice:needle.hidden_strike_direction", ["away", "toward"],
                        labels={"away": f"Push {target.display_name} 5 feet away from you", "toward": f"Pull {target.display_name} 5 feet toward you"},
                        target_id=target.entity_id, name="Hidden Strike — Misleading Impact", feature_id=HIDDEN,
                        prompt=f"Hidden Strike — Misleading Impact after {ctx.action.display_name}: push or pull {target.display_name} 5 feet (no action, no resource cost).",
                        prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
        typed_executor.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away",
                                          "evidence": "Misleading Impact: Push or pull 5 feet.",
                                          **({"direction": direction[0]} if direction else {})}])
    elif choice == "withdraw":
        from .needle import cell_options, free_cells, position_of, step_to

        cells = free_cells(engine, actor, 5) if engine._effective_speed(actor) > 0 else {actor.position: 0}
        options, labels = cell_options(engine, actor, cells)
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_withdraw", target.entity_id), actor,
                     "choice:needle.hidden_strike_withdraw", options, labels=labels, target_id=actor.entity_id,
                     name="Hidden Strike — Silent Withdrawal", feature_id=HIDDEN,
                     prompt=f"Hidden Strike — Silent Withdrawal after {ctx.action.display_name} hit {target.display_name}: "
                            "choose a space within 5 feet to move without provoking Opportunity Attacks (no action, no resource cost).",
                     prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
        if picked and picked[0] in options:
            step_to(engine, actor, position_of(picked[0]), sub.source)
    elif choice == "vanish":
        from .effect_durations import token

        engine._apply_condition(actor, STEALTH, sub.source, actor.entity_id, expires_on=token("end", current.entity_id, current.turns_started),
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"}},
                                      "label": "Hidden Strike — Vanishing Posture: Advantage on your next Stealth check before this turn ends; no cost"})
    elif choice == "smoke":
        engine._apply_condition(target, SMOKE_MARK, sub.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"owner_id": actor.entity_id, "label": f"Hidden Strike — Smoke Mark: Invisible gives no benefit against {actor.display_name} until its next turn; direction known inside its Smoke Veil; no cost"})
    else:
        typed_executor.run_effects(sub, [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                          "evidence": "Sever Awareness: Target cannot take Reactions until next turn."}])


@hook("event")
def vanishing_posture_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume the one-check benefit only after a Stealth check actually rolls."""
    if event_type != "CHECK_ROLLED":
        return
    payload = kwargs.get("payload") or {}
    if str(payload.get("check") or payload.get("skill") or "").lower() != "stealth":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is not None and any(c.condition_id == STEALTH for c in actor.conditions.values()):
        engine._remove_condition(actor, STEALTH, f"passive:{HIDDEN}")


@hook("event")
def step_stealth_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume an actual Stealth check, including either side of a contest."""
    if event_type != "CHECK_ROLLED":
        return
    from .roll_context import check_skill_receipts

    owners = {aid for aid, _, skill in check_skill_receipts(kwargs)
              if str(skill or "").casefold() == "stealth"}
    payload = kwargs.get("payload") or {}
    # Native Hide may share an already rolled check instead of drawing again.
    if "shared_total" in payload and str(payload.get("check") or "").casefold() == "stealth":
        owners.add(kwargs.get("actor_id"))
    for aid in owners:
        actor = engine.state.actors.get(aid)
        if actor is not None and any(c.condition_id == STEP_STEALTH for c in actor.conditions.values()):
            engine._remove_condition(actor, STEP_STEALTH, f"passive:{SHADOW_STEP}")


@hook("masked_conditions")
def smoke_mark_invisible(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """Ignore only the marked creature's Invisible benefit against its marker."""
    out = {}
    for bearer, other in ((attacker, target), (target, attacker)):
        if bearer is None or other is None or not _rows(engine, other, "hidden_strike"):
            continue
        if any(c.condition_id == SMOKE_MARK and c.data.get("owner_id") == other.entity_id for c in bearer.conditions.values()):
            out[bearer.entity_id] = {iid for iid, c in bearer.conditions.items() if c.condition_id == "condition:typed.invisible"}
    return out or None


@hook("status_description")
def smoke_mark_direction(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Read-only current direction for the Smoke Mark's existing status pill."""
    if holder is None or row.get("condition_id") != SMOKE_MARK:
        return None
    owner = engine.state.actors.get(data.get("owner_id"))
    if owner is None:
        return None
    from .. import zones

    inside = any(z.owner_id == owner.entity_id and z.trigger_profile.get("name") == "Smoke Veil" and zones._inside(engine, holder, z)
                 for z in zones.typed_zones(engine))
    dx, dy = holder.position.x - owner.position.x, holder.position.y - owner.position.y
    direction = " and ".join([*(["east" if dx > 0 else "west"] if dx else []), *(["south" if dy > 0 else "north"] if dy else [])]) or "at your position"
    return {"text": f"Smoke Mark: Invisible gives no benefit against {owner.display_name} until the start of its next turn. "
                    + (f"Direction from {owner.display_name}: {direction} (inside its Smoke Veil)." if inside else "Direction is known only inside its Smoke Veil."),
            "source_ability": "Hidden Strike", "handling": "No action or resource cost."}


# ------------------------------------------------------------------------------------------------ Pressure-Point Strike
PPS = "tianxia.subpath.body.shinobi.feature.pressure_point_strike"
PPS_CHOICE = "condition:typed.pressure_point_choice"
PPS_LABELS = {
    "reactions": "No Reactions until the start of its next turn",
    "speed": "Speed reduced by 10 feet until the start of its next turn",
    "attack": "Disadvantage on its next attack roll before the start of its next turn",
    "concentration": "Disadvantage on its next Concentration save before the start of its next turn",
    "whisper": "Cannot speak above a whisper until the start of its next turn",
}
PPS_OPTIONS = {key: f"prefer {label[0].lower() + label[1:]} (1 Stamina on an unarmed hit; once per turn)"
               for key, label in PPS_LABELS.items()}
PPS_OPTIONS["off"] = "don't spend Stamina (no effect)"


@hook("match_start")
def pressure_point_owner_metadata(engine: Any) -> None:
    """Expose legacy owners' decisions during AI turns without rewriting their saved bundle.

    Copy only engine-local passive metadata: no fight state, events or input documents change.
    """
    for actor_id, rows in (getattr(engine, "typed_passive_rows", {}) or {}).items():
        if not any(row.get("block") == "ninpo" and row.get("kind") in ("pressure_point", "hidden_strike") for row in rows):
            continue
        engine.typed_passive_rows[actor_id] = [
            {**row, "choice_owner": True} if row.get("block") == "ninpo" and row.get("kind") in ("pressure_point", "hidden_strike") else row
            for row in rows]


@hook("compile_actions")
def pressure_point_choices(info: dict[str, Any]) -> list[Any] | None:
    if PPS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.ninpo.pressure_point.{key}", display_name=f"Pressure-Point Strike: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "pressure_point_choice", "choice": key}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in PPS_OPTIONS.items()]


@effect("pressure_point_choice")
def pressure_point_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, PPS_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, PPS_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Pressure-Point Strike: {PPS_OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def pressure_point_strike(ctx: Any, target: Any, kind: str) -> None:
    """Once per turn, 1 Stamina on an unarmed hit: choose after a failed Constitution save.

    Standing picks are AI/default preferences; "off" keeps the Stamina. Success only denies Reactions.
    """
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or not target.active or actor.turn_flags.get("pressure_point_strike") or not _rows(engine, actor, "pressure_point"):
        return
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == PPS_CHOICE), "reactions")
    if choice == "off" or actor.resources.get(STAMINA, 0) < 1:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "pressure_point", target.entity_id), actor, "choice:needle.pressure_point_strike", ["use"],
                 labels={"use": f"1 Stamina: {target.display_name} makes a Constitution save"}, allow_decline=True, target_id=target.entity_id,
                 name="Pressure-Point Strike", feature_id=PPS,
                 prompt=f"Pressure-Point Strike: {ctx.action.display_name} hit {target.display_name}. Spend 1 Stamina "
                        "(once per turn) for a Constitution save, then choose an effect on failure; on success it cannot "
                        "take Reactions until the start of its next turn.")
    if not picked:
        return
    engine._spend_resource(actor, STAMINA, 1, f"passive:{PPS}")
    pressure_point(ctx, target, preferred=choice)


def pressure_point(ctx: Any, target: Any, *, preferred: str = "reactions") -> None:
    """Shared helper (shinobi.py's Assassination applies it without Stamina): the once-per-turn Constitution save and its asked
    failed-save effect. Nothing happens when this turn's use is spent."""
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("pressure_point_strike") or target is None or not target.active:
        return
    actor.turn_flags["pressure_point_strike"] = True
    until = "START_OF_TARGET_NEXT_TURN"
    labels = {k: v for k, v in PPS_OPTIONS.items() if k != "off"}
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}).with_source(f"passive:{PPS}")
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target",
                                      "on_fail": [{"type": "pressure_point_result", "preferred": preferred if preferred in labels else "reactions"}],
                                      "on_success": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": until}],
                                      "evidence": "Pressure-Point Strike: Constitution saving throw"}])


def _pps_results(until: str) -> dict[str, list[dict[str, Any]]]:
    return {"reactions": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": until}],
            "speed": [{"type": "speed", "flat": -10, "applies_to": "target", "expires_on": until}],
            "attack": [{"type": "pressure_point_attack"}],
            # Both real since 2026-09-29 (combat/concentration.py save_mode; combat/speech.py Silenced).
            "concentration": [{"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw", "expires_on": until,
                               "evidence": "Pressure-Point Strike: Disadvantage on its next Concentration saving throw before the start of its next turn."}],
            "whisper": [{"type": "condition", "condition": "silenced", "applies_to": "target", "expires_on": until,
                         "evidence": "Pressure-Point Strike: it cannot speak above a whisper until the start of its next turn."}]}


@effect("pressure_point_failed_choice")  # retained saved effects share the same implementation
@effect("pressure_point_result")
def pressure_point_result(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed-save effect, asked after the failure (the standing button's choice offered first)."""
    from .. import typed_executor
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    target = ctx.target
    if target is None or not target.active:
        return
    labels = PPS_LABELS
    preferred = str(eff.get("preferred") or "reactions")
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "pressure_point_result", target.entity_id), ctx.actor, "choice:needle.pressure_point_result",
                 list(labels), labels=labels, preferred=[preferred], target_id=target.entity_id, name="Pressure-Point Strike", feature_id=PPS,
                 prompt=f"Pressure-Point Strike: {target.display_name} failed its Constitution save after {ctx.action.display_name}. "
                        "Choose one effect until the start of its next turn. Normally this use costs 1 Stamina (once per turn); "
                        "Assassination grants it without spending Stamina.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, target))
    choice = picked[0] if picked and picked[0] in labels else preferred
    typed_executor.run_effects(ctx, _pps_results("START_OF_TARGET_NEXT_TURN")[choice])


@effect("pressure_point_attack")
def pressure_point_attack(ctx: Any, eff: dict[str, Any]) -> None:
    if ctx.target is not None:
        from ..typed_executor import stated_expiry

        # Resolve "its next turn" for the target, including a hit on another creature's turn.
        expires = stated_expiry(ctx, {"expires_on": "START_OF_TARGET_NEXT_TURN"}, ctx.target)
        ctx.engine._add_modifier(ctx.target, ctx.source, "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on=expires)


# ------------------------------------------------------------------------------------------ Vanishing Technique
@hook("compile_action")
def vanishing_action(action: Any, info: dict[str, Any]) -> Any | None:
    if VANISHING not in info["owned_ids"] or not action.source_definition_id.endswith(".feature.vanishing_technique"):
        return None
    typed = action.parameters.get("typed") or {}
    # The generic unconditional OA modifier cannot express the printed sense
    # exception. Keep the native Invisible/Stealth grants and replace that row.
    effects = [row for row in typed.get("effects") or [] if row.get("type") != "disadvantage"]
    return action.model_copy(update={"parameters": {**action.parameters,
        "typed": {**typed, "min_cl": 14, "effects": [*effects, {"type": "vanishing_state"}]}}})


def _vanishing_states(engine: Any, actor: Any) -> list[Any]:
    from .. import concentration
    from .effect_durations import due

    return [state for state in actor.conditions.values()
            if state.condition_id == VANISH_STATE
            and not due(engine, state.expires_on)
            and state.data.get("concentration_started_sequence") in concentration.copies(actor, state.source_definition_id)]


def vanishing_active(engine: Any, actor: Any) -> bool:
    """Public Ninpo state query for Vanishing's Step/Veil modifiers.

    Invisible may be temporarily absent; only the owned minute and its exact
    Concentration copy authorize these benefits. No state means no change.
    """
    return bool(_vanishing_states(engine, actor))


@effect("vanishing_state", harmful=False)
def vanishing_state(ctx: Any, eff: dict[str, Any]) -> None:
    current = ctx.actor.concentration
    if current is None or current.source_definition_id != ctx.source:
        return
    ctx.engine._apply_condition(ctx.actor, VANISH_STATE, ctx.source, ctx.actor.entity_id,
        expires_on=ctx.expires_on(), data={"concentration_started_sequence": int(current.started_sequence),
            "label": "Vanishing Technique: for 1 minute with Concentration, Invisible except after harmful actions until turn end; Shadow Step and Smoke Veil movement 30 feet, Stealth Advantage; 5 Qi, once per scene"})


def _vanishing_reveal(engine: Any, actor: Any) -> None:
    """Reveal only this feature's own grants, preserving unrelated sources.

    Reused from e0fc906e:APP/combat/ext/tabik_ninpo.py, tightened to evented,
    copy-owned primitive state rather than a transient turn flag.
    """
    from .. import concentration

    for state in _vanishing_states(engine, actor):
        starts = concentration.copies(actor, state.source_definition_id)
        grants = [held for held in actor.conditions.values()
                  if held.condition_id == INVISIBLE
                  and held.source_definition_id == state.source_definition_id
                  and held.source_actor_id == state.source_actor_id
                  and concentration.owner_copy(concentration.made_at(held.instance_id, held), starts)
                  == state.data["concentration_started_sequence"]]
        if not grants:
            continue
        # Event the pending turn boundary before removing Invisible. Native
        # condition updates and exact instance endings both survive replay.
        engine._update_condition_data(actor, state, {**state.data,
            "reveal_turn": f"{engine.state.round_number}:{engine.state.current_slot_index}"}, state.source_definition_id)
        for held in grants:
            engine._remove_condition_instance(actor, held.instance_id, held.source_definition_id,
                                               actor_id=actor.entity_id, expected=held)


@hook("event", nested=True)
def vanishing_harm(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Observe actual native attacks/damage/conditions/fields, never movement.

    Damage to any creature counts, including damage absorbed by temporary HP;
    enemy team alone never turns a beneficial condition into hostile harm.
    """
    if event_type not in {"ATTACK_ROLLED", "ATTACK_LOCATION_MISSED", "DAMAGE_COMMITTED", "OBJECT_UPDATED", "CONDITION_APPLIED", "ZONE_CREATED"}:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not vanishing_active(engine, actor):
        return
    payload = kwargs.get("payload") or {}
    harmful = event_type in {"ATTACK_ROLLED", "ATTACK_LOCATION_MISSED"}
    if event_type == "DAMAGE_COMMITTED":
        harmful = int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0
    elif event_type == "OBJECT_UPDATED":
        harmful = int((payload.get("damage") or {}).get("taken") or 0) > 0
    elif event_type == "CONDITION_APPLIED":
        from .karma_causes import inflicted_harm
        harmful = any(target_id != actor.entity_id and inflicted_harm(engine, payload, target_id)
                      for target_id in kwargs.get("target_ids") or ())
    elif event_type == "ZONE_CREATED":
        from ..effect_harm import classify_effect
        profile = (payload.get("zone") or {}).get("trigger_profile") or {}
        harmful = any(classify_effect(row) is True for row in [*profile.get("triggers", []), *profile.get("inside", [])])
    if harmful:
        _vanishing_reveal(engine, actor)


@hook("after_save")
def vanishing_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..effect_harm import classify_effect
    from .karma_causes import HARMFUL_CONDITIONS

    effect = getattr(ctx, "save_effect", None)
    # The shared save producer names a save's adverse consequences even when no exact block packet exists (custom callers
    # such as weather_shroud.throw): damage, damage type, unwilling transport, harmful conditions and forced movement.
    # The printed trigger is forcing the save, so this applies whatever the outcome.
    adverse = {str(name) for name in named or ()}
    hostile = (effect is not None and classify_effect(effect, saving_throw=True) is True) or bool(
        adverse & (HARMFUL_CONDITIONS | {"forced_movement", "damaging_save", "unwilling_spatial_transport"})
        or any(name.startswith("damage:") for name in adverse))
    if subject is not None and subject.entity_id != ctx.actor.entity_id and hostile:
        _vanishing_reveal(ctx.engine, ctx.actor)


@hook("forced_movement_committed")
def vanishing_manipulation(engine: Any, actor: Any, subject: Any, distance_ft: int, kind: str, unwilling: bool = True) -> None:
    # Printed trigger: "directly manipulating an unwilling creature". The receipt carries the row's willingness;
    # a consenting creature's push does not reveal. No consent is inferred from team, name or damage.
    if unwilling and subject.entity_id != actor.entity_id and distance_ft > 0:
        _vanishing_reveal(engine, actor)


@hook("teleport_settled")
def vanishing_teleport(ctx: Any, subject: Any, start: Any, destination: Any, unwilling: bool) -> None:
    if unwilling and subject.entity_id != ctx.actor.entity_id:
        _vanishing_reveal(ctx.engine, ctx.actor)


@hook("attack_mode")
def vanishing_opportunity(ctx: Any, target: Any) -> str | None:
    if getattr(ctx.engine, "_typed_oa_attacker", None) != ctx.actor.entity_id or not vanishing_active(ctx.engine, target):
        return None
    from .. import senses
    # Query a projected Invisible subject even while harmful actions have
    # revealed it: ordinary sight is not perceiving Invisible creatures.
    probe = target.model_copy(deep=True)
    state = _vanishing_states(ctx.engine, target)[0]
    probe.conditions["vanishing:sense-probe"] = state.model_copy(update={"condition_id": INVISIBLE})
    if not senses.perceives(ctx.engine, ctx.actor, probe, locate_concealed=True):
        return "DISADVANTAGE"
    return None


def _boundary(engine: Any) -> tuple[int, int]:
    return int(engine.state.round_number), int(engine.state.current_slot_index)


def _reveal_due(stamp: Any, now: tuple[int, int]) -> bool:
    """A reveal stamped at or before the current turn boundary is due. Any later turn-end harm (Shroud throws, Unmaking upkeep)
    can stamp the boundary after this hook has run, so a stamp that the boundary has passed still restores at the next
    turn end rather than being stranded forever."""
    try:
        round_number, slot = (int(part) for part in str(stamp).split(":"))
    except ValueError:
        return False
    return (round_number, slot) <= now


# turn_end_settled runs after the whole native turn-end dispatch and Second Ruin Form upkeep, so a reveal stamped by
# any turn-end harm (including upkeep that damages the owner) is restored at this same boundary.
@hook("turn_end_settled")
def vanishing_restore(engine: Any, actor: Any) -> None:
    now = _boundary(engine)
    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for state in _vanishing_states(engine, holder):
            if not _reveal_due(state.data.get("reveal_turn"), now):
                continue
            engine._update_condition_data(holder, state,
                {key: value for key, value in state.data.items() if key != "reveal_turn"}, state.source_definition_id)
            engine._apply_condition(holder, INVISIBLE, state.source_definition_id, state.source_actor_id,
                expires_on=state.expires_on, data={
                    "concentration_started_sequence": state.data["concentration_started_sequence"],
                    "label": "Invisible (Vanishing Technique): restored at turn end; no Hide required"})
