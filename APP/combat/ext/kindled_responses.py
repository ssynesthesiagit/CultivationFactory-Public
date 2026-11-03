"""One shared arbitration for a response family that draws on a single shared resource.

Yang's Kindled Responses print one sentence for the whole family: *"You may use these responses
when you spend a Kindled Mark."* That makes the six responses alternatives, not six independent
triggers: **one mark, one use**, and every one of them draws on the same once-per-round group
(``TAL_YANG_SPENDING_A_RISING_MARK``).

A family like that cannot be implemented as several hooks that each spend the mark the moment their
own checkpoint arrives.  Two of its members are armed by the same attack -- Complete Aim answers the
attack roll, Complete Force answers the hit -- so whichever resolves first silently takes the mark
and the player never gets to choose.  And offering the alternatives is not yet arbitrating them: the
player has to be able to answer "none of them", and that answer has to hold at the later checkpoints
too, or the member they just declined spends the mark anyway.  This module is the one place that
decides, and the one place that remembers what it decided.

Three parts:

* ``competing`` lists the owner's other *armed* members of the shared group whose moment this same
  action still reaches after the current checkpoint -- read from each row's own compiled ``kind``,
  and judged by the engine's own eligibility readers for the creatures actually involved: the one
  attacking and the one attacked.  A row that could not answer this attack is not an alternative to
  it, and offering one is how a player is offered a response their ally's swing cannot buy.
* ``choose`` puts those rivals into **one** menu with the current checkpoint's own option, and
  records the answer for this strike, restoring the parent after nested attacks.
* ``enforced`` is what the later checkpoints read: ``reaction_subject_allowed`` and
  ``ally_row_allowed`` use it to keep a member of the family from answering an occurrence the owner
  has already answered.  That is how "Not now" stops being a deferral, and how one mark still buys
  one response in a family with more members than the player can afford.

Nothing is stored in fight state: the record is engine-transient and is rebuilt from nothing for
each resolution, so a saved fight and its reload are untouched.  The group's own once-per-round flag
and the marks themselves remain the only lasting state.

The default answer is the member that waits for the confirmed outcome (``preferred`` order below),
because that is the safer default twice over -- it is the order the family resolved in before any
plug-in arbitrated, and a mark spent on it is not lost when the attack misses.

Consumers: ``yang_recovery`` (Yang's Kindled Responses: Complete Aim, and Furnace Backlash's
shared-round check).  Any plug-in that implements a member of a shared-once-group response family
should arbitrate through this module rather than adding its own deferral, so the family keeps one
owner per mark spend no matter how many members it has.
"""

from __future__ import annotations

from typing import Any

from . import hook
from . import trigger_occurrence as occurrence

# The printed once-per-round group every Kindled Response draws on, and the turn_flags key the
# engine's own generic reactions reserve for it (``typed_reactions._once_key``).
GROUP = "TAL_YANG_SPENDING_A_RISING_MARK"
ROUND_KEY = f"once_per_round:typed.{GROUP}"
MARK = "Kindled Mark"

# Native fallback; typed answers live in their individual strike's scratch frame.
RECORD = "_kindled_family_choice"

# The compiled row kinds that answer *after* the checkpoint they share with an earlier member:
# the attack roll has been made but the attack has not resolved yet.  A row whose kind is not
# listed here triggers on some other moment entirely (a heal, a save, a move) and is not a rival
# for this one, so it is left alone.  Read from row["kind"], never from an ability id.
_AFTER_THE_ROLL = ("own_hit", "ally_hit")
_OWN_KINDS = ("own_hit",)

# When each of those moments comes, in the player's own words.  A newcomer has to be able to tell
# the options apart from the buttons alone, so a label says when the response answers and what it
# does, not merely that it exists.
_WHEN = {"own_hit": "when this attack hits",
         "ally_hit": "when this attack hits one of your allies"}

# Typed effect types whose printed amount is extra damage or extra recovery; anything else is
# described from its own reviewed evidence sentence.
_EXTRA_DAMAGE = {"damage", "extra_damage"}
_EXTRA_RECOVERY = {"healing", "healing_bonus", "recovery_bonus", "temp_hp_gained"}

# The flat terms the engine's own effect vocabulary understands, in the sheet's own words.
_FORMULA_WORDS = {"pb": "your Proficiency Bonus",
                  "half_pb": "half your Proficiency Bonus",
                  "cl": "your Cultivation Level",
                  "key_ability_modifier": "your Key Ability modifier",
                  "attack_ability_modifier": "its attack ability modifier"}


def used_round(engine: Any, owner: Any) -> bool:
    """Whether this owner already spent this round's shared use of the group's mark."""
    return owner.turn_flags.get(ROUND_KEY) == engine.state.round_number


def reserve_round(engine: Any, owner: Any) -> None:
    """Claim the shared once-per-round use, in the same turn_flags slot the engine's own generic
    reactions read, so a later member of the family sees the mark as already spent."""
    owner.turn_flags[ROUND_KEY] = engine.state.round_number


def mark_cost(further: str = "nothing else") -> str:
    """The shared wording for what a member of the family costs: the mark itself, always, plus
    whatever else that member's own record charges."""
    return f"spends their {MARK} and {further}" if further else f"spends their {MARK}"


def _amount(row: dict[str, Any], effect: dict[str, Any]) -> str:
    """What one typed effect adds, in this owner's own numbers ("3d6 + your Key Ability modifier")."""
    from factory_authoring.typed_mechanics import dice_for_cl

    numbers = row.get("numbers") or {}
    dice = dice_for_cl(effect.get("dice_by_cl"), numbers.get("cl")) or effect.get("dice") or {}
    count, sides = int(dice.get("count") or 0), int(dice.get("sides") or 0)
    rolled = f"{count}d{sides}" if count > 0 and sides > 1 else ""
    flat = _FORMULA_WORDS.get(str(effect.get("formula") or ""), "")
    if not flat and effect.get("flat"):
        flat = str(int(effect["flat"]))
    return " + ".join(part for part in (rolled, flat) if part)


def _benefit(row: dict[str, Any]) -> str:
    """One plain clause for what spending the mark on this row does, in the owner's own numbers."""
    clauses = []
    damage_to = ("the damage this attack deals to your ally"
                 if row.get("kind") == "ally_hit" else "the damage this attack deals")
    for effect in row.get("effects") or ():
        if not isinstance(effect, dict) or effect.get("type") == "spend_mark":
            continue  # the shared mark is named once, as the cost
        amount, kind = _amount(row, effect), str(effect.get("type") or "")
        if amount and kind in _EXTRA_DAMAGE:
            clauses.append(f"adds {amount} to {damage_to}")
        elif amount and kind in _EXTRA_RECOVERY:
            clauses.append(f"recovers {amount} more")
        else:
            said = str(effect.get("evidence") or "").strip()
            if said:
                clauses.append(f"{said[0].lower()}{said[1:]}")
    return "; ".join(clauses)


def cost_words(row: dict[str, Any]) -> str:
    """Everything this row costs its owner besides the shared mark, in the table's cost wording."""
    from .choice_costs import quote

    prices = [part for part in (quote(row.get("costs")), "" if row.get("free") else "your Reaction") if part]
    return ", ".join(prices) if prices else "nothing else"


def label(row: dict[str, Any]) -> str:
    """The button text for one family member: its printed name, when it answers, what it does, and
    what it costs.  Never an internal id -- a row with no printed name falls back to what it does,
    because a button reading ``TAL_...#complete_force`` tells a player nothing.
    """
    name = str(row.get("name") or "").strip()
    benefit = _benefit(row) or str(row.get("reading") or "").strip()
    when = _WHEN.get(str(row.get("kind") or ""), "when this attack resolves")
    says = "; ".join(part for part in (when, benefit) if part)
    return f"{name}: {says} ({mark_cost(cost_words(row))})" if name else f"{says} ({mark_cost(cost_words(row))})"


def _records(engine: Any) -> dict:
    """Typed strikes isolate answers; legacy native attacks keep resolution-local records."""
    strike = occurrence.current_strike(engine)
    if strike is not None:
        return strike['scratch'].setdefault(RECORD, {})
    current = occurrence.resolution(engine)
    records = getattr(engine, RECORD, None)
    if not isinstance(records, dict) or records.get('resolution') != current:
        records = {'resolution': current, 'choices': {}}
        setattr(engine, RECORD, records)
    return records['choices']


def forget(engine: Any, owner: Any) -> None:
    """Drop this owner's recorded answer before its next arbitration.

    Called at the head of the earlier checkpoint so an occurrence the owner is asked about now can
    never be answered by one it was asked about earlier in the same resolution.
    """
    _records(engine).pop(owner.entity_id, None)


def _remember(engine: Any, owner: Any, attacker: Any, subjects: list[Any], chosen: str | None) -> None:
    _records(engine)[owner.entity_id] = {"attacker": attacker.entity_id,
                                           "subjects": {a.entity_id for a in subjects if a is not None},
                                           "chosen": chosen}


def enforced(engine: Any, reactor: Any, row: dict[str, Any] | None, subject: Any | None) -> bool:
    """Whether this occurrence of the family was already answered, and this row is not that answer.

    True means "the owner has already decided this attack's family -- do not spend the mark again
    here".  A recorded answer counts only for the creature it was asked about, so a family's answer
    for one creature's swing can never silence another creature's.  Nothing recorded (an earlier
    checkpoint that asked nobody, a save, a fight nobody arbitrates in) is False, which leaves every
    ordinary family member exactly as it was.
    """
    record = _records(engine).get(getattr(reactor, "entity_id", ""))
    if not record or row is None or subject is None:
        return False
    if record.get("chosen") == row.get("feature_id"):
        return False  # this is the member the owner picked for this very occurrence
    if subject.entity_id not in (record.get("subjects") or ()):
        return False  # a different creature's occurrence: its own family question stands
    if reactor.entity_id == record.get("attacker"):
        return True  # the owner's own swing: only the chosen member may answer it
    return str(row.get("kind") or "") not in _OWN_KINDS  # a bystander's member: same question, same mark


def competing(engine: Any, owner: Any, *, exclude: str, actor: Any = None, subjects: list[Any] | None = None,
              mark: str = MARK, kinds: tuple[str, ...] = _AFTER_THE_ROLL) -> list[dict[str, Any]]:
    """The owner's armed rows that share ``GROUP``, are not ``exclude``, and could answer *this*
    attack after the current checkpoint.

    "Armed" is read the way the engine's own generic reaction reader reads it: the row is in the same
    shared group, its once-per-round slot is unused, the owner is conscious and can pay, and the
    row's own mark requirement is met -- ``requires_self_mark`` (Complete Force, which answers only
    for the marked creature's own hits) on the attacking creature, or ``requires_mark`` on the
    creature that row names.  Team, reach and range come from the engine's own readers, so a row the
    attack cannot reach is never offered.

    ``actor`` is the creature making the attack and ``subjects`` the creatures it is aimed at: a
    family row belongs to the creature whose moment it is (``own_hit`` answers its owner's own hit)
    and to the creature it protects (``ally_hit`` answers a hit on the owner's ally), so without
    them an owner's ``own_hit`` row would be offered for a marked ally's swing, which that row can
    never answer.  A row that needs no mark of this one is skipped: it applies a mark of its own
    rather than spending this one.
    """
    if used_round(engine, owner):
        return []
    from . import needle
    from ..typed_executor import bears_mark

    if needle.incapacitated(owner) or not owner.active:
        return []
    from .. import typed_reactions

    offered = [a for a in (subjects or []) if a is not None and a.active]
    out = []
    for row in getattr(engine, "typed_reaction_rows", {}).get(owner.entity_id, []) or ():
        if row.get("feature_id") == exclude or row.get("once_group") != GROUP:
            continue
        kind = row.get("kind")
        if kind not in kinds:
            continue
        needed = row.get("requires_self_mark")
        if needed:
            if actor is not owner or not bears_mark(actor, actor.entity_id, needed):
                continue  # only the owner's own attack can reach an "its own hit" row
        elif not row.get("requires_mark"):
            continue  # a row that spends no mark of this one is not a rival for it
        elif actor is not None and not bears_mark(actor, owner.entity_id, str(row["requires_mark"])):
            continue
        if not typed_reactions._can_trigger(engine, owner, row) or not typed_reactions._generic_affordable(engine, owner, row):
            continue
        if any(_reaches(engine, owner, actor, subject, row, kind) for subject in offered):
            out.append(row)
    return out


def _reaches(engine: Any, owner: Any, actor: Any, subject: Any, row: dict[str, Any], kind: Any) -> bool:
    """Whether this row could answer an attack by ``actor`` on ``subject``, read by the engine's own
    eligibility readers -- the two ``on_own_event`` and ``_offer_ally_hit`` use, so a rival is offered
    exactly when the engine would run it."""
    from .. import typed_reactions

    if kind == "ally_hit":
        return (typed_reactions._ally_row_ok(engine, owner, actor, subject, row)
                and typed_reactions._generic_in_range(engine, owner, subject, row, subject=subject, source=actor))
    return (typed_reactions._subject_ok(engine, owner, subject, row)
            and typed_reactions._generic_in_range(engine, owner, subject, row))


def choose(engine: Any, intent: Any, owner: Any, marked: Any, action_name: str, *,
           mine: tuple[str, str], choice_id: str, checkpoint: str,
           feature_id: str, name: str, subjects: list[Any] | None = None,
           kinds: tuple[str, ...] = _AFTER_THE_ROLL, mark: str = MARK) -> str | None:
    """Ask ``owner`` which member of the family spends this mark.  Returns the chosen member's
    feature id, or ``None`` when the owner declines or nobody answers.

    This is deliberately **one** question, not a question per member: the player is choosing between
    alternatives, so the alternatives belong in a single menu.  Asking twice would also spend two
    answer slots in a controller that replays its answers positionally.

    ``mine`` is this checkpoint's own ``(option id, label)``; every armed rival contributes an option
    labelled from its own compiled record, so the table shows what the mark buys rather than an
    internal id.  The answer -- including "neither" -- is recorded for this resolution, so the members
    that answer later in the same attack read it instead of spending the mark anyway.
    """
    from . import needle

    rivals = competing(engine, owner, exclude=feature_id, actor=marked, subjects=subjects, mark=mark, kinds=kinds)
    options = [mine[0], *[str(row["feature_id"]) for row in rivals]]
    labels = {mine[0]: mine[1]}
    for row in rivals:
        labels[str(row["feature_id"])] = label(row)
    # Rivals first: the member that waits for the attack to land goes first (see the module
    # docstring), so an unanswered question keeps the behaviour the family had before arbitration.
    preferred = [*[str(row["feature_id"]) for row in rivals], mine[0]]
    picked = needle.ask(engine, intent, checkpoint, owner, choice_id, options,
                        labels=labels, preferred=preferred, allow_decline=True,
                        target_id=marked.entity_id, name=name, feature_id=feature_id,
                        prompt=(f'{name}: {marked.display_name} uses {action_name}. You can spend one '
                                f'Kindled Mark on exactly one of your responses -- pick which, or pass '
                                f'and keep the mark for later.'))
    chosen = picked[0] if picked else None
    _remember(engine, owner, marked, subjects or [], chosen)
    return chosen


@hook("reaction_subject_allowed")
def _subject_allowed(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """Keep a member of an arbitrated family from answering an occurrence its owner already answered.

    ``typed_reactions._subject_ok`` reads this on the reactor's own events, where ``other`` is the
    creature that was hit -- so the one thing a later checkpoint knows and the earlier one could not
    record is right here.
    """
    if row.get("once_group") != GROUP or row.get("kind") not in _AFTER_THE_ROLL:
        return None
    return False if enforced(engine, reactor, row, other) else None


@hook("ally_row_allowed")
def _ally_row_allowed(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """The same decision for a bystander's member of the family (an ``ally_hit`` row), where the
    creature protected is the one the owner answered for."""
    if row.get("once_group") != GROUP or row.get("kind") not in _AFTER_THE_ROLL:
        return None
    return False if enforced(engine, reactor, row, subject) else None


@hook("reaction_consent")
def selected_consent(engine: Any, row: dict[str, Any], reactor: Any, checkpoint: str) -> bool | None:
    """A selected later response already has the owner's consent from the family menu.

    This existing hook only answers manual Ask-me reactions. Eligibility and payment
    remain with the generic handler; other families and other attacks are inert.
    """
    if row.get("once_group") != GROUP or row.get("kind") not in _AFTER_THE_ROLL:
        return None
    record = _records(engine).get(reactor.entity_id)
    trigger = getattr(engine, "_reaction_trigger", None) or {}
    if (record and trigger.get("actor_id") == record.get("attacker")
            and trigger.get("target_id") in record.get("subjects", ())):
        return record.get("chosen") == row.get("feature_id")
    return None
