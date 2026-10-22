"""Metal rider gates, bound to reviewed owner text (riders lane 4).

``first_zone_subject`` runs the nested rows for the first creature to trigger that
zone, even if it succeeds on the save. The zone id comes from zones._run's event;
an evented mark on the creator records consumption for that particular casting.
``metal_severance`` denies healing if Bloodied or damaged by Slashing/Piercing in
this round (including the triggering hit, which precedes this on-hit line).
Ring the Flaw's successful check places a target-bound mark; only the marker's
next Metal attack consumes its Advantage, before the end of their next turn.
Uses documented extension hooks; no saved-fight fields or equipment facts are invented here.

``metal_canon`` stores the selected signs as evented active-state data. Its
after_hit_choice hook applies one sign, once on the user's turn, to every Metal attack
without the compiler's optional-variant caps. Menu buttons set the sign preset;
activation and its rest use are paid only when entering the state.

Weight uses the same preset-menu system to select Sharpen or a push/pull on
qualifying Metal hits. Triggered No Action menus carry their definitions on
their buttons (menus.py), since there is no standalone cast to catalogue.
The Marrow guard uses the final damage-floor checkpoint, including no-intent
packets inside an action transaction, and the shared forced-distance checkpoint
for its printed opposed check against forced movement. Its owner chooses the
save and, at Nascent Soul, the hostile thorn targets through the ordinary
recorded choice transport. Custom condition data are snapshot state; event-only
replay is not asserted.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook

CANON = "TAL_METAL_WHITE_TIGER_SEVEN_SLAUGHTER_CANON"
CANON_NAME = "Seven-Slaughter Canon"
CANON_MENU = "seven_slaughter_sign"
MOUNTAIN = "TAL_METAL_MOUNTAIN_ORE_DICTATE"
MOUNTAIN_REPEAT = "condition:typed.mountain_ore_repeat"
MARROW = "condition:typed.iron_marrow_sutra"
WEIGHT = "METAL_BASE_WEIGHT"
EXPRESSION_MENU = "metal_base_expression"
DOMAIN = "TAL_METAL_DOMAIN_OF_TEN_THOUSAND_BLADES"
DOMAIN_GATE = "typed_modifier_once:" + DOMAIN


def apply_metal_expression(ctx: Any, target: Any, choice: str) -> None:
    """Shared printed base effects for normal Weight and domain bonus expressions."""
    from ..typed_executor import Context, block_damage, block_save

    inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    if choice == "Sharpen":
        block_damage(inner, {"type": "extra_damage", "formula": "pb", "damage_types": ["slashing", "piercing"]})
    else:
        block_save(inner, {"ability": "STR", "max_size_cells": 2, "on_fail": [
            {"type": "forced_movement", "applies_to": "target",
             "direction": "away" if "Push" in choice else "toward", "distance_ft": 5}]})


def domain_supplied_expression(ctx: Any, target: Any) -> bool:
    """Transient identity for this hit; later hits keep their ordinary allowance."""
    latest_hit = next((event.sequence for event in reversed(ctx.engine.events)
                       if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id
                       and event.source_definition_id == ctx.source), 0)
    return ctx.damage_cache.get("_metal_domain_hit") == (target.entity_id, latest_hit)


@hook("damage_dealt")
def domain_expression(ctx: Any, target: Any, amount: int) -> None:
    """One optional expression per owner turn in an active, source-typed owned domain.

    Damage-triggered expressions share no allowance with the normal hit-triggered
    expressions. The transient cache prevents applying both on the triggering hit;
    only the integer turn flag persists. Pauses propagate through damage_dealt.
    """
    from .needle import CHOICE, ask, checkpoint_id

    if ctx.damage_cache.get("_metal_domain_running"):
        return
    actor, engine = ctx.actor, ctx.engine
    source = str(ctx.typed.get("source") or "")
    if (not is_metal(ctx.action) or source.startswith("METAL_BASE_")
            or engine.state.current_actor_id != actor.entity_id or actor.turn_flags.get(DOMAIN_GATE)
            or ctx.intent is None or not target.active):
        return
    eligible = False
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != actor.entity_id:
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters or {}).get("typed") or {} if action else {}
        if typed.get("source") != DOMAIN or not any(row.get("domain_expression") for row in typed.get("effects") or []):
            continue
        if engine._footprint_intersects(target, zone.affected_cells):
            eligible = True
            break
    if not eligible:
        return
    options = ["Sharpen"]
    if engine._footprint(target).width_cells <= 2:
        options += ["Weight: Push 5 feet", "Weight: Pull 5 feet"]
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "metal_domain", actor.entity_id, target.entity_id), actor,
                 CHOICE + "metal_domain_expression", options, allow_decline=True, target_id=target.entity_id,
                 name="Domain of Ten Thousand Blades",
                 prompt=f"Domain of Ten Thousand Blades: {ctx.action.display_name} damaged {target.display_name}. "
                        "Use Weight or Sharpen without consuming its normal use this turn?")
    if not chosen:
        return
    actor.turn_flags[DOMAIN_GATE] = 1
    ctx.damage_cache["_metal_domain_running"] = True
    try:
        apply_metal_expression(ctx, target, chosen[0])
    finally:
        ctx.damage_cache.pop("_metal_domain_running", None)
    latest_hit = next((event.sequence for event in reversed(engine.events)
                       if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor.entity_id
                       and event.source_definition_id == ctx.source), 0)
    ctx.damage_cache["_metal_domain_hit"] = (target.entity_id, latest_hit)


@hook("effect_allowed")
def domain_replaces_normal_expression(ctx: Any, row: dict[str, Any]) -> bool | None:
    """The bonus expression replaces the normal expression on this hit, preserving its use."""
    if (row.get("source_modifier") in (WEIGHT, "METAL_BASE_SHARPEN") and ctx.target is not None
            and domain_supplied_expression(ctx, ctx.target)):
        return False
    return None


def is_metal(action: Any) -> bool:
    source = str(((action.parameters or {}).get("typed") or {}).get("source") or "")
    return source.startswith(("METAL_BASE_", "TAL_METAL_", "tianxia.talent.metal."))


@hook("candidate_allowed")
def hide_expression_container(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    # The printed Weight has no standalone activation; its menu buttons choose the next on-hit expression.
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") == WEIGHT and any(row.get("id") == EXPRESSION_MENU for row in typed.get("effects") or []):
        return False
    return None


@hook("after_hit")
def weight_on_hit(ctx: Any, target: Any, kind: str) -> None:
    from . import menus

    if (not is_metal(ctx.action) or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or ctx.engine._footprint(target).width_cells > 2
            or domain_supplied_expression(ctx, target)):
        return
    picks = menus.picks(ctx.engine, ctx.actor, EXPRESSION_MENU)
    selected = next((pick for pick in picks if pick.startswith("Weight: ")), None)
    if selected is None or ctx.actor.turn_flags.get("typed_modifier_once:" + WEIGHT):
        return
    ctx.actor.turn_flags["typed_modifier_once:" + WEIGHT] = True
    apply_metal_expression(ctx, target, selected)


@effect("metal_canon")
def enter_canon(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry, mark_condition_id

    cid = mark_condition_id(CANON_NAME, ctx.actor.entity_id)
    ctx.engine._remove_condition(ctx.actor, cid, ctx.source)
    ctx.engine._apply_condition(ctx.actor, cid, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {"duration": {"kind": "one_minute"}}, ctx.actor, condition=True),
        data={"signs": eff["signs"], "numbers": dict(ctx.numbers), "label": CANON_NAME,
              "critical_recovery": eff.get("effects") or [],
              "additional_target": int(bool(eff.get("nascent_additional_target")) and int(ctx.numbers.get("cl", 1)) >= 15)})


@hook("damage_dealt")
def canon_damage_history(ctx: Any, target: Any, amount: int) -> None:
    """Evented same-owner-turn Metal damage, including damage before activation.

    Only owners of the source-typed Nascent upgrade record history. This covers
    the documented typed damage checkpoint, not native legacy damage paths.
    """
    from ..typed_executor import mark_condition_id

    actor, engine = ctx.actor, ctx.engine
    if amount <= 0 or not is_metal(ctx.action) or engine.state.current_actor_id != actor.entity_id:
        return
    owned = any(typed.get("source") == CANON and int(typed.get("numbers", {}).get("cl", 1)) >= 15
                and any(row.get("nascent_additional_target") for row in typed.get("effects") or [])
                for action_id in actor.action_ids
                if (action := engine.action_catalog.get(action_id)) is not None
                for typed in [(action.parameters or {}).get("typed") or {}])
    if not owned:
        return
    cid = mark_condition_id("Canon Metal damage this turn", actor.entity_id)
    old = next((c for c in actor.conditions.values() if c.condition_id == cid), None)
    targets = list(old.data.get("targets", [])) if old and old.data.get("turn") == actor.turns_started else []
    if target.entity_id in targets:
        return
    targets.append(target.entity_id)
    engine._remove_condition(actor, cid, ctx.source)
    engine._apply_condition(actor, cid, ctx.source, actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"turn": actor.turns_started, "targets": targets})


@hook("attack_result")
def canon_critical_recovery(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Optional once-per-activation recovery; meaningful-enemy kills need provenance.

    One choice combines using the benefit and selecting exactly one condition
    instance to end. The evented activation marker carries consumption across turns
    and table reload. No-intent callers cannot request a player's decision.
    """
    from ..typed_executor import Context, mark_condition_id, run_effects
    from .needle import CHOICE, ask, checkpoint_id
    from .riders_shared import remove_benefit_condition

    if not critical or not hit or not is_metal(ctx.action) or ctx.intent is None:
        return
    actor, engine = ctx.actor, ctx.engine
    cid = mark_condition_id(CANON_NAME, actor.entity_id)
    active = next((c for c in actor.conditions.values() if c.condition_id == cid), None)
    if active is None or active.data.get("recovery_used") or not active.data.get("critical_recovery"):
        return
    conditions = [c for c in actor.conditions.values()
                  if str(c.condition_id).lower() in ("condition:core.frightened", "condition:core.charmed",
                                                     "condition:typed.frightened", "condition:typed.charmed")]
    options = [c.instance_id for c in conditions] or ["Recover CP"]
    labels = {}
    for index, condition in enumerate(conditions, 1):
        source_action = engine.action_catalog.get(condition.source_definition_id)
        source_actor = engine.state.actors.get(condition.source_actor_id)
        origin = source_action.display_name if source_action else source_actor.display_name if source_actor else "unknown source"
        name = condition.data.get("label") or condition.condition_id.rsplit(".", 1)[-1].title()
        labels[condition.instance_id] = f"Recover CP and end {name} from {origin} (effect {index})"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "canon_recovery", actor.entity_id, target.entity_id),
                 actor, CHOICE + "metal_canon_recovery", options, labels=labels, allow_decline=True,
                 name="White Tiger Seven-Slaughter Canon",
                 target_id=target.entity_id,
                 prompt=f"White Tiger Seven-Slaughter Canon: {ctx.action.display_name} critically hit "
                        f"{target.display_name}. Recover CP and end one Frightened or Charmed effect on yourself?")
    if not picked:
        return
    remove_benefit_condition(engine, actor, active, "CANON_RECOVERY_USED")
    engine._apply_condition(actor, cid, active.source_definition_id, active.source_actor_id,
                            expires_on=active.expires_on, data={**active.data, "recovery_used": 1})
    inner = Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "numbers": active.data["numbers"]},
                    [actor], actor, ctx.damage_cache)
    run_effects(inner, active.data["critical_recovery"])
    selected = next((c for c in conditions if c.instance_id == picked[0]), None)
    if selected is not None:
        remove_benefit_condition(engine, actor, selected, "CANON_RECOVERY")


@hook("after_hit_choice")
def canon_sign(ctx: Any, target: Any, kind: str) -> None:
    from ..typed_executor import Context, mark_condition_id, run_effects
    from . import menus
    from .needle import CHOICE, ask, checkpoint_id
    from .riders_shared import remove_benefit_condition

    actor, engine = ctx.actor, ctx.engine
    if not is_metal(ctx.action) or engine.state.current_actor_id != actor.entity_id:
        return
    cid = mark_condition_id(CANON_NAME, actor.entity_id)
    active = next((c for c in actor.conditions.values() if c.condition_id == cid), None)
    if active is None or actor.turn_flags.get("typed_modifier_once:" + CANON):
        return
    picked = menus.picks(engine, actor, CANON_MENU)
    if ctx.intent is not None:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "canon_sign", actor.entity_id, target.entity_id),
                     actor, CHOICE + "metal_canon_sign", [row["label"] for row in active.data["signs"]],
                     preferred=picked, name="White Tiger Seven-Slaughter Canon", target_id=target.entity_id,
                     prompt=f"White Tiger Seven-Slaughter Canon: {ctx.action.display_name} hit {target.display_name}. Choose one slaughter sign.")
    sign = next((row for row in active.data["signs"] if row["label"] in picked), None)
    if sign is None:
        return
    first = active.data.get("sign_round") != engine.state.round_number
    extra = []
    if first and active.data.get("additional_target") and ctx.intent is not None:
        history_id = mark_condition_id("Canon Metal damage this turn", actor.entity_id)
        history = next((c for c in actor.conditions.values() if c.condition_id == history_id
                        and c.data.get("turn") == actor.turns_started), None)
        eligible = sorted((other for other in engine.state.actors.values()
                           if history and other.entity_id in history.data.get("targets", [])
                           and other.entity_id != target.entity_id and other.active
                           and engine._distance_actor_to_actor(actor, other) <= 30), key=lambda other: other.entity_id)
        extra = ask(engine, ctx.intent, checkpoint_id(engine, "canon_extra", actor.entity_id, target.entity_id),
                    actor, CHOICE + "metal_canon_extra", [other.entity_id for other in eligible],
                    labels={other.entity_id: other.display_name for other in eligible}, allow_decline=True,
                    name="White Tiger Seven-Slaughter Canon",
                    target_id=target.entity_id,
                    prompt=f"White Tiger Seven-Slaughter Canon: {ctx.action.display_name} hit {target.display_name}. "
                           f"Apply {sign['label']} to one additional creature damaged by your Metal talent this turn?")
    if active.data.get("additional_target"):
        remove_benefit_condition(engine, actor, active, "CANON_SIGN_ROUND")
        engine._apply_condition(actor, cid, active.source_definition_id, active.source_actor_id,
                                expires_on=active.expires_on,
                                data={**active.data, "sign_round": engine.state.round_number})
    actor.turn_flags["typed_modifier_once:" + CANON] = True
    typed = {**ctx.typed, "numbers": active.data["numbers"]}
    inner = Context(engine, actor, ctx.action, ctx.intent, typed, [target], target, ctx.damage_cache)
    run_effects(inner, sign["effects"])
    if extra:
        other = engine.state.actors[extra[0]]
        run_effects(Context(engine, actor, ctx.action, ctx.intent, typed, [other], other, ctx.damage_cache), sign["effects"])


@hook("technique_used")
def schedule_mountain_repeat(ctx: Any) -> None:
    """Retain the casting's area for a fresh owner choice at the next turn start."""
    from ..typed_executor import effect_expiry

    if ctx.typed.get("source") != MOUNTAIN or not any(row.get("repeat_owner") for row in ctx.typed.get("effects") or []):
        return
    made = next((event for event in reversed(ctx.engine.events) if event.event_type == "ZONE_CREATED"
                 and event.source_definition_id == ctx.source), None)
    if made is None:
        return
    ctx.engine._apply_condition(ctx.actor, MOUNTAIN_REPEAT, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {"duration": "until_end_of_your_next_turn"}, ctx.actor, condition=True),
        data={"zone_id": made.payload["zone"]["zone_id"], "turn": ctx.actor.turns_started,
              "label": "Mountain-Ore Dictate: repeat chosen effect at your next turn start"})


@hook("turn_start")
def repeat_mountain(engine: Any, actor: Any) -> None:
    from ..typed_executor import Context, _area_targets, run_effects
    from .needle import CHOICE, ask, checkpoint_id
    from . import menus

    for marker in list(actor.conditions.values()):
        if marker.condition_id != MOUNTAIN_REPEAT or actor.turns_started <= marker.data["turn"]:
            continue
        # Remove just this casting's marker (multiple areas can coexist).
        del actor.conditions[marker.instance_id]
        engine._append_event("CONDITION_REMOVED", marker.source_definition_id, actor_id=actor.entity_id,
            target_ids=(actor.entity_id,), payload={"condition_id": marker.condition_id, "instance_id": marker.instance_id})
        zone = engine.state.zones.get(marker.data["zone_id"])
        action = engine.action_catalog.get(marker.source_definition_id)
        if zone is None or action is None:
            continue
        typed = dict(action.parameters["typed"])
        intent = getattr(engine, "_active_intent", None)
        menu = next(row for row in typed["effects"] if row.get("type") == "menu")
        choice = ask(engine, intent, checkpoint_id(engine, "mountain_repeat", actor.entity_id, zone.zone_id),
                     actor, CHOICE + "mountain_ore_repeat", menu["options"],
                     preferred=menus.picks(engine, actor, menu["id"]), name="Mountain-Ore Dictate",
                     prompt=f"Mountain-Ore Dictate: {actor.display_name}'s turn starts. Choose the repeated effect affecting "
                            + ", ".join(other.display_name for other in engine.state.actors.values()
                                        if engine._footprint_intersects(other, zone.affected_cells)) + ".")
        typed["_area_centre"] = (zone.center.x, zone.center.y)
        subjects = _area_targets(engine, actor, zone.center, typed["area"])
        ctx = Context(engine, actor, action, intent, typed, subjects, subjects[0] if len(subjects) == 1 else None,
                      {"_checkpoint_aim": zone.center})
        rows = [dict(row) for row in typed["effects"] if row.get("type") not in ("zone", "menu")
                and (not row.get("menu") or row.get("option") in choice)]
        for row in rows:
            row.pop("menu", None)
            row.pop("option", None)
            if row.get("type") == "save" and choice == ["Buried iron edges"]:
                # TURN_STARTED runs inside the locked event dispatcher. Damage
                # there suppresses downstream event riders; do not silently
                # apply an incomplete packet. The save can still ask its owner.
                row["on_fail"] = [{"type": "gm", "evidence":
                    "Mountain-Ore Dictate: failed repeated Dexterity save; apply 4d8 Piercing damage (GM: lock round 3 needs a deferred damage checkpoint with downstream riders)."}]
        if choice and choice[0] in menu.get("gm", {}):
            rows.append({"type": "gm", "evidence": menu["gm"][choice[0]]})
        run_effects(ctx, rows)


@effect("metal_marrow_state")
def enter_marrow(ctx: Any, eff: dict[str, Any]) -> None:
    """Track the Sutra's save-to-stay-at-1-HP rider through ordinary evented state."""
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, MARROW, ctx.source)
    ctx.engine._apply_condition(ctx.actor, MARROW, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {"duration": "one_minute"}, ctx.actor, condition=True),
        data={"numbers": dict(ctx.numbers), "attempt_round": 0, "label": "Indestructible Iron Marrow Sutra"})


def _remove_source(engine: Any, actor: Any, source: str) -> None:
    """End this activation only, preserving other sources even if their condition names coincide."""
    for iid, condition in list(actor.conditions.items()):
        if condition.source_definition_id != source:
            continue
        del actor.conditions[iid]
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid})
    for mid, modifier in list(actor.modifiers.items()):
        if modifier.source_definition_id == source:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid})


@hook("choice_reactors")
def marrow_choosers(engine: Any) -> tuple[str, ...]:
    """Enroll active Sutra owners for manual choices during an AI actor's action."""
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if any(c.condition_id == MARROW for c in actor.conditions.values()))


@hook("damage_floor", priority=10)
def marrow_floor(engine: Any, target: Any, pending: int, damage_type: str, source_id: str,
                 source_actor_id: str | None, intent: Any) -> int | None:
    """Optional save after every defense, including packets with no own intent.

    The enclosing action supplies the turn-boundary decision transport. A bare
    engine caller without a provider retains the historical automatic attempt.
    The shared save helper is no longer registered at the earlier would_drop
    checkpoint, so a packet cannot attempt twice or roll before final reductions.
    Priority 10 runs after default-priority nonlethal choices even when this
    module was imported before plug-in discovery; accepted Mercy is then known.
    """
    state = next((c for c in target.conditions.values() if c.condition_id == MARROW), None)
    provenance = engine.damage_context()
    if provenance is not None:
        from .body_iron_fist import MERCIFUL_HAND_ID
        from .packet_decisions import recorded_for_packet

        if (provenance.component == "primary"
                and recorded_for_packet(engine, MERCIFUL_HAND_ID, target.entity_id, provenance.roll_id)):
            return None
    if (state is None or not target.active or target.current_hp <= 0
            or pending < target.current_hp + target.temporary_hp
            or state.data["attempt_round"] == engine.state.round_number):
        return None
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context
    from ..history_text import history_name

    actor = engine.state.actors.get(source_actor_id)
    context = action_context(engine, actor, source_id, target)
    context["action_name"] = context["action_name"] or history_name(source_id, {})
    selected = ask(engine, intent, checkpoint_id(engine, "marrow_save", target.entity_id, source_id), target,
        CHOICE + "marrow_save", ["save"], allow_decline=True,
        labels={"save": "Make the Constitution save; success leaves you at 1 HP and ends the Sutra"},
        name="Indestructible Iron Marrow Sutra", feature_id=state.source_definition_id,
        target_id=target.entity_id, prompt_context=context,
        prompt=f"Indestructible Iron Marrow Sutra: {context['action_name']} would reduce {target.display_name} "
               "to 0 HP. Make a Constitution saving throw against your own Metal Save DC? "
               "On success, stay at 1 HP and the Sutra ends. Once per round; no action or resource cost.")
    if not selected:
        return None
    remaining = marrow_save(engine, target, pending, source_actor_id, intent=intent,
                            trigger_name=context["action_name"])
    return 1 if remaining is not None else None


@hook("forced_distance")
def marrow_holds_ground(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    """The active Sutra stays put unless the moving effect wins its opposed check."""
    state = next((c for c in mover.conditions.values() if c.condition_id == MARROW), None) if mover else None
    if (state is None or not mover.active or mover.current_hp <= 0
            or any("unconscious" in str(c.condition_id).lower() for c in mover.conditions.values())):
        return None
    if source is None:
        # An unattributed force cannot win the opposed check required by the rule.
        return max(0, int(distance_ft))

    from .. import ext
    from ..typed_executor import Context, check_modes

    def source_action() -> Any | None:
        transaction_id = getattr(engine, "_transaction_id", None)
        accepted = next((event for event in reversed(engine.events)
                         if event.event_type == "INTENT_ACCEPTED" and event.actor_id == source.entity_id
                         and event.transaction_id == transaction_id), None)
        return engine.action_catalog.get(accepted.source_definition_id) if accepted is not None else None

    trigger = source_action()
    trigger_typed = (trigger.parameters or {}).get("typed") or {} if trigger is not None else {}
    trigger_numbers = trigger_typed.get("numbers") or {}
    intent = getattr(engine, "_active_intent", None)

    def check(actor: Any, opponent: Any, action: Any, numbers: dict[str, Any], reason: str) -> Any:
        source_qualified = action is not None
        if action is None:
            # The hook has no source-qualified typed check context for legacy or
            # unattributed movement. Do not borrow another action's ability bonus.
            from ..gate2_runtime_models import ActionDefinition
            action = ActionDefinition(source_definition_id=reason, display_name=reason,
                owner_id=actor.entity_id, economy="NONE", resolution_kind="TYPED",
                target_kind="HOSTILE_ENTITY")
        typed = (action.parameters or {}).get("typed") or {}
        ctx = Context(engine, actor, action, intent, typed, [], opponent)
        modifier = (int(actor.proficiency_bonus or 0) if source_qualified else 0) + int(numbers.get("key_mod") or 0)
        modifier += sum(ext.run("check_bonus", ctx, actor))
        modes = check_modes(actor, "ALL", engine=engine, against_creature=opponent)
        mode = modes.pop() if len(modes) == 1 else "NORMAL"
        source_id = action.source_definition_id
        with engine.d20_scope({"kind": "check", "actor_id": actor.entity_id,
                               "target_id": opponent.entity_id, "source_id": source_id,
                               "source_actor_id": actor.entity_id, "ability": "ALL", "reason": reason}):
            roll = engine.roller.d20(modifier=modifier, actor_id=actor.entity_id,
                                     reason=reason, mode=mode)
        engine._record_roll(roll)
        return roll

    metal_action = engine.action_catalog.get(state.source_definition_id)
    mover_roll = check(mover, source, metal_action, (state.data or {}).get("numbers") or {},
                       f"CHECK:{state.source_definition_id}:Metal Check")
    source_roll = check(source, mover, trigger, trigger_numbers,
                        f"CHECK:{trigger.source_definition_id if trigger is not None else 'forced movement'}:forced movement")
    held = int(mover_roll.total) >= int(source_roll.total)
    if held:
        engine._append_event("GM_RIDER", state.source_definition_id, actor_id=mover.entity_id,
            target_ids=(mover.entity_id, source.entity_id), payload={"rider":
                f"Indestructible Iron Marrow Sutra (3 CP, 1 minute): {mover.display_name} stays in place against "
                f"{source.display_name}'s forced movement after winning or tying the Metal Check "
                f"({mover_roll.total} to {source_roll.total})."})
        return max(0, int(distance_ft))
    return None


def marrow_save(engine: Any, target: Any, pending: int, source_actor_id: str | None, *,
                intent: Any = None, trigger_name: str = "incoming damage") -> int | None:
    from ..typed_executor import Context, _deal, _roll
    from ..gate2_runtime_models import DiceSpec

    state = next((c for c in target.conditions.values() if c.condition_id == MARROW), None)
    if state is None or state.data["attempt_round"] == engine.state.round_number or target.current_hp <= 0:
        return None
    data = {**state.data, "attempt_round": engine.state.round_number}
    engine._remove_condition(target, MARROW, state.source_definition_id)
    engine._apply_condition(target, MARROW, state.source_definition_id, target.entity_id,
                            expires_on=state.expires_on, data=data)
    dc = int(data["numbers"]["save_dc"])
    roll = engine._roll_save(target, "CON", dc, state.source_definition_id)
    if roll is None or roll.total < dc:
        return None
    action = engine.action_catalog[state.source_definition_id]
    foes = [foe for foe in engine.state.actors.values() if foe.active and foe.team_id != target.team_id
            and engine._distance_actor_to_actor(target, foe) <= 10]
    chosen: list[str] = []
    if int(data["numbers"].get("cl") or 1) >= 15 and foes:
        from .needle import CHOICE, ask, checkpoint_id
        chosen = ask(engine, intent, checkpoint_id(engine, "marrow_thorns", target.entity_id), target,
            CHOICE + "marrow_thorns", [foe.entity_id for foe in foes], minimum=0, maximum=len(foes),
            allow_decline=True, default="all", name="Indestructible Iron Marrow Sutra",
            feature_id=state.source_definition_id, target_id=target.entity_id,
            labels={foe.entity_id: f"{foe.display_name}: 3d8 + Constitution modifier Piercing damage" for foe in foes},
            prompt=f"Indestructible Iron Marrow Sutra saves {target.display_name} from {trigger_name} dropping them to 0 HP. "
                   "Choose any hostile creatures within 10 feet for the immediate metal thorns: "
                   "3d8 + your Constitution modifier Piercing damage; no action or resource cost.")
    _remove_source(engine, target, state.source_definition_id)
    if int(data["numbers"].get("cl") or 1) >= 15:
        ctx = Context(engine, target, action, None, {"numbers": data["numbers"]}, [], None, {})
        amount = _roll(ctx, DiceSpec(count=3, sides=8, modifier=int(data["numbers"].get("con_mod") or 0)), "IRON_MARROW_THORNS")
        for foe in foes:
            if foe.entity_id in chosen:
                _deal(ctx, foe, amount, "PIERCING")
    return max(0, target.current_hp + target.temporary_hp - 1)


@hook("event")
def filings_clock(engine: Any, event_type: str, kwargs: Any) -> None:
    """Core Formation's cloud survives the next turn start and ends at its end."""
    from ..typed_executor import _walk_rows

    if event_type != "ZONE_CREATED":
        return
    row = (kwargs.get("payload") or {}).get("zone") or {}
    zone = engine.state.zones.get(row.get("zone_id"))
    if zone is None or "metal_filings_end_turn" in zone.trigger_profile:
        return
    action = engine.action_catalog.get(zone.source_definition_id)
    typed = (action.parameters or {}).get("typed") or {} if action else {}
    if not any(e.get("metal_filings_clock") for e in _walk_rows(typed.get("effects") or [])):
        return
    if int((typed.get("numbers") or {}).get("cl") or 1) < 10:
        return
    owner = engine.state.actors[zone.owner_id]
    zone = zone.model_copy(update={"duration_rounds": None,
        "trigger_profile": {**zone.trigger_profile, "metal_filings_end_turn": owner.turns_started + 1}})
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                         payload={"zone": zone.model_dump(mode="json")})


@hook("turn_end")
def end_filings(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .. import zones
    from .effect_durations import custom_turn_due

    for zone in list(engine.state.zones.values()):
        turn = zone.trigger_profile.get("metal_filings_end_turn")
        if zone.owner_id == actor.entity_id and turn is not None and custom_turn_due(
                actor, turn, zone.per_turn_triggered, "metal_filings", nominal=nominal):
            zones.remove(engine, zone, "DURATION_ENDED")


@hook("nominal_slot_boundary")
def nominal_filings(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        end_filings(engine, actor, nominal=True)


@hook("attack_mode")
def ring_advantage(ctx: Any, target: Any) -> str | None:
    from ..typed_executor import bears_mark, mark_condition_id

    if is_metal(ctx.action) and bears_mark(target, ctx.actor.entity_id, "Ring the Flaw"):
        ctx.engine._remove_condition(target, mark_condition_id("Ring the Flaw", ctx.actor.entity_id), ctx.source)
        return "ADVANTAGE"
    return None


@effect("first_zone_subject")
def first_zone_subject(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    event = next((event for event in reversed(ctx.engine.events)
                  if event.event_type == "PASSIVE_TRIGGERED" and event.source_definition_id == ctx.source
                  and (event.payload or {}).get("zone_id") and not (event.payload or {}).get("history_hidden")), None)
    if event is None:
        return
    name = f"First subject: {event.payload['zone_id']}"
    if te.bears_mark(ctx.actor, ctx.actor.entity_id, name):
        return
    te.block_mark(ctx, {"mark": name, "applies_to": "self", "duration": {"kind": "until_end_of_your_next_turn"}})
    te.run_effects(ctx, eff.get("effects") or [])


@effect("metal_severance")
def metal_severance(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import block_healing_reduction
    from .blood_bloodied import is_bloodied

    target = ctx.target
    if target is None:
        return
    damaged = False
    for event in reversed(ctx.engine.events):
        if event.event_type == "ROUND_STARTED":
            break
        if event.event_type == "DAMAGE_COMMITTED" and target.entity_id in event.target_ids:
            packet = event.payload or {}
            if str(packet.get("damage_type") or "").upper() in ("SLASHING", "PIERCING") and int(packet.get("reduced_to") or 0) > 0:
                damaged = True
                break
    if is_bloodied(target) or damaged:
        block_healing_reduction(ctx, {"applies_to": "target", "evidence": "cannot regain HP until the start of your next turn",
                                      "expires_on": "START_OF_SOURCE_NEXT_TURN"})


HEAVENLY = 'tianxia.talent.metal.heavenly_needle_sutra'
MERIDIAN = 'TAL_METAL_MERIDIAN_NAIL'
FILINGS = 'TAL_METAL_IRON_FILINGS_CLOUD'


def metal_turn_stamp(engine):
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@effect('metal_needle_targets')
def needle_targets(ctx, spec):
    """Reuse bounded recipient selection; the caster can see their own body."""
    from dataclasses import replace
    from .. import stealth
    from .rider_outcomes import targets
    if ctx.typed.get('source') != HEAVENLY:
        return
    candidates = [actor for actor in ctx.engine.state.actors.values()
                  if actor.active and (actor is ctx.actor or stealth.sees(ctx.engine, ctx.actor, actor))
                  and ctx.engine._distance_actor_to_actor(ctx.actor, actor) <= int(spec['range_ft'])]
    # The generic automatic policy fills the maximum. Bound its harmful picks
    # to the preferred hostile roster while manual owners retain the full menu.
    mode = (getattr(ctx.engine, 'typed_control_modes', {}) or {}).get(ctx.actor.entity_id, 'MANUAL')
    if mode == 'LOCAL_AUTO':
        count = min(int(ctx.numbers.get('pb') or 0), sum(a.team_id != ctx.actor.team_id for a in candidates))
        if not count:
            return
        spec = {**spec, 'count': count}
    targets(replace(ctx, targets=candidates), {**spec, 'area_only': True, 'requires_visibility': False})


@effect('metal_needle_seal')
def needle_seal(ctx, spec):
    """Actual failed-save/hit recipient chooses distinct reviewed needle effects."""
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import run_effects
    if ctx.typed.get('source') not in {HEAVENLY, MERIDIAN} or ctx.target is None:
        return
    options = spec.get('options') or []
    labels = [row['label'] for row in options]
    count = 1
    if (spec.get('extra_at_cl') and int(ctx.numbers.get('cl') or 1) >= spec['extra_at_cl']
            and not ctx.damage_cache.get('_metal_second_seal')):
        extra = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'metal_second_seal', ctx.target.entity_id),
            ctx.actor, CHOICE+'metal_second_seal', ['SECOND'], allow_decline=True, preferred=['SECOND'],
            target_id=ctx.target.entity_id, name=spec['name'],
            labels={'SECOND':'Give this creature two different needle seals'},
            prompt=f"{spec['name']}: {ctx.target.display_name} failed its Dexterity save. Give this creature two different seals until your next turn starts? Only one creature per use; no extra cost.")
        if extra:
            ctx.damage_cache['_metal_second_seal'] = 1
            count = 2
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'metal_needle_seal', ctx.target.entity_id),
        ctx.actor, CHOICE+'metal_needle_seal', labels, minimum=count, maximum=count,
        preferred=labels[:count], target_id=ctx.target.entity_id, name=spec['name'],
        prompt=f"{spec['name']}: choose {count} different effect{'s' if count > 1 else ''} for {ctx.target.display_name} until your next turn starts. No extra cost.")
    for row in options:
        if row['label'] in picked:
            run_effects(ctx, row['effects'])


@effect('metal_needle_interference')
def needle_interference(ctx, spec):
    """Needle Flick's known active Concentration, without unrelated check penalties."""
    from ..typed_executor import run_effects
    if ctx.typed.get('source') != 'TAL_METAL_NEEDLE_FLICK' or ctx.target is None or ctx.target.concentration is None:
        return
    run_effects(ctx, spec.get('effects') or [])


@effect('metal_filings_cloud')
def filings_ground(ctx, spec):
    """One ground placement after actual final saves; success exemption is local."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    from . import placed
    if ctx.typed.get('source') != FILINGS or getattr(ctx.intent,'destination',None) is None:
        return
    ctx.damage_cache['_filings_results'] = {'failed':[], 'succeeded':[]}
    sub = replace(ctx, typed={**ctx.typed, '_metal_filings_receipt':1})
    run_effects(sub, spec['effects'])
    results = ctx.damage_cache.pop('_filings_results')
    if not results['failed']:
        return
    aim = ctx.intent.destination
    area = placed.area(ctx.engine, aim, 'sphere', 10)
    cells = [aim, *(cell for cell in area if cell != aim)]
    placed.place(ctx.engine, ctx.actor, source=ctx.source, tag='metal_filings', cells=cells,
        name='Iron Filings Cloud: difficult terrain', shape='sphere', size_ft=10,
        difficult={'who':'any', 'metal_filings_terrain':1}, numbers=ctx.numbers,
        placed={'casting_turn':metal_turn_stamp(ctx.engine), 'succeeded':results['succeeded'],
                'expires_turn':int(ctx.actor.turns_started)+1, 'end':int(int(ctx.numbers.get('cl') or 1)>=10)})


@hook('save_final')
def filings_result(ctx, target, ability, named, failed):
    results = ctx.damage_cache.get('_filings_results')
    if ctx.typed.get('source') == FILINGS and ctx.typed.get('_metal_filings_receipt') and results is not None:
        results['failed' if failed else 'succeeded'].append(target.entity_id)


@hook('zone_recipient_allowed')
def filings_success_exemption(engine, zone, actor, spec):
    from . import placed
    if not spec.get('metal_filings_terrain'):
        return None
    data = placed.data(zone)
    if data.get('casting_turn') == metal_turn_stamp(engine) and actor.entity_id in data.get('succeeded',[]):
        return False
    return None


def expire_filings(engine, actor, at_end, nominal=False):
    # Same shared custom clock as every other placed expiry (effect_durations.custom_turn_due),
    # so a cloud whose owner's turns are skipped (skip_finalized_v1) still ends on schedule.
    from . import placed
    from .effect_durations import custom_turn_due
    for zone in placed.of(engine, 'metal_filings', owner_id=actor.entity_id):
        data = placed.data(zone)
        if bool(data.get('end')) == at_end and custom_turn_due(
                actor, data['expires_turn'], zone.per_turn_triggered, 'metal_filings_cloud', nominal=nominal):
            placed.drop(engine, zone, 'DURATION_ENDED')


@hook('turn_start')
def filings_start_expiry(engine, actor):
    expire_filings(engine, actor, False)


@hook('turn_end')
def filings_end_expiry(engine, actor):
    expire_filings(engine, actor, True)


@hook('nominal_slot_boundary')
def filings_nominal_expiry(engine, actor, checkpoint):
    expire_filings(engine, actor, checkpoint == 'END_OF_TURN', nominal=True)


@hook('compile_action')
def heavenly_recipient_catalog(action, info):
    """Any initial creature is legal; the actual bounded roster is chosen on use."""
    if HEAVENLY in info.get('owned_ids',()) and ((action.parameters or {}).get('typed') or {}).get('source') == HEAVENLY:
        return action.model_copy(update={'target_kind':'ANY_CREATURE'})
    return None


GLANCE = 'TAL_METAL_WHITE_TIGER_GLANCE'


def _source_is_metal(engine, source_definition_id):
    """Whether recorded damage came from a Metal-catalogued attack or technique.

    Only a recorded source that resolves to a Metal typed action (or a Metal source id)
    counts.  A plain weapon hit carrying Metal Qi through an unrecorded medium is a
    later delivery-provenance contract (M1/M2); it is deliberately not inferred here.
    """
    if not source_definition_id:
        return False
    if str(source_definition_id).startswith(('METAL_BASE_', 'TAL_METAL_', 'tianxia.talent.metal.')):
        return True
    action = engine.action_catalog.get(source_definition_id)
    if action is None:
        return False
    return is_metal(action)


def metal_damaged_this_turn(engine, owner, target):
    """Whether ``owner`` dealt this target real damage from a Metal source this turn.

    Public shared helper (checklist 5): the printed 'you damaged this turn with a Metal
    attack or technique' prerequisite.  Scans the owner's current turn window from the
    owner's most recent TURN_STARTED and reads committed DAMAGE_COMMITTED events, so it
    is derived from what actually happened rather than from marks or appearance.
    """
    window = None
    for event in reversed(engine.events):
        if event.event_type == 'TURN_STARTED' and event.actor_id == owner.entity_id:
            window = event.sequence
            break
    for event in reversed(engine.events):
        if window is not None and event.sequence <= window:
            break
        if (event.event_type == 'DAMAGE_COMMITTED' and event.actor_id == owner.entity_id
                and target.entity_id in (event.target_ids or ())
                and int((event.payload or {}).get('reduced_to') or 0) > 0
                and _source_is_metal(engine, event.source_definition_id)):
            return True
    return False


@hook('target_eligibility')
def glance_target_eligibility(engine, actor, target, action):
    """White Tiger Glance's printed prerequisite, enforced as a pure target veto.

    Only the owner of an owned Glance is affected, and only for that ability; every other
    actor and action is untouched, so unrelated fights and old saved states are unchanged.
    A target the owner has not Metal-damaged this turn is vetoed with ``False``.  A target
    it has is answered with ``None``, not ``True``: the printed word is "one creature you
    can see", so the ordinary knowledge, range and line-of-sight checks still decide.  A
    ``True`` reply would be an owned visibility exception and would wrongly reach Glance
    through cover, obscured ground or a blocked path.
    """
    if getattr(action, 'owner_id', None) != actor.entity_id:
        return None
    if str(((action.parameters or {}).get('typed') or {}).get('source') or '').split('#')[0] != GLANCE:
        return None
    return None if metal_damaged_this_turn(engine, actor, target) else False
