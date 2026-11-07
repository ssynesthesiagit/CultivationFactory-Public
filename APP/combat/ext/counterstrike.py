"""Counterstrike, Reflexive Preparation and Raging Bull (Retribution) as a Ready action (automation lane H2, 2026-09-29,
on Astra's lock-round-2 hooks prepared_trigger / prepared_action).

Owner text (rules_text.json RETRIBUTION_BASE_COUNTERSTRIKE):
  * Action, "Ready Action": prepare one melee weapon attack or Unarmed Strike as a Counterstrike; choose the attack, one
    perceivable trigger and one Counter talent you know, if any. Until the start of your next turn, when a chosen trigger
    begins you may take your Reaction to make the prepared attack against the triggering creature. It resolves before the
    triggering activity finishes, which then continues normally; you must perceive the trigger; the triggering creature
    must be a legal target when the Counterstrike resolves; you may ignore a trigger and keep waiting.
  * Hit: the attack's ordinary damage plus your Proficiency Bonus on one damage roll. After a Counterstrike hits you regain
    your Reaction if it is expended (an exception that does not allow a second Counterstrike); one Counterstrike per round.
  * Reflexive Preparation (Bonus Action, Martial Focus): prepare Counterstrike without taking the Ready Action.
  * Raging Bull (Counter): when the chosen trigger begins, move up to half your Speed in a straight line first; it must end
    with the triggering creature within reach, uses your movement, provokes Opportunity Attacks, and cannot pass through
    occupied spaces; if you cannot reach the creature you may ignore the trigger and keep waiting.

How it runs
  * Declaring is the compiled action ("Counterstrike", "Counterstrike + <Counter talent>", one Action): the compiler defers its
    attack, runs the Counter talent's use-time effects (Tight Guard's AC) and, from the authority override
    (reviewed_final.d/zz_h2.json), a ``ready_counterstrike`` effect asks which melee weapon attack and which trigger, then holds
    the preparation as the lock round's own condition (until the start of the fighter's next turn, replaced by a new one).
    Reflexive Preparation is the same choice among every Counter talent for a Bonus Action and its Martial Focus, running the
    chosen talent's use-time effects and costs. The table shows the choice by name; the built-in AI takes its preferred one.
  * Triggers (one per choice, "choose one perceivable trigger"): a hostile creature starts an action that targets you; starts
    an action that targets an ally of yours; starts to move out of your reach; or has just moved into your reach (the move has
    finished in the engine's model, so the Counterstrike resolves right after it lands: judgment call).
  * The prepared attack runs the variant's own typed effects through ``run_effects`` (so every Counter talent that is already
    typed, Haymaker and the rest, applies) with the chosen weapon's damage and attack bonus. A hit gives the Reaction back; a
    round flag keeps it to one Counterstrike per round.
  * Table: the Use / Decline prompt of the lock round; the built-in AI's declaration carries ``automatic_use``.
  * The preparation is held until the start of the fighter's next turn and is NOT ended by using it (reading: "You may make
    only one Counterstrike per round, regardless of how many triggers you chose or how many Reactions you can take" only says
    something if one preparation can fire again); the round limit gates it. Heaven-Reading Stillness (CL 15) adds the trigger "a
    hostile creature within your reach begins any hostile action" (an attack, harmful effect, Grapple or Shove; not a defensive
    action, a move or speech). Two Answers Within One Breath (CL 17) makes the limit two a round while Court of the Awaiting Blade
    is up, still never two in one creature's turn. The Court (its aura zone on the map) also gives one additional trigger when
    preparing (of the same kind of event as the first: the lock round's held preparation listens for one event name), regains
    Martial Focus once a round on a Counterstrike hit, and the target cannot take Reactions until the start of its next turn. Not
    done: the Court's "once per turn when you prepare, move up to 10 feet" and Read the Tell.
  * Intercepting Strike (Guard): "when you prepare Counterstrike, you may choose to intercept one physical attack rather than
    attack the creature making it" -- one more kind of choice, per melee weapon, with the triggers "a melee weapon attack is made
    within your reach" (its attacker or its target is) and "a physical projectile targets a creature within your reach" (a ranged
    weapon attack). When the foe's attack action is accepted, the Reaction makes the chosen weapon's attack roll against the
    incoming one (rolled then for the attacker, with that attack's bonus: it has not been rolled yet); equal or higher negates
    that creature's next attack on the protected creature (typed_executor's negate_attack, so only a typed weapon attack can be
    negated; the trigger never fires for anything else). It counts as the round's Counterstrike and does not give the Reaction
    back. Reactive Interception, the talent's compiled Reaction, now costs the Martial Focus its text asks (zz_h2.json).
  * Patient Breath: a preparation that expires at the start of the fighter's turn without having been used gives back Martial
    Focus (a turn flag "open"/"used" from the declaration, read when the lock round's condition expires).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id

BASE = "RETRIBUTION_BASE_COUNTERSTRIKE"
REFLEXIVE = "TAL_RETRIBUTION_REFLEXIVE_PREPARATION"
BULL = "TAL_RETRIBUTION_RAGING_BULL"
COURT = "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE"
SOURCE = "ready:retribution.counterstrike"
ROUND_KEY = "once_per_round:counterstrike"  # "<round>:<Counterstrikes made>:<whose turn the last one was in>"
BLOCK = "counterstrike"
FOCUS = "resource:core.martial_focus"


@hook("decision_text")
def decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Explain this plugin's preparation and discharge without changing the held option."""
    prepared = (context.get("choice_trigger") or {}).get("prepared") or {}
    choice = str(context.get("reaction_source_id") or "")
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not (prepared.get("source_id") == SOURCE or choice.startswith(CHOICE + "counterstrike")):
        return None
    if not variants(engine, actor):
        return None
    from ..decision_text import costs_text

    if prepared:
        variant = engine.action_catalog.get((prepared.get("data") or {}).get("variant"))
        intercept = bool((prepared.get("data") or {}).get("intercept"))
        return {"feature_id": BASE, "cost": "Reaction now; preparation costs were paid earlier",
                "summary": ("Roll your prepared melee weapon attack to intercept the incoming physical attack. An equal or higher roll negates it; this does not restore your Reaction."
                            if intercept else f"Make your prepared attack against the triggering creature: {prepared['label']}."),
                "limits": _decision_limits(engine, actor, [prepared.get("data") or {}], printed_rules),
                "table_note": "Pass keeps the preparation for another legal trigger before it expires.",
                **({"feature_id": INTERCEPTING if intercept else _typed(variant).get("source") or BASE} if variant else {})}
    event = next((e for e in reversed(context.get("recent_events") or []) if e.get("event_type") == "INTENT_ACCEPTED"
                  and e.get("actor_id") == actor.entity_id), {})
    action = engine.action_catalog.get(event.get("source_definition_id"))
    rows = _affordable(actor, variants(engine, actor)) if action and _typed(action).get("source") == REFLEXIVE else [action] if action else variants(engine, actor)
    descriptions = {}
    choices = options(engine, actor, rows)
    for option in choices:
        variant = engine.action_catalog[option["data"]["variant"]]
        cost = costs_text(variant.costs) or "no resource cost"
        from ..decision_text import plain
        intercept = bool(option["data"].get("intercept"))
        modifier = INTERCEPTING if intercept else (_typed(variant).get("modifier") or {}).get("id")
        rule = plain(printed_rules.get(modifier, "")) if modifier else ""
        response = ("When the named trigger begins, spend your Reaction to roll against the incoming physical attack. "
                    "An equal or higher attack roll negates it; you do not attack the creature or restore your Reaction. "
                    "Normally cannot negate spell attacks, beams, intangible supernatural effects or area effects. "
                    "Massive projectiles require a weapon or technique capable of intercepting them. "
                    if intercept else "When the named trigger occurs, spend your Reaction to make this attack before the activity finishes. ")
        descriptions[option["option_id"]] = (f"Prepare {option['label']}. Preparation: {cost}. "
            + response + "Expires at the start of your next turn." + (f"\n{rule}" if rule else ""))
    has_intercepts = any(key.startswith("intercept:") for key in descriptions)
    return {"feature_id": _typed(action).get("source") if action else BASE,
            "cost": (costs_text(action.costs) or "No resource cost") + ("; Bonus Action" if action and _typed(action).get("source") == REFLEXIVE else "; Action"),
            "summary": ("Choose the melee attack and the event you will watch for. When it happens, you may spend your Reaction to strike the triggering creature."
                        + (" Alternatively, choose Intercepting Strike to negate an incoming physical attack with an equal or higher attack roll instead of attacking its attacker." if has_intercepts else "")),
            "limits": _decision_limits(engine, actor, [option["data"] for option in choices], printed_rules),
            "table_note": "Use prepares the selected attack and trigger; it does not attack immediately.",
            "option_descriptions": descriptions}
TRIGGERS = {
    "targets_me": ("INTENT_ACCEPTED", "a foe starts an action that targets you"),
    "targets_ally": ("INTENT_ACCEPTED", "a foe starts an action that targets an ally"),
    "leaves_reach": ("INTENT_ACCEPTED", "a foe in your reach starts to move away"),
    "enters_reach": ("MOVEMENT_COMMITTED", "a foe has moved into your reach"),
    "hostile_action": ("INTENT_ACCEPTED", "a foe in your reach begins any hostile action"),  # Heaven-Reading Stillness only
}
HARMFUL = {"attack", "damage", "extra_damage", "save", "condition", "forced_movement", "grapple", "shove", "reaction_denied"}
DEFENSIVE = {"system:combat.dodge", "system:combat.dash", "system:combat.disengage"}
AI_TRIGGER = "targets_me"
# Intercepting Strike (Guard): "When you prepare Counterstrike, you may choose to intercept one physical attack rather than attack
# the creature making it" -- a preparation of its own kind, with these triggers ("a physical projectile passes through your reach"
# is not offered: the table has no projectile path).
INTERCEPTING = "TAL_RETRIBUTION_INTERCEPTING_STRIKE"
INTERCEPTS = {
    "melee_in_reach": ("INTENT_ACCEPTED", "a melee weapon attack is made within your reach"),
    "projectile_in_reach": ("INTENT_ACCEPTED", "a physical projectile targets a creature within your reach"),
}
PATIENT = "TAL_RETRIBUTION_PATIENT_BREATH"
PREP_FLAG = "once_per_round:counterstrike_prepared"  # "open" from the declaration until a Counterstrike is made from it ("used")


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


# ------------------------------------------------------------------------------------------------ what the fighter owns
def _typed(action: Any) -> dict[str, Any]:
    return (action.parameters or {}).get("typed") or {}


def _owned(engine: Any, actor: Any, kind: str) -> bool:
    """A Retribution Realm Evolution or Domain the fighter owns (feature block ``counterstrike``, combat/rules/feature_blocks.d/zz_h2.json)."""
    return any(row.get("block") == BLOCK and row.get("kind") == kind for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def court_active(engine: Any, actor: Any) -> bool:
    """Court of the Awaiting Blade is up: its aura zone is on the map, made by this fighter, who is not Incapacitated."""
    return (_owned(engine, actor, "court") and actor.active
            and not any(row.condition_id.endswith("incapacitated") for row in actor.conditions.values())
            and any(zone.active and zone.owner_id == actor.entity_id and (zone.trigger_profile or {}).get("name") == "Court of the Awaiting Blade"
                    for zone in engine.state.zones.values()))


def limit(engine: Any, actor: Any) -> int:
    """Counterstrikes a round: one, or two with Two Answers Within One Breath while the Court is up."""
    return 2 if _owned(engine, actor, "two_answers") and court_active(engine, actor) else 1


def _decision_limits(engine: Any, actor: Any, choices: list[dict[str, Any]], printed_rules: dict[str, str]) -> str:
    """Display the discharge allowance and targeting rules of the offered variant data."""
    from ..decision_text import plain

    allowance = ("Up to two Counterstrikes per round while Court of the Awaiting Blade is active, "
                 "with Two Answers Within One Breath; never more than one during the same creature's turn."
                 if limit(engine, actor) == 2 else "Only one Counterstrike per round.")
    targeting = []
    for data in choices:
        variant = engine.action_catalog.get(data.get("variant"))
        if data.get("intercept"):
            text = "Intercepting Strike requires an incoming physical attack within your reach as described by the chosen trigger."
        elif variant and _bull(variant):
            text = "Raging Bull can target a creature initially outside reach. " + plain(printed_rules.get(BULL, ""))
        else:
            text = "The triggering creature must be within your prepared attack's reach when you strike."
        if text not in targeting:
            targeting.append(text)
    return ("Preparation ends at the start of your next turn. " + allowance
            + " Each requires an available Reaction and a legal chosen trigger and target. " + " ".join(targeting))


def used(engine: Any, actor: Any) -> tuple[int, str]:
    """(Counterstrikes made this round, the creature whose turn the last one was in)."""
    parts = str(actor.turn_flags.get(ROUND_KEY) or "").split(":", 2)
    return (int(parts[1]), parts[2]) if len(parts) == 3 and parts[0] == str(engine.state.round_number) and parts[1].isdigit() else (0, "")


def _spent(engine: Any, actor: Any) -> bool:
    count, last = used(engine, actor)
    return count >= limit(engine, actor) or (count >= 1 and last == engine.state.current_actor_id)  # never two in one creature's turn


def variants(engine: Any, actor: Any) -> list[Any]:
    """The compiled Counterstrike actions the fighter owns: the plain one first, then one per Counter talent."""
    rows = [action for action in engine.action_catalog.values()
            if action.owner_id == actor.entity_id and _typed(action).get("source") == BASE]
    return sorted(rows, key=lambda action: (bool(_typed(action).get("modifier")), action.source_definition_id))


def _strikes(action: Any) -> bool:
    """A plain weapon attack or Unarmed Strike (not a Grapple, a Shove or another maneuver that borrows the weapon record)."""
    rows = _typed(action).get("effects") or []
    return any(row.get("type") == "attack" and str(row.get("attack_kind") or "") in ("weapon", "melee weapon", "unarmed", "melee") for row in rows)


def weapons(engine: Any, actor: Any) -> list[Any]:
    """Melee weapon attacks the fighter could make (natural weapons included), the strongest first."""
    rows = [action for action in engine.action_catalog.values()
            if action.owner_id == actor.entity_id and _typed(action).get("weapon") and "#" not in action.source_definition_id
            and not action.source_definition_id.endswith(".pickup") and ".improvised." not in action.source_definition_id
            and not _typed(action).get("range_ft") and not _typed(action).get("opportunity_of")
            and action.resolution_kind == "TYPED" and action.target_kind == "HOSTILE_ENTITY" and _strikes(action)]
    return sorted(rows, key=lambda action: (-int((action.parameters or {}).get("expected_damage") or 0), action.source_definition_id))


def _reach(action: Any) -> int:
    return int(action.reach_ft or action.range_ft or 5)


def _bull(variant: Any) -> bool:
    return (_typed(variant).get("modifier") or {}).get("id") == BULL


def _short(text: str) -> str:
    return text.rsplit(".", 1)[-1][-18:]


def _label(variant: Any, weapon: Any, trigger: str) -> str:
    return f"{variant.display_name} ({weapon.display_name.removesuffix(' attack')}), when {TRIGGERS[trigger][1]}"


def _variant_rank(variant: Any) -> tuple[int, str]:
    hit_rows = sum(len(row.get("on_hit") or []) for row in _typed(variant).get("effects") or [] if row.get("type") == "attack")
    return (-(0 if _bull(variant) else hit_rows), variant.source_definition_id)


def _affordable(actor: Any, rows: list[Any]) -> list[Any]:
    return [row for row in rows if all(actor.resources.get(resource, 0) >= amount for resource, amount in row.costs)]


def _ai_pick(engine: Any, actor: Any) -> tuple[str, str, str] | None:
    """(weapon id, variant id, trigger) the built-in AI prefers: its strongest weapon, its richest affordable Counter talent,
    a foe that targets it."""
    swords, rows = weapons(engine, actor), _affordable(actor, variants(engine, actor))
    if not swords or not rows:
        return None
    return swords[0].source_definition_id, sorted(rows, key=_variant_rank)[0].source_definition_id, AI_TRIGGER


def options(engine: Any, actor: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """Every prepared Counterstrike among ``rows`` (compiled variants) the fighter can declare: each melee weapon x variant x
    trigger, the strongest weapon first, then (Intercepting Strike) each melee weapon x interception trigger.

    Ranking orders the menu; it must not remove a legal prepared attack or trigger.
    """
    out: list[dict[str, Any]] = []
    intercepts: list[dict[str, Any]] = []
    if _owned(engine, actor, "intercepting_strike") and rows:
        plain = next((row for row in rows if not _typed(row).get("modifier")), rows[0])  # a Counter talent adds nothing to an interception
        for weapon in weapons(engine, actor):
            for trigger, (event, text) in INTERCEPTS.items():
                intercepts.append({"option_id": f"intercept:{trigger}:{_short(weapon.source_definition_id)}", "source_id": SOURCE,
                                   "label": f"Intercepting Strike ({weapon.display_name.removesuffix(' attack')}), when {text}",
                                   "trigger": event, "automatic_use": True,
                                   "data": {"kind": "counterstrike", "intercept": True, "trigger": trigger, "triggers": [trigger],
                                            "variant": plain.source_definition_id, "weapon": weapon.source_definition_id, "bull": False}})
    for weapon in weapons(engine, actor):
        for variant in rows:
            for trigger, (event, _text) in TRIGGERS.items():
                if trigger == "hostile_action" and not _owned(engine, actor, "heaven_reading"):
                    continue
                identifier = f"counterstrike:{trigger}:{_short(variant.source_definition_id)}:{_short(weapon.source_definition_id)}"
                out.append({"option_id": identifier, "source_id": SOURCE, "label": _label(variant, weapon, trigger), "trigger": event,
                            "automatic_use": True,
                            "data": {"kind": "counterstrike", "trigger": trigger, "triggers": [trigger], "variant": variant.source_definition_id,
                                     "weapon": weapon.source_definition_id, "bull": _bull(variant)}})
    return out + intercepts


# ------------------------------------------------------------------------------------------------ declaring
def ready(engine: Any, actor: Any, option: dict[str, Any]) -> None:
    """Hold one preparation until the start of the fighter's next turn (what prepared_actions.prepare does for a Ready)."""
    from ..prepared_actions import CONDITION, SOURCE as READY_SOURCE, PreparedOption

    held = PreparedOption.model_validate(option).model_dump(mode="json")
    engine._remove_condition(actor, CONDITION, READY_SOURCE)
    engine._apply_condition(actor, CONDITION, held["source_id"], actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN", data=held)


def _holding(actor: Any) -> bool:
    from ..prepared_actions import CONDITION

    return any(row.condition_id == CONDITION and row.source_definition_id == SOURCE for row in actor.conditions.values())


def _preparation_effects(variant: Any) -> list[dict[str, Any]]:
    """What a Counter talent does the moment Counterstrike is prepared (Tight Guard's AC), not on the strike itself."""
    return [row for row in _typed(variant).get("effects") or []
            if row.get("type") not in ("attack", "ready_counterstrike", "raging_bull") and not row.get("deferred")]


@effect("ready_counterstrike")
def _declare(ctx: Any, spec: dict[str, Any]) -> None:
    """Choose the weapon attack and the trigger (and, for Reflexive Preparation, the Counter talent), then hold the preparation."""
    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    reflexive = _typed(ctx.action).get("source") == REFLEXIVE
    rows = _affordable(actor, variants(engine, actor)) if reflexive else [ctx.action]
    combos = options(engine, actor, rows)
    if not combos:
        ctx.rider(f"{ctx.action.display_name}: no melee weapon attack to prepare as a Counterstrike.")
        return
    by_id = {row["option_id"]: row for row in combos}
    pick = _ai_pick(engine, actor)
    preferred = next((row["option_id"] for row in combos if (row["data"]["weapon"], row["data"]["variant"], row["data"]["trigger"]) == pick),
                     combos[0]["option_id"])
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "COUNTERSTRIKE", actor.entity_id), actor, CHOICE + "counterstrike",
                 list(by_id), labels={key: row["label"] for key, row in by_id.items()}, preferred=[preferred],
                 prompt="Prepare which Counterstrike?", target_id=actor.entity_id)
    if not picked or picked[0] not in by_id:
        return
    chosen = by_id[picked[0]]
    if court_active(engine, actor):
        # Court of the Awaiting Blade: "when you prepare Counterstrike, choose one additional trigger". The lock round's held
        # preparation listens for one kind of event, so the extra trigger must be of the same kind as the first.
        first = chosen["data"]["trigger"]
        pool = INTERCEPTS if chosen["data"].get("intercept") else TRIGGERS  # an interception's extra trigger is another interception
        more = {name: text for name, (event, text) in pool.items() if name != first and event == chosen["trigger"]
                and (name != "hostile_action" or _owned(engine, actor, "heaven_reading"))}
        if more:
            extra = ask(engine, ctx.intent, checkpoint_id(engine, "COUNTERSTRIKE_EXTRA", actor.entity_id), actor, CHOICE + "counterstrike_extra",
                        list(more), labels={name: f"Also when {text}" for name, text in more.items()}, preferred=[next(iter(more))],
                        prompt="Court of the Awaiting Blade: one additional trigger", allow_decline=True, target_id=actor.entity_id)
            if extra and extra[0] in more:
                chosen = {**chosen, "data": {**chosen["data"], "triggers": [first, extra[0]]},
                          "label": chosen["label"] + f", or when {more[extra[0]]}"}
    ready(engine, actor, chosen)
    actor.turn_flags[PREP_FLAG] = "open"  # Patient Breath: prepared, not used yet
    ctx.rider(f"{actor.display_name} prepares: {chosen['label']}.")
    if reflexive:  # the chosen Counter talent's own use-time cost and effects, as its Action would have run them
        variant = engine.action_catalog[chosen["data"]["variant"]]
        for resource, amount in variant.costs:
            engine._spend_resource(actor, resource, amount, variant.source_definition_id)
        rows = _preparation_effects(variant)
        if rows:
            typed = {**_typed(variant), "numbers": dict(_typed(variant).get("numbers") or {})}
            run_effects(Context(engine, actor, variant, ctx.intent, typed, [], None), rows)
    else:
        # General preparation seam: providers can resolve rules triggered by replacing an Attack Action attack.
        # Bonus Action Reflexive Preparation deliberately does not reach it.
        from .. import ext

        ext.run_strict("counterstrike_prepare", engine, actor, engine.action_catalog[chosen["data"]["variant"]],
                       ctx.intent, reflexive)


@hook("ai_candidate_allowed")
def _ai_declares(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI prepares one Counterstrike (its richest Counter talent) with its Action, or for a Bonus Action when the
    Action is already spent; never twice, never after this round's Counterstrike."""
    source = _typed(action).get("source") if action is not None else None
    if source not in (BASE, REFLEXIVE) or action.owner_id != actor.entity_id:
        return None
    pick = _ai_pick(engine, actor)
    if pick is None or _holding(actor) or _spent(engine, actor):
        return False
    if source == REFLEXIVE:
        return not actor.action_available
    return action.source_definition_id == pick[1]


# ------------------------------------------------------------------------------------------------ the trigger
def _foe(engine: Any, actor: Any, event: Any) -> Any | None:
    other = engine.state.actors.get(event.actor_id or "")
    if other is None or not other.active or other.entity_id == actor.entity_id or other.team_id == actor.team_id:
        return None
    return other


def _perceives(engine: Any, actor: Any, other: Any) -> bool:
    from .. import stealth

    return bool(engine._line_of_sight_actor_to_actor(actor, other)) and bool(stealth.sees(engine, actor, other))


def _within(engine: Any, actor: Any, other: Any, reach: int, *, actor_at: Any = None, other_at: Any = None) -> bool:
    """Whether ``other`` is within ``reach`` feet of ``actor`` (each optionally at another position)."""
    return engine._distance_actor_to_actor(actor, other, actor_position=actor_at, target_position=other_at) <= reach


def _straight_charge(engine: Any, actor: Any, other: Any, reach: int) -> list[Any] | None:
    """Raging Bull: the shortest straight line of at most half the Speed, over open ground, that ends with ``other`` in reach
    (the squares after the first, or an empty list when it is in reach already); None when no line does."""
    from ..gate2_grid import NEIGHBORS
    from ..gate2_runtime_models import Position
    from .frightened_movement import path_allowed

    if _within(engine, actor, other, reach):
        return []
    limit = int(engine._effective_speed(actor)) // 2
    occupied, footprint, difficult = engine._occupied_cells_except(actor.entity_id), engine._footprint(actor), engine._hostile_difficult_cells(actor)
    best: list[Any] | None = None
    for dx, dy in sorted(NEIGHBORS):
        current, spent, line = actor.position, 0, []
        while True:
            if not engine.grid.in_bounds((current.x + dx, current.y + dy)):
                break
            nxt = Position(x=current.x + dx, y=current.y + dy)
            if not engine.grid.step_legal(current, nxt, occupied_cells=occupied, footprint=footprint):
                break
            spent += engine.grid.square_size_ft * engine.grid.movement_step_multiplier(current, nxt, footprint=footprint, difficult_cells=difficult)
            if spent > limit:
                break
            line.append(nxt)
            current = nxt
            if _within(engine, actor, other, reach, actor_at=current):
                if path_allowed(engine, actor, [actor.position, *line]) and (best is None or len(line) < len(best)):
                    best = list(line)
                break
    return best


def _hostile_action(engine: Any, event: Any) -> bool:
    """Heaven-Reading Stillness: an attack, harmful supernatural effect, deliberate Grapple or Shove, or another action that
    would harm or restrain; not a purely defensive action, a move, or speech."""
    if str((event.payload or {}).get("kind")) not in ("ACTION", "BONUS_ACTION") or event.source_definition_id in DEFENSIVE:
        return False
    action = engine.action_catalog.get(event.source_definition_id)
    if action is None:
        return bool(event.target_ids)
    if action.resolution_kind in ("ATTACK", "MULTI_ATTACK", "ATTACK_THEN_SAVE", "SAVE_DAMAGE"):
        return True

    def walk(rows):
        for row in rows or []:
            if isinstance(row, dict):
                yield row
                for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                    yield from walk(row.get(branch))

    return any(row.get("type") in HARMFUL and row.get("applies_to") not in ("self", "ally", "allies") for row in walk(_typed(action).get("effects")))


def _fires(engine: Any, actor: Any, option: dict[str, Any], event: Any) -> bool:
    data = option.get("data") or {}
    if data.get("kind") != "counterstrike" or _spent(engine, actor):
        return False
    variant, weapon = engine.action_catalog.get(data.get("variant")), engine.action_catalog.get(data.get("weapon"))
    other = _foe(engine, actor, event)
    if variant is None or weapon is None or other is None or not _perceives(engine, actor, other):
        return False
    reach, payload = _reach(weapon), event.payload or {}
    if data.get("intercept"):
        return _protected(engine, actor, data, event, other, reach) is not None
    ok = False
    for trigger in data.get("triggers") or [data.get("trigger")]:
        if event.event_type == "INTENT_ACCEPTED" and not str(event.source_definition_id).startswith("system:combat.ready:"):
            kind, targets = payload.get("kind"), set(event.target_ids or ())
            acting = kind in ("ACTION", "BONUS_ACTION")
            if trigger == "targets_me":
                ok = acting and actor.entity_id in targets
            elif trigger == "targets_ally":
                ok = acting and any((ally := engine.state.actors.get(target)) is not None and ally.active and ally.team_id == actor.team_id
                                    and ally.entity_id != actor.entity_id for target in targets)
            elif trigger == "leaves_reach":
                destination = getattr(engine._active_intent, "destination", None)
                ok = kind == "MOVE" and destination is not None and _within(engine, actor, other, reach) \
                    and not _within(engine, actor, other, reach, other_at=destination)
            elif trigger == "hostile_action":
                ok = _owned(engine, actor, "heaven_reading") and _within(engine, actor, other, reach) and _hostile_action(engine, event)
        elif event.event_type == "MOVEMENT_COMMITTED" and trigger == "enters_reach":
            from ..gate2_runtime_models import Position

            if not (payload.get("forced") or payload.get("teleport") or payload.get("dragged_by") or not payload.get("path")):
                ok = _within(engine, actor, other, reach) and not _within(engine, actor, other, reach, other_at=Position.model_validate(payload["path"][0]))
        if ok:
            break
    if not ok:
        return False
    return _straight_charge(engine, actor, other, reach) is not None if data.get("bull") else _within(engine, actor, other, reach)


@hook("prepared_trigger")
def _trigger(engine: Any, actor: Any, option: dict[str, Any], event: Any) -> bool | None:
    if option.get("source_id") != SOURCE:
        return None
    return True if _fires(engine, actor, option, event) else False


# ------------------------------------------------------------------------------------------------ the counterstrike
def _charge(engine: Any, actor: Any, other: Any, reach: int, intent: Any) -> None:
    """Raging Bull's move: square by square (Opportunity Attacks, zones), then one movement record."""
    from .. import typed_reactions, zones

    line = _straight_charge(engine, actor, other, reach)
    if line is None:
        raise ValueError("Raging Bull cannot reach the triggering creature")
    if not line:
        return
    start, previous, traversed, spent = actor.position, actor.position, [actor.position], 0
    for nxt in line:
        spent += engine.grid.square_size_ft * engine.grid.movement_step_multiplier(
            previous, nxt, footprint=engine._footprint(actor), difficult_cells=engine._hostile_difficult_cells(actor))
        engine._resolve_leave_reach(actor, previous, nxt, intent)  # "provokes Opportunity Attacks normally"
        if not actor.active or engine.state.terminal_result is not None:
            break
        actor.position = nxt
        traversed.append(nxt)
        previous = nxt
        engine._resolve_qi_hazard(actor)
        engine._resolve_zone_entry_triggers(actor)
        engine._remove_zone_leave_conditions(actor)
        if not actor.active or engine.state.terminal_result is not None:
            break
    engine._append_event("MOVEMENT_COMMITTED", SOURCE, actor_id=actor.entity_id,
                         payload={"destination": actor.position.model_dump(mode="json"), "path": [p.model_dump(mode="json") for p in traversed],
                                  "cost_ft": spent, "forced": False, "reaction": True, "counterstrike": "raging_bull"})
    if actor.active and len(traversed) > 1:
        zones.on_moved(engine, actor, start, actor.position)
        if getattr(engine, "typed_actor_ids", None):
            typed_reactions.on_creature_event(engine, actor, "moved", moved_ft=(len(traversed) - 1) * engine.grid.square_size_ft)
            typed_reactions.on_moved_geometry(engine, actor, start, actor.position)


@hook("after_hit")
def _after_hit(ctx: Any, target: Any, kind: str) -> None:
    probe = getattr(ctx.engine, "_counterstrike_probe", None)
    if probe is not None and ctx.actor.entity_id == probe["actor"] and _typed(ctx.action).get("source") == BASE:
        probe["hit"] = True


@hook("prepared_action")
def _resolve(engine: Any, actor: Any, option: dict[str, Any], event: Any, intent: Any) -> bool | None:
    if option.get("source_id") != SOURCE:
        return None
    from ..typed_executor import Context, run_effects

    data = option["data"]
    variant, weapon = engine.action_catalog[data["variant"]], engine.action_catalog[data["weapon"]]
    other = engine.state.actors[event.actor_id]
    reach = _reach(weapon)
    count, _last = used(engine, actor)
    actor.turn_flags[ROUND_KEY] = f"{engine.state.round_number}:{count + 1}:{engine.state.current_actor_id}"  # a key that survives the turn's reset
    actor.turn_flags[PREP_FLAG] = "used"
    if data.get("intercept"):
        _intercept(engine, actor, variant, weapon, other, _protected(engine, actor, data, event, other, reach), event, intent)
        if actor.active:
            ready(engine, actor, option)
        return True
    if data.get("bull"):
        _charge(engine, actor, other, reach, intent)
    if not actor.active or not other.active or not _within(engine, actor, other, reach):
        return True
    typed = {**_typed(variant), "weapon": _typed(weapon)["weapon"], "range_ft": None, "reaction_attack": True, "reaction_range_ft": reach,
             "numbers": {**(_typed(variant).get("numbers") or {}), "attack_bonus": int((_typed(weapon).get("numbers") or {}).get("attack_bonus") or 0)}}
    # The compiler marks the attack "deferred" (the action itself never attacks); this is the moment it does.
    effects = [{**row, "deferred": False} for row in typed.get("effects") or [] if row.get("type") == "attack"]
    probe = engine._counterstrike_probe = {"actor": actor.entity_id, "hit": False}
    try:
        run_effects(Context(engine, actor, variant, intent, typed, [other], other), effects)
    finally:
        engine._counterstrike_probe = None
    if probe["hit"]:
        actor.reaction_available = True  # "After a Counterstrike hits, you regain your Reaction" (recorded by REACTION_RESOLVED)
        # Documented seam: a Counter talent that spends the Reaction this strike restored (Clinch) runs here, after the
        # restore, so "spend the Reaction restored by Counterstrike" is exact. Providers only see the variant they may
        # read for their own reviewed modifier; core names no ability.
        from .. import ext

        for _ in ext.run_strict("counterstrike_hit", engine, actor, variant, other, intent):
            break
        if court_active(engine, actor):
            _court(engine, actor, other, variant, intent)
    # The preparation stands "until the start of your next turn": using it does not end it, the once-per-round limit (two with
    # Two Answers Within One Breath) is what stops a second Counterstrike ("regardless of how many triggers you chose"); the
    # lock round removed it before dispatch, so put it back.
    if actor.active:
        ready(engine, actor, option)
    return True


def _court(engine: Any, actor: Any, target: Any, variant: Any, intent: Any) -> None:
    """Court of the Awaiting Blade, on a Counterstrike hit: once per round regain Martial Focus, and the target cannot take
    Reactions until the start of its next turn."""
    from ..typed_executor import Context, run_effects

    key = f"once_per_round:court_focus:{engine.state.round_number}"
    if not actor.turn_flags.get(key) and actor.resources.get(FOCUS, 0) < actor.resource_maximums.get(FOCUS, 0):
        actor.turn_flags[key] = True
        engine._gain_resource(actor, FOCUS, 1, COURT)
    if target.active:
        court = next((row for row in engine.action_catalog.values() if row.owner_id == actor.entity_id and _typed(row).get("source") == COURT), None)
        rows = [{**row, "deferred": False} for row in (_typed(court).get("effects") if court else []) or []
                if row.get("type") == "condition" and row.get("condition") == "reaction_denied"]
        if rows and court is not None:
            run_effects(Context(engine, actor, court, intent, dict(_typed(court)), [target], target), rows)


# ------------------------------------------------------------------------------------------------ Intercepting Strike
def _weapon_attack(action: Any) -> bool | None:
    """Whether a typed action is a weapon attack, and ranged (True) or melee (False); None when it is not a physical weapon attack
    ("cannot negate spell attacks, beams, intangible supernatural effects, area effects"; only a typed attack can be negated:
    typed_executor's block_attack reads the negation)."""
    if action is None or action.resolution_kind != "TYPED":
        return None
    typed = _typed(action)
    if not typed.get("weapon") or not any(row.get("type") == "attack" for row in typed.get("effects") or []):
        return None
    return bool(typed.get("range_ft"))


def _protected(engine: Any, actor: Any, data: dict[str, Any], event: Any, attacker: Any, reach: int) -> Any | None:
    """The creature whose incoming attack an Intercepting Strike preparation would negate, or None when this action is not its
    trigger. The fighter itself first, then its allies, then anyone else in reach."""
    if event.event_type != "INTENT_ACCEPTED" or str((event.payload or {}).get("kind")) not in ("ACTION", "BONUS_ACTION"):
        return None
    ranged = _weapon_attack(engine.action_catalog.get(event.source_definition_id))
    if ranged is None:
        return None
    targets = [row for row in (engine.state.actors.get(target) for target in event.target_ids or ()) if row is not None and row.active]
    targets.sort(key=lambda row: (row.entity_id != actor.entity_id, row.team_id != actor.team_id, row.entity_id))
    in_reach = [row for row in targets if _within(engine, actor, row, reach)]
    for trigger in data.get("triggers") or [data.get("trigger")]:
        if trigger == "projectile_in_reach" and ranged and in_reach:
            return in_reach[0]
        if trigger == "melee_in_reach" and not ranged and targets and (in_reach or _within(engine, actor, attacker, reach)):
            return (in_reach or targets)[0]
    return None


def _intercept(engine: Any, actor: Any, variant: Any, weapon: Any, attacker: Any, protected: Any, event: Any, intent: Any) -> None:
    """"Make one melee weapon attack or Unarmed Strike against the incoming attack. If your attack roll equals or exceeds the
    triggering attack roll, negate the triggering attack." The triggering attack is not rolled yet when its action is accepted,
    so the contest rolls it for the attacker with that attack's bonus (typed_executor's negate_attack, as the Reactive
    Interception reaction does); a win negates that creature's next attack on the protected one."""
    from ..typed_executor import Context, run_effects

    if protected is None:
        return
    action = engine.action_catalog[event.source_definition_id]
    typed = {**_typed(variant), "weapon": _typed(weapon)["weapon"],
             "numbers": {**(_typed(variant).get("numbers") or {}), "attack_bonus": int((_typed(weapon).get("numbers") or {}).get("attack_bonus") or 0)}}
    previous = getattr(engine, "_typed_pending_attack", None)
    engine._typed_pending_attack = {"attacker": attacker.entity_id, "target": protected.entity_id,
                                    "bonus": int((_typed(action).get("numbers") or {}).get("attack_bonus") or 0),
                                    "reach": int(action.range_ft or action.reach_ft or 5)}
    try:
        run_effects(Context(engine, actor, variant.model_copy(update={"display_name": "Intercepting Strike"}), intent, typed, [attacker], attacker),
                    [{"type": "negate_attack", "contest": "attack",
                      "evidence": "Intercepting Strike: your attack roll against the incoming attack; equal or higher negates it"}])
    finally:
        engine._typed_pending_attack = previous


# ------------------------------------------------------------------------------------------------ Patient Breath
@hook("event")
def _patient_breath(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Patient Breath: "If your prepared Counterstrike expires at the start of your turn without being used, regain Martial Focus."
    """
    if event_type != "CONDITION_REMOVED":
        return
    from ..prepared_actions import CONDITION

    payload = kwargs.get("payload") or {}
    if payload.get("condition_id") != CONDITION or payload.get("checkpoint") != "START_OF_TURN":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or PREP_FLAG not in actor.turn_flags:
            continue
        state = actor.turn_flags.pop(PREP_FLAG)
        if (state == "open" and actor.active and _owned(engine, actor, "patient_breath")
                and actor.resources.get(FOCUS, 0) < actor.resource_maximums.get(FOCUS, 0)):
            engine._gain_resource(actor, FOCUS, 1, f"passive:{PATIENT}")


@effect("raging_bull")
def _raging_bull_marker(ctx: Any, spec: dict[str, Any]) -> None:
    """The talent's marker makes "Counterstrike + Raging Bull" a variant; the move itself is made by the resolver."""
    return None
