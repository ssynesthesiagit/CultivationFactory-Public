"""Fate Reader (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Fate Reader: Fate Tension, CL3 Omen Glimpse, CL6 Read the Thread, CL10 Nudge
Consequence, CL14 Borrowed Ending, CL18 Sever One Thread). No Spheres 5e or D&D 5.5e counterpart. Invoke the Omen and Sever One
Thread are d20 rewrites in combat/ext/d20_rewrite_fate.py (automation lane H1). Ownership: the ``spirit_tradition`` rows of
combat/rules/feature_blocks.d/riders_c8.json (Nudge Consequence, Borrowed Ending).

Fate Tension (tradition text): a pool on the sheet (resource:named.fate_tension), 0 at the start, maximum = Proficiency Bonus; at
its maximum you are Fate-Tangled (the pool full is the state -- no second condition).

What runs:
  * Nudge Consequence (Reaction, 4 Resonance): when a creature you can see within 60 feet makes an attack roll, ability check or saving
    throw whose outcome the table knows, before the outcome you may add or subtract 1d8 (asked; the AI helps its side's rolls and
    hinders its foes' when 8 could turn them). Worsening an unwilling creature's roll: it makes a Charisma save against your DC --
    failed, the full die; success, only 1d4 and your chosen Spiritual Pressure. If the modifier turns a success into a failure or a
    failure into a success, you gain 1 Fate Tension.
  * Borrowed Ending (Reaction, 6 Resonance and 1 Fate Tension taken on -- you cannot while Fate-Tangled): when you or an ally within 30
    feet would drop to 0 Hit Points, or would become Charmed or Frightened by a hostile creature (asked), the consequence is delayed
    until the end of that creature's next turn: it stays at 1 Hit Point / the condition has not taken hold. A visible Ending Token
    (an object: AC your Cultivation Save DC, 6 x PB Hit Points, immune Poison and Psychic) is attached to it. At the end of its next
    turn the Ending dissolves if the cause changed -- it regained Hit Points, or the creature that would have Charmed or Frightened it
    is gone -- otherwise the original consequence occurs (it drops to 0 Hit Points; the condition lands). Destroying the token makes
    the consequence occur at once. One Borrowed Ending from you at a time on a creature.

Plug-in surface: effects none; hooks d20_bonus, would_drop, condition_attempt, turn_end, event. Public helper: ``gain_tension``.
Shared helpers used: spirit_traditions (row/context/numbers/feature_action/can_react/remove), needle.ask, d20_rewrite.context_of,
stealth.sees, typed_executor (run_effects); spirit_traditions delay_condition/land_delayed_condition/landing.
"""

from __future__ import annotations

from typing import Any

from . import hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.fate_reader.feature."
NUDGE = TRADITION + "nudge_consequence"
BORROWED = TRADITION + "borrowed_ending"
TENSION = "resource:named.fate_tension"
RESONANCE = "resource:core.resonance"
ENDING = "condition:typed.borrowed_ending"
TOKEN = "object:typed.borrowed_ending:"
_NUDGING = "_c8_nudging"
_RESOLVING = "_c8_borrowed_resolving"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def gain_tension(engine: Any, actor: Any, amount: int, source: str) -> None:
    """Fate Tension up to its maximum (Proficiency Bonus)."""
    room = int(actor.resource_maximums.get(TENSION, 0) or 0) - int(actor.resources.get(TENSION, 0) or 0)
    if room > 0 and amount > 0:
        engine._gain_resource(actor, TENSION, min(room, amount), source)


def tangled(actor: Any) -> bool:
    return int(actor.resource_maximums.get(TENSION, 0) or 0) > 0 and actor.resources.get(TENSION, 0) >= actor.resource_maximums.get(TENSION, 0)


# ---------------------------------------------------------------------------------------------------------- Nudge Consequence
def _succeeded(rc: Any, total: int) -> bool | None:
    if rc.kind == "attack":
        if rc.ac is None:
            return None
        return rc.natural != 1 and (rc.natural == 20 or total >= rc.ac)
    if rc.dc is None:
        return None
    return total >= rc.dc


@hook("d20_bonus")
def nudge(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    if engine.__dict__.get(_NUDGING) or roll.natural_result is None:
        return None
    from .d20_rewrite import context_of

    rc = context_of(engine, roll)
    if rc is None or rc.kind not in ("attack", "save", "check"):
        return None
    now = _succeeded(rc, int(roll.total))
    if now is None:
        return None
    from .. import stealth

    for reader in list(engine.state.actors.values()):
        if (not reader.active or st.row(engine, reader, "nudge_consequence") is None or not st.can_react(reader)
                or reader.resources.get(RESONANCE, 0) < 4):
            continue
        roller = rc.roller
        if roller is not reader and (engine._distance_actor_to_actor(reader, roller) > 60 or not stealth.sees(engine, reader, roller)):
            continue
        ours = roller.team_id == reader.team_id
        # the AI's aim: help its own side's failing roll, hinder a foe's succeeding one, when 8 could turn it
        target_number = rc.ac if rc.kind == "attack" else rc.dc
        helpful = ours and not now and int(target_number) - int(roll.total) <= 8
        harmful = not ours and now and int(roll.total) - int(target_number) < 8 and rc.natural != 20
        from . import needle

        options = ["add", "subtract"]
        labels = {"add": "Add 1d8 to the roll", "subtract": "Subtract 1d8 from the roll"}
        preferred = ["add"] if helpful else ["subtract"] if harmful else []
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "NUDGE", roll.roll_id), reader, "choice:needle.fate_reader.nudge", options,
                            labels=labels, preferred=preferred, allow_decline=True, automatic=bool(preferred),
                            default="first" if preferred else "decline", name="Nudge Consequence", feature_id=NUDGE, target_id=roller.entity_id,
                            prompt=f"Nudge Consequence (Reaction, 4 Resonance): {roller.display_name}'s {rc.kind} roll is {roll.total} "
                                   f"({'succeeding' if now else 'failing'}). Add or subtract 1d8 before the outcome?")
        if not chosen or chosen[0] not in options:
            continue
        engine.__dict__[_NUDGING] = True
        try:
            return _apply_nudge(engine, reader, rc, roll, chosen[0] == "add", ours, now)
        finally:
            engine.__dict__.pop(_NUDGING, None)
    return None


def _apply_nudge(engine: Any, reader: Any, rc: Any, roll: Any, add: bool, ours: bool, before: bool) -> dict[str, Any]:
    from ..gate2_runtime_models import DiceSpec

    engine._spend_resource(reader, RESONANCE, 4, NUDGE)
    reader.reaction_available = False
    engine._append_event("REACTION_RESOLVED", NUDGE, actor_id=reader.entity_id, target_ids=(rc.roller.entity_id,),
                         payload={"checkpoint": "D20_BONUS", "reaction_name": "Nudge Consequence"})
    sides = 8
    worsens = not add
    if worsens and not ours and rc.roller.active:
        # "If the target is unwilling and you worsen its result, it makes a Charisma saving throw."
        dc = int(st.numbers(engine, reader).get("save_dc") or 10)
        saved = engine._roll_save(rc.roller, "CHA", dc, NUDGE)
        if saved is not None and saved.total >= dc:
            sides = 4
            ctx = st.context(engine, reader, st.feature_action(engine, reader, NUDGE), [rc.roller], st.numbers(engine, reader))
            _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "the target suffers one ordinary Spiritual Pressure effect"}])
    die = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=reader.entity_id, reason=f"D20_BONUS:{NUDGE}")
    engine._record_roll(die)
    bonus = int(die.total) if add else -int(die.total)
    after = _succeeded(rc, int(roll.total) + bonus)
    if after is not None and after != before:
        gain_tension(engine, reader, 1, NUDGE)  # "gain 1 Fate Tension if the modifier changed success to failure or failure to success"
    note(engine, NUDGE, reader, f"Nudge Consequence: {'+' if add else '-'}{die.total} on {rc.roller.display_name}'s roll.", (rc.roller,))
    return {"source_id": NUDGE, "bonus": bonus}


# ---------------------------------------------------------------------------------------------------------- Borrowed Ending
def _endings(creature: Any, reader_id: str | None = None) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == ENDING and (reader_id is None or c.source_actor_id == reader_id)]


def _readers(engine: Any, subject: Any) -> list[Any]:
    """Fate Readers who may borrow this creature's ending: it is them or an ally within 30 feet."""
    out = []
    for reader in engine.state.actors.values():
        if (reader.active and reader.team_id == subject.team_id and st.row(engine, reader, "borrowed_ending") is not None and st.can_react(reader)
                and reader.resources.get(RESONANCE, 0) >= 6 and not tangled(reader) and not _endings(subject, reader.entity_id)
                and (reader is subject or engine._distance_actor_to_actor(reader, subject) <= 30)):
            out.append(reader)
    return out


def _ask(engine: Any, reader: Any, subject: Any, what: str, intent: Any) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BORROWED_ENDING", subject.entity_id), reader, "choice:needle.fate_reader.borrowed_ending",
                        ["borrow"], labels={"borrow": f"Borrowed Ending (Reaction, 6 Resonance, +1 Fate Tension): delay it until the end of {subject.display_name}'s next turn"},
                        prompt=f"{subject.display_name} would {what}.", preferred=["borrow"], allow_decline=True, name="Borrowed Ending",
                        feature_id=BORROWED, target_id=subject.entity_id)
    return bool(chosen)


def _borrow(engine: Any, reader: Any, subject: Any, data: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    engine._spend_resource(reader, RESONANCE, 6, BORROWED)
    gain_tension(engine, reader, 1, BORROWED)
    reader.reaction_available = False
    engine._append_event("REACTION_RESOLVED", BORROWED, actor_id=reader.entity_id, target_ids=(subject.entity_id,),
                         payload={"checkpoint": "CONSEQUENCE", "reaction_name": "Borrowed Ending"})
    numbers = st.numbers(engine, reader)
    hp = 6 * int(numbers.get("pb") or 2)
    token = RuntimeObjectState(object_id=f"{TOKEN}{reader.entity_id}:{subject.entity_id}:{engine.state.event_sequence}", object_kind="BORROWED_ENDING_TOKEN",
                               position=subject.position, unattended=False, flammable=False, owner_id=reader.entity_id,
                               ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
                               component={"ending_of": subject.entity_id, "label": "Ending Token"})
    engine._update_object(token, BORROWED, reader.entity_id)
    engine._apply_condition(subject, ENDING, BORROWED, reader.entity_id, expires_on="UNTIL_REMOVED",
                            data={**data, "token": token.object_id, "turn": int(subject.turns_started),
                                  "label": f"Borrowed Ending: {data.get('what')} is delayed until the end of its next turn"})
    note(engine, BORROWED, reader, f"Borrowed Ending: {subject.display_name}'s fate is delayed ({data.get('what')}).", (subject,))


@hook("would_drop")
def borrow_the_fall(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    if engine.__dict__.get(_RESOLVING) == target.entity_id:
        return None
    if any((held.data or {}).get("kind") == "zero_hp" for held in _endings(target)):
        return max(0, target.current_hp + target.temporary_hp - 1)  # "During the delay: The target remains at a minimum of 1 Hit Point"
    if target.current_hp <= 1:
        return None
    for reader in _readers(engine, target):
        if not _ask(engine, reader, target, "drop to 0 Hit Points", engine._active_intent):
            continue
        _borrow(engine, reader, target, {"kind": "zero_hp", "what": "dropping to 0 Hit Points", "source_actor": source_actor_id})
        return max(0, target.current_hp + target.temporary_hp - 1)  # "The target remains at a minimum of 1 Hit Point"
    return None


@hook("condition_attempt")
def borrow_the_condition(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    name = str(effect_row.get("condition") or "").lower()
    engine = ctx.engine
    if (name not in ("charmed", "frightened") or subject is None or ctx.actor.team_id == subject.team_id
            or engine.__dict__.get(_RESOLVING) == subject.entity_id or st.landing(engine, subject)):
        return None
    for reader in _readers(engine, subject):
        if not _ask(engine, reader, subject, f"become {name.title()}", ctx.intent):
            continue
        _borrow(engine, reader, subject, {"kind": "condition", "what": f"becoming {name.title()}", **st.delay_condition(ctx, effect_row, name)})
        return False  # "has not yet taken hold"
    return None


@hook("turn_end")
def ending_arrives(engine: Any, actor: Any) -> None:
    for held in list(_endings(actor)):
        if actor.turns_started > int((held.data or {}).get("turn") or 0):
            _resolve(engine, actor, held, at_once=False)


@hook("event")
def token_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Destroying the token by hostile action causes the original consequence to occur immediately"."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(TOKEN) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    holder = engine.state.actors.get(str((obj.get("component") or {}).get("ending_of") or ""))
    if holder is None:
        return
    for held in _endings(holder):
        if (held.data or {}).get("token") == obj.get("object_id") and kwargs.get("actor_id") != held.source_actor_id:
            _resolve(engine, holder, held, at_once=True)


def _resolve(engine: Any, holder: Any, held: Any, *, at_once: bool) -> None:
    data = dict(held.data or {})
    st.remove(engine, holder, held, "RESOLVED")
    token = engine.state.objects.get(str(data.get("token") or ""))
    if token is not None and not token.destroyed:
        engine._update_object(token.model_copy(update={"destroyed": True, "current_hp": 0}), BORROWED, held.source_actor_id)
    source = engine.state.actors.get(str(data.get("source_actor") or ""))
    if data.get("kind") == "zero_hp":
        if not at_once and holder.current_hp > 1:
            note(engine, BORROWED, holder, f"Borrowed Ending dissolves: {holder.display_name} was healed.")
            return
        engine.__dict__[_RESOLVING] = holder.entity_id
        engine.__dict__["_damage_unreduced"] = holder.entity_id
        try:
            engine._commit_damage(holder, holder.current_hp + holder.temporary_hp, "UNTYPED", BORROWED, str(data.get("source_actor") or held.source_actor_id),
                                  engine._active_intent, reaction_depth=1)
        finally:
            engine.__dict__.pop(_RESOLVING, None)
            if engine.__dict__.get("_damage_unreduced") == holder.entity_id:
                engine.__dict__.pop("_damage_unreduced", None)
        note(engine, BORROWED, holder, f"The borrowed ending arrives: {holder.display_name} drops to 0 Hit Points.")
        return
    if data.get("kind") == "condition":
        if st.land_delayed_condition(engine, holder, data):
            note(engine, BORROWED, holder, f"The borrowed ending arrives: {holder.display_name} becomes {str(data.get('condition')).title()}.")
        else:
            note(engine, BORROWED, holder, f"Borrowed Ending dissolves: the creature that would have {data.get('condition')} {holder.display_name} is gone.")
