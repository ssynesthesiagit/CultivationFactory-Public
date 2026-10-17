"""Choir of the Unopened Eye (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "12. Choir of the Unopened Eye"). No Spheres 5e or D&D 5.5e counterpart.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json; hooks return early without them.

What runs:
  * Witness Note (CL3): Soul Gaze's optional +1 Resonance variant places a Witness Note on its target (typed modifier). Chorus
    Recognition: once per turn, when a hostile creature bearing your Witness Note becomes Resonance Marked by you, it suffers Revealed
    Disturbance (combat/ext/spirit_awakening.py) at no cost.
  * Hymn of Stillness (CL6): typed; a failed save also leaves it unable to benefit from being Invisible against you (combat/ext/exposed.py)
    and, if Resonance Marked by you, your ordinary Spiritual Pressure. Sustained Refrain: at the start of your next turn you may spend 1
    Resonance to make a creature that failed save again -- a failure keeps it still (no Reactions, -10 feet Speed, still exposed)
    until the start of your following turn, a success ends it. One Hymn sustained at a time. Asked; the AI sustains.
  * Forced Confession (CL10): only a creature bearing your Witness Note or Resonance Mark; the save is typed, what it confesses the
    GM's.
  * All Eyes Open (CL14): the field (30 feet, the scene). While it lasts ordinary invisibility cannot grant a creature Advantage against
    you, and once per round, when a hostile creature in the field becomes Resonance Marked, it suffers your Spiritual Pressure.
  * Edict of Perfect Witness (CL18): only a creature bearing both your Witness Note and Resonance Mark, or one in your field that has
    failed a save against your features this fight. Failed save: Perfect Witness for up to 1 minute -- the combat bullets run:
    "cannot target a creature other than you with an attack or hostile technique while you are a legal target, unless it first uses its
    Action to state one emotionally true reason" (its other targets are withheld until it takes the free-standing "Refuse the witness"
    Action that turn), and "cannot benefit from ordinary invisibility against creatures you designate" (you and your allies). At the
    end of each of its turns it saves again: a success removes one bullet of its choice (asked; the AI drops the targeting bullet
    first), three end it, a failure imposes your Spiritual Pressure. Successful save: exposed to you until the end of its next turn and
    two different Spiritual Pressure effects.

Plug-in surface: effects choir_hymn_record, choir_edict, choir_refuse; hooks mark_applied, turn_start_choice, turn_end,
candidate_allowed, masked_conditions, match_start, additional_actions. Shared helpers used: spirit_traditions (row/feature_of/context/
pick_creature), spirit_awakening.chosen_pressure, needle.ask, typed_executor.block_save/bears_mark.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.choir_of_the_unopened_eye.feature."
WITNESS = TRADITION + "witness_note"
HYMN = TRADITION + "hymn_of_stillness"
CONFESSION = TRADITION + "forced_confession"
ALL_EYES = TRADITION + "all_eyes_open"
EDICT = TRADITION + "edict_of_perfect_witness"
NOTE = "Witness Note"
HYMN_HELD = "condition:typed.choir_hymn_sustain"
PERFECT = "condition:typed.perfect_witness"
REFUSED = "choir_refused_witness"
REFUSE_ACTION = "system:combat.refuse_the_witness"
BULLETS = {"focus": "cannot target anyone but the witness while the witness is a legal target (unless it spends its Action to refuse)",
           "unveiled": "cannot benefit from ordinary invisibility against the witness and its allies",
           "speech": "cannot speak a deliberate lie or conceal whether it is possessed, oath-bound, coerced or disguised (the GM's)",
           "passage": "must use an Action to declare the method and destination before teleporting or departing spiritually"}


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _is_resonance(name: str) -> bool:
    te = _te()
    return te.mark_condition_id(name, "x") == te.mark_condition_id("Resonance", "x")


def _pressure(ctx: Any, subject: Any, option: str | None = None) -> None:
    _te().run_effects(st.context(ctx.engine, ctx.actor, ctx.action, [subject], ctx.numbers, ctx.intent),
                      [{"type": "spiritual_pressure", "applies_to": "target", **({"option": option} if option else {})}])


@effect("choir_hymn_success")
def hymn_success(ctx: Any, row: dict[str, Any]) -> None:
    """Even a successful initial save leaves one chosen Stillness penalty."""
    from . import needle
    if ctx.target is None:
        return
    options = ["speed", "reactions"]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "HYMN_SUCCESS", ctx.target.entity_id),
                        ctx.actor, "choice:needle.choir.hymn_success", options,
                        labels={"speed": "Reduce Speed by 10 feet", "reactions": "Prevent Reactions"},
                        preferred=["reactions"], name="Hymn of Stillness", feature_id=HYMN,
                        target_id=ctx.target.entity_id,
                        prompt=f"{ctx.target.display_name} resisted Hymn of Stillness. Choose its penalty until the start of your next turn.")
    _te().run_effects(ctx, [dict(_STILL[1 if chosen and chosen[0] == "speed" else 0])])


@effect("choir_confession_note")
def confession_note(ctx: Any, row: dict[str, Any]) -> None:
    """The confession grants a free optional Note, independent of other limits."""
    from . import needle
    if ctx.target is None:
        return
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "CONFESSION_ECHO", ctx.target.entity_id),
                        ctx.actor, "choice:needle.choir.confession_echo", ["note"],
                        labels={"note": "Place a Witness Note on the confession without spending more Resonance"},
                        preferred=["note"], allow_decline=True, name="Confession Echo", feature_id=CONFESSION,
                        target_id=ctx.target.entity_id,
                        prompt=f"Place a Witness Note on {ctx.target.display_name}'s true statement?")
    if chosen:
        _te().block_mark(ctx, {"type": "mark", "mark": NOTE, "applies_to": "target",
                               "duration": {"kind": "until_removed"}, "data": {"notation": "Confession Echo"}})


# ------------------------------------------------------------------------------------------------ Chorus Recognition, All Eyes Open
def _fields(engine: Any, owner: Any) -> list[Any]:
    from .. import zones

    return [z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id
            and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == ALL_EYES]


@hook("mark_applied")
def chorus(ctx: Any, name: str, subject: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _is_resonance(name) or subject is None or not subject.active or subject.team_id == actor.team_id:
        return
    te = _te()
    if (st.row(engine, actor, "witness_note") is not None and not actor.turn_flags.get("chorus_recognition")
            and te.bears_mark(subject, actor.entity_id, NOTE)):
        actor.turn_flags["chorus_recognition"] = True
        _pressure(ctx, subject, "revealed_disturbance")
    key = "choir_round_all_eyes"
    if (st.row(engine, actor, "all_eyes_open") is not None and actor.turn_flags.get(key) != engine.state.round_number
            and any(engine._footprint_intersects(subject, zone.affected_cells) for zone in _fields(engine, actor))):
        actor.turn_flags[key] = engine.state.round_number
        _pressure(ctx, subject)


@hook("masked_conditions")
def eyes_see_through(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """All Eyes Open: "Ordinary invisibility ... cannot grant Advantage against you"."""
    if attacker is None or target is None or st.row(engine, target, "all_eyes_open") is None or not _fields(engine, target):
        return None
    invisible = {iid for iid, c in attacker.conditions.items() if c.condition_id == "condition:typed.invisible"}
    return {attacker.entity_id: invisible} if invisible else None


# ------------------------------------------------------------------------------------------------------ Hymn of Stillness
_STILL = [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn", "evidence": "it cannot take Reactions"},
          {"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn", "evidence": "its Speed is reduced by 10 feet"},
          {"type": "exposed", "applies_to": "target", "benefits": "invisible", "against": "you", "duration": "until_start_of_next_turn",
           "evidence": "it cannot willingly benefit from ordinary invisibility ... against you"}]


@effect("choir_hymn_record")
def hymn_record(ctx: Any, row: dict[str, Any]) -> None:
    """A creature that failed the Hymn: kept on the singer for Sustained Refrain (one Hymn sustained at a time)."""
    subject = ctx.target
    if subject is None:
        return
    for iid, held in list(ctx.actor.conditions.items()):
        if held.condition_id == HYMN_HELD and held.source_actor_id == ctx.actor.entity_id:
            ctx.actor.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": HYMN_HELD, "instance_id": iid, "reason": "REPLACED"})
    ctx.engine._apply_condition(ctx.actor, HYMN_HELD, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"target": subject.entity_id, "turn": int(ctx.actor.turns_started),
                                      "label": f"Hymn of Stillness on {subject.display_name} (Sustained Refrain at the start of your next turn)"})


@hook("nominal_slot_boundary")
def nominal_refrain(engine: Any, actor: Any, checkpoint: str) -> None:
    """A skipped next turn cannot sustain an expired Hymn or defer that choice."""
    if checkpoint != "START_OF_TURN":
        return
    from .effect_durations import custom_turn_due
    for held in list(actor.conditions.values()):
        if held.condition_id == HYMN_HELD and held.source_actor_id == actor.entity_id and custom_turn_due(
                actor, int((held.data or {}).get("turn") or 0) + 1, actor.turn_flags, held.instance_id, nominal=True):
            st.remove(engine, actor, held, "DURATION_ENDED")


@hook("turn_start_choice")
def sustained_refrain(engine: Any, actor: Any) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == HYMN_HELD and c.source_actor_id == actor.entity_id), None)
    if held is None:
        return
    data = held.data or {}
    subject = engine.state.actors.get(str(data.get("target") or ""))

    def drop() -> None:
        for iid, c in list(actor.conditions.items()):
            if c is held:
                actor.conditions.pop(iid)
                engine._append_event("CONDITION_REMOVED", HYMN, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": HYMN_HELD, "instance_id": iid, "reason": "ENDED"})

    if subject is None or not subject.active or int(data.get("turn") or 0) != int(actor.turns_started) - 1 \
            or actor.resources.get("resource:core.resonance", 0) < 1:
        drop()
        return
    from . import needle

    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "SUSTAINED_REFRAIN", subject.entity_id), actor,
                        "choice:needle.choir.sustained_refrain", ["sustain"],
                        labels={"sustain": f"Sustained Refrain: 1 Resonance, {subject.display_name} repeats the Wisdom save"},
                        prompt=f"Hymn of Stillness: spend 1 Resonance so {subject.display_name} must repeat its Wisdom save? On a failure the "
                               "Stillness continues until the start of your following turn; on a success it ends.",
                        preferred=["sustain"], allow_decline=True, name="Hymn of Stillness", feature_id=HYMN, target_id=subject.entity_id)
    if not chosen:
        drop()
        return
    engine._spend_resource(actor, "resource:core.resonance", 1, HYMN)
    action = next((engine.action_catalog[a] for a in actor.action_ids if a in engine.action_catalog
                   and st.feature_of(engine.action_catalog[a]) == HYMN), None)
    if action is None:
        drop()
        return
    ctx = st.context(engine, actor, action, [subject])
    before = len(engine.events)
    _te().block_save(ctx, {"type": "save", "ability": "wis", "applies_to": "target", "on_fail": [dict(row) for row in _STILL], "on_success": []})
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    failed = bool(rolled) and (rolled[-1].payload or {}).get("success") is False
    drop()
    if failed:
        engine._apply_condition(actor, HYMN_HELD, HYMN, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={**data, "turn": int(actor.turns_started),
                                      "label": f"Hymn of Stillness on {subject.display_name} (Sustained Refrain at the start of your next turn)"})
        note(engine, HYMN, actor, f"Sustained Refrain: {subject.display_name} stays still.", (subject,))
    else:
        note(engine, HYMN, actor, f"Sustained Refrain: {subject.display_name} breaks the Stillness.", (subject,))


# ---------------------------------------------------------------------------------------------- target requirements
@hook("candidate_allowed")
def requirements(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feature = st.feature_of(action) if action is not None else ""
    if feature not in (CONFESSION, EDICT):
        return _witness_focus(engine, actor, candidate, action)
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    te = _te()
    noted, marked = te.bears_mark(target, actor.entity_id, NOTE), te.bears_mark(target, actor.entity_id, "Resonance")
    if feature == CONFESSION:
        return None if noted or marked else False  # "bears your Witness Note or Resonance Mark"
    in_field = any(engine._footprint_intersects(target, z.affected_cells) for z in _fields(engine, actor))
    failed = in_field and _failed_against(engine, actor, target)
    return None if (noted and marked) or failed else False


def _failed_against(engine: Any, owner: Any, creature: Any) -> bool:
    mine = {a for a in owner.action_ids}
    return any(e.event_type == "SAVE_ROLLED" and e.actor_id == creature.entity_id and (e.payload or {}).get("success") is False
               and e.source_definition_id in mine for e in engine.events)


# ------------------------------------------------------------------------------------------------ Edict of Perfect Witness
def _perfect(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == PERFECT), None)


@effect("choir_edict")
def edict(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    for iid, held in list(subject.conditions.items()):
        if held.condition_id == PERFECT and held.source_actor_id == ctx.actor.entity_id:
            subject.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                     payload={"condition_id": PERFECT, "instance_id": iid, "reason": "REPLACED"})
    rounds = _te().clock_expiry(ctx.engine, "minutes", 1) or "UNTIL_REMOVED"
    ctx.engine._apply_condition(subject, PERFECT, ctx.source, ctx.actor.entity_id, expires_on=rounds,
                                data={"bullets": list(BULLETS), "successes": 0, "numbers": dict(ctx.numbers),
                                      "label": "Perfect Witness: " + "; ".join(BULLETS.values())})


def _witness_focus(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    held = _perfect(actor)
    if held is None or "focus" not in ((held.data or {}).get("bullets") or []) or actor.turn_flags.get(REFUSED):
        return None
    witness = engine.state.actors.get(held.source_actor_id)
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    targets = [t for t in targets if t is not None and t is not actor]
    if witness is None or not witness.active or not targets or action is None or action.economy.value not in ("ACTION", "BONUS_ACTION", "REACTION"):
        return None
    hostile = [t for t in targets if t.team_id != actor.team_id]
    if not hostile or all(t is witness for t in hostile):
        return None
    # "while you are a legal target": the witness is within this ability's reach or range
    reach = int(action.range_ft or action.reach_ft or 5)
    if engine.grid.distance_ft(actor.position, witness.position) > reach:
        return None
    return False


@hook("match_start")
def refuse_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[REFUSE_ACTION] = ActionDefinition(
        source_definition_id=REFUSE_ACTION, display_name="Refuse the witness (state a true reason)", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "choir_refuse"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "choir_refuse": True,
                    "description": "Under Perfect Witness: use your Action to state one emotionally true reason you refuse the witness; for the rest "
                                   "of this turn you may attack or target creatures other than the witness."})


@hook("additional_actions")
def refuse_offered(engine: Any, actor: Any) -> list[str]:
    held = _perfect(actor)
    if held is None or "focus" not in ((held.data or {}).get("bullets") or []) or actor.turn_flags.get(REFUSED):
        return []
    return [REFUSE_ACTION]


@effect("choir_refuse")
def refuse(ctx: Any, row: dict[str, Any]) -> None:
    ctx.actor.turn_flags[REFUSED] = True
    note(ctx.engine, REFUSE_ACTION, ctx.actor, f"{ctx.actor.display_name} states why it refuses the witness and may choose other targets this turn.")


@hook("masked_conditions")
def witness_unveils(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for who, other in ((attacker, target), (target, attacker)):
        if who is None or other is None:
            continue
        held = _perfect(who)
        if held is None or "unveiled" not in ((held.data or {}).get("bullets") or []):
            continue
        witness = engine.state.actors.get(held.source_actor_id)
        if witness is None or other.team_id != witness.team_id:
            continue  # "against creatures you designate": you and your allies
        invisible = {iid for iid, c in who.conditions.items() if c.condition_id == "condition:typed.invisible"}
        if invisible:
            out.setdefault(who.entity_id, set()).update(invisible)
    return out or None


@hook("turn_end")
def witness_repeat_save(engine: Any, actor: Any) -> None:
    from .effect_durations import apply_condition_preserving_clock
    held = _perfect(actor)
    if held is None or not actor.active:
        return
    witness = engine.state.actors.get(held.source_actor_id)
    data = dict(held.data or {})
    action = next((engine.action_catalog[a] for a in (witness.action_ids if witness else ()) if a in engine.action_catalog
                   and st.feature_of(engine.action_catalog[a]) == EDICT), None)
    if witness is None or action is None:
        return
    ctx = st.context(engine, witness, action, [actor], data.get("numbers") or None)
    before = len(engine.events)
    _te().block_save(ctx, {"type": "save", "ability": "cha", "applies_to": "target", "on_fail": [], "on_success": []})
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == actor.entity_id]
    success = bool(rolled) and bool((rolled[-1].payload or {}).get("success"))
    if not success:
        _pressure(ctx, actor)
        return
    bullets = list(data.get("bullets") or [])
    successes = int(data.get("successes") or 0) + 1
    for iid, c in list(actor.conditions.items()):
        if c is held:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": PERFECT, "instance_id": iid, "reason": "SAVED" if successes >= 3 else "NARROWED"})
    if successes >= 3 or not bullets:
        note(engine, EDICT, witness, f"Perfect Witness ends on {actor.display_name} (three successful saves).", (actor,))
        return
    from . import needle

    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "PERFECT_WITNESS", actor.entity_id), actor, "choice:needle.choir.perfect_witness",
                        bullets, labels={b: BULLETS[b] for b in bullets}, preferred=["focus"] if "focus" in bullets else bullets[:1],
                        prompt=f"{actor.display_name} succeeds on its save against Perfect Witness: remove one of its restrictions.",
                        name="Perfect Witness", feature_id=EDICT, target_id=actor.entity_id)
    drop = chosen[0] if chosen else bullets[0]
    bullets = [b for b in bullets if b != drop]
    apply_condition_preserving_clock(engine, actor, held, PERFECT, held.source_definition_id, held.source_actor_id, expires_on=held.expires_on,
                            data={**data, "bullets": bullets, "successes": successes,
                                  "label": "Perfect Witness: " + "; ".join(BULLETS[b] for b in bullets)})


DECLARE_ACTION = "system:combat.declare_witness_departure"
DECLARED = "choir_declared_departure"


@hook("match_start")
def declaration_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[DECLARE_ACTION] = ActionDefinition(
        source_definition_id=DECLARE_ACTION, display_name="Declare Departure to the Witness", owner_id="*",
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "choir_declare_departure", "applies_to": "self"}],
                               "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0,
                    "description": "Perfect Witness: spend your Action to declare your intended departure method and destination. "
                                   "The Witness records both declarations; the teleport still follows its ordinary rules."})


@hook("additional_actions")
def declaration_offered(engine: Any, actor: Any) -> list[str]:
    held = _perfect(actor)
    return [DECLARE_ACTION] if held is not None and "passage" in (held.data or {}).get("bullets", []) else []


@effect("choir_declare_departure")
def declare_departure(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    held = _perfect(actor)
    if held is None or "passage" not in (held.data or {}).get("bullets", []):
        return
    from .teleport_steps import destinations
    cells = destinations(engine, actor, max(engine.grid.width, engine.grid.height) * engine.grid.square_size_ft)
    # The declaration grants no perception, reach or legal teleport. It merely
    # names a destination; the eventual technique retains all its own gates.
    ids = [needle.cell_id(cell) for cell in cells]
    if not ids:
        return
    preferred = min(cells, key=lambda cell: (engine.grid.distance_ft(actor.position, cell), cell.y, cell.x))
    methods = ["spell", "technique", "item", "other"]
    method = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WITNESS_DEPARTURE_METHOD", actor.entity_id), actor,
                        "choice:needle.choir.departure_method", methods,
                        labels={"spell": "Spell", "technique": "Technique", "item": "Item", "other": "Other method"},
                        prompt="Perfect Witness: which method will you use to depart?",
                        name="Declare Departure Method", feature_id=EDICT)
    if not method:
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WITNESS_DEPARTURE", actor.entity_id), actor,
                        "choice:needle.choir.departure", ids,
                        labels={needle.cell_id(cell): f"Declare departure to {cell.x},{cell.y}" for cell in cells},
                        preferred=[needle.cell_id(preferred)], name="Declare Departure to the Witness", feature_id=EDICT,
                        prompt="Perfect Witness: choose your intended destination for this departure.")
    if chosen:
        destination = needle.position_of(chosen[0])
        actor.turn_flags[DECLARED] = {"method": method[0], "destination": destination.model_dump(mode="json")}
        note(engine, EDICT, actor, f"{actor.display_name} declares {method[0]} to {destination.x},{destination.y}.")


@hook("teleport_context_check")
def declared_teleport(engine: Any, actor: Any, start: Any, destination: Any, movement_context: str) -> bool | None:
    if movement_context != "WILLING":
        return None
    held = _perfect(actor)
    if held is None or "passage" not in (held.data or {}).get("bullets", []):
        return None
    declared = actor.turn_flags.get(DECLARED)
    if declared is None or destination.model_dump(mode="json") != declared.get("destination"):
        return False
    return None
