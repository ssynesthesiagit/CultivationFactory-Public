"""Execution Mark (Axes, CL 5): the axe-blow mark that turns a wounded creature's own recovery into your next swing.

Owner text (APP/authority/typed_mechanics/rules_text.json, TAL_AXES_EXECUTION_MARK):
"When you hit a Bloodied creature with Hewing Strike or Cast Axe, you may place an Execution Mark instead of a normal rider.
The mark lasts until the start of your next turn and counts as Bite for your Axes talents. The first time before the mark ends
that the target regains HP, teleports, turns Invisible, or takes the Disengage action, you may use your Reaction to make one axe
weapon attack against it if it is within your weapon's reach or within the legal range of a lodged or thrown axe line you
control."

Root cause this lane fixed: the talent's printed Reaction -- the second sentence -- had no implementation anywhere, so it
reached the table as the GM rider "The first time before the mark ends that the target regains HP, teleports, turns Invisible,
or takes the Disengage action ...". The mark itself is typed and placed (rider lane 3); the four triggers below run the axe
swing the mark's owner may buy with a Reaction.

How it runs
  * Placement is already typed (rider lane 3: a hit on a Bloodied creature with Hewing Strike or Cast Axe places the mark,
    which counts as Bite, until the start of your next turn). This lane adds what never ran: the printed Reaction below.
  * The four printed triggers are one question each, asked of the owner when the marked creature does the thing, all read
    by one function (:func:`_printed_trigger`): committed recovery (a HEALING_APPLIED that actually raised its Hit Points,
    so a heal that was prevented or that changed nothing is not a recovery), its own teleport, Invisibility it gains from
    anyone at all, and the Disengage action it takes. "Regains HP" and "turns Invisible" are states of the *target*, so who
    brings them about does not matter: an ally's or an item's Invisibility counts, and so does an ally's healing.
  * "The first time" is remembered from the recorded events (the mark's applied_sequence and the four replayed trigger
    event types), not from a field on the mark, so the same answer holds before and after a table commit and reload.
  * Who decides the one Reaction is read from the mark owner's own recorded control mode
    (``combat/tabletop_service.py`` MANUAL_MODES via ``needle.answerable``), not from whether a reaction provider happens
    to be installed: a provider also answers for AI fighters, so an AI owner keeps its first opportunity with one at the
    table, and a player's owner is never spent for even with no provider. A player whose trigger carries no action of
    theirs in flight is asked nowhere (there is no supported checkpoint outside an action), so the mark's one trigger
    passes unspent and the note says so -- including that the *first time* is then gone, because the trigger event is
    recorded either way and the window is read back from the log. That loss is a lock-round limitation, not an answer.
  * The Reaction costs the owner nothing else and is the ordinary shared admission (typed_reactions.can_use_reaction /
    open_reaction), so a spent Reaction, Incapacitation or a reaction-denied condition all still stop it.
  * The swing is the owner's own compiled melee axe attack, run through the executor with reaction_attack (the same shape a
    prepared Counterstrike uses), so its weapon damage, dice, criticals and defenses are the shipped ones. Only a mark within
    the axe's reach qualifies; the printed "legal range of a lodged or thrown axe line you control" has no line on this table
    and stays with the GM (the remaining rider in the typed record).
  * Using the Reaction does not end the mark: it still lasts until the start of your next turn and still counts as Bite for
    the owner's Axes talents. Only its one trigger is spent.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import hook, note
from .needle import CHOICE, answerable, ask, checkpoint_id

TALENT = "TAL_AXES_EXECUTION_MARK"
MARK = "Execution Mark"
BITE = "Bite"
INVISIBLE = ("condition:typed.invisible", "condition:core.invisible")
DISENGAGE = "system:combat.disengage"
AXE_WORDS = ("axe", "hatchet", "francisca", "tomahawk")


# ------------------------------------------------------------------------------------------------- ownership
def _owned(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` owns Execution Mark (never another character's).

    The shared compiled-ownership query (combat/alternative_payments.owned) answers from the sealed bundle: the talent's
    own reaction/passive rows, its action ids, or a "+ Execution Mark" rider variant. Without it every hook below returns
    early, so no other character and no old saved fight changes.
    """
    from ..alternative_payments import owned

    return owned(engine, actor, TALENT)


def _marked(engine: Any, creature: Any) -> list[tuple[str, Any]]:
    """(instance id, owner) for each Execution Mark on ``creature``, its own or another's."""
    from ..typed_executor import mark_condition_id

    out = []
    for instance, condition in sorted(getattr(creature, "conditions", {}).items()):
        if condition.condition_id == mark_condition_id(MARK, condition.source_actor_id or "") and \
                _owned(engine, engine.state.actors.get(condition.source_actor_id or "")):
            out.append((instance, engine.state.actors[condition.source_actor_id]))
    return [(instance, owner) for instance, owner in out if owner is not None and owner.active]


# ------------------------------------------------------------------------------------------------- the four triggers
def _printed_trigger(engine: Any, event_type: str, kwargs: dict[str, Any]) -> tuple[Any, str] | None:
    """(creature, what it did) for the four printed triggers, from one place.

    "The first time before the mark ends that the target regains HP, teleports, turns Invisible, or takes the
    Disengage action" is one sentence, so it is read in one place and used twice: by the live hooks below, and
    by :func:`_already_triggered` when a reloaded fight asks whether its first trigger has been seen.

    Each branch is the printed condition, not a near miss:
      * "regains HP" reads committed healing (HEALING_APPLIED, ``after`` above ``before``), so a heal that was
        offered and then prevented -- or that a creature at full Hit Points did not actually regain -- is not
        a recovery.  The mark does not ask *who* healed it: the printed line is about the marked creature's
        Hit Points, so a heal from an ally, a stranger or an item reaches the mark exactly as a self-heal does.
      * "turns Invisible" is the creature becoming invisible, whoever granted it: an ally's or an item's
        Invisibility turns the marked creature Invisible, and the mark does not care who cast it.
      * "teleports" is the creature's own teleport. A dragged or forced move is not a teleport (the engine
        records those with ``forced`` set and no ``teleport``), and the printed line is the target's own act.
      * "takes the Disengage action" is the shipped Disengage intent, as an action or as a move.
    """
    payload = kwargs.get("payload") or {}
    targets = tuple(kwargs.get("target_ids") or ())
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if event_type == "HEALING_APPLIED" and int(payload.get("after") or 0) > int(payload.get("before") or 0):
        creature = engine.state.actors.get(targets[0]) if targets else actor
        return (creature, "regains Hit Points") if creature is not None else None
    creature = engine.state.actors.get(targets[0]) if targets else None
    if creature is None:
        return None
    if event_type == "MOVEMENT_COMMITTED" and payload.get("teleport") and not payload.get("forced") \
            and kwargs.get("actor_id") == creature.entity_id:
        return creature, "teleports"
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "") in INVISIBLE:
        return creature, "turns Invisible"  # granted by anyone: the marked creature is the one that turns Invisible
    if event_type == "INTENT_ACCEPTED" and str(kwargs.get("source_definition_id") or "") == DISENGAGE \
            and kwargs.get("actor_id") == creature.entity_id and str(payload.get("kind")) in ("ACTION", "MOVE"):
        return creature, "takes the Disengage action"
    return None


@hook("event", nested=True)
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The four printed triggers, all read by :func:`_printed_trigger`."""
    found = _printed_trigger(engine, event_type, kwargs)
    if found is not None:
        _offer(engine, found[0], found[1], _event_sequence(engine, kwargs))


def _event_sequence(engine: Any, kwargs: dict[str, Any]) -> int:
    """The recorded sequence number of the very event being answered.

    "The first time" excludes the trigger that is happening *now*, so the ceiling has to be this
    event's own recorded identity.  ``event_sequence`` is the mutable log tail: a Ready response
    (combat/prepared_actions.py) runs before extension delivery and appends its own events, which
    pushes the tail past the trigger and makes it look already spent.  The engine preserves the exact
    recorded Event in ``kwargs["originating_event"]`` for exactly this attribution
    (combat/ext/__init__.py, "use the Event's source/sequence, never the mutable log tail"); the
    mutable tail is only the fallback for an old engine that does not supply it.
    """
    recorded = getattr(kwargs.get("originating_event"), "sequence", None)
    if recorded is not None:
        return int(recorded)
    return int(getattr(engine.state, "event_sequence", 0) or 0)


def _already_triggered(engine: Any, creature: Any, mark: Any, before: int = 0) -> bool:
    """Whether this mark's one printed trigger already happened between its placement and ``before``.

    Read back from the recorded events rather than stored on the mark, so it is the same answer before and
    after a table commit and reload: the four triggers are all replayed event types, and the mark's
    ``applied_sequence`` says when its window opened.  ``before`` is the sequence of the event being
    answered -- the trigger that is happening *now* is not yet a spent trigger, so it is excluded.
    The mark's other printed line ("counts as Bite for your Axes talents") is a separate condition placed
    by rider lane 3 and is never touched here.
    """
    opened = int(getattr(mark, "applied_sequence", 0) or 0)
    ceiling = int(before or 0)
    for event in engine.events:
        sequence = int(getattr(event, "sequence", 0) or 0)
        if sequence <= opened or (ceiling and sequence >= ceiling):
            continue
        found = _printed_trigger(engine, event.event_type, {
            "payload": event.payload, "target_ids": event.target_ids, "actor_id": event.actor_id,
            "source_definition_id": event.source_definition_id})
        if found is not None and found[0] is creature:
            return True
    return False


# ------------------------------------------------------------------------------------------------- the Reaction
def _offer(engine: Any, creature: Any, what: str, before: int = 0) -> None:
    """Ask the marked creature's own Execution Mark owner for the one Reaction the printed text allows."""
    from ..typed_reactions import can_use_reaction, open_reaction

    if creature is None or not getattr(creature, "active", False):
        return
    # The in-flight intent, when there is one.  A turn-boundary or zone recovery has none, and the
    # choice transport can only put a question to somebody while an intent is in flight, so
    # :func:`ask` would answer the owner's own Reaction for them (see :func:`answerable` below).
    intent = getattr(engine, "_active_intent", None)
    for instance, owner in _marked(engine, creature):
        mark = creature.conditions.get(instance)
        if mark is None:
            continue
        if _already_triggered(engine, creature, mark, before):
            continue  # "The first time": *this* mark's one trigger has already come and gone
        row = {"feature_id": TALENT, "name": "Execution Mark", "reaction": True,
               "target_ids": (creature.entity_id,), "effects": [], "numbers": {}}
        if not can_use_reaction(engine, owner, creature, row):
            continue
        attack = _axe_attack(engine, owner)
        if attack is None or engine._distance_actor_to_actor(owner, creature) > int(attack.reach_ft or attack.range_ft or 5):
            continue  # "within your weapon's reach": the printed axe-line range stays with the GM
        reach = int(attack.reach_ft or attack.range_ft or 5)
        manual = answerable(engine, owner)
        if intent is None and manual:
            # This owner's own Reaction is a player's to decide, and this trigger carries no action of
            # theirs to attach the question to, so there is no supported checkpoint to put it at.
            # Choosing for them would spend their own Reaction behind their back, so the mark's one
            # trigger passes unspent and says so.  (Their recorded control mode -- not the mere
            # presence of a provider, which also answers for AI fighters -- is what says they are
            # a player's; see needle.answerable.)
            note(engine, TALENT, owner,
                 f"Execution Mark: {creature.display_name} {what}, but no action of yours was in progress to ask about, "
                 f"so this mark's one Reaction could not be offered and its first time is spent. Your Reaction itself is "
                 f"untouched, and the mark still lasts until the start of your next turn.")
            continue
        picked = ask(engine, intent, checkpoint_id(engine, "AXES_EXECUTION_MARK", owner.entity_id, creature.entity_id), owner,
                     CHOICE + "axes_execution_mark", [attack.source_definition_id],
                     labels={attack.source_definition_id: f"Attack {creature.display_name} with {attack.display_name}"},
                     preferred=[attack.source_definition_id], maximum=1, allow_decline=True,
                     prompt=f"Execution Mark: {creature.display_name} {what}. Spend your Reaction to strike it with "
                            f"{attack.display_name} (reach {reach} feet).", name="Execution Mark",
                     feature_id=TALENT, target_id=creature.entity_id,
                     prompt_context=_trigger_context(engine))
        if not picked:
            continue
        checkpoint = checkpoint_id(engine, "AXES_EXECUTION_MARK", owner.entity_id, creature.entity_id)
        with activation(engine, owner, TALENT):
            open_reaction(engine, row, owner, (creature.entity_id,), checkpoint)  # spends the Reaction and opens its window
            if not owner.active or not creature.active:
                continue
            _strike(engine, owner, attack, creature, intent)
            engine._append_event("REACTION_RESOLVED", TALENT, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"reaction": TALENT, "log": f"Execution Mark: {owner.display_name} strikes "
                                                                      f"{creature.display_name} with {attack.display_name} as it {what}."})
        # The mark itself is left alone: it still "lasts until the start of your next turn" and still "counts as Bite
        # for your Axes talents". Its one trigger is spent, and :func:`_already_triggered` is what remembers that.
        # The loop continues: each mark is its own "first time", so a second axe fighter's freshly placed mark
        # still gets its own offer.


def _trigger_context(engine: Any) -> dict[str, str]:
    """Display-only metadata naming the action this free trigger rode, so the prompt can name it."""
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return {}
    action = engine.action_catalog.get(getattr(intent, "source_definition_id", "") or "")
    return {"source_definition_id": getattr(action, "source_definition_id", "") or "",
            "action_name": getattr(action, "display_name", "") or ""}


def _axe_attack(engine: Any, owner: Any) -> Any:
    """The owner's own strongest compiled melee axe attack (its own weapon, dice and bonuses)."""
    def melee(action: Any) -> bool:
        typed = (action.parameters or {}).get("typed") or {}
        return bool(typed.get("weapon")) and not typed.get("range_ft") and action.target_kind == "HOSTILE_ENTITY" \
            and action.resolution_kind == "TYPED" and any(row.get("type") == "attack" for row in typed.get("effects") or [])

    def axe(action: Any) -> bool:
        return any(word in str(action.display_name).lower() for word in AXE_WORDS)

    rows = [action for action in engine.action_catalog.values()
            if action.owner_id == owner.entity_id and melee(action) and axe(action)
            and "#" not in action.source_definition_id and ".object_attack." not in action.source_definition_id
            and not str(action.source_definition_id).endswith(".pickup")]
    return max(rows, key=lambda action: (int((action.parameters or {}).get("expected_damage") or 0),
                                         action.source_definition_id), default=None)


def _strike(engine: Any, owner: Any, attack: Any, creature: Any, intent: Any) -> None:
    """The owner's axe attack through the executor's own attack path (the prepared-Counterstrike shape)."""
    from ..typed_executor import Context, run_effects

    typed = dict((attack.parameters or {}).get("typed") or {})
    reach = int(attack.reach_ft or attack.range_ft or 5)
    typed.update(reaction_attack=True, reaction_range_ft=reach, range_ft=None,
                 numbers={**dict(typed.get("numbers") or {}),
                          "attack_bonus": int((typed.get("numbers") or {}).get("attack_bonus") or 0)})
    effects = [{**row, "deferred": False} for row in typed.get("effects") or [] if row.get("type") == "attack"]
    run_effects(Context(engine, owner, attack, intent, typed, [creature], creature), effects)
