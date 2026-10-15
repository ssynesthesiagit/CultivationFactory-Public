"""Ancient Desolate Sacred Body (v0 2C) combat automation (owner 2026-10-12, A2R03).

The printed combat effects of the foundation's eight features
(authority/typed_mechanics/rules_text.json), resolved through the documented
seams in combat/ext/__init__.py:

* Generate Golden Sea Pulse -- the ``generate`` block (combat/pressure.py) for
  hostile damage, an aggressor's press, an eligible resistance roll and a won
  hostile physical contest; the last two are generated here, at the roll that
  made them.
* Saint-Body Frame -- the ``save_bonus`` block (saves) plus this plug-in's
  ``d20_bonus`` consumer for ability checks, sharing one once-per-round budget,
  and the always-on maximum Hit Point increase through the general
  ``compile_maximum_hp`` seam.
* Golden Sea Guard -- the compiled generic damage-reduction reaction, plus the
  corruptive +Proficiency Bonus here (``damage_reduction_bonus``) and Golden
  Blood Root's next-save Advantage (``save_mode``).
* Saint-Body Rebuke -- a prior-Pulse ``hit_snapshot`` receipt and paid strict
  ``hit_final`` choice; the standing setting supplies a preference.
* Refuse Heaven-Lock -- the compiled generic failed-save rescue, plus this
  plug-in's ``d20_rewrite`` rule for ability checks and its minor-rider release
  on a changed success.
* Golden Blood Root, Pressure Becomes Method, Sacred Body Wake -- the Refined
  and Perfected riders below (``save_final``, ``opposed_check_resolved``,
  ``event``, the Wake's own bonus action and its state's mode hooks).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, needle, note
from .d20_rewrite import Rule, register
from .. import pressure
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import Context, clock_expiry, run_effects

FEATURE = "foundation.ancient_desolate_sacred_body_v0_2C"
PULSE = "resource:foundation.golden_sea_pulse"
BLOCK = "sacred_body"

GENERATE = FEATURE + ".generate_golden_sea_pulse"
GUARD = FEATURE + ".golden_sea_guard"
FRAME = FEATURE + ".saint_body_frame"
REBUKE = FEATURE + ".saint_body_rebuke"
RESCUE = FEATURE + ".refuse_heaven_lock"
BLOOD = FEATURE + ".refined_golden_blood_root"
METHOD = FEATURE + ".refined_pressure_becomes_method"
WAKE = FEATURE + ".perfected_sacred_body_wake"

WAKE_CONDITION = "condition:typed.sacred_body_wake"
GUARD_ADVANTAGE = "condition:typed.sacred_body_guard_advantage"
WAKE_ACTION = "action:typed.sacred_body_wake"

# The printed body-pressure list shared by Saint-Body Frame's bonus, Sacred Body
# Wake's Advantage and Refuse Heaven-Lock's rescue: forced movement, being knocked
# Prone, Grappled, Restrained, hostile body suppression, curse-pressure,
# possession-pressure, poison-pressure or exhaustion-pressure.
BODY_PRESSURE = frozenset({
    "forced_movement", "prone", "grappled", "restrained", "body_suppression",
    "curse", "possession", "poison", "poisoned", "exhaustion", "paralyzed",
    "stunned", "incapacitated",
})

# A corruptive or suppressive source (Golden Sea Guard's and Golden Blood Root's
# printed lists): body suppression, curse-pressure, possession-pressure,
# poison-pressure, demonic pressure, necrotic corruption, hostile forced movement
# impact.
CORRUPTIVE_DAMAGE_TYPES = frozenset({"poison", "necrotic"})
CORRUPTIVE_CONDITIONS = frozenset({
    "body_suppression", "curse", "possession", "forced_movement", "prone",
    "grappled", "restrained", "poison", "poisoned", "exhaustion",
})
DEMONIC = frozenset({"demon", "fiend"})

# Body-bound Saint-Body expressions (the printed Saint-Body Rebuke trigger): a
# Body Refining technique, Iron Fist method, Brute method or Athletics method.
BODY_METHODS = ("tianxia.path.body_refining.", "tal_iron_fist", "tal_brute", "tal_athletics")

# Minor body-seizing riders (the printed "a brief speed reduction, an imposed
# Prone rider or a minor suppression mark"): a speed penalty or Prone.
MINOR_SPEED = frozenset({"slowed", "formation_maze_slowed", "sky_net_slow_down"})


def hostile(a: Any, b: Any) -> bool:
    return a is not None and b is not None and a.team_id != b.team_id


def row_of(engine: Any, actor_id: str, block: str, kind: str) -> dict[str, Any] | None:
    for row in (*((getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])),
                 *((getattr(engine, "typed_reaction_rows", {}) or {}).get(actor_id, []))):
        if row.get("block") == block and (row.get("kind") == kind or row.get("feature_id") == kind):
            return row
    return None


def owns(engine: Any, actor: Any, feature_id: str) -> bool:
    return any(row.get("feature_id") == feature_id
               for row in (*((getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])),
                           *((getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, []))))


def frame_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    return row_of(engine, actor.entity_id, "save_bonus", FRAME) if actor is not None else None


def _hazards(named: Any) -> frozenset[str]:
    return frozenset(str(hazard).lower() for hazard in (named or ()))


def _eligible(row: dict[str, Any] | None, ability: str, named: Any) -> bool:
    """Whether an own Strength or Constitution roll of this ability is an eligible
    resistance roll against the row's printed body-pressure list."""
    if row is None:
        return False
    if str(ability or "").upper()[:3] not in [str(entry).upper()[:3] for entry in row.get("abilities") or []]:
        return False
    return bool(_hazards(named) & frozenset(str(entry).lower() for entry in row.get("against") or []))


def _con_mod(actor: Any, numbers: dict[str, Any] | None = None) -> int:
    """The sealed raw Constitution modifier (the fighter's compiled ``con_mod``,
    not the save modifier that proficiency may raise)."""
    if numbers is not None and isinstance(numbers.get("con_mod"), int):
        return int(numbers["con_mod"])
    return int((actor.saving_throws or {}).get("CON", 0)) if actor is not None and actor.saving_throws else 0


def _body_method(source: str | None) -> bool:
    return bool(source) and any(str(source).lower().startswith(prefix) for prefix in BODY_METHODS)


def _generated_by_this_roll(engine: Any, actor: Any) -> bool:
    """Whether this actor's Golden Sea Pulse was gained during the settlement of
    the roll that is only now finishing: the gain event sits after that roll's
    own event."""
    for event in reversed(getattr(engine, "events", []) or []):
        if event.event_type == "RESOURCE_GAINED" and event.actor_id == actor.entity_id \
                and event.source_definition_id == f"passive:{GENERATE}":
            return True
        if event.event_type in {"SAVE_ROLLED", "CHECK_ROLLED", "ATTACK_ROLLED", "OPPOSED_CHECK_RESOLVED"} \
                and event.actor_id == actor.entity_id:
            return False
    return False


def _minor_riders(engine: Any, actor: Any, source_actor_id: str | None) -> list[Any]:
    """The actor's minor body-seizing riders from one source: a speed penalty or Prone."""
    riders = []
    for instance in (actor.conditions or {}).values():
        if source_actor_id is not None and instance.source_actor_id != source_actor_id:
            continue
        if instance.condition_id.split(":")[-1] in MINOR_SPEED or instance.condition_id.split(":")[-1] == "prone":
            riders.append(instance)
    return riders


def _release(engine: Any, actor: Any, intent: Any, source: Any, feature: str, riders: list[Any]) -> None:
    """The printed "you may ... end one minor ... from the same source" choice:
    the player picks which rider ends; an AI actor ends the first one."""
    if not riders:
        return
    question = (f"{source.display_name if source is not None else 'The source'}: end one minor "
                f"body-seizing rider it gave you -- a speed penalty or Prone?")
    choice = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "SACRED_BODY_RELEASE", actor.entity_id),
                        actor, f"choice:needle.{feature}",
                        [f"release:{instance.instance_id}" for instance in riders],
                        labels={f"release:{instance.instance_id}":
                                    f"End {instance.condition_id.split(':')[-1].replace('_', ' ')}"
                                    for instance in riders},
                        prompt=f"{'Refuse Heaven-Lock' if feature == RESCUE else 'Pressure Becomes Method'}: {actor.display_name}, {question}",
                        name="Refuse Heaven-Lock" if feature == RESCUE else "Pressure Becomes Method",
                        minimum=0, maximum=1, allow_decline=True)
    picked = next((instance for instance in riders
                   if f"release:{instance.instance_id}" == (choice[0] if choice else "")), None)
    if picked is None:
        return
    engine._remove_condition_instance(actor, picked.instance_id, picked.source_definition_id)
    note(engine, feature, actor,
         f"{actor.display_name} ends {picked.condition_id.split(':')[-1].replace('_', ' ')}.")


def _becomes_method(engine: Any, actor: Any, source: Any, action: Any = None) -> None:
    """Refined: Pressure Becomes Method -- the printed post-generation choice to
    move up to 10 feet, stand from Prone, or end one minor speed penalty from
    the same source."""
    if not owns(engine, actor, METHOD):
        return
    intent = getattr(engine, "_active_intent", None)
    if action is None:
        # The action whose roll generated the Pulse: the d20 scope names it
        # as its source (combat/typed_executor.py resolve_opposed_check, block_save).
        action = engine.action_catalog.get((engine.d20_context() or {}).get("source_id"))
    options = ["move"]
    if any(instance.condition_id.split(":")[-1] == "prone" for instance in (actor.conditions or {}).values()):
        options.append("stand")
    riders = _minor_riders(engine, actor, source.entity_id if source is not None else None)
    if riders:
        options.append("release")
    choice = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "SACRED_BODY_METHOD", actor.entity_id),
                        actor, "choice:needle.pressure_becomes_method", options,
                        labels={"move": "Move up to 10 feet", "stand": "Stand from Prone",
                                "release": "End one minor speed penalty from the same source"},
                        prompt=(f"Pressure Becomes Method: {actor.display_name} generated Golden Sea Pulse "
                                f"after {action.display_name if action is not None else 'the resistance roll'} "
                                f"against {source.display_name if source is not None else 'the pressure source'}. "
                                "You may move up to 10 feet, stand from Prone, or end one minor speed penalty "
                                "from that source. This costs no Action, Reaction or additional resource. What do you do?"),
                        name="Pressure Becomes Method", minimum=0, maximum=1, allow_decline=True,
                        preferred=["move"])
    picked = choice[0] if choice else None
    if picked == "move":
        from .granted_moves import choose
        choose(engine, actor, 10, METHOD, "Pressure Becomes Method", intent=intent,
               action_name=action.display_name if action is not None else None)
    elif picked == "stand":
        engine._remove_condition(actor, "condition:typed.prone", "condition:typed.prone")
        note(engine, METHOD, actor, f"{actor.display_name} stands from Prone (Pressure Becomes Method).")
    elif picked == "release":
        _release(engine, actor, intent, source, METHOD, riders)


@hook("compile_maximum_hp")
def frame_maximum_hp(owned_ids: list[str], context: dict[str, Any]) -> int | None:
    """Saint-Body Frame: "Your maximum Hit Points increase by twice your
    Proficiency Bonus"; Golden Blood Root: "Saint-Body Frame's maximum Hit Point
    increase becomes three times your Proficiency Bonus"."""
    if FRAME not in owned_ids:
        return None
    return int((context or {}).get("pb") or 2) * (3 if BLOOD in owned_ids else 2)


@hook("d20_bonus", priority=-10)
def frame_check_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Saint-Body Frame's ability-check half: "+PB to a Strength or Constitution
    ability check ... against [body pressure]", once per round on the same budget
    as the save half."""
    context = engine.d20_context(roll) or {}
    if context.get("kind") != "check":
        return None
    actor = engine.state.actors.get(context.get("actor_id") or getattr(roll, "actor_id", None))
    row = frame_row(engine, actor) if actor is not None else None
    if not _eligible(row, context.get("ability"), context.get("named")):
        return None
    clock = actor.turn_flags.setdefault(pressure.CLOCK, {})
    key = f"save_bonus:{FRAME}"
    if clock.get(key) == engine.state.round_number:
        return None
    clock[key] = engine.state.round_number
    return {"source_id": FRAME, "bonus": int(row["bonus"])}


@hook("save_final")
def frame_resistance_roll(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Generate Golden Sea Pulse when the fighter makes an eligible Saint-Body
    Frame resistance roll -- independently of whether the once-per-round numeric
    bonus was spent -- and offer Pressure Becomes Method when that generation
    happened."""
    engine = ctx.engine
    row = frame_row(engine, subject)
    if not _eligible(row, ability, named):
        return
    pressure.generate(engine, subject, "pressure_save")
    if not _generated_by_this_roll(engine, subject):
        return
    source = None
    save_result = getattr(ctx, "save_result", None)
    if save_result is not None:
        context = engine.d20_context(save_result) or {}
        source = engine.state.actors.get(context.get("source_actor_id"))
    _becomes_method(engine, subject, source, ctx.action)


@hook("opposed_check_resolved")
def contest_generation(ctx: Any, target: Any, result: Any, actor_check: dict[str, Any] | None,
                       target_check: dict[str, Any] | None) -> None:
    """Settle the Frame and Generator triggers after the check resolves.

    A Frame bonus is applied while the d20 is being rolled, but its Pulse
    and Pressure Becomes Method choice wait until the check's outcome is
    final, preventing that same check from spending the Pulse it generated.
    A separate won hostile physical contest can generate the same once per
    round resource.
    """
    engine = ctx.engine
    actor = ctx.actor
    for subject, opponent, check_spec in ((actor, target, actor_check),
                                          (target, actor, target_check)):
        if subject is None:
            continue
        frame = frame_row(engine, subject)
        # Both reasons modify one generation event. Collect its successful
        # receipt before offering the rider, so overlapping Frame/contest
        # eligibility cannot settle the same Pulse twice.
        generated = False
        if _eligible(frame, (check_spec or {}).get("ability"), (check_spec or {}).get("hazards")):
            generated = pressure.generate(engine, subject, "pressure_save")
        won = result is not None and not result.tied and (
            result.success if subject is actor else not result.success)
        if (won and owns(engine, subject, GENERATE)
                and str((check_spec or {}).get("ability") or "").upper()[:3] in {"STR", "CON"}
                and hostile(subject, opponent)):
            generated = pressure.generate(engine, subject, "contest") or generated
        if generated and _generated_by_this_roll(engine, subject):
            _becomes_method(engine, subject, opponent, ctx.action)


def _creature_kinds(actor: Any) -> frozenset[str]:
    """The creature's printed kinds (combat/ext/creature_kinds.py, the one
    place that answers "is this creature of that kind")."""
    from . import creature_kinds

    return frozenset(str(kind).lower() for kind in (creature_kinds.labels(actor) or ()))


def _corruptive(engine: Any, attacker: Any, source_id: str | None) -> bool:
    """Whether this damage comes from a corruptive or suppressive source: its
    damage type, a demonic attacker, or its source action's own typed effects."""
    if str(getattr(engine, "_typed_pending_damage_type", None) or "").lower() in CORRUPTIVE_DAMAGE_TYPES:
        return True
    if attacker is not None and DEMONIC & _creature_kinds(attacker):
        return True
    action = engine.action_catalog.get(source_id) if source_id else None
    typed = (action.parameters if action else {}).get("typed") or {}
    for effect_row in typed.get("effects") or []:
        if not isinstance(effect_row, dict):
            continue
        if effect_row.get("type") == "condition" \
                and str(effect_row.get("condition") or "").lower() in CORRUPTIVE_CONDITIONS:
            return True
        if (effect_row.get("type") == "forced_movement" or
                effect_row.get("type") == "movement" and effect_row.get("forced") is True) \
                and str(effect_row.get("mode") or "voluntary") != "teleport":
            return True
    return False


@hook("damage_reduction_bonus")
def guard_corruptive_bonus(engine: Any, owner: Any, protected: Any, attacker: Any,
                           reaction_row: dict[str, Any]) -> int | None:
    """Golden Sea Guard: "If the damage or rider comes from [a corruptive or
    suppressive source], increase the reduction by your Proficiency Bonus."
    This is a pure quote; Golden Blood Root settles on the paid receipt."""
    if not reaction_row or str(reaction_row.get("feature_id") or "") != GUARD or protected is None:
        return None
    if not _corruptive(engine, attacker, getattr(engine, "_active_action_source_id", None)):
        return None
    return int(owner.proficiency_bonus or 2)


@hook("state_event")
def guard_blood_settled(engine: Any, event: Any) -> None:
    """Grant Golden Blood Root only after Golden Sea Guard pays and reduces damage."""
    if event.event_type != "REACTION_RESOLVED" or event.source_definition_id != GUARD:
        return
    owner = engine.state.actors.get(event.actor_id)
    attacker = engine.state.actors.get(next(iter(event.target_ids or ()), None))
    payload = event.payload or {}
    if (owner is not None and owns(engine, owner, BLOOD) and attacker is not None
            and int(payload.get("pending_after", 0)) < int(payload.get("pending_before", 0))
            and _corruptive(engine, attacker, getattr(engine, "_active_action_source_id", None))):
        engine._apply_condition(owner, GUARD_ADVANTAGE, f"passive:{BLOOD}", owner.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"source": attacker.entity_id})


@hook("save_mode")
def guard_advantage_and_wake(engine: Any, subject: Any, ability: str, dc: Any, source_id: str,
                             rc: Any) -> str | None:
    """Golden Blood Root's Advantage on the next eligible save against the
    guarded source, and Sacred Body Wake's Advantage on eligible Strength and
    Constitution saves against body pressure."""
    modes = []
    a = str(ability or "").upper()[:3]
    named = _hazards((rc or {}).get("named"))
    if a in {"STR", "CON"} and named & BODY_PRESSURE:
        for instance_id, instance in list((subject.conditions or {}).items()):
            if instance.condition_id == GUARD_ADVANTAGE \
                    and (instance.data or {}).get("source") == (rc or {}).get("source_actor_id"):
                engine._remove_condition_instance(subject, instance_id, f"passive:{BLOOD}")
                note(engine, BLOOD, subject,
                     f"{subject.display_name} has Advantage on the saving throw (Golden Blood Root).")
                modes.append("ADVANTAGE")
                break
    if (a in {"STR", "CON"} and named & BODY_PRESSURE
            and any(instance.condition_id == WAKE_CONDITION for instance in (subject.conditions or {}).values())
            and not _incapacitated(subject)):
        modes.append("ADVANTAGE")
    return "ADVANTAGE" if modes else None


@hook("ability_check_hazards")
def wake_check_mode(engine: Any, actor: Any, ability: str, skill: Any, hazards: Any) -> str | None:
    """Sacred Body Wake: Advantage on eligible Strength and Constitution
    ability checks against body pressure -- the check's own named
    hazards carry that pressure, which ``check_modes`` passes here
    even without an opposing creature."""
    if (str(ability or "").upper()[:3] in {"STR", "CON"} and _hazards(hazards) & BODY_PRESSURE
            and any(instance.condition_id == WAKE_CONDITION for instance in (actor.conditions or {}).values())
            and not _incapacitated(actor)):
        return "ADVANTAGE"
    return None


def _incapacitated(actor: Any) -> bool:
    from .needle import incapacitated

    return bool(actor is not None and incapacitated(actor))


OPTIONS = {
    "push": "Push the target 5 feet",
    "reactions": "It cannot take Reactions against you until the start of your next turn",
    "frame": "Advantage on your next Saint-Body Frame roll against the target",
    "off": "No Saint-Body Rebuke this fight",
}


@hook("compile_actions")
def compile_rebuke_settings(info: dict[str, Any]) -> list[Any] | None:
    """Standing rider preferences; each paid hit still offers every legal rider."""
    if REBUKE not in info.get("owned_ids", ()):
        return None

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.saint_body_rebuke.{key}",
        display_name=f"Saint-Body Rebuke: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED",
        target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "saint_body_rebuke_choice", "choice": key}],
                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("saint_body_rebuke_choice")
def rebuke_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, "condition:typed.saint_body_rebuke_choice", ctx.source)
    ctx.engine._apply_condition(ctx.actor, "condition:typed.saint_body_rebuke_choice", ctx.source,
                                ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"),
                                      "label": f"Saint-Body Rebuke: {OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("hit_snapshot")
def rebuke_pulse_before_hit(engine: Any, actor: Any, target: Any, attack_context: Any,
                           intent: Any) -> dict[str, Any] | None:
    """Keep a prior-event Pulse separate from one earned by this hit."""
    if not owns(engine, actor, REBUKE):
        return None
    return {"sacred_body_rebuke": int(actor.resources.get(PULSE, 0))}


@hook("hit_final")
def saint_body_rebuke(ctx: Any, target: Any, kind: str) -> None:
    """Saint-Body Rebuke: spend 1 Golden Sea Pulse after you hit a creature
    within 5 feet with an unarmed strike, natural weapon, melee weapon or other
    body-bound Saint-Body expression: +PB + your Constitution modifier damage,
    then the rider you chose."""
    engine, actor = ctx.engine, ctx.actor
    if not owns(engine, actor, REBUKE) or not target.active or not hostile(actor, target):
        return
    from ..attack_notifications import is_melee_hit
    close = (engine._distance_actor_to_actor(actor, target) <= 5
             and is_melee_hit(ctx) and kind in {"unarmed", "weapon"})
    if not close and not _body_method(ctx.typed.get("source")):
        return
    if actor.resources.get(PULSE, 0) < 1 or not (ctx.hit_snapshots or {}).get("sacred_body_rebuke"):
        return
    choice = next((str((condition.data or {}).get("choice")) for condition in actor.conditions.values()
                   if condition.condition_id == "condition:typed.saint_body_rebuke_choice"), "reactions")
    if choice == "off":
        return
    legal = [key for key in ("push", "reactions", "frame")
             if key != "push" or engine._footprint(target).width_cells <= engine._footprint(actor).width_cells + 1]
    picked = needle.ask(engine, ctx.intent,
                        needle.checkpoint_id(engine, "SAINT_BODY_REBUKE", actor.entity_id),
                        actor, "choice:needle.saint_body_rebuke", legal,
                        labels={key: OPTIONS[key] for key in legal},
                        prompt=(f"Saint-Body Rebuke: after {ctx.action.display_name} hits {target.display_name}, "
                                f"spend 1 Golden Sea Pulse to add {int(actor.proficiency_bonus or 2) + _con_mod(actor, ctx.numbers)} "
                                "damage and choose a rider?"), name="Saint-Body Rebuke",
                        minimum=0, maximum=1, allow_decline=True,
                        preferred=[choice if choice in legal else "reactions"])
    if not picked:
        return
    choice = picked[0]
    engine._spend_resource(actor, PULSE, 1, f"passive:{REBUKE}")
    dealt = next((event for event in reversed(engine.events[-30:])
                  if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    damage_type = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    bonus = int(ctx.numbers.get("pb") or 2) + _con_mod(actor, ctx.numbers)
    sub = Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{REBUKE}", actor_id=actor.entity_id,
                         target_ids=(target.entity_id,), payload={"trigger": "Saint-Body Rebuke"})
    run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": bonus,
                       **({"damage_types": [damage_type.lower()]} if damage_type and damage_type != "UNTYPED" else {}),
                       "evidence": "Add damage equal to your Proficiency Bonus + your Constitution modifier."}])
    if not target.active:
        return
    if choice == "push":
        if engine._footprint(target).width_cells <= engine._footprint(actor).width_cells + 1:
            run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5,
                               "direction": "away",
                               "evidence": "push the target 5 feet if it is no more than one size larger than you"}])
    elif choice == "frame":
        engine._apply_condition(actor, "condition:typed.saint_body_frame_advantage", f"passive:{REBUKE}",
                                actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"against": target.entity_id,
                                      "label": f"Advantage on the next Saint-Body Frame roll against {target.display_name}"})
    else:
        run_effects(sub, [{"type": "deny_reactions_against", "applies_to": "target",
                           "evidence": "the target cannot take Reactions against you until the start of your next turn"}])


@hook("save")
def frame_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """The chosen Saint-Body Rebuke rider: Advantage on the next Strength or
    Constitution save against the target, consumed once."""
    if str(ability or "").upper()[:3] not in ("STR", "CON") or not BODY_PRESSURE & _hazards(named):
        return None
    held = [iid for iid, condition in subject.conditions.items()
            if condition.condition_id == "condition:typed.saint_body_frame_advantage"
            and (condition.data or {}).get("against") == ctx.actor.entity_id]
    if not held:
        return None
    condition = subject.conditions.pop(held[0])
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id,
                             target_ids=(subject.entity_id,),
                             payload={"condition_id": "condition:typed.saint_body_frame_advantage",
                                      "instance_id": held[0], "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("contest_check_mode")
def frame_advantage_check(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any]) -> str | None:
    """The chosen Saint-Body Rebuke rider's ability-check half:
    Advantage on the next eligible Frame resistance check against the
    target, consumed once; unrelated contests leave the rider available."""
    if not _eligible(frame_row(ctx.engine, subject), spec.get("ability"), spec.get("hazards")):
        return None
    held = [iid for iid, condition in (subject.conditions or {}).items()
            if condition.condition_id == "condition:typed.saint_body_frame_advantage"
            and (condition.data or {}).get("against") == (opponent.entity_id if opponent is not None else None)]
    if not held:
        return None
    ctx.engine._remove_condition_instance(subject, held[0], f"passive:{REBUKE}")
    return "ADVANTAGE"


@hook("after_hit")
def wake_first_hit(ctx: Any, target: Any, kind: str) -> None:
    """Sacred Body Wake: the first qualifying close-range or body-bound
    Saint-Body hit on each of the fighter's turns deals an extra PB damage."""
    engine, actor = ctx.engine, ctx.actor
    if not any(instance.condition_id == WAKE_CONDITION for instance in (actor.conditions or {}).values()):
        return
    if engine.state.current_actor_id != actor.entity_id or _incapacitated(actor) \
            or actor.turn_flags.get("sacred_body_wake_hit"):
        return
    from ..attack_notifications import is_melee_hit
    close = (target is not None and target.active and engine._distance_actor_to_actor(actor, target) <= 5
             and is_melee_hit(ctx) and kind in {"unarmed", "weapon"})
    if not close and not _body_method(ctx.typed.get("source")):
        return
    actor.turn_flags["sacred_body_wake_hit"] = 1
    bonus = int(ctx.numbers.get("pb") or 2)
    run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                [{"type": "extra_damage", "applies_to": "target", "flat": bonus,
                  "evidence": "Perfected: Sacred Body Wake -- the first qualifying hit on each of your turns deals an extra Proficiency Bonus damage."}])
    note(engine, WAKE, actor, f"{actor.display_name}'s Sacred Body Wake adds {bonus} damage to the hit.")


@hook("event", nested=True)
def wake_ends_incapacitated(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Sacred Body Wake lasts 1 minute "or until you are Incapacitated"."""
    if event_type != "CONDITION_APPLIED":
        return
    holder = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if holder is None or not _incapacitated(holder):
        return
    for instance_id, instance in list((holder.conditions or {}).items()):
        if instance.condition_id == WAKE_CONDITION:
            engine._remove_condition_instance(holder, instance_id, f"passive:{WAKE}")
            note(engine, WAKE, holder, f"{holder.display_name} is Incapacitated: Sacred Body Wake ends.")


@hook("compile_block")
def compile_sacred_body(block: str, spec: dict[str, Any], row: dict[str, Any],
                        numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Compile this foundation's own ``sacred_body`` rows -- the Refined and
    Perfected riders, so the plug-in can find what a fighter owns."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1),
             "pb": int(numbers.get("pb") or 2), "con_mod": int(numbers.get("con_mod") or 0),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@hook("compile_actions")
def compile_wake(info: dict[str, Any]) -> list[Any] | None:
    """Perfected: Sacred Body Wake -- the bonus action: "As a bonus action, spend
    1 Golden Sea Pulse (once per short or long rest): you gain temporary Hit
    Points equal to your cultivation level plus your Constitution modifier, and
    for 1 minute ... or until you are Incapacitated ...". The once-per-rest
    limit is once per fight (the engine keeps no rest inside a fight; the
    candidate_allowed gate below names it in plain text)."""
    if WAKE not in info.get("owned_ids", ()):
        return None
    numbers = info.get("numbers") or {}
    return [ActionDefinition(
        source_definition_id=WAKE_ACTION,
        display_name="Sacred Body Wake",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED",
        target_kind="SELF", costs=((PULSE, 1),),
        parameters={"typed": {
            "source": WAKE,
            "numbers": dict(numbers),
            "action_subtype": "technique",
            "effects": [{"type": "sacred_body_wake", "applies_to": "self",
                         "evidence": "Perfected: Sacred Body Wake"}],
        }, "description": "Spend 1 Golden Sea Pulse as a Bonus Action, once per rest. Gain temporary Hit Points equal to your Cultivation Level + Constitution modifier. For 1 minute or until Incapacitated, gain Advantage against Strength/Constitution body pressure and add your Proficiency Bonus to your first qualifying hit each turn."},
    )]


WAKE_USED = "typed_round_once:sacred_body_wake"


@hook("candidate_allowed")
def wake_once_per_rest(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The Wake's printed "once per short or long rest": once per fight (the
    engine keeps no rest inside a fight), named before any payment."""
    if getattr(action, "source_definition_id", None) != WAKE_ACTION:
        return None
    if actor.turn_flags.get(WAKE_USED):
        return False
    return None


@effect("sacred_body_wake")
def sacred_body_wake(ctx: Any, eff: dict[str, Any]) -> None:
    """Grant the Wake's temporary Hit Points and its one-minute state."""
    engine, actor = ctx.engine, ctx.actor
    numbers = ctx.numbers or {}
    amount = int(numbers.get("cl") or 1) + _con_mod(actor, numbers)
    engine._grant_temp_hp(actor, max(0, amount), f"passive:{WAKE}", actor.entity_id)
    engine._apply_condition(actor, WAKE_CONDITION, f"passive:{WAKE}", actor.entity_id,
                            expires_on=clock_expiry(engine, "minutes", 1),
                            data={"cl": int(numbers.get("cl") or 1)})
    actor.turn_flags[WAKE_USED] = 1  # "once per short or long rest": once per fight
    note(engine, WAKE, actor,
         f"{actor.display_name} gains {max(0, amount)} temporary Hit Points and enters "
         f"Sacred Body Wake for 1 minute: Advantage on eligible Strength and Constitution "
         f"ability checks and saving throws against body pressure, and the first qualifying "
         f"close-range or body-bound hit on each of their turns deals an extra "
         f"{int(numbers.get('pb') or 2)} damage.")


# Refuse Heaven-Lock's ability-check rescue: a d20_rewrite rule. The failed-save
# rescue is the compiled generic reaction; this rule answers the printed
# "or ability check" half, and releases one minor rider when it turns the
# failure into a success.
def _rescue_guard(engine: Any, holder: Any, rc: Any) -> bool:
    """A failed Strength or Constitution ability check against the printed
    body-pressure list, by a fighter that owns the Lock and holds a Golden
    Sea Pulse."""
    if not owns(engine, holder.actor, RESCUE):
        return False
    if not _hazards(rc.named) & BODY_PRESSURE:
        return False
    if rc.dc is None:
        return False
    return rc.total < rc.dc


def _rescue_bonus(engine: Any, holder: Any, rc: Any) -> int:
    return int((holder.numbers or {}).get("pb") or 2) + _con_mod(holder.actor, holder.numbers)


def _hazard_words(rc: Any) -> str:
    hazards = sorted(_hazards(rc.named))
    return ", ".join(hazard.replace("_", " ") for hazard in hazards) or "the effect"


def _rescue_say(engine: Any, holder: Any, rc: Any, roll: Any) -> str:
    return ("Refuse Heaven-Lock: spend 1 Golden Sea Pulse to add {bonus} to the failed "
            "{ability} check against {hazard}.".format(bonus=_rescue_bonus(engine, holder, rc),
                                                       ability=str(rc.ability or "ability").upper()[:3],
                                                       hazard=_hazard_words(rc)))


def _rescue_ai(engine: Any, holder: Any, rc: Any) -> bool:
    """The AI buys back a failed check that a body-pressure effect would punish."""
    return True


def _rescue_on_use(engine: Any, holder: Any, rc: Any) -> None:
    """If the rescue turns the failure into a success, the fighter may
    end one minor body-seizing rider from the same source.

    An additive (op="bonus") rule cannot carry an ``after`` rider, so the
    changed-success release is decided here, where the original (pre-bonus)
    total is still on the roll: the rescue is only bought for a roll that
    failed (``rc.total < dc``) and only releases when the bonus reaches the
    DC (``rc.total + bonus >= dc``)."""
    dc = rc.dc
    actor = holder.actor
    if dc is None or not owns(engine, actor, RESCUE):
        return
    if rc.total >= int(dc) or rc.total + _rescue_bonus(engine, holder, rc) < int(dc):
        return
    source = rc.source_actor
    intent = getattr(engine, "_active_intent", None)
    _release(engine, actor, intent, source, RESCUE,
             _minor_riders(engine, actor, source.entity_id if source is not None else None))


register(Rule(
    "refuse_heaven_lock_check", "Refuse Heaven-Lock (Body Check)",
    feature=RESCUE,
    rolls=("check", "save"),
    who="self",
    when="failed",
    abilities=("STR", "CON"),
    op="bonus",
    costs=((("golden_sea_pulse", 1),),),
    reaction=True,
    guard=_rescue_guard,
    bonus=_rescue_bonus,
    on_use=_rescue_on_use,
    say=_rescue_say,
    ai=_rescue_ai,
))
