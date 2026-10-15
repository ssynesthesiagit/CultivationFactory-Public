"""Body Refining's Core Tempering Expressions and Stomping Step.

Selections are persisted, including two distinct simultaneous expressions at
CL20. Golden Bell grants AC/save benefits, zero-damage Stamina Guard Temporary
HP and Perfected d12s; its typed-push anchoring compares the actual source CL
and honors an explicit ignores_bodily_anchoring exemption. Blood Furnace's
existing resource-spend delivery heals or grants Temporary HP once per creature
turn; Perfected actual healing may end one represented Bleeding state of no
higher Source CL. Mountain-Rending holds its empowerment through misses until
the source's next turn ends, and supplies its selected hit rider.

Remaining gaps include countered-but-paid Blood Furnace/Mountain activation,
non-save push/Prone checks, native displacement anchoring, and Mountain's object
result. These features are not certified complete by this module.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
SECOND_CTE = "tianxia.path.body_refining.feature.second_core_tempering_expression"
IMMORTAL_BODY = "tianxia.path.body_refining.feature.immortal_body"
CHOICE_CONDITION = "condition:typed.core_tempering_expression"
GOLDEN_BELL_STANCE = "Golden Bell Circulation"
READY_CONDITION = "condition:typed.mountain_rending_ready"
MR_CHOICE_CONDITION = "condition:typed.mountain_rending_choice"
LABELS = {"golden_bell": "Golden Bell Circulation", "blood_furnace": "Blood-Furnace Circulation", "mountain_rending": "Mountain-Rending Pulse"}
EXPRESSION_LIFETIME = "Your choice is permanent until a later Realm breakthrough; you cannot change it during this fight."


@hook("setting_lifetime")
def expression_lifetime(action: dict[str, Any]) -> str | None:
    """Read-only lifetime for owned Expression selectors, including old catalogs."""
    if (action.get("parameters") or {}).get("cte_choice"):
        return EXPRESSION_LIFETIME
    return None


def _numbers(engine: Any, actor_id: str) -> dict[str, Any]:
    """Read sealed action numbers, identically during compilation, reload and replay."""
    from .needle import numbers_of

    return numbers_of(engine, engine.state.actors[actor_id])


def _expression(actor: Any) -> str | None:
    return next(iter(_expressions(actor)), None)


def _expressions(actor: Any) -> tuple[str, ...]:
    """Read one legacy choice or both CL20 slots in persisted selection order."""
    held = sorted((c for c in actor.conditions.values() if c.condition_id == CHOICE_CONDITION), key=lambda c: c.applied_sequence)
    return tuple(dict.fromkeys(str((c.data or {}).get("expression")) for c in held if (c.data or {}).get("expression")))


def _expression_slots(engine: Any, actor: Any) -> int:
    return 2 if any((engine.action_catalog.get(aid).parameters or {}).get("cte_expression_slots") == 2
                    for aid in actor.action_ids if engine.action_catalog.get(aid) is not None) else 1


def _perfected(engine: Any, actor_id: str) -> bool:
    return int(_numbers(engine, actor_id).get("cl") or 1) >= 17


@hook("compile_block")
def body_refining_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "bodya_body_refining" or spec.get("kind") != "immortal_regeneration":
        return None
    return [{**row, "block": "bodya_body_refining", "kind": "immortal_regeneration"}]


@hook("turn_start")
def immortal_regeneration(engine: Any, actor: Any) -> None:
    """Immortal Regeneration: "At the start of each of your turns, if you have at least 1 Hit Point, regain 20 Hit Points."

    The 20 HP is an ordinary typed ``healing`` row run through typed_executor.run_effects, the shared healing path
    (Liver Furnace in organ_furnaces.py does the same): the ``effect_allowed`` seam can stop it, block_healing applies
    "cannot regain HP", halving, flat reductions and spends a one-use "next healing" reduction, then records
    HEALING_APPLIED and the "healed" creature event. Nothing is offered at full HP, so no one-use reduction is spent
    on a heal that could not restore anything."""
    if actor.current_hp <= 0 or actor.current_hp >= actor.maximum_hp or not any(
        row.get("block") == "bodya_body_refining" and row.get("kind") == "immortal_regeneration"
        for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    ):
        return
    from .. import typed_executor as te
    from .states import context

    ctx = context(engine, actor, IMMORTAL_BODY, [actor], _numbers(engine, actor.entity_id)).with_source(IMMORTAL_BODY)
    te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "flat": 20, "regeneration": True,
                          "evidence": "Immortal Regeneration: at the start of your turn, with at least 1 HP, regain 20 HP."}])


def _combat_turn(engine: Any) -> str:
    """Stable identity of this combat turn, including turns belonging to other actors."""
    current = engine.state.actors[engine.state.current_actor_id]
    return f"{current.entity_id}:{current.turns_started}"


# ------------------------------------------------------------------------------------------------------- build choice
@hook("compile_actions")
def cte_actions(info: dict[str, Any]) -> list[Any] | None:
    if CTE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS

    actor_id, numbers, short = info["actor_id"], info["numbers"], info["short"]
    # Structured owner-sheet choice: canonical key or printed expression name.
    # It is sealed in the action bundle so reload never consults a live sheet.
    recorded = (info["owner_sheet"].get("path_and_subpath") or {}).get("core_tempering_expression")
    recorded_key = next((key for key, label in LABELS.items() if str(recorded or "").casefold() in
                         (key.casefold(), label.casefold())), None)
    slots = 2 if SECOND_CTE in info["owned_ids"] and int(numbers.get("cl") or 1) >= 20 else 1
    out: list[Any] = []
    for key, label in LABELS.items():
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.core_tempering_expression.{key}", display_name=f"Core Tempering Expression: {label}",
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "cte_choice", "expression": key}], "numbers": numbers, "duration": {"kind": "instant"},
                                  "riders": []}, "expected_damage": 0, "player_only": True, "cte_choice": True,
                        "cte_expression_slots": slots}))
    out.append(ActionDefinition(
        source_definition_id=f"action:typed.{short}.golden_bell_circulation", display_name="Golden Bell Circulation",
        owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        costs=((RESOURCE_IDS["stamina"], 3),),
        parameters={"typed": {"effects": [{"type": "stance", "name": GOLDEN_BELL_STANCE, "rounds": 10,
                                          "evidence": "For the duration: +2 AC; Advantage on checks and saving throws against being pushed, "
                                                      "pulled, or knocked Prone; once per round, Temporary HP when Stamina Guard reduces a "
                                                      "damage packet to 0."}],
                              "numbers": numbers, "duration": {"kind": "special"}, "riders": []},
                    "expected_damage": 0, "cte_expression_gate": "golden_bell"}))
    for key, choice_label in (("push", "Push"), ("deny_reactions", "Deny Reactions")):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.mountain_rending_choice.{key}", display_name=f"Mountain-Rending: {choice_label}",
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "mountain_rending_choice", "choice": key}], "numbers": numbers,
                                  "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True,
                        "cte_expression_gate": "mountain_rending"}))
    if int(numbers.get("cl") or 1) >= 17:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.mountain_rending_choice.prone", display_name="Mountain-Rending: Knock Prone",
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "mountain_rending_choice", "choice": "prone"}], "numbers": numbers,
                                  "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True,
                        "cte_expression_gate": "mountain_rending"}))
    for index, action in enumerate(out):
        if action.parameters.get("cte_choice"):
            expression = action.parameters["typed"]["effects"][0]["expression"]
            benefit = {
                "golden_bell": "Golden Bell Circulation: a Bonus Action and 3 Stamina give you +2 AC for 1 minute, "
                               "Advantage on saves against pushes, pulls and being knocked Prone, and temporary hit points "
                               "once per round when Stamina Guard reduces damage to 0.",
                "blood_furnace": "Blood-Furnace Circulation: once per turn after spending Stamina on a successful feature, "
                                 "you regain hit points equal to your Proficiency Bonus (twice that at level 17). "
                                 "If already at full health, gain temporary hit points instead. No extra Stamina cost.",
                "mountain_rending": "Mountain-Rending Pulse: once per turn after spending Stamina, your next Body Refining "
                                   "melee hit before the end of your next turn deals an extra 1d8 Force damage (2d8 at level 17). "
                                   "On a hit, push the target 5 feet or stop its Reactions until its next turn starts. "
                                   "At level 17, push 10 feet or knock it Prone on a failed Strength save. No extra Stamina cost.",
            }[expression]
            out[index] = action.model_copy(update={"parameters": {**action.parameters,
                "setting_lifetime": EXPRESSION_LIFETIME,
                "setting_description": "Choose your Core Tempering Expression. This takes no action and costs no Stamina. "
                                       "It is permanent until a later Realm breakthrough; you cannot change it during this fight. "
                                       + ("At level 20 you choose two different Expressions; both work at the same time. "
                                          if slots == 2 else "") + benefit,
                **({"cte_sheet_expression": recorded_key} if recorded_key else {}),
                **({"ai_setting_default": {
                    "condition_id": CHOICE_CONDITION, "source_definition_id": CTE,
                    "data": {"expression": expression,
                             "label": "Core Tempering Expression: Blood-Furnace Circulation",
                             "description": benefit + " Your expression stays until a later Realm breakthrough."},
                }} if expression == "blood_furnace" else {})}})
    return out


@hook("match_start")
def recorded_expression(engine: Any) -> None:
    for action in engine.action_catalog.values():
        expression = (action.parameters or {}).get("cte_sheet_expression")
        if not expression:
            continue
        actor = engine.state.actors.get(action.owner_id)
        if actor is not None and _expression(actor) is None:
            engine._apply_condition(actor, CHOICE_CONDITION, CTE, actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"expression": expression, "label": f"Core Tempering Expression: {LABELS[expression]}"})


@hook("candidate_allowed")
def cte_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    if parameters.get("cte_choice"):
        selected = _expressions(actor)
        return actor.turns_started <= 1 and len(selected) < int(parameters.get("cte_expression_slots") or 1) \
            and str((parameters.get("typed") or {}).get("effects", [{}])[0].get("expression")) not in selected
    gate = parameters.get("cte_expression_gate")
    if gate:
        return gate in _expressions(actor)
    return None


@effect("cte_choice")
def cte_choice(ctx: Any, eff: dict[str, Any]) -> None:
    expression = str(eff.get("expression") or "")
    selected = _expressions(ctx.actor)
    if expression not in LABELS or len(selected) >= _expression_slots(ctx.engine, ctx.actor) or expression in selected:
        return  # also protect direct effect execution and stale/duplicated choice effects
    ctx.engine._apply_condition(ctx.actor, CHOICE_CONDITION, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"expression": expression, "label": f"Core Tempering Expression: {LABELS.get(expression, expression)}"})
    ctx.rider(f"Core Tempering Expression set to {LABELS.get(expression, expression)}.")


# ------------------------------------------------------------------------------------------------------- Golden Bell
@hook("ac")
def golden_bell_ac(engine: Any, actor: Any) -> int | None:
    from .. import stances

    return 2 if any((c.data or {}).get("name") == GOLDEN_BELL_STANCE for c in stances.active(actor)) else None


@hook("save")
def golden_bell_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    from .. import stances

    if not {"prone", "forced_movement"} & {str(row).lower() for row in named or ()}:
        return None
    if not any((c.data or {}).get("name") == GOLDEN_BELL_STANCE for c in stances.active(subject)):
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("soak_dice")
def perfected_golden_bell_dice(engine: Any, target: Any, row: dict[str, Any], spend: int, dice: Any) -> Any | None:
    """Perfected Golden Bell changes its owner's Stamina Guard dice to d12 while its stance is active."""
    if not _perfected(engine, target.entity_id) or "golden_bell" not in _expressions(target):
        return None
    from .. import stances

    if not any((condition.data or {}).get("name") == GOLDEN_BELL_STANCE for condition in stances.active(target)):
        return None
    from ..gate2_rolls import DiceSpec

    return DiceSpec(count=spend, sides=12, modifier=dice.modifier)


@hook("event")
def golden_bell_soak(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .. import stances

    if event_type != "REACTION_RESOLVED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("pending_after") != 0 or "spend" not in payload:
        return  # only a damage_soak (Stamina Guard) resolution carries "spend"; damage_reduction/save_rescue rows do not
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None:
        return
    active = next((c for c in stances.active(actor) if (c.data or {}).get("name") == GOLDEN_BELL_STANCE), None)
    if active is None:
        return
    flag = "bodya_golden_bell_soak_round"
    if actor.turn_flags.get(flag) == engine.state.round_number:
        return
    actor.turn_flags[flag] = engine.state.round_number
    pb = int(_numbers(engine, actor.entity_id).get("pb") or 2)
    amount = 2 * pb if _perfected(engine, actor.entity_id) else pb
    engine._grant_temp_hp(actor, amount, active.source_definition_id, actor.entity_id)


@hook("event")
def golden_bell_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") != "condition:typed.unconscious":
        return
    from .. import stances

    actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is None:
        return
    for condition in list(stances.active(actor)):
        if (condition.data or {}).get("name") == GOLDEN_BELL_STANCE:
            engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)


# --------------------------------------------------------------------------------------------------- Blood-Furnace
@hook("event")
def blood_furnace(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "RESOURCE_SPENT" or (kwargs.get("payload") or {}).get("resource_id") != "resource:core.stamina":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or "blood_furnace" not in _expressions(actor) or not actor.active or actor.current_hp <= 0:
        return
    flag = "bodya_blood_furnace_used"
    turn = _combat_turn(engine)
    if actor.turn_flags.get(flag) == turn:
        return
    actor.turn_flags[flag] = turn
    pb = int(_numbers(engine, actor.entity_id).get("pb") or 2)
    amount = 2 * pb if _perfected(engine, actor.entity_id) else pb
    source_id = "tianxia.path.body_refining.feature.core_tempering_expression"
    if actor.current_hp >= actor.maximum_hp:
        engine._grant_temp_hp(actor, amount, source_id, actor.entity_id)
    else:
        from .healing_policy import ordinary_preparation
        if ordinary_preparation(engine, actor):
            from ..typed_executor import stored_healing_reductions
            amount = stored_healing_reductions(engine, actor, amount, healer=actor, source=source_id)
        before = actor.current_hp
        engine._heal(actor, amount, source_id, actor.entity_id, notify_healed=True)
        if actor.current_hp > before and _perfected(engine, actor.entity_id):
            _end_one_bleeding(engine, actor, source_id)


# ------------------------------------------------------------------------------------------------- Mountain-Rending
@effect("mountain_rending_choice")
def mountain_rending_choice(ctx: Any, eff: dict[str, Any]) -> None:
    choice = str(eff.get("choice") or "push")
    ctx.engine._remove_condition(ctx.actor, MR_CHOICE_CONDITION, ctx.source)
    ctx.engine._apply_condition(ctx.actor, MR_CHOICE_CONDITION, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": choice, "label": f"Mountain-Rending: {choice}"})


def _mr_choice(actor: Any) -> str:
    return next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == MR_CHOICE_CONDITION), "push")


@hook("event")
def mountain_rending_ready(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "RESOURCE_SPENT" or (kwargs.get("payload") or {}).get("resource_id") != "resource:core.stamina":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or "mountain_rending" not in _expressions(actor) or not actor.active or actor.current_hp <= 0:
        return
    flag = "bodya_mountain_rending_used"
    turn = _combat_turn(engine)
    if actor.turn_flags.get(flag) == turn:
        return
    actor.turn_flags[flag] = turn
    engine._remove_condition(actor, READY_CONDITION, "tianxia.path.body_refining.feature.core_tempering_expression")
    engine._apply_condition(actor, READY_CONDITION, "tianxia.path.body_refining.feature.core_tempering_expression", actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}", data={"label": "Mountain-Rending Pulse: next hit empowered"})


@hook("after_hit")
def mountain_rending_strike(ctx: Any, target: Any, kind: str) -> None:
    if not _melee_kind_body_refining(ctx, kind):
        return
    ready = next((c for c in ctx.actor.conditions.values() if c.condition_id == READY_CONDITION), None)
    if ready is None:
        return
    ctx.engine._remove_condition(ctx.actor, READY_CONDITION, ready.source_definition_id)
    perfected = _perfected(ctx.engine, ctx.actor.entity_id)
    choice = _mr_choice(ctx.actor)
    effects: list[dict[str, Any]] = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2 if perfected else 1, "sides": 8},
                                      "damage_types": ["force"], "evidence": "Mountain-Rending Pulse."}]
    if choice == "deny_reactions":
        # stated_expiry converts this to the target's persisted next-start clock.
        effects.append({"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                        "evidence": "Mountain-Rending Pulse: cannot take Reactions until the start of its next turn."})
    elif choice == "prone" and perfected:
        effects.append({"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target",
                        "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target",
                                    "evidence": "Perfected Mountain-Rending Pulse: knocked Prone."}], "on_success": [],
                        "evidence": "Perfected Mountain-Rending Pulse: Strength save or fall Prone."})
    else:
        effects.append({"type": "forced_movement", "applies_to": "target", "distance_ft": 10 if perfected else 5,
                        "evidence": "Mountain-Rending Pulse: push."})
    from ..typed_executor import run_effects

    run_effects(ctx.on_hit_context(target), effects)


def _melee_kind_body_refining(ctx: Any, kind: str) -> bool:
    return kind == "unarmed" or (kind == "weapon" and int(ctx.typed.get("range_ft") or 5) <= 5)


# --------------------------------------------------------------------------------------------------- Stomping Step
STOMPING_STEP = "tianxia.path.body_refining.feature.stomping_step"
DASH_OR_DISENGAGE = "dash_or_disengage"
DASH_OR_DISENGAGE_LABELS = {
    "dash": "Dash: gain extra movement equal to your Speed this turn",
    "disengage": "Disengage: your movement doesn't provoke Opportunity Attacks for the rest of this turn",
}


@effect(DASH_OR_DISENGAGE)
def dash_or_disengage(ctx: Any, eff: dict[str, Any]) -> None:
    """Stomping Step (CL1, Bonus Action, no Stamina): "Take either the Dash action or Disengage action."

    The typed effect of Stomping Step's own action (reviewed_final.d/bodya.json), so every Stomping Step action -- the
    plain one and each Swaying Step variant -- keeps its single action id, and the plug-ins that react to Stomping Step
    (sky_treading's Thousand-Mile Legs, karate's Perfect Breath, by action id) fire whichever is chosen.
    Asked of a player-controlled fighter; an AI fighter Disengages while a hostile creature is within 5 feet of it and
    Dashes otherwise. Dash runs the existing typed Dash (movement equal to Speed; refused under no_dash); Disengage sets
    the core Disengage's own turn flag (gate2_engine: "disengaged"), cleared with the other turn flags when the
    fighter's next turn starts, exactly like the Disengage action. A no_dash / no_disengage rule
    (Clinging Seal, Thick Darkness) removes that option. Usable by any "take the Dash or Disengage action" ability."""
    from ..typed_executor import condition_rules, run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    rules = condition_rules(actor)
    options = [key for key, rule in (("dash", "no_dash"), ("disengage", "no_disengage")) if not any(row.get(rule) for row in rules)]
    name = str(ctx.action.display_name)
    if not options:
        ctx.rider(f"{name}: blocked -- it cannot take the Dash or Disengage action right now.")
        return
    threatened = any(other.active and other.entity_id != actor.entity_id and other.team_id != actor.team_id
                     and engine._distance_actor_to_actor(actor, other) <= 5 for other in engine.state.actors.values())
    preferred = "disengage" if threatened and "disengage" in options else options[0]
    if len(options) == 1:
        picked = options  # the other action is barred right now: nothing to ask
    else:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, DASH_OR_DISENGAGE, actor.entity_id), actor, CHOICE + DASH_OR_DISENGAGE,
                     options, labels={key: DASH_OR_DISENGAGE_LABELS[key] for key in options}, preferred=[preferred],
                     target_id=actor.entity_id, name=name, feature_id=STOMPING_STEP,
                     prompt=f"{name} (Bonus Action): take the Dash action (move up to your Speed again this turn) or the Disengage "
                            "action (moving away doesn't provoke Opportunity Attacks for the rest of this turn)?",
                     prompt_context=action_context(engine, actor, ctx.source, actor))
    choice = picked[0] if picked else preferred
    evidence = str(eff.get("evidence") or "Take either the Dash action or Disengage action.")
    if choice == "dash":
        run_effects(ctx, [{"type": "movement", "distance_ft": "speed", "evidence": evidence}])
        return
    actor.turn_flags["disengaged"] = True
    from . import run_strict
    run_strict("movement_action_resolved", ctx, "disengage")
    text = f"{name}: Disengage -- {actor.display_name}'s movement doesn't provoke Opportunity Attacks for the rest of this turn."
    engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=actor.entity_id, payload={"trigger": text, "text": text})


def _end_one_bleeding(engine: Any, actor: Any, source: str) -> None:
    """A real healing result may end one source-qualified Bleeding state."""
    from .needle import ask, checkpoint_id, numbers_of
    from .condition_events import drop_condition
    cl = int(_numbers(engine, actor.entity_id).get("cl") or 1)
    eligible = []
    labels = {}
    for held in actor.conditions.values():
        if held.condition_id != "condition:typed.bleeding":
            continue
        action = engine.action_catalog.get(held.source_definition_id)
        numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") if action else None
        source_actor = engine.state.actors.get(held.source_actor_id)
        source_cl = (held.data or {}).get("source_cl")
        if source_cl is None:
            source_cl = (numbers or (numbers_of(engine, source_actor) if source_actor is not None else {})).get("cl")
        if source_cl is not None and int(source_cl) <= cl:
            eligible.append(held)
            source_name = (source_actor.display_name if source_actor is not None
                           else getattr(action, "display_name", None) or "Unknown source")
            feature_name = getattr(action, "display_name", None) or "Bleeding"
            severity = (held.data or {}).get("severity") or (held.data or {}).get("damage_per_turn")
            detail = f", severity {severity}" if severity is not None else ", continues until ended"
            labels[held.instance_id] = f"{source_name}: {feature_name} (Source cultivation level {int(source_cl)}{detail})"
    picked = ask(engine, engine._active_intent, checkpoint_id(engine, "blood_furnace_bleeding", actor.entity_id),
        actor, "choice:needle.blood_furnace_bleeding", [h.instance_id for h in eligible], allow_decline=True,
        labels=labels,
        name="Perfected Blood-Furnace Circulation", feature_id=CTE,
        prompt="Blood-Furnace Circulation restored Hit Points. End one Bleeding state caused by a source with a cultivation level no higher than yours, or keep it?")
    if picked:
        drop_condition(engine, actor, picked[0], source)


@hook("forced_movement_restriction")
def perfected_golden_bell_anchor(ctx: Any, subject: Any, effect: Any, maximum_ft: int) -> int | None:
    """Printed lower-CL anchoring uses the actual push's source and opt-out."""
    if subject is None or ctx.actor is subject or effect.get("ignores_bodily_anchoring"):
        return None
    from .. import stances
    if not _perfected(ctx.engine, subject.entity_id) or "golden_bell" not in _expressions(subject):
        return None
    if not any((c.data or {}).get("name") == GOLDEN_BELL_STANCE for c in stances.active(subject)):
        return None
    source_cl = int(ctx.numbers.get("cl") or 1)
    return 0 if source_cl < int(_numbers(ctx.engine, subject.entity_id).get("cl") or 1) else None
