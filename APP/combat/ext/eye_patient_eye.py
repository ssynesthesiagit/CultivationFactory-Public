"""Heaven Keeps No Secret from the Patient Eye (The Hidden Eye, CL 17 Inheritance, auto6 2026-10-05).

Printed text (owner text, rules_text.json TAL_THE_HIDDEN_EYE_HEAVEN_KEEPS_NO_SECRET_FROM_THE_PATIENT_EYE):

  Time: 1 Action. Range: 120 feet. Target: One creature you can perceive or your current rival.
  Duration: 1 minute. Uses: Once per week.
  Open the perfected record of the target's revealed existence. The target becomes Analyzed by you for the
  duration even if it would normally be protected from Analyze. Learn every Analyzable Characteristic the target
  possesses that is not concealed by an artifact, a Realm-defining protection, or another Secret Inheritance of
  equal or greater narrative weight. For the duration:
    you know the target's direction and approximate distance while it remains on the same plane;
    the target cannot benefit from being hidden from you;
    you perceive the target if it is Invisible and not behind Total Cover;
    allies of your choice within 120 feet treat the target as Analyzed by you for the purpose of one Research
      talent you know, chosen when you activate the Inheritance;
    once during each of your turns when you damage the target, choose one known Damage Resistance to suppress
      until the start of your next turn;
    once during the duration when you damage the target, you may treat one known Damage Immunity as Resistance
      for that instance of damage.

What the table does (everything a fight can decide):
  - the Action itself, its 120-foot reach and its single use (a use counter, as the compiler does for a printed
    "once per <rest/week>" use limit; the week itself is the GM's, since a fight is shorter than a week);
  - the target becomes Analyzed by the user for a minute, through this plug-in's OWN record rather than the
    ordinary Analyze mark (``mind_hidden_eye.PATIENT_EYE_ANALYZED``, read by the shared ``analyzed_by`` predicate
    every Analyzed benefit already asks). That is what "even if it would normally be protected from Analyze"
    means here: the target's immunity to the Analyze mark never applies to a record the Inheritance opens, and the
    minute cannot outlive the mark an ordinary Analyze would have left behind (an Analyze the user already spent
    on this creature is untouched);
  - the target cannot benefit from being hidden from, or being Invisible to, this one user (masked_conditions,
    the shared per-pair concealment mask -- it grants no sight through walls or Total Cover);
  - the two damage lines, asked of the user at the damage packet they ride: suppress one of the target's Damage
    Resistances until the start of the user's next turn (once during each of the user's turns), and treat one of
    the target's Damage Immunities as Resistance for one instance (once per minute).

  Both damage lines read the real packet through ``pending_damage.current``, the engine's general damage-packet
  context: it is set for every packet the sealed engine commits, so a damaging saving-throw technique and other
  damage without an attack roll ask the same questions an attack does. ``engine.damage_context()`` is deliberately
  NOT used: it is attack provenance only and is explicitly cleared for such packets.

  The suppressed Resistance is filed on the TARGET as an ordinary ``resistance_suppressed`` modifier
  (``typed_reactions._defenses`` already reads it, before any source is considered), so it suppresses that
  Resistance against every packet of that damage type for the rest of the window -- an ally's hit, a hazard, the
  user's next attack -- which is what "the target's Resistance, until the start of your next turn" says. The
  window itself ends on the shared turn clock: ``effect_durations.token("start", user, turns_started + 1)``.

  Suppression may only be *chosen* on the user's own turn (``"once during each of your turns when you damage the
  target"``), which is checked against the engine's own current actor, so an Opportunity Attack on someone else's
  turn cannot open the window.

What stays with the GM or the player, and why:
  - "Learn every Analyzable Characteristic" and "you know its direction and approximate distance" are knowledge
    about a creature, not a rule the fight can resolve: which characteristics exist is GM information (the
    shared Analyze path already prints "(GM: pick one Analyzable Characteristic)"), and a direction/distance
    readout has no fight mechanic (see also No Footstep Escapes the World, left as text).
  - "allies of your choice ... for the purpose of one Research talent you know" names one of the user's own
    talents: a choice this plug-in cannot resolve for an arbitrary sheet, exactly like Advisory Researcher and
    Advisory Stalker (combat/rules/feature_status.d/eye.json).
  - "not concealed by an artifact, a Realm-defining protection, or another Secret Inheritance of equal or
    greater narrative weight" is the campaign-scale adjudication line the printed text asks for.

Ownership and persistence: the record is one evented condition (integer/string data only) on the TARGET naming the
user who opened it, so it survives a table commit and reload; spending the once-per-record Immunity use refreshes
that record through its own CONDITION_REMOVED/CONDITION_APPLIED events (keeping its expiry and its other data), so
replaying the fight rebuilds the same record. The once-per-turn suppression flag is the user's own ``turn_flags``,
which the engine clears at the start of that creature's next turn, and the suppressed Resistance is an evented
modifier with the same shared expiry name. Inert for anyone who does not own the talent: every hook returns early
unless the user holds the record (and, at compile time, unless it owns the talent).

Hooks: compile_actions, compile_resources, effect "eye_patient_eye", masked_conditions, resistance_ignored,
immunity_as_resistance. The minute is not one of them: it rides the shared expiry name on the record
(``effect_durations.round_token``), so the shared sweep ends each instance at its own deadline. No saved-fight
lock edits.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FEATURE = "TAL_THE_HIDDEN_EYE_HEAVEN_KEEPS_NO_SECRET_FROM_THE_PATIENT_EYE"
PASSIVE_KIND = "patient_eye"   # this talent's "hidden_eye" passive row kind (combat/rules/feature_blocks.d/eye.json)
SOURCE = "typed:eye.patient_eye"
USES = "resource:uses.eye_patient_eye"
REACH = 120
DURATION_ROUNDS = 10  # "Duration: 1 minute"
RESIST_USED = "eye_patient_eye_resist_used"  # "once during each of your turns": a turn flag the engine clears
IMMUNE_USED = "eye_patient_eye_immunity_used"  # "once during the duration": stored in the record, dies with it
NAME = "Heaven Keeps No Secret from the Patient Eye"


def _record_id() -> str:
    """The record's condition id, owned by the module that also publishes ``analyzed_by`` (which reads it)."""
    from .mind_hidden_eye import PATIENT_EYE_ANALYZED

    return PATIENT_EYE_ANALYZED


def record(target: Any, user: Any = None) -> Any:
    """The open record on ``target`` naming ``user`` (any user's record when ``user`` is None), or None."""
    wanted = getattr(user, "entity_id", user)
    return next((condition for condition in target.conditions.values()
                 if condition.condition_id == _record_id()
                 and (wanted is None or str((condition.data or {}).get("by") or "") == str(wanted))), None)


def opened(engine: Any, attacker: Any, target: Any) -> bool:
    """Whether ``attacker`` currently holds an open record naming ``target``."""
    from .eye_common import has as eye_has  # the shared "hidden_eye" block reader, not this module's private state

    if not eye_has(engine, getattr(attacker, "entity_id", ""), PASSIVE_KIND):
        return False
    held = record(target, attacker)
    return held is not None and bool((held.data or {}).get("until_round"))


def _packet(engine: Any, source_actor_id: Any) -> tuple[Any, Any, Any] | None:
    """The user, the target and the packet of real damage ``source_actor_id`` is dealing right now, or None.

    ``pending_damage.current`` is the engine's general damage-packet context (``combat/pending_damage.py``, opened by
    ``gate2_engine._commit_damage`` for every committed packet), so an estimate, a preview or a pure
    ``damage_factor`` query outside a commit never asks. The subscriber also checks that this packet's
    target matches the target passed by the resistance hook.
    """
    from ..pending_damage import current as pending_packet

    packet = pending_packet(engine)
    if packet is None or str(packet.source_actor_id or "") != str(source_actor_id or ""):
        return None
    user = engine.state.actors.get(str(source_actor_id or ""))
    target = engine.state.actors.get(str(packet.target_id or ""))
    if user is None or target is None or not target.active:
        return None
    return user, target, packet


def _resists(engine: Any, target: Any, kind: str, source_id: str) -> bool:
    """Whether ``target``'s own defences halve ``kind`` damage from ``source_id``.

    ``typed_reactions.resists`` is the shared reader, and it is safe to call from inside the ``resistance_ignored``
    seam: it passes no source actor, so it never re-enters this plug-in's own answer.
    """
    from ..typed_reactions import resists

    return resists(engine, target, kind, source_id)


def _immune(engine: Any, target: Any, kind: str, source_id: str) -> bool:
    """Whether ``target``'s own defences annihilate ``kind`` damage from ``source_id`` (``damage_factor`` is 0.0),
    read the same non-re-entering way so this plug-in's own "treat Immunity as Resistance" cannot answer itself."""
    from ..typed_reactions import damage_factor

    return damage_factor(engine, target, kind, source_id, None) == 0.0


def _suppressed(engine: Any, target: Any, kind: str) -> bool:
    """Whether one of this plug-in's open windows already set ``target``'s ``kind`` Resistance aside."""
    return any(m.target_field == "resistance_suppressed" and str(m.value) == kind and m.source_definition_id == SOURCE
               for m in target.modifiers.values())


def _refresh(engine: Any, target: Any, held: Any, **changes: Any) -> Any:
    """Rewrite ``held``'s data through condition events, keeping its expiry and everything else it carries.

    The recorded state of a fight is rebuilt from events (gate3_reducer), so an in-place edit of ``held.data`` would
    make a replayed fight's canonical state diverge from the live one. Dropping the instance and applying it again
    under the same source keeps the record's own expiry and adds the change to the recorded history.
    """
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    from .condition_events import drop_condition

    data = {**(held.data or {}), **changes}
    skipped = skipped_expiry_slots(target, held)
    drop_condition(engine, target, held.instance_id, SOURCE)  # this instance only: another user's record stays
    apply_condition_preserving_clock(engine, target, held, held.condition_id, SOURCE, held.source_actor_id, expires_on=held.expires_on,
                            data=data, skipped_slots=skipped)


def _ask(engine: Any, user: Any, target: Any, packet: Any, choice_id: str, offer: str, question: str) -> bool:
    """Ask ``user`` the printed "you may"/"choose one" question at the packet that carries the damage.

    Declining is always legal (both printed lines are optional), and a fight with nobody answering falls back to the
    printed benefit, as ``needle.ask`` documents. The prompt names the ability (``name``/``feature_id``), the action
    the question rides and the creature it affects, so the table never shows an id.
    """
    from .needle import CHOICE, ask, checkpoint_id

    action = engine.action_catalog.get(str(packet.source_id or ""))
    return bool(ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, choice_id, user.entity_id), user,
                   CHOICE + choice_id, ["yes"], labels={"yes": offer}, allow_decline=True,
                   prompt=question, name=NAME, feature_id=FEATURE, target_id=target.entity_id,
                   prompt_context={"source_definition_id": str(packet.source_id or ""),
                                   "action_name": getattr(action, "display_name", "") or str(packet.source_id or ""),
                                   "affected_id": target.entity_id}))


# --------------------------------------------------------------------------- compilation
@hook("compile_resources")
def patient_eye_resources(info: dict[str, Any]) -> list[Any] | None:
    """"Uses: Once per week" -- one use per fight, as the compiler does for its own printed use limits."""
    if FEATURE not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=USES, initial=1, maximum=1)]


@hook("compile_actions")
def patient_eye_action(info: dict[str, Any]) -> list[Any] | None:
    if FEATURE not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.patient_eye", display_name=NAME, owner_id=info["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=REACH,
        costs=((USES, 1),),
        parameters={"typed": {"effects": [{"type": "eye_patient_eye", "evidence": "Open the perfected record of the "
                                                                               "target's revealed existence; the target "
                                                                               "becomes Analyzed by you for 1 minute."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": [
                                  "Uses: Once per week. This fight spends one use; the rest of the week is the GM's.",
                                  "For one minute the target counts as Analyzed by you, even if it cannot normally be "
                                  "studied that way: your other Hidden Eye talents treat it as studied (attack "
                                  "rolls against it can score a Critical Hit on a 19, and you gain half your "
                                  "Proficiency Bonus, rounded down, to your AC against its attacks; while you hold "
                                  "Martial Focus the same bonus applies to your saving throws against its "
                                  "effects), and it gains no benefit from being Hidden or Invisible against you.",
                                  "On your own turn, the first time you damage it you may set aside one of its "
                                  "Damage Resistances until the start of your next turn; anyone who damages it in "
                                  "that window meets no Resistance of that type. Once in the minute, you may treat "
                                  "one of its Damage Immunities as Resistance for a single instance of damage.",
                                  "Still yours to run, not the table's: you learn every Analyzable Characteristic it "
                                  "still has that no artifact, Realm-defining protection or greater Secret "
                                  "Inheritance hides (GM); you always know which way it is and roughly how far while "
                                  "it stays on the plane; and you pick one Research talent you know plus any allies "
                                  "of your choice within 120 feet, and those allies treat the target as Analyzed by "
                                  "you for that one talent (GM: which talent, which allies)."]},
                     "expected_damage": 0})]


# --------------------------------------------------------------------------- the Inheritance itself
@effect("eye_patient_eye")
def open_record(ctx: Any, eff: dict[str, Any]) -> None:
    from .condition_events import drop_condition as _drop
    from .effect_durations import round_token

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    record_id = _record_id()
    # A second use for the same creature refreshes this user's own record (and its minute); another user's record on
    # the same creature is another character's business and stays where it is.
    for iid, old in list(target.conditions.items()):
        if old.condition_id == record_id and str((old.data or {}).get("by") or "") == actor.entity_id:
            _drop(engine, target, iid, SOURCE)
    engine._apply_condition(target, record_id, SOURCE, actor.entity_id, expires_on=round_token(engine, DURATION_ROUNDS),
                            data={"by": actor.entity_id, "until_round": engine.state.round_number + DURATION_ROUNDS,
                                  "label": f"Analyzed by {actor.display_name}: {NAME} (1 minute)"})
    actor.turn_flags.pop(RESIST_USED, None)
    ctx.rider(f"{NAME}: {actor.display_name}'s perfected record of {target.display_name} is open for one minute. It "
              f"counts as Analyzed by {actor.display_name} (so your Hidden Eye talents read it, and it cannot hide "
              f"from {actor.display_name}), and on {actor.display_name}'s own turn one of its Damage Resistances can "
              f"be set aside until the start of {actor.display_name}'s next turn. Learn every Analyzable "
              f"Characteristic it still has (GM), and pick one Research talent {actor.display_name} knows plus any "
              f"allies of {actor.display_name}'s choice within 120 feet, who then treat it as Analyzed by "
              f"{actor.display_name} for that one talent (GM: which talent, which allies).")


# --------------------------------------------------------------------------- "the target cannot benefit from being hidden from you"
@hook("masked_conditions")
def patient_eye_concealment(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    # The engine's empty-square probe (senses.perceives_cell) is not a creature: a tile owns no printed rule, so
    # ask before reading any attribute of a full creature (MMX105).
    from ..senses import is_creature, rules as sense_rules

    if not is_creature(attacker) or not is_creature(target) or not opened(engine, attacker, target):
        return None
    hidden = set(sense_rules().get("hidden_conditions") or []) | {"condition:typed.invisible"}
    masked = {iid for iid, condition in target.conditions.items() if condition.condition_id in hidden}
    return {target.entity_id: masked} if masked else None


# --------------------------------------------------------------------------- the two damage lines
@hook("resistance_ignored")
def suppress_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any) -> bool | None:
    """"once during each of your turns when you damage the target, choose one known Damage Resistance to suppress
    until the start of your next turn". Asked at the damage packet (attack, saving throw or plain damage alike) and
    only for a damage type the recorded target really does resist -- the printed word is "one known Damage
    Resistance". The chosen Resistance is then set aside on the target itself, so it is gone against every packet
    until the user's next turn, not only against this attack."""
    packet = _packet(engine, source_actor_id)
    if packet is None or str(packet[1].entity_id) != getattr(target, "entity_id", ""):
        return None
    user, target, current = packet
    if engine.state.current_actor_id != user.entity_id:
        return None  # "during each of your turns": an Opportunity Attack or another off-turn packet cannot open it
    if not opened(engine, user, target):
        return None
    upper = str(kind).upper()
    if _suppressed(engine, target, upper):
        return True  # an open window already set that Resistance aside; it lasts to the start of the user's next turn
    if user.turn_flags.get(RESIST_USED):
        return None  # once during each of your turns, and this turn's choice is already spent
    if not _resists(engine, target, kind, str(current.source_id or "")):
        return None
    readable = upper.replace("_", " ").title()
    if not _ask(engine, user, target, current, "eye_patient_eye_resist",
                f"Suppress {target.display_name}'s Resistance to {readable} damage",
                f"Set aside {target.display_name}'s Resistance to {readable} damage until the start of "
                f"{user.display_name}'s next turn? ({user.display_name} may choose this once on each of "
                f"{user.display_name}'s own turns.)"):
        return None
    from .effect_durations import token

    user.turn_flags[RESIST_USED] = True
    engine._add_modifier(target, SOURCE, "resistance_suppressed", "ADD", upper, "ALWAYS",
                         expires_on=token("start", user.entity_id, int(user.turns_started) + 1))
    engine._append_event("PASSIVE_TRIGGERED", FEATURE, actor_id=user.entity_id, target_ids=(target.entity_id,),
                         payload={"feature_id": FEATURE, "suppressed_resistance": upper,
                                  "log": f"{NAME}: {target.display_name}'s Resistance to {readable} damage is set "
                                         f"aside until the start of {user.display_name}'s next turn."})
    return True


@hook("immunity_as_resistance")
def immunity_as_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any) -> bool | None:
    """"once during the duration when you damage the target, you may treat one known Damage Immunity as Resistance
    for that instance of damage". Asked only for a damage type the recorded target really is immune to, and on the
    same general damage packet the Resistance line uses."""
    packet = _packet(engine, source_actor_id)
    if packet is None or str(packet[1].entity_id) != getattr(target, "entity_id", ""):
        return None
    user, _, current = packet
    held = record(target, user)
    if held is None or (held.data or {}).get(IMMUNE_USED):
        return None
    if not _immune(engine, target, kind, str(current.source_id or "")):
        return None
    readable = str(kind).upper().replace("_", " ").title()
    if not _ask(engine, user, target, current, "eye_patient_eye_immunity",
                f"Treat {target.display_name}'s Immunity to {readable} damage as Resistance for this one instance",
                f"Count {target.display_name}'s Immunity to {readable} damage as Resistance for this one instance "
                f"of damage? ({user.display_name} may choose this once while this record lasts.)"):
        return None
    _refresh(engine, target, held, **{IMMUNE_USED: 1})
    engine._append_event("PASSIVE_TRIGGERED", FEATURE, actor_id=user.entity_id, target_ids=(target.entity_id,),
                         payload={"feature_id": FEATURE, "immunity_as_resistance": str(kind).upper(),
                                  "log": f"{NAME}: {target.display_name}'s Immunity to {readable} damage counts as "
                                         f"Resistance for this instance."})
    return True


# --------------------------------------------------------------------------- expiry
# "Duration: 1 minute" is carried by the shared expiry name the record is filed with
# (``effect_durations.round_token`` -> START_OF_SLOT_AT:<round>:<slot>), and the shared sweep
# (effect_durations.turn_started) takes each instance off at its own deadline on the shared turn clock.
# This plug-in adds no expiry hook of its own: a second, round-only fallback here used to read the first
# record it found on the target and then ``_remove_condition`` every instance with that id, which expired a
# record early whenever the target moved before the caster and deleted another user's still-live record
# (AUTO6r1). One expiry, the shared one, owns the deadline per instance.
