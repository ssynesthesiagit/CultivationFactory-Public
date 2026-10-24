"""Shared reviewed affliction categories are exposed by affliction_category.

Qi Cultivation Path features (owner 2026-09-28: "make sure all the talents and class abilities and foundations and
methods and everything is applied"). They had compiled as: Golden Core Form's two Forms as Bonus Actions (free Qi every
turn), Meridian Regulation as Disadvantage on the ally it helps (or no Reactions for a foe), Domain Armament as a free
Bonus Action attack from your own square.

Golden Core Form (CL10; which Form is a build choice the sheet does not record: "Golden Core Form: <Form>", free choices
offered until its first turn ends; Stable when none is chosen)
  Stable       when the fight begins, Qi up to PB; at the start of its turn, +1 Qi while below PB (CL17: 2 x PB, +2)
  Circulating  once per turn, after a successfully resolved Qi spend: choose movement, a stance shift, Temporary HP
               or Armament movement. CL17 chooses two different benefits with the printed larger amounts.
  Reservoir    "Golden Core Reservoir", a Bonus Action once per scene: regain PB + key modifier Qi (CL17: 2 x PB + key)
Domain Armament (CL9)
  "Domain Armament: Manifest"  Bonus Action, 1 Qi: the floating Armament (it occupies no space, so the table keeps no
                               token) appears on the unoccupied point within 30 feet you choose, which the table
                               remembers; Assault Mode. Left beyond 30 feet of you it drifts to the nearest legal point
  "Domain Armament Attack"     Bonus Action in Assault Mode: the Armament moves up to 20 feet (staying within 30 feet of
                               you) and makes a Cultivation Attack against a creature within 5 feet of it -- on the table,
                               a creature within 35 feet of you; 1d8/2d8/3d8 (CL 9/13/17) + key modifier, Force
  "Domain Armament: Guard Mode" / "Assault Mode"  once per turn, no action; in Guard Mode, at the end of your turn you
                               choose one creature within 5 feet of the floating Armament (the table asks) and it gains
                               +2 AC against ranged attack rolls until the start of your next turn. The shield ends if
                               that creature walks more than 5 feet from the Armament, the Armament changes mode, or the
                               Domain Armament ends
Meridian Regulation (CL2)  Action, touch, 1 Qi: choose ONE effect on the target and resolve the branch that effect falls in.
                            "Choose one poison, disease, or directly caused physical impairment affecting the target":
                            the category belongs to the ABILITY, so it is reviewed data, one row per printed ability with
                            the printed sentence that establishes it (combat/rules/affliction_sources.json). That file
                            holds both halves of the review: "sources" places an ability in one of the printed three,
                            "left_to_the_gm" records an ability the review read and left out (with why), so an ability
                            in neither list is one the table has not read and stays the GM's -- a dream or an illusion
                            is not a physical impairment however its penalty is worded, and neither is a slowing that
                            only happens to a creature that is already Frightened.
                            "Effect with Repeat Saves": the target repeats that save with Advantage, and on a success the
                            effect's normal successful-save result applies. "Effect without Repeat Saves": a Constitution
                            save with Advantage against the effect's printed DC, and on a success one of that effect's
                            penalties (Poisoned, a Speed reduction, Disadvantage on attack rolls / ability checks /
                            saving throws, no Reactions) stops applying until the end of the target's next turn. Both
                            branches are offered in one question, so a repeating effect never hides another effect.
                            The other printed limits ("have a printed saving throw DC", "not have the Curse, Tribulation,
                            Foundation Injury, Hidden Injury, Possession, Permanent or Soul Damage tag") are checked
                            before anything is offered, and a penalty whose printed record or printed DC the table cannot
                            read stays the GM's.

Immortal of Qi (CL20)  "At the start of each of your turns, regain 5 Qi": the generic free row for the record's own
                           start-of-turn trigger (combat/rules/reaction_trigger_phrases.json's own_turn_start), so it
                           costs no Reaction and needs nothing from this module.
Shared public armament_condition, armament_point and move_armament helpers
serve Qi Path, Devil-Qi Augment and Mantra fields; they read/update the existing
source-owned Armament condition without duplicating a physical item.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import BuildChoiceRefused, effect, hook, note, register_build_choice, register_feature_use_flag

QI = "resource:core.qi"
GOLDEN = "tianxia.path.qi_cultivation.feature.golden_core_form"
SECOND_GOLDEN = "tianxia.path.qi_cultivation.feature.second_golden_core_form"
ARMAMENT = "tianxia.path.qi_cultivation.feature.domain_armament"
FORM = "condition:typed.golden_core_form"
ARMED = "condition:typed.domain_armament"
NASCENT_SOUL = "tianxia.path.qi_cultivation.feature.nascent_soul"
# Spent in a fight, the use is carried onto the sheet, where the CL15 replacement window reads it.
register_feature_use_flag("nascent_continuity_used_round_scene", NASCENT_SOUL)
FORMS = {"stable": "Stable Golden Core", "circulating": "Circulating Golden Core", "reservoir": "Golden Core Reservoir"}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == "qi_path"]


def _has(engine: Any, actor: Any, kind: str) -> bool:
    return any(row.get("kind") == kind for row in _rows(engine, actor))


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    row = next((row for row in _rows(engine, actor) if row.get("numbers")), None)
    return (row or {}).get("numbers") or {}


def form(actor: Any) -> str | None:
    """The first recorded Form, or None: a character with no recorded Form holds no Form condition."""
    return next(iter(forms(actor)), None)


def forms(actor: Any, *, permanent_only: bool = False) -> tuple[str, ...]:
    """Return Forms in persisted order.

    Qi Path's selection limits and Borrowed Golden Form use ``permanent_only``
    to count permanent choices without charging temporary grants a choice slot.
    Benefit readers include every Form by default.
    """
    held = sorted((c for c in actor.conditions.values() if c.condition_id == FORM
                   and (not permanent_only or not (c.data or {}).get("borrowed"))),
                  key=lambda c: c.applied_sequence)
    return tuple(dict.fromkeys(str((c.data or {}).get("form") or "stable") for c in held))


def form_state(engine: Any, actor: Any, form_key: str) -> bool:
    """Whether one recorded Form is Perfected.

    General seam (owner 2026-10-13): the Form's own condition records its Perfected
    state when a Source Rule set one -- "At CL17, your chosen Form becomes Perfected"
    reads the character's Cultivation Level, but a rule that perfects or un-perfects
    one specific Form (Perfected Golden Core, a borrowed Form) records it on the
    condition, and that record wins. Absent the flag, the character's level decides
    exactly as before, so no existing character changes.
    """
    # A temporary copy may coexist with a later permanent build choice. Read
    # the permanent grant first; removing it reveals the unchanged borrowed tier.
    matching = sorted((c for c in actor.conditions.values() if c.condition_id == FORM
                       and str((c.data or {}).get("form") or "stable") == form_key),
                      key=lambda c: bool((c.data or {}).get("borrowed")))
    held = (matching[0].data or {}).get("perfected") if matching else None
    return bool(held) if held is not None else int(_numbers(engine, actor).get("cl") or 1) >= 17


def _armed(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == ARMED), None)


@hook("compile_block")
def qi_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "qi_path":
        return None
    return [{**row, "block": "qi_path", "kind": spec.get("kind"), "numbers": dict(numbers)}]


@hook("compile_actions")
def qi_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, short, numbers = info["owned_ids"], info["short"], info["numbers"]
    out = []

    def make(key: str, name: str, economy: Any, effects: list[dict[str, Any]], *, target: str = "SELF", range_ft: int | None = None,
             costs: tuple = (), expected: int = 0, **parameters: Any) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.qi_path.{key}", display_name=name, owner_id=info["actor_id"],
                                economy=economy, resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=costs,
                                parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                                                      "source": key}, "expected_damage": expected, **parameters})
    if GOLDEN in owned:
        # The Form is a fixed build choice recorded on the character sheet and in the growth record. It is
        # compiled here as a fixed condition at match start and never offered as an in-fight switch.
        # No Form recorded -> no Form condition (no default Stable).
        fixed = [row["id"] for row in form_rows(info["owner_sheet"])]
        out.append(make("reservoir", "Golden Core Reservoir", EconomyKind.BONUS_ACTION, [{"type": "golden_core_reservoir"}],
                        golden_reservoir=True, recovery_limit=2 if "insight.reservoir-core-refinement" in owned else 1,
                        golden_fixed_forms=fixed[:2 if SECOND_GOLDEN in owned and int(numbers.get("cl") or 1) >= 20 else 1]))
    if ARMAMENT in owned:
        cl, key_mod = int(numbers.get("cl") or 1), int(numbers.get("key_mod") or 0)
        count = 3 if cl >= 17 else 2 if cl >= 13 else 1
        # Domain Armament Link (CL13): control range 60 feet, movement 30 -- the target within 65 feet instead of 35.
        # The control range travels on the compiled actions so the drift correction uses the range this build has.
        link = "tianxia.path.qi_cultivation.feature.domain_armament_link" in owned
        control = 60 if link else CONTROL_RANGE
        out.append(make("armament.manifest", "Domain Armament: Manifest", EconomyKind.BONUS_ACTION,
                        [{"type": "domain_armament", "do": "manifest", "applies_to": "self",
                          "picks_destination": True, "distance_ft": 30,
                          "evidence": "Initial Position: One unoccupied point within 30 feet"}],
                        costs=((QI, 1),), armament="manifest", armament_control_ft=control))
        reach = 65 if link else 35
        out.append(make("armament.attack", "Domain Armament Attack", EconomyKind.BONUS_ACTION,
                        [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1,
                          "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "formula": "key_ability_modifier",
                                      "damage_types": ["force"], "evidence": "Projected Armament Hit: CL9 1d8 + key ability modifier"}],
                          "evidence": "Move the Armament up to 20 feet, then make a Cultivation Attack against one creature within 5 feet."}],
                        target="HOSTILE_ENTITY", range_ft=reach, expected=int(count * 4.5 + key_mod), armament="attack",
                        armament_control_ft=control))
        for mode in ("guard", "assault"):
            out.append(make(f"armament.{mode}", f"Domain Armament: {mode.title()} Mode", EconomyKind.NONE, [{"type": "domain_armament", "do": mode}],
                            player_only=True, armament=mode, armament_control_ft=control))
    return out or None


@hook("candidate_allowed")
def qi_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    if parameters.get("golden_reservoir"):
        return "reservoir" in forms(actor) and recovery_available(engine, actor, GOLDEN)
    kind = parameters.get("armament")
    if kind:
        armed = _armed(actor)
        if kind == "manifest":
            return armed is None
        if armed is None:
            return False
        mode = (armed.data or {}).get("mode")
        if kind == "attack":
            return mode == "assault"
        return mode != kind and not actor.turn_flags.get("armament_mode_changed")
    return None


# ------------------------------------------------------------------------------------------------ Golden Core Form
@hook("match_start")
def golden_core_fixed(engine: Any) -> None:
    """Apply the Golden Core Form(s) the sheet recorded as fixed conditions. Borrowed grants are separate.

    A Golden Core character with no recorded Form gets no Form condition: Stable is never assumed."""
    for action in engine.action_catalog.values():
        parameters = action.parameters or {}
        fixed = parameters.get("golden_fixed_forms")
        if not fixed:
            continue
        actor = engine.state.actors.get(action.owner_id)
        if actor is None:
            continue
        for key in fixed or ():
            if key not in forms(actor, permanent_only=True):
                engine._apply_condition(actor, FORM, GOLDEN, actor.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"form": key, "fixed": True,
                                              "label": f"Golden Core Form: {FORMS[key]} (fixed build choice)"})




@hook("button_description")
def reservoir_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    parameters = row.get("parameters") or {}
    typed = parameters.get("typed") or {}
    if parameters.get("armament") == "manifest":
        control = int(parameters.get("armament_control_ft") or CONTROL_RANGE)
        return ("Manifest a floating weapon or shield as a Bonus Action, paying 1 Qi. "
                "Qi pays for your Qi Cultivation techniques. Choose an unoccupied point within 30 feet. "
                f"The Armament must stay within {control} feet of you. "
                "Its printed duration is 1 hour, and it ends if you become Unconscious. "
                "Assault Mode lets it attack; Guard Mode lets it protect a nearby creature.\n\n"
                + printed_rule_text(ARMAMENT))
    if any(eff.get("type") == "golden_core_reservoir" for eff in typed.get("effects") or []):
        numbers = typed.get("numbers") or {}
        pb, key_mod = int(numbers.get("pb") or 2), int(numbers.get("key_mod") or 0)
        return (f"Bonus action. Unperfected Reservoir: regain {pb + key_mod} Qi. "
                f"Perfected Reservoir: regain {2 * pb + key_mod} Qi. Recovery cannot exceed your maximum. "
                "A borrowed Reservoir remains unperfected unless a rule explicitly perfects it, even at Cultivation Level 17. "
                "Qi pays for your Qi Cultivation techniques. " +
                ("You can use it twice per scene with Reservoir Core Refinement. The second use gives you one level "
                 "of Exhaustion after restoring Qi; that level cannot be prevented, transferred or removed before "
                 "the scene ends. Exhaustion reduces d20 Tests by 2 and Speed by 5 feet per level.\n\n"
                 if int(parameters.get("recovery_limit") or 1) == 2 else "You can use this Bonus Action once per scene.\n\n")
                + printed_rule_text("tianxia.path.qi_cultivation.feature.golden_core_form"))
    return None


@effect("golden_core_reservoir")
def golden_core_reservoir(ctx: Any, eff: dict[str, Any]) -> None:
    pb, key_mod, cl = int(ctx.numbers.get("pb") or 2), int(ctx.numbers.get("key_mod") or 0), int(ctx.numbers.get("cl") or 1)
    if QI in ctx.actor.resources and recovery_available(ctx.engine, ctx.actor, GOLDEN):
        recover(ctx.engine, ctx.actor, GOLDEN, QI,
                (2 * pb if form_state(ctx.engine, ctx.actor, "reservoir") else pb) + key_mod, ctx.source)


def recovery_available(engine: Any, actor: Any, feature: str) -> bool:
    """General scene-limited recovery admission; used by Golden Core's action and turn trigger."""
    return int(actor.turn_flags.get("golden_core_reservoir_round_used") or 0) < recovery_limit(engine, actor, feature)


def recovery_limit(engine: Any, actor: Any, feature: str) -> int:
    """Read an optional recovery allowance without changing nonowners' records."""
    from . import run_strict
    return max([1, *[int(value) for value in run_strict("scene_recovery_limit", engine, actor, feature)
                     if value is not None]])


def recover(engine: Any, actor: Any, feature: str, resource: str, amount: int, source: str) -> None:
    """Restore the resource, then notify mandatory aftermath, inside the enclosing transaction."""
    from . import run_strict
    uses = int(actor.turn_flags.get("golden_core_reservoir_round_used") or 0) + 1
    actor.turn_flags["golden_core_reservoir_round_used"] = uses if recovery_limit(engine, actor, feature) > 1 else True
    engine._gain_resource(actor, resource, amount, source)
    if run_strict("scene_recovery_used", engine, actor, feature, uses):
        raise ValueError("scene_recovery_used providers must return None")


@hook("turn_start")
def golden_core_turn(engine: Any, actor: Any) -> None:
    nascent = next((row for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
                    if row.get("feature_id") == NASCENT_SOUL), None)
    # The engine clears ordinary turn flags at each turn start. The retained
    # marker records this once-per-scene use as integer fight state.
    if nascent is not None and QI in actor.resources and actor.resources.get(QI, 0) == 0 \
            and not actor.turn_flags.get("nascent_continuity_used_round_scene"):
        actor.turn_flags["nascent_continuity_used_round_scene"] = 1
        engine._gain_resource(actor, QI, int(actor.proficiency_bonus or 2), f"passive:{NASCENT_SOUL}.continuity")
    if not _has(engine, actor, "golden_core") or QI not in actor.resources:
        return
    numbers = _numbers(engine, actor)
    pb, cl = int(numbers.get("pb") or actor.proficiency_bonus or 2), int(numbers.get("cl") or 1)
    chosen = forms(actor)
    reservoir_perfected = form_state(engine, actor, "reservoir")
    if "reservoir" in chosen and reservoir_perfected and actor.resources.get(QI, 0) == 0 and not actor.turn_flags.get("golden_core_reservoir_round_used"):
        recover(engine, actor, GOLDEN, QI, 2 * pb + int(numbers.get("key_mod") or 0), f"passive:{GOLDEN}.reservoir")
    if "stable" not in chosen:
        return
    threshold = 2 * pb if form_state(engine, actor, "stable") else pb
    held = int(actor.resources.get(QI, 0))
    if not actor.turn_flags.get("golden_core_initiative_round_done"):
        actor.turn_flags["golden_core_initiative_round_done"] = True  # "When Initiative is rolled" (its first turn, on the table)
        if held < threshold:
            engine._gain_resource(actor, QI, threshold - held, f"passive:{GOLDEN}.stable")
        return
    if held < threshold:
        engine._gain_resource(actor, QI, min(2 if form_state(engine, actor, "stable") else 1, threshold - held), f"passive:{GOLDEN}.stable")


@hook("technique_used")
def circulating(ctx: Any) -> None:
    actor = ctx.actor
    opted = bool((ctx.action.parameters or {}).get("golden_core_choices"))
    stamp = f"{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}:{ctx.engine.state.current_actor_id}"
    used = actor.turn_flags.get("circulating_golden_core")
    if not _has(ctx.engine, actor, "golden_core") or "circulating" not in forms(actor) or (used == stamp if opted else used):
        return
    if opted:
        spent = refunded = 0
        for event in reversed(ctx.engine.events):
            if event.event_type == "INTENT_ACCEPTED" and event.actor_id == actor.entity_id:
                break
            if event.actor_id != actor.entity_id or (event.payload or {}).get("resource_id") != QI:
                continue
            if event.event_type == "RESOURCE_SPENT" and event.source_definition_id == ctx.source:
                spent += int(event.payload.get("amount") or 0)
            if event.event_type == "RESOURCE_GAINED" and event.payload.get("cost_source_id") == ctx.source:
                refunded += int(event.payload.get("gained") or 0)
        if spent <= refunded:
            return
    elif not any(resource == QI and int(amount) > 0 for resource, amount in (ctx.action.costs or ())):
        return
    actor.turn_flags["circulating_golden_core"] = stamp if opted else True
    pb, cl = int(ctx.numbers.get("pb") or 2), int(ctx.numbers.get("cl") or 1)
    perfected = form_state(ctx.engine, actor, "circulating")
    if not opted:
        ctx.engine._grant_temp_hp(actor, 2 * pb if perfected else pb, f"passive:{GOLDEN}.circulating", actor.entity_id)
        return
    from .needle import ask, checkpoint_id
    from .granted_moves import destinations, commit
    from ..target_knowledge import can_see
    from ..typed_reactions import physical_melee_reach
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell

    feet = 10 if perfected else 5
    reach = int(physical_melee_reach(ctx.engine, actor) or 5)
    routes = [r for r in destinations(ctx.engine, actor, feet, lambda cell: True) if r[0] != actor.position]
    nearby = [a for a in ctx.engine.state.actors.values() if a.active and a is not actor
              and can_see(ctx.engine, actor, a) and ctx.engine._distance_actor_to_actor(actor, a) <= reach]
    options = ["temp_hp"]
    labels = {"temp_hp": f"Gain {2 * pb if perfected else pb} Temporary Hit Points"}
    if routes:
        options.append("move"); labels["move"] = f"Move up to {feet} feet without Opportunity Attacks"
    shifts = {a.entity_id: [r for r in routes if ctx.engine._distance_actor_to_actor(actor, a, actor_position=r[0]) <= reach]
              for a in nearby}
    shifts = {key: values for key, values in shifts.items() if values}
    if shifts:
        options.append("shift"); labels["shift"] = "Shift around one creature in reach; avoid its Opportunity Attack"
    arm_feet = 20 if perfected else 10
    arm_routes = _armament_destinations(ctx.engine, actor, arm_feet, can_see) if _armed(actor) is not None else []
    if arm_routes:
        options.append("armament"); labels["armament"] = f"Move your Domain Armament up to {arm_feet} feet"
    count = min(2 if perfected else 1, len(options))
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "golden_benefits", actor.entity_id), actor,
        "choice:needle.golden_benefits", options, labels=labels, minimum=count, maximum=count,
        # Preferences are hints to the generic chooser, and must always be a subset of
        # the options this actor can currently take (for example, an immobilized actor
        # may still choose Temporary Hit Points).
        preferred=[option for option in ("temp_hp", "move") if option in options],
        name="Circulating Golden Core", feature_id=GOLDEN,
        prompt=f"Circulating Golden Core: {ctx.action.display_name} spent Qi. Choose {count} different benefits; no extra Qi cost.")

    def choose_armament() -> None:
        arm_routes_now = _armament_destinations(ctx.engine, actor, arm_feet, can_see)
        if not arm_routes_now:
            ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id,
                payload={"trigger": "Circulating Golden Core: no legal Armament destination remains after your movement."})
            return
        arm_ids = [f"cell:{p.x},{p.y}" for p in arm_routes_now]
        arm_selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "golden_armament", actor.entity_id), actor,
            "choice:needle.golden_armament", arm_ids, labels={i: f"Armament to {p.x},{p.y}" for i,p in zip(arm_ids,arm_routes_now)},
            automatic_options=[i for i,p in zip(arm_ids,arm_routes_now) if perceives_cell(ctx.engine, actor, p)],
            allow_decline=True, name="Circulating Golden Core",
            prompt=f"Choose a legal point within {arm_feet} feet of your Armament, or leave it in place.")
        if arm_selected and not move_armament(ctx.engine, actor, arm_routes_now[arm_ids.index(arm_selected[0])],
                                               ctx.source, max_distance_ft=arm_feet, require_clear_route=True):
            ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id,
                payload={"trigger": "Circulating Golden Core could not move your Domain Armament to that point; the destination is unavailable."})

    for benefit in picked:
        if benefit == "temp_hp":
            ctx.engine._grant_temp_hp(actor, 2 * pb if perfected else pb, f"passive:{GOLDEN}.circulating", actor.entity_id)
        elif benefit in {"move", "shift"}:
            exempt = ()
            offered = [r for r in destinations(ctx.engine, actor, feet, lambda cell: True) if r[0] != actor.position]
            if benefit == "shift":
                # A preceding selected benefit can change both position and who is
                # in reach. Rebuild from current, perceived creatures and legal
                # movement routes at the point this choice is resolved.
                nearby_now = [a for a in ctx.engine.state.actors.values() if a.active and a is not actor
                              and can_see(ctx.engine, actor, a)
                              and ctx.engine._distance_actor_to_actor(actor, a) <= reach]
                live_routes = [r for r in destinations(ctx.engine, actor, feet, lambda cell: True)
                               if r[0] != actor.position]
                live_shifts = {a.entity_id: a for a in nearby_now if any(
                    ctx.engine._distance_actor_to_actor(actor, a, actor_position=r[0]) <= reach
                    for r in live_routes)}
                targets = list(live_shifts)
                if not targets:
                    unused = [option for option in options if option not in picked]
                    if not unused:
                        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id,
                            payload={"trigger": "Circulating Golden Core: no creature remained eligible for the selected shift, and no other benefit remains available."})
                        continue
                    replacement = ask(ctx.engine, ctx.intent,
                        checkpoint_id(ctx.engine, "golden_benefit_replacement", actor.entity_id), actor,
                        "choice:needle.golden_benefit_replacement", unused,
                        labels={option: label for option,label in {
                            "temp_hp": f"Gain {2 * pb if perfected else pb} Temporary Hit Points",
                            "move": f"Move up to {feet} feet without Opportunity Attacks",
                            "armament": f"Move your Domain Armament up to {arm_feet} feet"}.items()
                            if option in unused},
                        allow_decline=True, name="Circulating Golden Core",
                        prompt="No creature can be shifted around from your current position. Choose another available benefit, or keep this benefit unused.")
                    if replacement and replacement[0] == "temp_hp":
                        ctx.engine._grant_temp_hp(actor, 2 * pb if perfected else pb,
                                                  f"passive:{GOLDEN}.circulating", actor.entity_id)
                    elif replacement and replacement[0] == "move":
                        repl_routes = [r for r in destinations(ctx.engine, actor, feet, lambda cell: True)
                                       if r[0] != actor.position]
                        repl_ids = [f"step:{r[0].x},{r[0].y},{r[0].z}" for r in repl_routes]
                        repl = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "golden_step", actor.entity_id, "move"), actor,
                            "choice:needle.golden_step", repl_ids,
                            labels={i: f"Move to {r[0].x},{r[0].y} ({r[2]} feet)" for i,r in zip(repl_ids,repl_routes)},
                            allow_decline=True, name="Circulating Golden Core", prompt=f"Choose up to {feet} feet of movement, or stay put.")
                        if repl:
                            commit(ctx.engine, actor, repl_routes[repl_ids.index(repl[0])][1], ctx.source,
                                   budget_ft=feet, provokes=False, intent=ctx.intent)
                    elif replacement and replacement[0] == "armament":
                        choose_armament()
                    else:
                        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id,
                            payload={"trigger": "Circulating Golden Core: no creature remained eligible for the selected shift; the benefit was not applied."})
                    continue
                selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "golden_shift", actor.entity_id), actor,
                    "choice:needle.golden_shift", targets,
                    labels={key: live_shifts[key].display_name for key in targets}, name="Circulating Golden Core",
                    prompt="Choose the creature to shift around. Only its Opportunity Attack is avoided.")
                if not selected: continue
                other = ctx.engine.state.actors[selected[0]]
                exempt = (other.entity_id,)
                offered = [r for r in offered if ctx.engine._distance_actor_to_actor(actor, other, actor_position=r[0]) <= reach]
            ids = [f"step:{r[0].x},{r[0].y},{r[0].z}" for r in offered]
            selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "golden_step", actor.entity_id, benefit), actor,
                "choice:needle.golden_step", ids, labels={i: f"Move to {r[0].x},{r[0].y} ({r[2]} feet)" for i,r in zip(ids,offered)},
                allow_decline=True, name="Circulating Golden Core", prompt=f"Choose up to {feet} feet of movement, or stay put.")
            if selected:
                commit(ctx.engine, actor, offered[ids.index(selected[0])][1], ctx.source,
                       budget_ft=feet, provokes=benefit == "shift", ignore_oa_from=exempt, intent=ctx.intent)
        elif benefit == "armament":
            # A prior selected benefit may have moved the owner. Rebuild this menu from
            # the live owner/Armament positions and current occupancy before asking.
            choose_armament()


# ------------------------------------------------------------------------------------------------ Domain Armament
GUARD = f"passive:{ARMAMENT}.guard"
GUARD_CHOICE = "choice:needle.armament_guard"
SHIELD = 5   # "designate one creature within 5 feet"; it keeps the shield only while it stays that close
CONTROL_RANGE = 30   # "It must remain within 30 feet"; Domain Armament Link (CL13) makes the control range 60


def _place(actor: Any) -> tuple[int, int] | None:
    """The point the floating Armament hovers at, saved as two integers on its condition so a table commit
    and reload keep it. None for a fight saved before it had a place: that Armament rides with its owner."""
    data = (_armed(actor).data if _armed(actor) is not None else {}) or {}
    x, y = data.get("ax"), data.get("ay")
    return (int(x), int(y)) if isinstance(x, int) and isinstance(y, int) else None


def _hovering(actor: Any) -> tuple[int, int]:
    """Where the Armament is right now: the point it was manifested at, or its owner's square (a projected
    Armament "occupies no space", so one riding its owner still shields whoever stands beside it)."""
    return _place(actor) or (actor.position.x, actor.position.y)


def _control_range_ft(engine: Any, actor: Any) -> int:
    """"It must remain within 30 feet" -- and Domain Armament Link (CL13) makes the control range 60. The owner's own
    compiled Domain Armament actions carry the range its build really has; an older save records it on the
    Armament; a fight answered before either keeps the printed 30."""
    for action in (engine.action_catalog or {}).values():
        if action.owner_id != actor.entity_id or "qi_path.armament" not in str(action.source_definition_id):
            continue
        carried = (getattr(action, "parameters", None) or {}).get("armament_control_ft")
        if isinstance(carried, int):
            return carried
    armed = _armed(actor)
    recorded = (armed.data or {}).get("reach_ft") if armed is not None else None
    return recorded if isinstance(recorded, int) else CONTROL_RANGE


def armament_condition(owner: Any) -> Any | None:
    """Public read-only query for a live Domain Armament; also used by Devil-Qi Augment."""
    return _armed(owner)


def armament_point(owner: Any) -> tuple[int, int]:
    """Return the integer map point where the floating Domain Armament hovers."""
    return _hovering(owner)


def armament_control_range(engine: Any, owner: Any) -> int:
    """Return the same control range used by native Armament movement and drift."""
    return _control_range_ft(engine, owner)


def _armament_destinations(engine: Any, owner: Any, max_distance_ft: int, can_see: Any) -> list[Any]:
    """Build perceived legal Armament destinations from its live position and owner range."""
    from ..gate2_runtime_models import Position
    origin = _hovering(owner)
    occupied = {cell for other in engine.state.actors.values() if other.active
                and (other is owner or can_see(engine, owner, other)) for cell in engine._actor_cells(other)}
    return [Position(x=x, y=y) for x in range(engine.grid.width) for y in range(engine.grid.height)
            if engine.grid.distance_ft(origin, (x,y)) <= max_distance_ft
            and engine.grid.distance_ft(owner.position, (x,y)) <= _control_range_ft(engine, owner)
            and (x,y) != origin and engine.grid.placement_legal((x,y), occupied_cells=occupied)
            and engine.grid.line_of_sight(Position(x=origin[0], y=origin[1]), Position(x=x, y=y))]


def move_armament(engine: Any, owner: Any, point: Any, source: str, *, distance_ft: int = 15, max_distance_ft: int | None = None, require_clear_route: bool = False) -> bool:
    """Move a manifested Armament to a selected legal point, preserving its saved mode and range.

    The default preserves Devil-Qi Augment's 15-foot relocation. Callers may
    supply a printed distance and request a clear physical route. Only the
    owner's condition stores the integer position; mode and duration survive.
    """
    # Shared by Qi Path, Devil-Qi Augment, Furnace Motion and Terrain Attunement.
    # Accept both reviewed callers' distance keywords; the explicit alias wins.
    max_distance_ft = distance_ft if max_distance_ft is None else max_distance_ft
    armed = _armed(owner)
    if armed is None:
        return False
    old = _hovering(owner)
    x, y = int(point.x), int(point.y)
    from ..gate2_runtime_models import Position
    if ((require_clear_route and not engine.grid.line_of_sight(Position(x=old[0], y=old[1]), Position(x=x, y=y)))
            or not engine.grid.placement_legal((x, y), occupied_cells={cell for other in engine.state.actors.values()
                                                               if other.active for cell in engine._actor_cells(other)})
            or int(engine.grid.distance_ft(old, (x, y))) > max_distance_ft
            or int(engine.grid.distance_ft((x, y), owner.position)) > _control_range_ft(engine, owner)):
        return
    data = {**dict(armed.data or {}), "ax": x, "ay": y}
    engine._remove_condition(owner, ARMED, armed.source_definition_id)
    engine._apply_condition(owner, ARMED, source, owner.entity_id, expires_on="UNTIL_REMOVED", data=data)
    return True


def _drifting(engine: Any, actor: Any, point: tuple[int, int]) -> bool:
    """Whether the Armament has ended outside its owner's control range."""
    return point != (actor.position.x, actor.position.y) and engine.grid.distance_ft(actor.position, point) > _control_range_ft(engine, actor)


def _nearest_legal_point(engine: Any, actor: Any, point: tuple[int, int]) -> tuple[int, int] | None:
    """"If a projected Armament ends outside range, it moves to the nearest legal point in range": the point closest to
    where the Armament ended that is still within its owner's control range and is a point it may legally hover on --
    on the map, not inside a wall, and not on a square another creature stands on."""
    grid = engine.grid
    reach = _control_range_ft(engine, actor)
    taken = {cell for other in engine.state.actors.values() if other.active
             for cell in engine._actor_cells(other)}
    best: tuple[int, int, int, int] | None = None
    for x in range(grid.width):
        for y in range(grid.height):
            cell = (x, y)
            if grid.distance_ft(cell, actor.position) > reach or not grid.placement_legal(cell, occupied_cells=taken):
                continue
            # Nearest to where it ended; among equals, the straightest line from it, then a stable reading order.
            key = (grid.distance_ft(cell, point), abs(x - point[0]) + abs(y - point[1]), x, y)
            if best is None or key < best:
                best = key
    return (best[2], best[3]) if best else None


def _recentre(engine: Any, actor: Any, armed: Any) -> tuple[int, int]:
    """"If a projected Armament ends outside range, it moves to the nearest legal point in range"."""
    from_point = _place(actor) or (actor.position.x, actor.position.y)
    reach = _control_range_ft(engine, actor)
    landed = _nearest_legal_point(engine, actor, from_point) or (actor.position.x, actor.position.y)
    engine._remove_condition(actor, ARMED, f"passive:{ARMAMENT}")
    engine._apply_condition(actor, ARMED, f"passive:{ARMAMENT}", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={**dict(armed.data or {}), "ax": landed[0], "ay": landed[1],
                                  "reach_ft": reach})
    return landed


def _shields(engine: Any, owner: Any) -> list[tuple[Any, str]]:
    """The creatures this owner's Domain Armament is shielding, with their modifier ids: a shield is the +2 AC
    modifier whose source actor is this owner, so one owner's Armament never shields, inspects or unshield another's.
    The owner is among the creatures it may name -- "designate one creature within 5 feet" says nothing else."""
    return [(other, mid) for other in engine.state.actors.values() if other.active
            for mid, item in other.modifiers.items()
            if item.source_definition_id == GUARD and item.source_actor_id == owner.entity_id]


def _shielded(engine: Any, owner: Any) -> Any:
    """The creature this owner's Domain Armament is currently shielding, if any."""
    return next((other for other, _mid in _shields(engine, owner)), None)


def _unshield(engine: Any, owner: Any, reason: str) -> None:
    """"The protection ends if the creature moves more than 5 feet from the Armament, the Armament changes
    mode, or the Domain Armament ends" -- and only for the protection this owner granted."""
    for shielded, mid in _shields(engine, owner):
        del shielded.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", GUARD, actor_id=owner.entity_id,
                             target_ids=(shielded.entity_id,), payload={"modifier_id": mid, "reason": reason})
        note(engine, GUARD, owner, f"The Domain Armament stops shielding {shielded.display_name}.", (shielded,))


@effect("domain_armament")
def domain_armament(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    do = str(eff.get("do") or "")
    armed = _armed(actor)
    if do == "manifest":
        # "Initial Position: One unoccupied point within 30 feet"; a fight answered with no square manifests it
        # beside its owner rather than nowhere at all.
        point = ctx.destination
        where = (int(point.x), int(point.y)) if point is not None else (actor.position.x, actor.position.y)
        engine._apply_condition(actor, ARMED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"mode": "assault", "ax": where[0], "ay": where[1],
                                      "reach_ft": _control_range_ft(engine, actor),
                                      "label": "Domain Armament (Assault Mode)"})
        return
    if armed is None:
        return
    actor.turn_flags["armament_mode_changed"] = True
    _unshield(engine, actor, "ARMAMENT_CHANGED_MODE")   # changing mode ends the Guard Mode protection
    engine._remove_condition(actor, ARMED, ctx.source)
    engine._apply_condition(actor, ARMED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={**dict(armed.data or {}), "mode": do, "label": f"Domain Armament ({do.title()} Mode)"})


@hook("turn_end")
def armament_guard(engine: Any, actor: Any) -> None:
    """Guard Mode: "At the end of your turn, designate one creature within 5 feet as protected until the start
    of your next turn. The creature gains +2 AC against ranged attack rolls." The table asks which creature near
    the Armament is protected; a built-in AI answers for its own creature."""
    armed = _armed(actor)
    if armed is None or (armed.data or {}).get("mode") != "guard" or not actor.active:
        return
    from .needle import ask, checkpoint_id
    from ..target_knowledge import can_see
    from ..relations import relation

    point = _hovering(actor)
    nearby = sorted(other.entity_id for other in engine.state.actors.values()
                    if other.active and engine.grid.distance_ft(point, other.position) <= SHIELD)
    _unshield(engine, actor, "A_NEW_CREATURE_WAS_PROTECTED")   # one creature is protected at a time
    if not nearby:
        return
    names = {eid: engine.state.actors[eid].display_name for eid in nearby}
    # A player picks for themselves and may name any creature. When nobody is answering -- a built-in AI answering at
    # the end of its own turn -- the shield goes to the owner first and then to an ally, so the Armament never
    # hands a ranged-attack bonus to the enemy whose id happens to sort first. With no one friendly in reach the
    # printed rule still designates whoever is there.
    friendly = [eid for eid in nearby if relation(engine, actor, engine.state.actors[eid]) == "ALLY"]
    picked = ask(engine, None, checkpoint_id(engine, "armament_guard", actor.entity_id), actor, GUARD_CHOICE,
                 nearby, labels=names, name="Domain Armament: Guard Mode", feature_id=ARMAMENT, allow_decline=True,
                 preferred=sorted(friendly, key=lambda eid: (eid != actor.entity_id, eid)),
                 automatic_options=[eid for eid in friendly if can_see(engine, actor, engine.state.actors[eid])],
                 target_id=actor.entity_id, prompt=(
                     f"Domain Armament (Guard Mode): {actor.display_name} chooses one creature within 5 feet of the "
                     f"floating Armament to shield until the start of {actor.display_name}'s next turn. It gains +2 AC "
                     "against ranged attacks. Which creature is protected?"))
    if not picked or picked[0] not in names:
        return
    protected = engine.state.actors[picked[0]]
    # "until the start of your next turn" -- the owner's, not the protected creature's: the source-only token, so an
    # ally acting in between keeps the shield.
    engine._add_modifier(protected, GUARD, "armor_class_vs_ranged", "ADD", 2, "SELF",
                         expires_on="START_OF_SOURCE_NEXT_TURN")
    note(engine, GUARD, actor, f"The Domain Armament shields {protected.display_name}: +2 AC against ranged attacks "
                               f"until the start of {actor.display_name}'s next turn.", (protected,))


@hook("decision_text")
def armament_guard_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """The Guard Mode question in plain words: which creature, standing how far from what, gains what, until when.
    Presentation only, and inert for anyone who has no Domain Armament manifested."""
    if str(context.get("reaction_source_id") or "") != GUARD_CHOICE:
        return None
    owner = engine.state.actors.get(str(context.get("reactor_id") or ""))
    if owner is None or _armed(owner) is None:
        return None
    trigger = context.get("choice_trigger") or {}
    options = [str(option) for option in trigger.get("needle_options") or []]
    creatures = {eid: engine.state.actors[eid] for eid in options if eid in engine.state.actors}
    return {
        "name": "Domain Armament: Guard Mode",
        "feature_id": ARMAMENT,
        "summary": (f"{owner.display_name}'s floating Domain Armament is in Guard Mode. Choose one creature standing "
                    "within 5 feet of it: that creature gains +2 AC against ranged attack rolls until the start of "
                    f"{owner.display_name}'s next turn. The shield ends early if that creature walks more than 5 feet "
                    "from the Armament, the Armament changes mode, or the Domain Armament ends. It does not help "
                    "against melee attacks or saving throws."),
        "cost": "No additional action or resource cost: this happens at the end of your turn.",
        "limits": "One creature is protected at a time.",
        "option_descriptions": {
            eid: f"{other.display_name}: +2 AC against ranged attack rolls until the start of {owner.display_name}'s next turn."
            for eid, other in creatures.items()},
    }


@hook("event")
def armament_moves(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The two printed rules a move can reach: a protected creature "moves more than 5 feet from the Armament"
    loses the shield, and an Armament left beyond its control range "moves to the nearest legal point in range"."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if mover is None or not mover.active:
        return
    for owner in list(engine.state.actors.values()):
        armed = _armed(owner)
        if armed is None or not owner.active:
            continue
        point = _hovering(owner)
        if _drifting(engine, owner, point):
            landed = _recentre(engine, owner, armed)
            # Correcting the Armament's place is not itself an end condition: the shield only goes if the point it
            # landed on leaves the protected creature more than 5 feet away.
            protected = _shielded(engine, owner)
            if protected is not None and engine.grid.distance_ft(landed, protected.position) > SHIELD:
                _unshield(engine, owner, "ARMAMENT_LEFT_RANGE")
        elif _shielded(engine, owner) is mover and engine.grid.distance_ft(point, mover.position) > SHIELD:
            _unshield(engine, owner, "MOVE_TOO_FAR_FROM_ARMAMENT")


@hook("event")
def armament_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Ends if you become Unconscious" (or are defeated)."""
    if event_type not in ("ENTITY_DEFEATED", "CONDITION_APPLIED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") if event_type == "ENTITY_DEFEATED" else next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is None or _armed(actor) is None:
        return
    if event_type == "CONDITION_APPLIED" and (kwargs.get("payload") or {}).get("condition_id") != "condition:typed.unconscious":
        return
    _unshield(engine, actor, "ARMAMENT_ENDED")
    engine._remove_condition(actor, ARMED, f"passive:{ARMAMENT}")


# ------------------------------------------------------------------------------------------------ Meridian Regulation
def _regulable(engine: Any, subject: Any) -> list[tuple[str, Any]]:
    """The target's own effects that a repeated save could resolve, and that the printed rule lets the fighter choose.

    "Choose one poison, disease, or directly caused physical impairment affecting the target": an effect cast by someone
    else that remembers a printed DC it could be asked to repeat, that the reviewed table places in one of the printed
    three, and whose printed record carries none of the seven excluded tags. Nothing of the bearer's own doing is
    excluded: the printed rule limits the effect, not who cast it.
    """
    return [(iid, c) for iid, c in subject.conditions.items()
            if _repeat_contract(c) is not None and _regulable_effect(engine, c.source_definition_id)]


def _repeat_contract(condition: Any) -> dict[str, Any] | None:
    """The effect's native repeated save, including chosen afflictions ending one part."""
    data = condition.data or {}
    save = data.get("repeat_save") or data.get("repeat_one")
    if (isinstance(save, dict) and str(save.get("ability") or "").upper() in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
            and isinstance(save.get("dc"), int)
            and not isinstance(save["dc"], bool) and save["dc"] > 0):
        return save
    return None


# "Effect without Repeat Saves": "On success, suppress one penalty until the end of the target's next turn: Poisoned /
# Speed reduction / Disadvantage on attack rolls / Disadvantage on ability checks / Disadvantage on saving throws /
# Inability to take Reactions." Only the printed list, and only as this table stores it.
_CONDITION_PENALTIES = {
    "poisoned": "Poisoned",
    "slowed": "Speed reduced",
    "reaction_denied": "Cannot take Reactions",
}
# The effect's printed limits: "The effect must: have a printed saving throw DC. Not have the Curse, Tribulation,
# Foundation Injury, Hidden Injury, Possession, Permanent, or Soul Damage tag." Both are read from the effect's own
# printed record -- the DC from the save it remembers (a condition row stores that; combat/typed_executor.py's
# save_provenance is why a Disadvantage row stores it too) or from the DC its ability printed (a Speed reduction is a
# modifier and stores nothing), and the tag from the "Tags:" header of that ability's printed text, read the same way
# combat/ext/persist_augment.py reads the Glamer talents' header. An effect the table cannot identify, or whose DC it
# cannot read, is not offered: the printed rule allows only an effect known to have a DC and known not to be tagged.
FORBIDDEN_TAGS = ("curse", "tribulation", "foundation injury", "hidden injury", "possession", "permanent", "soul damage")
_TAG_HEADER = re.compile(r"^Tags?:[^\n]*", re.M)


@lru_cache(maxsize=1)
def _printed_rules() -> dict[str, str]:
    """The owner's printed rules text by mechanic id (authority/typed_mechanics/rules_text.json)."""
    import json
    from pathlib import Path

    texts = json.loads((Path(__file__).resolve().parents[2] / "authority" / "typed_mechanics"
                        / "rules_text.json").read_text(encoding="utf-8"))
    return {key: text for key, text in texts.items() if isinstance(text, str)}


@lru_cache(maxsize=1)
def _affliction_sources() -> dict[str, dict[str, Any]]:
    """Meridian Regulation's printed category per source ability (combat/rules/affliction_sources.json).

    The printed rule chooses "one poison, disease, or directly caused physical impairment affecting the target", and the
    category belongs to the ABILITY, not to the penalty it happens to leave: a dream, an illusion or a sound is not one
    of the printed three however it is worded. So the category is reviewed data, one row per printed ability with the
    printed sentence that establishes it, and an ability the file does not place is one the table cannot place in the
    printed three -- which is the GM's, exactly as the printed limit says. Nothing here reads a penalty to decide.

    Only "sources" is returned, so this is the placement alone; the file's "left_to_the_gm" list is the review's record
    of the abilities it read and left out (with the reason), which no runtime path needs -- tests/test_auto2_paths_b.py
    holds both halves to the ability to leave a repeating effect.
    """
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).resolve().parents[1] / "rules" / "affliction_sources.json").read_text(encoding="utf-8"))
    sources = data.get("sources") or {}
    return {key: row for key, row in sources.items() if isinstance(row, dict) and str(row.get("category") or "")}


def _typed_of(engine: Any, source_definition_id: Any) -> dict[str, Any]:
    """The typed row of the action that produced an effect, or {} when the source is not a compiled action."""
    source = str(source_definition_id or "")
    action = engine.action_catalog.get(source)
    if action is None:
        # Native zone/variant receipts retain a suffix on their actual source
        # action. Resolve only an explicit catalog prefix, longest first.
        key = max((key for key in engine.action_catalog if source.startswith(key + ":")
                   or source.startswith(key + "#")), key=len, default="")
        action = engine.action_catalog.get(key)
    return ((getattr(action, "parameters", None) or {}).get("typed") or {})


def _printed_key(engine: Any, source_definition_id: Any) -> str:
    """The printed id an effect is looked up by: the ability's own mechanic id when it is a compiled action, else the
    source definition itself. One key for the printed record and for the printed category, so the two can never disagree
    about which ability did this."""
    typed = _typed_of(engine, source_definition_id)
    return str(typed.get("option_of") or typed.get("source") or source_definition_id or "")


def _affliction_category(engine: Any, source_definition_id: Any) -> str:
    """Which of the printed three ("poison", "disease", "physical_impairment") this effect's ability is, or "" when the
    reviewed table does not place it. Read from combat/rules/affliction_sources.json, never from the penalty."""
    return str((_affliction_sources().get(_printed_key(engine, source_definition_id)) or {}).get("category") or "")


def affliction_category(engine: Any, source_definition_id: Any) -> str:
    """Shared printed source category for repeating-save consumers, or empty when unreviewed."""
    return _affliction_category(engine, source_definition_id)


def _printed_dc(engine: Any, source_definition_id: Any) -> int | None:
    """The saving-throw DC an effect printed, for a penalty the table keeps as a modifier (a Speed reduction) and so
    cannot remember the save that applied it: the DC its own ability rolled against."""
    from ..typed_executor import _walk_rows
    typed = _typed_of(engine, source_definition_id)
    # A caster having a technique DC does not establish that this ability
    # printed a saving throw. Require the actual compiled source's save row.
    if not any(row.get("type") in ("save", "poison_delivery_save")
               for row in _walk_rows(typed.get("effects") or [])):
        return None
    values = set()
    for row in _walk_rows(typed.get("effects") or []):
        if row.get("type") != "save":
            continue
        dc = row.get("dc")
        if dc is None or dc == "technique_save_dc":
            dc = (typed.get("numbers") or {}).get("save_dc")
        if isinstance(dc, int) and not isinstance(dc, bool) and dc > 0:
            values.add(dc)
        else:
            return None
    return next(iter(values)) if len(values) == 1 else None


def _tagged_forbidden(engine: Any, source_definition_id: Any) -> bool:
    """Whether the printed record of the ability behind an effect carries one of the seven tags Meridian Regulation
    excludes. An unknown record is not "tagged": it is simply not offerable, which ``_regulable_effect`` decides."""
    record = _printed_rules().get(_printed_key(engine, source_definition_id))
    header = _TAG_HEADER.search(record[:900]) if isinstance(record, str) else None
    return bool(header) and any(tag in header.group(0).lower() for tag in FORBIDDEN_TAGS)


def _condition_penalty(condition: Any) -> str:
    """Which of the printed penalties one stored condition is, in words a player knows. Empty when it is not one.

    The rules live under ``data["rule"]`` and each of the three roll-mode rows spells them differently:
    ``check_mode`` is a dict of check name -> mode, ``concentration_mode`` is the mode itself, and ``save_against`` is a
    dict with its own ``mode`` (combat/typed_executor.py's block_advantage). A Concentration save is a saving throw, so
    that row is the printed "Disadvantage on saving throws" too. Only DISADVANTAGE counts: an Advantage row is a
    benefit. Attack-roll Disadvantage is stored as a modifier; _modifier_penalty
    reads it separately with its original source and native save provenance.
    """
    rule = (condition.data or {}).get("rule") or {}
    # Owned one-check plug-ins use the same single-penalty metadata under their
    # own IDs. Do not remove a composite condition and suppress other effects;
    # printed-source category and tag checks still decide eligibility below.
    if isinstance(rule.get("check_mode"), dict) and (
            condition.condition_id == "condition:typed.check_mode" or set(rule) == {"check_mode"}):
        modes = {str(mode).upper() for mode in rule["check_mode"].values()}
        return "Disadvantage on ability checks" if "DISADVANTAGE" in modes else ""
    if condition.condition_id == "condition:typed.concentration_mode":
        return "Disadvantage on saving throws" if str(rule.get("concentration_mode") or "").upper() == "DISADVANTAGE" else ""
    if condition.condition_id == "condition:typed.save_against":
        return "Disadvantage on saving throws" if str((rule.get("save_against") or {}).get("mode") or "").upper() == "DISADVANTAGE" else ""
    return _CONDITION_PENALTIES.get(condition.condition_id.removeprefix("condition:typed."), "")


def _speed_penalty(modifier: Any) -> str:
    """"Speed reduction": a printed "its Speed is reduced by 10 feet" is a harmful modifier on the creature, not a
    condition, and is read the way combat/ext/life_riders.py reads one."""
    if modifier.target_field == "speed_halved" or (modifier.target_field == "speed_ft"
                                                    and isinstance(modifier.value, int) and modifier.value < 0):
        return "Speed reduced"
    return ""


def _modifier_penalty(modifier: Any) -> str:
    """One source-owned modifier, never incoming attacks or an Advantage benefit."""
    if modifier.target_field == "attack_mode" and str(modifier.value).upper() == "DISADVANTAGE":
        return "Disadvantage on attack rolls"
    return _speed_penalty(modifier)


def _regulable_effect(engine: Any, source_definition_id: Any) -> bool:
    """Everything the printed rule asks of an effect BEFORE it is offered, on the ability behind the effect:

    * it is one of the printed three -- a poison, a disease, or a directly caused physical impairment -- which the
      reviewed table (combat/rules/affliction_sources.json, read by ``_affliction_category``) establishes from that
      ability's own printed sentence. The category is never read off the penalty: a dream that leaves a printed penalty
      is not a physical impairment;
    * its printed record can be found, so the printed tag list below can be read from it;
    * it carries none of the seven tags the printed rule excludes.

    Anything that fails is simply not offered, which is what the printed rule says about an effect the table cannot
    place: it is the GM's to rule on.
    """
    key = _printed_key(engine, source_definition_id)
    return (bool(_affliction_category(engine, source_definition_id))
            and isinstance(_printed_rules().get(key), str)
            and not _tagged_forbidden(engine, source_definition_id))


def _suppressible(engine: Any, subject: Any) -> list[tuple[str, Any, str, int]]:
    """The target's penalties that the printed "Effect without Repeat Saves" branch can resolve: ``(benefit id, the row,
    the printed penalty, the printed DC)``, easiest DC first.

    Every printed limit is checked here, so nothing is offered that the rule does not allow:

    * one of the printed six penalties (a condition this table stores as a row, or a harmful Speed modifier);
    * an effect that repeats its own save -- that is the *other* printed branch, chosen from the same question;
    * a printed saving throw DC: the save the row remembers (``repeat_saves.save_of``, which now includes the
      roll-mode rows because ``typed_executor.save_provenance`` stores it there too), or the DC the ability printed for a
      Speed reduction;
    * a source the reviewed table places in the printed three, whose printed record the table can identify, carrying
      none of the seven excluded tags (all of that in ``_regulable_effect``).

    Nothing of the bearer's own doing is excluded: the printed rule limits the effect, not who cast it.
    """
    from .repeat_saves import save_of

    repeating_applications = {_effect_application(engine, c) for c in subject.conditions.values()
                              if (c.data or {}).get("repeat_save") or (c.data or {}).get("repeat_one")}
    found: list[tuple[str, Any, str, int]] = []
    for iid, condition in subject.conditions.items():
        if _effect_application(engine, condition) in repeating_applications:
            continue  # "Effect with Repeat Saves": the other branch, offered from the same question
        if condition.condition_id == "condition:typed.affliction":
            # A chosen symptom may coexist with damage/healing/other symptoms.
            # Suppress one mechanical field, keeping the native parent alive.
            dc = _printed_dc(engine, condition.source_definition_id)
            if dc is not None and _regulable_effect(engine, condition.source_definition_id):
                for path, penalty in _affliction_penalties(condition):
                    found.append((f"component:{iid}|{path}", condition, penalty, dc))
            continue
        # Grouped Speed reductions are conditions so each caster keeps its own
        # expiry. Read the shared movement contract instead of recognizing any
        # particular ability or condition id here.
        from ..motion import grouped_speed_penalty
        grouped_speed = grouped_speed_penalty(engine, subject, condition)
        if grouped_speed:
            dc = _printed_dc(engine, condition.source_definition_id)
            if dc is not None and _regulable_effect(engine, condition.source_definition_id):
                found.append((f"condition:{iid}", condition, "Speed reduced", dc))
            continue
        penalty, save = _condition_penalty(condition), save_of(condition)
        if not penalty:
            continue
        if not _regulable_effect(engine, condition.source_definition_id):
            continue
        dc = save.get("dc") if save is not None else _printed_dc(engine, condition.source_definition_id)
        if isinstance(dc, int) and not isinstance(dc, bool) and dc > 0:
            found.append((f"condition:{iid}", condition, penalty, dc))
    for mid, modifier in subject.modifiers.items():
        if _effect_application(engine, modifier) in repeating_applications:
            continue
        penalty = _modifier_penalty(modifier)
        provenance = getattr(modifier, "origin_save", None) or {}
        dc = provenance.get("dc") if provenance.get("ability") else _printed_dc(engine, modifier.source_definition_id)
        if isinstance(dc, bool) or not isinstance(dc, int) or dc <= 0:
            continue
        if not penalty or dc is None:
            continue
        if not _regulable_effect(engine, modifier.source_definition_id):
            continue
        found.append((f"modifier:{mid}", modifier, penalty, dc))
    return sorted(found, key=lambda row: (row[3], row[0]))


def _effect_application(engine: Any, row: Any) -> tuple[str, str, int]:
    """Group native sibling penalties by source, caster and committed activation.

    Receipt sequence, rather than penalty text or caster identity alone, keeps a
    later nonrepeating application distinct from an earlier repeating one.
    Native reactions within an intent remain separately qualified by source and
    applier. Direct legacy rows without an intent retain a zero receipt boundary.
    """
    from ..concentration import made_at
    key = getattr(row, "instance_id", None) or getattr(row, "modifier_id", "")
    sequence = made_at(key, row)
    start = next((e.sequence for e in reversed(engine.events)
                  if sequence is not None and e.sequence <= sequence and e.event_type == "INTENT_ACCEPTED"), 0)
    return row.source_definition_id, row.source_actor_id, start


def _affliction_penalties(condition: Any) -> list[tuple[str, str]]:
    """Named mechanical fields of a nonrepeating chosen affliction; no text inference."""
    data, out = condition.data or {}, []
    rule = data.get("rule") or {}
    if int(data.get("speed") or 0) < 0:
        out.append(("speed", "Speed reduced"))
    for key, label in (("attacks_have", "Disadvantage on attack rolls"),
                       ("concentration_mode", "Disadvantage on saving throws")):
        if str(rule.get(key) or "").upper() == "DISADVANTAGE":
            out.append(("rule." + key, label))
    for key, label in (("save_mode", "Disadvantage on saving throws"),
                       ("check_mode", "Disadvantage on ability checks")):
        # Each mode is its own penalty, so an Advantage entry is never removed.
        for ability, mode in (rule.get(key) or {}).items():
            if str(mode).upper() == "DISADVANTAGE":
                out.append((f"rule.{key}.{ability}", label))
    if rule.get("no_reactions"):
        out.append(("rule.no_reactions", "Cannot take Reactions"))
    return out


def _one_plain(repeat: dict[str, Any]) -> str:
    """One option's label, for a player who knows only basic D&D: what repeats, which throw, against what DC."""
    return f"{_ability_words(repeat.get('ability'))} saving throw, DC {int(repeat.get('dc') or 10)}"


def _ability_words(ability: Any) -> str:
    """A saving throw's ability in words. "CON" is a code, not something a player reads."""
    words = {"CON": "Constitution", "DEX": "Dexterity", "STR": "Strength", "INT": "Intelligence",
             "WIS": "Wisdom", "CHA": "Charisma"}
    code = str(ability or "CON").upper()[:3]
    return words.get(code, "Constitution")


def _cast_by_words(engine: Any, row: Any) -> str:
    """Which ability put this effect on the target, and which creature used it -- the two things a player can act on."""
    from .ability_source import source_label
    source = engine.state.actors.get(row.source_actor_id)
    who = getattr(source, "display_name", None) or "another creature"
    return f"{source_label(engine, row.source_definition_id)}, cast by {who}"


def _lasts_words(engine: Any, row: Any, holder: Any) -> str:
    """How long this one lasts, in the battle log's own plain words, never a raw expiry token (history_text.expiry_text)."""
    from ..history_text import expiry_text

    if not row.expires_on:
        return ""
    names = {actor.entity_id: actor.display_name for actor in engine.state.actors.values()}
    return expiry_text(row.expires_on, names, names.get(row.source_actor_id, "its source"),
                       getattr(holder, "display_name", "the affected creature"))


def _tell_apart(labels: dict[str, str]) -> dict[str, str]:
    """Two options that read identically would be an unanswerable question, so identical labels are counted in plain
    English instead ("... (2 of 3)")."""
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    if any(count > 1 for count in counts.values()):
        seen: dict[str, int] = {}
        for key, label in labels.items():
            if counts[label] > 1:
                seen[label] = seen.get(label, 0) + 1
                labels[key] = f"{label} ({seen[label]} of {counts[label]})"
    return labels


def _regulable_labels(engine: Any, subject: Any, eligible: list[tuple[str, Any]]) -> dict[str, str]:
    """One plain label per repeating effect, so a player can tell two of the same kind apart.

    "Choose one poison, disease, or physical impairment": the target can be carrying two Poisoned effects from different
    abilities, with different ends and different consequences, and they share a name and a DC. Each option therefore says
    which ability cast it, who cast it and how long it lasts, so the choice is answerable; the internal instance id that
    actually selects the effect stays hidden.
    """
    from ..presentation import condition_label

    labels: dict[str, str] = {}
    for iid, condition in eligible:
        parts = [f"{condition_label(condition.condition_id, condition.data)} ({_one_plain(_repeat_contract(condition))})",
                 _cast_by_words(engine, condition)]
        lasts = _lasts_words(engine, condition, subject)
        if lasts:
            parts.append(lasts)
        labels[iid] = " — ".join(parts)
    return _tell_apart(labels)


def _penalty_labels(engine: Any, subject: Any, eligible: list[tuple[str, Any, str, int]]) -> dict[str, str]:
    """One plain label per printed penalty, with the save that would be rolled against it and how long it lasts."""
    labels = {}
    for benefit_id, row, penalty, dc in eligible:
        parts = [f"{penalty} — {_cast_by_words(engine, row)} (Constitution saving throw with Advantage, DC {dc})"]
        lasts = _lasts_words(engine, row, subject)
        if lasts:
            parts.append(lasts)
        labels[benefit_id] = " — ".join(parts)
    return _tell_apart(labels)


def _suppress_penalty(ctx: Any, subject: Any, chosen: tuple[str, Any, str, int]) -> None:
    """"Effect without Repeat Saves": a Constitution saving throw with Advantage against the effect's printed DC, and on
    a success one of that effect's penalties is suppressed until the end of the target's next turn.

    The penalty is taken off the target and kept on the shared ``condition:typed.benefit_suppressed`` row
    (``benefit_suppression.suppress``, the helper module Void's riders use), with ``until="holder_turn_end"`` so the
    printed "until the end of the target's next turn" is the lifetime. The save is the printed one: Constitution, with
    Advantage, against the DC the effect itself remembers. ``_suppressible`` has already refused anything the printed
    limits do not allow -- including an effect the reviewed table cannot place in the printed three -- and a failed save
    changes nothing, exactly as printed.
    """
    from .benefit_suppression import suppress, suppress_component

    engine = ctx.engine
    benefit_id, row, penalty, dc = chosen
    # The grant changes the saving ability/mode, not which effect is resisted.
    # Preserve the native source/caster for source-qualified save protections.
    roll = engine._roll_save(subject, "CON", dc, row.source_definition_id, extra_mode="ADVANTAGE",
                             receipt_source_id=ctx.source, roll_context={"source_actor_id": row.source_actor_id})
    if roll is None or roll.total < dc:
        note(engine, ctx.source, ctx.actor, f"Meridian Regulation: {subject.display_name} fails the Constitution saving "
                                            f"throw (DC {dc}), so {penalty.lower()} is not suppressed.", (subject,))
        return
    label = f"Meridian Regulation: {penalty} suppressed until the end of {subject.display_name}'s next turn"
    if benefit_id.startswith("component:"):
        iid, path = benefit_id.removeprefix("component:").rsplit("|", 1)
        done = suppress_component(engine, ctx.actor, subject, iid, path, "holder_turn_end", ctx.source, label)
    else:
        done = suppress(engine, ctx.actor, subject, benefit_id, "holder_turn_end", ctx.source, label=label)
    if not done:
        ctx.rider(f"Meridian Regulation: {penalty} on {subject.display_name} could not be suppressed; the GM rules on it.")
        return
    note(engine, ctx.source, ctx.actor, f"Meridian Regulation: {penalty} on {subject.display_name} is suppressed until the "
                                        f"end of {subject.display_name}'s next turn (Constitution save with Advantage, DC "
                                        f"{dc}). The underlying effect is not removed and its duration still runs.", (subject,))


def _repeat_save(ctx: Any, subject: Any, iid: str, condition: Any) -> None:
    """"Effect with Repeat Saves": the target immediately repeats the saving throw with Advantage; on a success the
    effect's normal successful-save result applies (an end to it, the table's standing result for an effect whose own
    successful branch is empty)."""
    if (condition.data or {}).get("repeat_one"):
        from .afflictions import repeat_one_effect
        repeat_one_effect(ctx.engine, subject, iid, condition, extra_mode="ADVANTAGE", roll_source=ctx.source)
        return
    ctx.engine.resolve_repeat_save(subject, iid, condition, _repeat_contract(condition),
                                   "GRANTED_REPEAT", extra_mode="ADVANTAGE", roll_source=ctx.source)


@effect("meridian_regulation")
def meridian_regulation(ctx: Any, eff: dict[str, Any]) -> None:
    """Choose ONE of the target's effects, then resolve the printed branch that effect falls in.

    The printed rule chooses an *effect*, not a branch, and its two branches are "Effect with Repeat Saves" (repeat that
    save with Advantage; on a success its normal successful-save result applies) and "Effect without Repeat Saves" (a
    Constitution save with Advantage against the effect's printed DC; on a success one printed penalty stops applying
    until the end of the target's next turn). One question therefore offers every effect the printed limits allow, of
    either branch, and the selection decides which branch runs: an effect that repeats its save no longer hides another
    effect's penalties from the printed choice.
    """
    from .choice_prompt import action_context
    from .needle import ask, checkpoint_id

    engine, subject = ctx.engine, ctx.target or ctx.actor
    repeating = [(f"condition:{iid}", condition) for iid, condition in _regulable(engine, subject)]
    penalties = _suppressible(engine, subject)
    if not repeating and not penalties:
        ctx.rider("Meridian Regulation: nothing on the target is an effect this table can regulate. The printed rule "
                  "needs a poison, disease or directly caused physical impairment that has a printed saving throw DC "
                  "and carries none of the Curse, Tribulation, Foundation Injury, Hidden Injury, Possession, Permanent "
                  "or Soul Damage tags; the GM regulates one by hand.")
        return
    labels = {**_regulable_labels(engine, subject, repeating), **_penalty_labels(engine, subject, penalties)}
    order = [key for key, _ in repeating] + [row[0] for row in penalties]
    # "Choose one ...": the printed choice belongs to the player, so the table asks which one, naming what each branch
    # would roll. The choice rides the shared Needle transport (``choice:needle.*``, the seam ``ask`` carries its
    # options on), so this plug-in adds no new transport. Nobody answering (the built-in AI, an old saved fight) keeps
    # the first one.
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "meridian_regulation", subject.entity_id), ctx.actor,
                 "choice:needle.meridian_regulation", order, labels=labels,
                 name="Meridian Regulation",
                 prompt=(f"Meridian Regulation on {subject.display_name}: choose one of the poison, disease or physical "
                         "impairments affecting it to regulate. If that effect makes it repeat a saving throw, it "
                         "repeats that throw with Advantage; otherwise it makes a Constitution saving throw with "
                         "Advantage against that effect's printed DC, and on a success one of that effect's penalties "
                         "stops applying until the end of its next turn."),
                 target_id=subject.entity_id, preferred=[order[0]],
                 prompt_context=action_context(engine, ctx.actor, ctx.source, subject))
    chosen = picked[0] if picked and picked[0] in labels else order[0]
    repeat = next((pair for pair in repeating if pair[0] == chosen), None)
    if repeat is not None:
        _repeat_save(ctx, subject, chosen.removeprefix("condition:"), repeat[1])
        return
    _suppress_penalty(ctx, subject, next(row for row in penalties if row[0] == chosen))


# ------------------------------------------------------------------------------------------------ Golden Core Efficiency
@hook("technique_used")
def golden_core_efficiency(ctx: Any) -> None:
    """"Once per turn, reduce the Qi cost of one Qi-powered feature with a final cost of at least 2 Qi by 1" -- refunded as
    it resolves (the cost was paid when it was used)."""
    actor = ctx.actor
    if not _has(ctx.engine, actor, "golden_core_efficiency") or actor.turn_flags.get("golden_core_efficiency"):
        return
    paid = sum(int(amount) for resource, amount in (ctx.action.costs or ()) if resource == QI)
    if paid >= 2 and QI in actor.resources:
        from ..technique_costs import refund
        if not refund(ctx.engine, actor, ctx.source, ctx.action.costs, QI, 1,
                      "passive:tianxia.path.qi_cultivation.feature.golden_core_efficiency"):
            return
        actor.turn_flags["golden_core_efficiency"] = True


# ---------------------------------------------------------------------------------------- Meridian Regulation wording
@hook("decision_text")
def meridian_regulation_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """The Meridian Regulation question in plain words: which effect, what happens next, what it costs and what it does
    not do. One question covers both printed branches, so the wording has to name both.

    Presentation only, and inert for a character with no Meridian Regulation row on the table."""
    if str(context.get("reaction_source_id") or "") not in ("choice:needle.meridian_regulation",
                                                           "choice:needle.meridian_regulation_penalty"):
        return None
    owner = engine.state.actors.get(str(context.get("reactor_id") or ""))
    trigger = context.get("choice_trigger") or {}
    options = [str(option) for option in trigger.get("needle_options") or []]
    labels = {option: str((trigger.get("labels") or {}).get(option, "")) for option in options}
    if owner is None or not options:
        return None
    return {
        "name": "Meridian Regulation",
        "feature_id": "tianxia.path.qi_cultivation.feature.meridian_regulation",
        "summary": (f"{owner.display_name} regulates an effect already on a creature with Meridian Regulation. Choose one "
                    "of that creature's poisons, diseases or physical impairments. If that effect makes the creature repeat "
                    "a saving throw, it repeats that throw with Advantage and a successful repeat applies the effect's own "
                    "successful result. If the effect does not repeat its save, the creature makes a Constitution saving "
                    "throw with Advantage against the DC printed on the effect; on a success the chosen penalty stops "
                    "applying until the end of that creature's next turn. A failed save leaves everything as it was."),
        "cost": "1 Qi, spent when Meridian Regulation is used (the printed Action cost).",
        "limits": ("One effect per use. The underlying effect is not removed, its duration still runs, and this does not "
                   "cure a disease or poison, restore Hit Points, stop damage over time, remove Exhaustion, or remove a "
                   "higher-authority effect."),
        "option_descriptions": {option: label for option, label in labels.items() if label},
    }


@hook("compile_action")
def golden_choices(action: Any, info: dict[str, Any]) -> Any:
    """Seal the reviewed Circulating per-use option (its two-benefit choice at CL17) once; historical catalogs keep their
    previous benefit. This is the per-use option, not a Form pick: the Golden Core Form is a sheet record (build choice)."""
    if any(row.get("type") == "golden_core_choices" for row in (info["mechanics"].get(GOLDEN) or {}).get("effects") or []):
        return action.model_copy(update={"parameters": {**(action.parameters or {}), "golden_core_choices": True}})
    return None


@effect("golden_core_choices")
def golden_choices_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Reviewed declaration read by compile_action."""


GOLDEN_FIRST_CL, GOLDEN_REPLACE_CL, GOLDEN_SECOND_CL = 10, 15, 20  # printed: CL10 first Form; CL15 one replacement; CL20 second

# What each Form does, in the printed words, so the Grow tab can tell a player what a permanent choice buys before
# they make it. "Perfected" is the CL17 behaviour (both Forms are Perfected from CL20).
FORM_BENEFITS: dict[str, dict[str, str]] = {
    "stable": {
        "benefit": ("When Initiative is rolled, if your Qi is below your Proficiency Bonus you regain Qi up to it. "
                    "At the start of your turn you regain 1 Qi while you are still below that. Once per round, a hostile "
                    "effect that would reduce your Qi, your maximum Qi or your restored Qi reduces that loss by your "
                    "Proficiency Bonus instead. It does not reduce Qi you choose to spend."),
        "perfected": ("From Cultivation Level 17: recover up to 2 × Proficiency Bonus on Initiative and 2 Qi at the "
                      "start of your turn, and reduce hostile Qi loss by 2 × Proficiency Bonus."),
    },
    "circulating": {
        "benefit": ("Once per turn, after you spend Qi on a feature that resolves successfully, choose one: move 5 feet "
                    "without provoking Opportunity Attacks; shift around one creature in your weapon's reach without "
                    "provoking that creature's Opportunity Attack; gain Temporary Hit Points equal to your Proficiency "
                    "Bonus; or move your Domain Armament 10 feet. It does not trigger from refunded costs, invalid "
                    "activations, or the Qi you spend to use it."),
        "perfected": ("From Cultivation Level 17 you choose two different benefits, movement becomes 10 feet, "
                      "Temporary Hit Points become 2 × Proficiency Bonus and Domain Armament movement 20 feet."),
    },
    "reservoir": {
        "benefit": ("Bonus Action, once per scene: regain Qi equal to your Proficiency Bonus plus your Qi Cultivation "
                    "key ability modifier."),
        "perfected": ("From Cultivation Level 17 you regain 2 × Proficiency Bonus plus your key ability modifier. If "
                      "you begin your turn with 0 Qi and this is unused, it recovers before any other recovery, needs "
                      "no Bonus Action, and stays limited to once per scene."),
    },
}


def owns_feature(sheet: dict[str, Any], feature_id: str) -> bool:
    """Whether this character's sheet actually grants a Path feature (shared by every Qi build choice).

    A sheet lists the Path features it took in ``path_and_subpath.path_feature_record_ids`` and in
    ``earned_feature_occurrences``; this reads both, the same way combat/armour.py and the factory compiler do.
    A build choice is only offered to a character that owns the feature that grants it, so a character on another
    Path (or a plain character) can never acquire a stray Golden Core Form record."""
    paths = sheet.get("path_and_subpath") or {}
    if feature_id in set(paths.get("path_feature_record_ids") or []):
        return True
    return any(isinstance(row, dict) and row.get("feature_id") == feature_id
               for row in paths.get("earned_feature_occurrences") or [])


def form_rows(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """The Golden Core Form(s) the character's own sheet records, with the level and time they were recorded.

    A sheet may store a Form as its plain id or as a row carrying ``id``, ``cl`` and ``at``, so a Form recorded
    during character creation keeps the same provenance as one recorded later at the table."""
    out: list[dict[str, Any]] = []
    for row in (sheet.get("path_and_subpath") or {}).get("golden_core_forms") or []:
        if isinstance(row, str) and row in FORMS:
            out.append({"id": row, "cl": None, "at": None})
        elif isinstance(row, dict) and row.get("id") in FORMS:
            out.append({"id": str(row["id"]), "cl": int(row["cl"]) if row.get("cl") else None,
                        "at": str(row.get("at") or "") or None})
    return out


def _breakthrough_recorded(table: dict[str, Any] | None, cl: int) -> bool:
    """True when the growth record holds a successful CL15 breakthrough (table["breakthroughs"], recorded at the table)."""
    return cl >= GOLDEN_REPLACE_CL and any(int(row.get("cl") or 0) == GOLDEN_REPLACE_CL for row in (table or {}).get("breakthroughs") or [])


def _feature_used(table: dict[str, Any] | None, feature_id: str) -> bool:
    """True when the growth record holds a recorded use of a realm feature (table["feature_uses"], recorded at the table).

    The printed rules close some windows on *using* a realm feature ("before using your CL15 Nascent Soul feature"),
    so the table records the use beside the character and the build choice reads it back."""
    return any(str(row.get("feature_id")) == feature_id for row in (table or {}).get("feature_uses") or [])


class GoldenCoreChoice:
    """The Golden Core Form build choice. The printed rule lives here, not in the table: a first Form at CL10; one
    replacement only after a successful CL15 breakthrough and before the CL15 Nascent Soul feature has been used; a
    second Form at CL20.

    "You may replace the chosen Form after a successful CL15 breakthrough before using your CL15 Nascent Soul feature."
    Both edges of that window are enforced from the growth record: the breakthrough must be recorded
    (``record_breakthrough``) and the Nascent Soul use must not be recorded (``record_feature_use``)."""

    kind = "golden_core"

    @staticmethod
    def _slots(base: dict[str, Any], rows: list[dict[str, Any]], cl: int) -> dict[int, tuple[str, str, int | None, str | None]]:
        """slot -> (Form, source, CL recorded, time recorded): the sheet's own Forms, then each growth-record row
        reached at this CL."""
        slots: dict[int, tuple[str, str, int | None, str | None]] = {}
        recorded = form_rows(base)
        if recorded:
            slots[1] = (recorded[0]["id"], "sheet", recorded[0]["cl"], recorded[0]["at"])
        if len(recorded) > 1:
            slots[2] = (recorded[1]["id"], "sheet", recorded[1]["cl"], recorded[1]["at"])
        for row in rows:
            slot, at = int(row.get("slot") or 1), int(row.get("cl") or 0)
            if row.get("id") in FORMS and at <= cl and (slot == 1 and at >= GOLDEN_FIRST_CL or slot == 2 and at >= GOLDEN_SECOND_CL):
                slots[slot] = (str(row["id"]), "record", at, str(row.get("at") or "") or None)
        return slots

    def effective(self, base: dict[str, Any], rows: list[dict[str, Any]], cl: int) -> list[str]:
        slots = self._slots(base, rows, cl)
        return [slots[slot][0] for slot in (1, 2) if slot in slots]

    def overlay(self, out: dict[str, Any], base: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        cl = int((base.get("identity") or {}).get("cultivation_level") or 1)
        out.setdefault("path_and_subpath", {})["golden_core_forms"] = self.effective(base, rows, cl)

    def validate(self, base: dict[str, Any], rows: list[dict[str, Any]], cl: int, *, slot: Any, choice: str,
                 table: dict[str, Any] | None = None) -> dict[str, Any]:
        if not owns_feature(base, GOLDEN):
            raise BuildChoiceRefused("TABLETOP_GOLDEN_NO_FEATURE",
                                     "This character does not have the Golden Core Form feature, so it has no Form to choose.", 409)
        if type(slot) is not int or slot not in (1, 2):
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "Choose Form slot 1 or 2.", 400)
        if choice not in FORMS:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_FORM", "Choose Stable, Circulating or Reservoir.", 400)
        if cl < GOLDEN_FIRST_CL:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_CL", "A Golden Core Form is chosen from Cultivation Level 10.", 409)
        slots = self._slots(base, rows, cl)
        if slot == 1 and _feature_used(table, NASCENT_SOUL):
            # Printed: "...before using your CL15 Nascent Soul feature." The printed permission the
            # CL10 first Form rides ends with that use as well, so no slot-1 record survives it.
            raise BuildChoiceRefused("TABLETOP_GOLDEN_CLOSED", "You have already used your Nascent Soul feature. The printed permission to choose or replace your Golden Core Form ended with that use, so your Form choice is closed.")
        other = slots.get(2 if slot == 1 else 1)
        if other and other[0] == choice:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "The second Form must differ from the first." if slot == 2
                                     else "The first Form must differ from the second active Form.")
        if slot == 2:
            if cl < GOLDEN_SECOND_CL:
                raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "The second Form is chosen at Cultivation Level 20.")
            if 1 not in slots:
                raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "Choose the first Form before the second.")
            if 2 in slots:
                raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "Your second Form is already recorded.")
            return {"id": choice, "slot": 2}
        current = slots.get(1)
        if current is None:
            return {"id": choice, "slot": 1}
        if current[0] == choice:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "That is already your first Form.")
        if cl < GOLDEN_REPLACE_CL:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "The first Form can be replaced from Cultivation Level 15, after your breakthrough.")
        if cl > GOLDEN_REPLACE_CL:
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "The replacement window (Cultivation Level 15, after your breakthrough, before Nascent Soul) has closed.")
        if _feature_used(table, NASCENT_SOUL):
            # Printed: "...before using your CL15 Nascent Soul feature." The use closes the window.
            raise BuildChoiceRefused("TABLETOP_GOLDEN_CLOSED", "You have already used your Nascent Soul feature. The printed permission to replace your first Form ended before that use, so your Form is fixed now.")
        if not _breakthrough_recorded(table, cl):
            raise BuildChoiceRefused("TABLETOP_GOLDEN_BREAKTHROUGH", "Record your successful Cultivation Level 15 breakthrough first (Grow tab, Golden Core Forms), then you can replace your first Form.")
        if any(row.get("replaces") and int(row.get("cl") or 0) == GOLDEN_REPLACE_CL for row in rows):
            raise BuildChoiceRefused("TABLETOP_GOLDEN_SLOT", "You have already replaced your first Form at this breakthrough.")
        return {"id": choice, "slot": 1, "replaces": current[0]}

    def panel(self, base: dict[str, Any], rows: list[dict[str, Any]], cl: int, *, table: dict[str, Any] | None = None) -> dict[str, Any]:
        # A character without the Golden Core Form feature has no Form to show or choose, so the
        # Grow tab offers no options for it (the same ownership rule validate enforces).
        if not owns_feature(base, GOLDEN):
            return {"cl": cl, "owned": False, "forms": [], "options": [], "breakthrough": None}
        slots = self._slots(base, rows, cl)
        forms = [{"slot": slot, "id": slots[slot][0], "name": FORMS[slots[slot][0]], "source": slots[slot][1],
                  "cl": slots[slot][2], "at": slots[slot][3], **FORM_BENEFITS.get(slots[slot][0], {})}
                 for slot in (1, 2) if slot in slots]
        options = []
        for slot in (1, 2):
            for key, name in FORMS.items():
                try:
                    self.validate(base, rows, cl, slot=slot, choice=key, table=table)
                    allowed, reason = True, ("Choose as your first Form." if slot == 1 and 1 not in slots
                                             else "Replace your first Form (one replacement at this breakthrough)." if slot == 1
                                             else "Choose as your second Form.")
                except BuildChoiceRefused as exc:
                    allowed, reason = False, exc.message
                options.append({"slot": slot, "id": key, "name": name, "allowed": allowed, "reason": reason,
                                **FORM_BENEFITS.get(key, {})})
        # The Grow tab offers the CL15 breakthrough record only while a replacement is still possible.
        breakthrough = ({"cl": GOLDEN_REPLACE_CL, "recorded": _breakthrough_recorded(table, cl)}
                        if cl == GOLDEN_REPLACE_CL and 1 in slots else None)
        # Whether the printed window has already closed by using the CL15 Nascent Soul feature.
        nascent_used = _feature_used(table, NASCENT_SOUL)
        return {"cl": cl, "owned": True, "forms": forms, "options": options, "breakthrough": breakthrough,
                "nascent_used": nascent_used, "nascent_feature_id": NASCENT_SOUL}


GOLDEN_CHOICE = register_build_choice(GoldenCoreChoice())
