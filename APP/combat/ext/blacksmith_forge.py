"""The Blacksmith sphere's Forge Mark chassis and the Forge Responses that had nothing running (auto17, round 25).

Owner text. The sphere's own "### Forge Marks" section (printed with the sphere, not as a mechanic of its own,
APP/authority/typed_mechanics/rules_text.json holds the sphere's base abilities):

    Unless a talent says otherwise:
    a workpiece can hold a number of Forge Marks from you equal to your Proficiency Bonus;
    a Forge Mark lasts for 1 minute during action scenes;
    ...
    A workpiece cannot exceed your normal Forge Mark limit.        (Hammer the Mark)

Neither half ran. combat/typed_executor.py's block_mark keys one condition instance per mark name, so a second
Hammer the Mark on the same workpiece refreshed that instance and changed nothing -- the printed "Place 1 Forge
Mark on it" never accumulated -- and the compiled rows carry ``duration {"kind": "until_removed"}``, so a mark
lasted for the whole fight instead of one minute. Every Forge Mark cost in the sphere (Set Edge, Fit Armor,
Tempering Sequence, Hammer Rebuke, Quench in Breath, Seven-Hammer Revision) therefore paid the same one permanent
mark, over and over.

This module owns the chassis through the general mark seams combat/ext/__init__.py documents -- mark_apply
(place/refresh with the printed limit and the printed one-minute clock), mark_consume (spending one mark takes
one off the count) and mark_spent (Quench in Breath's "when you spend a Forge Mark") -- and adds the printed Forge
Responses that compiled to nothing at all:

  Tempering Sequence    (CL 10+) "When a workpiece has at least 3 Forge Marks from you, you may spend all of them
                        to perform a Tempering Sequence. Choose one: Hardening / Softening / Purifying / Awakening."
  Field Repair          "When a creature within reach has a weapon, shield, armor, tool, or object damaged by an
                        attack, hazard, or failed check, use your Reaction to Set the Workpiece to that object and
                        place 1 Forge Mark on it."  (+ the printed CL 5 Close-the-Crack extension for 1 CP)
  Seven-Hammer Revision "spend 1 Forge Mark to revise the strike. Reroll a number of damage dice up to your
                        Proficiency Bonus and use the new rolls. ... also add your Intelligence modifier"

Every hook returns early unless the actor owns the talent it is about (a combat/rules/feature_blocks.d/blacksmith.json
row, or its own compiled catalog row for Hammer the Mark), so a character without these records sees no new
condition, no new button and no new event.

Shared with combat/ext/ironclad_blacksmith.py (Set Edge / Fit Armor, the Forge-Fitted tempers): ``held_condition``,
the read-only "which stored condition does this creature carry" query both modules need, because
ActorState.conditions is keyed by instance id and a plain dict lookup silently finds nothing.

auto17f1 (review round) corrected four things here, all against the printed text and all found by this lane's own
table tests:

  * the printed one-minute life was measured from the NEWEST mark, so a mark placed later kept an older one alive.
    The count now ends one minute after the placement that started it (:func:`set_marks`).
  * "When you or an ally within 30 feet" was measured with a hand-counted grid distance that is longer than the
    map's own, so a smith across the diagonal of the ally's square fell outside the printed range. It now reads the
    shared measure, combat/action_geometry.distance.
  * Seven-Hammer Revision was priced with the STRIKER's Proficiency Bonus and key-ability modifier and gave the
    Intelligence modifier on every revision, dropping "If the workpiece is one you personally forged or prepared
    during the current day". Both numbers are the smith's now, and the modifier waits for the fighter's own toggle.
  * the revision answered ANY damage packet, including an unarmed strike, which is not one of the printed "weapon,
    tool, object, or construct attack" (:func:`printed_workpiece_attack`).

And one printed choice was missing: the Tempering Sequence's "Choose one: Hardening / Softening / Purifying /
Awakening" offered only three buttons.

auto17r1f1 (second review round) closed four more, again against the printed text:

  * the counted mark shared ONE deadline, so a mark placed later lost the minutes between its own placement and the
    oldest mark's (:func:`set_marks` now stores one deadline per mark and :func:`forge_mark_expires_one_at_a_time`
    retires them one at a time). A fight saved with the single ``since_round``/``since_slot`` pair keeps exactly the
    deadline it was saved with (:func:`stored_deadlines`).
  * the personal-work declaration was one-way and lasted the whole fight. It is now two buttons -- declare and end
    the declaration -- and it has a defined reset: it lapses when the smith's last Forge Mark is spent or expires,
    because there is then no marked workpiece for it to describe. Its AI answer is stated rather than left to the
    harness (:data:`AI_DECLARES_PERSONAL_WORK`).
  * a Forge Mark the smith spent on someone else's strike was announced with the STRIKER's context, so Quench in
    Breath asked the ally whether the ally owned the talent and priced the reduction with the ally's Proficiency
    Bonus (:func:`spend_marks` now announces the spending smith, as typed_executor.block_spend_mark does).

auto17r2f1 (third review round) split the row's count in two, because carrying an undated save over as one number
could not say which marks had a clock of their own:

  * the mark a player places AFTER resuming a save whose row this module cannot date now gets its own printed minute.
    Before, the whole count was written back undated on the save's expiry, so a new mark inherited a row that never
    came due -- "a Forge Mark lasts for 1 minute" silently did not apply to it (:func:`set_marks`,
    :func:`stored_populations`). The marks the save was already holding keep their own expiry, and the row expires
    at whichever of the two is sooner.

auto17r4f2 (review round) made that last promise true. A row counting both populations has ONE ``expires_on``, and
the engine's own expiry sweep reads only that name, so the dated minute had taken the row over and the save's own
expiry -- an ``END_OF_TURN_AT`` name, or any turn-based name a fight made for itself -- was left sitting in the row's
data with nothing reading it. A save whose marks were due to go at the smith's seventh turn, resumed and then marked
again at round 3, kept spending both of them ten rounds past that turn. :func:`soonest_expiry` hands the row to the
engine on the clock that comes due first wherever the two names can be ordered, and
:func:`retire_saved_forge_mark_expiries` reads the saved expiry at the turn boundaries the engine already sweeps at,
so the earlier of the two always ends first whichever name the row is parked on. Both are inert for a row with no
undated mark in it, and for every creature but the holders of a Forge Mark row.

MGR-T14 (Incarnation of the Living Forge, "your Blacksmith Temporary Tempers may last for 10 minutes
instead of 1 minute"): the printed "may" is the owner's, so a Tempering Sequence performed while the
Incarnation stands (:func:`_incarnated`) puts the lifetime question through the shared needle choice
transport (:func:`_temper`). Both printed lifetimes stay in the menu, the one-minute option is the
default for a smith nobody answers for, and the built-in AI takes the printed longer one the way it
takes Two-Beat Temper's "place two". The ten-minute choice clocks on the public
``typed_executor.clock_expiry(engine, "minutes", 10)`` round token, so a cold reload keeps it and the
Incarnation's own one-minute condition ends on its own clock without truncating the temper. A smith
who does not own the Incarnation is never asked and keeps the chassis minute; the Incarnation itself,
its other benefits and every other forge state are untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

BLOCK = "blacksmith_forge"
FORGE_MARK = "Forge Mark"
ONE_MINUTE = "one_minute"

QUENCH_BREATH = "condition:typed.quench_in_breath"
SOFTENED = "condition:typed.tempering_softened"
HARDENED = "condition:typed.tempering_hardened"
SPIRIT_SIGN = "condition:typed.item_spirit_sign"
SEVEN_HAMMER_KEY = "seven_hammer_revision"
PERSONAL_WORK = "condition:typed.seven_hammer_personal_work"

TEMPERING_SEQUENCE = "tianxia.talent.blacksmith.tempering_sequence"
FIELD_REPAIR = "tianxia.talent.blacksmith.field_repair"
SEVEN_HAMMER_REVISION = "tianxia.talent.blacksmith.seven_hammer_revision"
QUENCH_IN_BREATH = "tianxia.talent.blacksmith.quench_in_breath"
INCARNATION = "tianxia.talent.blacksmith.incarnation_of_the_living_forge"
TWO_BEAT = "tianxia.talent.blacksmith.two_beat_temper"
TWO_BEAT_LOCK = "condition:typed.blacksmith_two_beat_lock."
TWO_BEAT_SCENE = "condition:typed.blacksmith_two_beat_scene"
WORKSHOP = "condition:typed.blacksmith_workshop"
FURNACE_DISCIPLINE = "tianxia.talent.blacksmith.furnace_discipline"
HELD_TOOL = "condition:typed.blacksmith_held_tool"

# Each talent that gets a block of its own, so a hook can ask "does this fighter have it?" without reading the catalog.
BLOCKS = {
    TEMPERING_SEQUENCE: "tempering_sequence",
    FIELD_REPAIR: "field_repair",
    SEVEN_HAMMER_REVISION: SEVEN_HAMMER_KEY,
    QUENCH_IN_BREATH: "quench_in_breath",
    TWO_BEAT: "two_beat_temper",
    FURNACE_DISCIPLINE: "furnace_discipline",
}


@hook("compile_block")
def forge_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The inert ownership rows this module's hooks read, one per talent that gets a block of its own."""
    if block != BLOCK or not spec.get("kind"):
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}]


def owns(engine: Any, actor: Any, kind: str) -> bool:
    """Whether this fighter owns the record a hook is about. Every hook here asks first, so a character without
    the record sees no condition, no button and no event."""
    from .passive_rows import row_of

    if kind == "forge_marks":
        return _is_smith(engine, actor)
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


def _is_smith(engine: Any, actor: Any) -> bool:
    """A Blacksmith, read from its own compiled catalog. Hammer the Mark cannot carry a compile_block row: the
    compiler skips a feature a plug-in claims (typed_reactions.compile_blocks -> factory_compiler's `if mechanic_id
    in blocks["automated"]: continue`) and Hammer the Mark is an ordinary Bonus Action, so claiming it would delete
    the button. Its catalog row is the ownership signal instead."""
    catalog = getattr(engine, "action_catalog", {}) or {}
    return any(str(catalog[aid].source_definition_id if aid in catalog else aid).endswith("BLACKSMITH_BASE_HAMMER_THE_MARK")
               for aid in (getattr(actor, "action_ids", ()) or ()))


def mark_row(actor: Any, owner_id: str, *, item_key: str = "") -> Any:
    """The one Forge Mark instance this owner keeps on this workpiece, and where its count lives. Conditions are
    keyed by instance id, so a stored condition is found by its ``condition_id``."""
    from ..typed_executor import mark_condition_id

    return held_condition(actor, item_mark_id(owner_id, item_key))


def item_mark_id(owner_id: str, item_key: str = "") -> str:
    """Distinct per-smith, per-inventory-item mark identity; empty key retains the actor chassis."""
    from ..typed_executor import mark_condition_id
    import json
    base = mark_condition_id(FORGE_MARK, owner_id)
    return base + ".item:" + json.dumps(item_key, ensure_ascii=True) if item_key else base


def item_lock_id(owner_id: str, item_key: str = "") -> str:
    """Two-Beat's lock uses the same exact workpiece identity as its marks."""
    import json
    base = TWO_BEAT_LOCK + owner_id
    return base + '.item:' + json.dumps(item_key, ensure_ascii=True) if item_key else base


def set_marks(engine: Any, owner: Any, subject: Any, number: int, source: str, *, item_key: str = "") -> int:
    """Store exactly ``number`` Forge Marks from this owner on this workpiece, as ONE condition instance.

    ``engine._apply_condition`` mints a fresh instance id every call (``condition-instance:<id>:<actor>:<seq>``), so
    counting marks by re-applying the same condition leaves one instance per placement and every reader that finds
    "the" mark by condition id sees whichever was stored first. The instance is therefore removed and re-applied with
    the new count, the same way combat/ext/verdant_chassis.py stores its counted Growth Marks.

    "a Forge Mark lasts for 1 minute during action scenes" is measured per mark, so the row keeps one deadline per
    mark it counts (:func:`stored_deadlines`): a placement adds a deadline of its own and never touches the ones
    already standing, a spend retires the deadline that would have come first, and the instance's own expiry is the
    soonest of them -- which is what brings the engine to :func:`forge_mark_expires_one_at_a_time` at that mark's
    minute. ``expires_on`` therefore stays a name the engine removes and no mark outlives its own printed minute.

    A mark carried over from a save this module cannot date is counted separately (:func:`stored_populations`) and
    keeps the expiry that save was saved with, so the two populations are never confused: every placement made here
    and now gets its own printed minute, and only the marks a player already paid for stay on the save's terms.

    Returns how many marks were added (0 when the workpiece is already at the printed limit).
    """
    if subject is None:
        return 0
    if not subject.active:
        # Item marks live on the original inventory owner, even after defeat.
        # Only a real item still carried by a living bearer remains work/payable;
        # ordinary actor marks retain their active-subject admission rule.
        from ..item_uses import carried_item
        if not item_key or carried_item(engine, subject.entity_id, item_key) is None:
            return 0
    # Two-Beat locks only this smith's work on this holder until their next turn.
    # All placement paths (including Field Repair) share this check; old saves
    # without the new lock condition retain their placement behavior.
    if number > 0 and held_condition(subject, item_lock_id(owner.entity_id, item_key)) is not None:
        return 0
    from .rider_support import remove_instance

    old = mark_row(subject, owner.entity_id, item_key=item_key)
    old_data = dict(old.data or {}) if old is not None else {}
    held = int(old_data.get("count") or 0)
    ceiling = limit(engine, owner)
    wanted = min(ceiling, max(held, held + number)) if number > 0 else held + number
    wanted = min(max(wanted, 0), ceiling)
    # The two populations this row is counting, before the old instance is taken off.
    deadlines, undated, undated_until = stored_populations(old_data, old.expires_on if old is not None else None)
    if old is not None:
        remove_instance(engine, subject, old.instance_id, source)
    if wanted <= 0:
        # The row is already off, so a scan of what is left is exact. Another holder may still stand a mark from
        # this smith, and the printed answer is about any workpiece of theirs (:func:`owner_has_marks`).
        if held > 0 and not owner_has_marks(engine, owner):
            lapse_personal_work(engine, owner, source)
        return wanted - held
    now = (int(engine.state.round_number), int(engine.state.current_slot_index))
    if number > 0:
        # Every mark placed by this call dates itself, whichever population the ones already there came from.
        deadlines = sorted(deadlines + [now] * (wanted - held))
    else:
        for _ in range(held - wanted):
            # A spend retires the mark that would have gone first: the soonest dated one, or else one of the marks
            # the save was already holding, which have no minute to order them by.
            if deadlines:
                deadlines.pop(0)
            elif undated:
                undated -= 1
    store_marks(engine, subject, owner.entity_id,
                old.source_definition_id if old is not None else source, deadlines, ceiling,
                undated=undated, undated_until=undated_until, item_key=item_key)
    return wanted - held


def stored_deadlines(data: dict[str, Any] | None, count: int | None = None,
                     expires_on: str | None = None) -> list[tuple[int, int]]:
    """This Forge Mark row's per-mark deadlines, oldest first, as ``(round, slot)`` pairs.

    A row written before the per-mark shape (``deadlines``) carries the single ``since_round``/``since_slot`` pair
    that started its clock: every mark in it shared that one minute then, so every mark is given it back here and a
    saved fight keeps exactly the deadline it was saved with.

    A row written before that (auto17's own counted mark) stored a count and a label and nothing else, and its
    ``expires_on`` is the printed one-minute clock name itself -- which is the same shared minute seen from the
    other end, so :func:`deadline_of` runs it back to the placement the save was made at and every mark gets it.
    Reading it this way keeps the expiry the save was saved with, instead of starting a new minute for marks a
    player already paid for.

    A row whose expiry is not one of this module's clock names is returned as no deadlines at all;
    :func:`stored_populations` then counts every mark in it as undated and hands that expiry back untouched rather
    than inventing a minute for it.
    """
    raw = (data or {}).get("deadlines")
    pairs: list[tuple[int, int]] = []
    for entry in raw if isinstance(raw, list) else ():
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and all(type(part) is int for part in entry):
            pairs.append((int(entry[0]), int(entry[1])))
    if not pairs:
        round_number, slot_index = (data or {}).get("since_round"), (data or {}).get("since_slot")
        if type(round_number) is int and type(slot_index) is int:
            return [(round_number, slot_index)] * max(1, int((data or {}).get("count") if count is None else count))
        from . import effect_durations

        ended = effect_durations.parse_round(expires_on)
        if ended is not None:
            from ..typed_executor import duration_round_count

            rounds = duration_round_count(ONE_MINUTE) or 10
            return [(int(ended[0]) - rounds, int(ended[1]))] * max(1, int((data or {}).get("count")
                                                                        if count is None else count))
    return sorted(pairs)


def stored_populations(data: dict[str, Any] | None, expires_on: str | None = None
                       ) -> tuple[list[tuple[int, int]], int, str]:
    """This Forge Mark row's two populations, as ``(dated deadlines oldest first, undated count, their expiry)``.

    A dated mark is one whose own placement minute this module recorded, so it ends on the printed "a Forge Mark
    lasts for 1 minute" (:func:`stored_deadlines`). An undated mark is one a resumed save was already holding on an
    expiry this module cannot date -- ``UNTIL_REMOVED``, or any name of a fight's own making -- and it keeps that
    expiry verbatim, because no mark a player already paid for is dropped, none is renewed, and the fight still ends
    when that save said it would. The two are counted apart, so a mark placed now always gets its own minute even
    when it shares a row with marks from such a save, and spending knows which population it is retiring.

    The third value is the name the undated marks ride on. A row that carries both populations expires at the dated
    marks' soonest minute instead (the undated expiry is stored beside the count, not in ``expires_on``, or the two
    could not both be true of one instance), so it has to be kept to hand back when the dated ones have gone.
    """
    row = data or {}
    total = int(row.get("count") or 0)
    undated = min(max(int(row.get("undated") or 0), 0), total)
    until = str(row.get("undated_until") or expires_on or "UNTIL_REMOVED")
    if total - undated <= 0:
        return [], undated, until
    deadlines = stored_deadlines(row, total - undated, expires_on)
    if not deadlines:
        # A row with a count and an expiry that is not one of this module's clock names: every mark in it is one
        # this module cannot date, and the save's own expiry is all it has to say when they end.
        return [], total, until
    return deadlines, undated, until


def store_marks(engine: Any, subject: Any, owner_id: str, source: str, deadlines: list[tuple[int, int]],
                ceiling: int, *, count: int | None = None, undated: int = 0,
                undated_until: str | None = None, item_key: str = "") -> None:
    """Write the counted Forge Mark row for ``owner_id`` with one deadline per dated mark, expiring at the soonest.

    Only integers and strings go into fight state (``count``, ``undated``, ``since_round``, ``since_slot`` and a list
    of integer pairs), so the row survives a table commit and reload unchanged.

    ``undated`` is for marks carried over from a resumed save whose row kept no per-mark clock this module can read
    (see :func:`stored_populations`): that many of the count hold no ``deadlines`` entry, and they keep
    ``undated_until`` -- the expiry that save was saved with -- for as long as they stand. Dated and undated marks are
    counted separately and both are integers, so a save round-trips either way. An instance carrying both is parked
    on whichever of the two clocks comes due first (:func:`soonest_expiry`) and hands the other one back afterwards,
    so the earlier of the two ends first whichever it happens to be.
    """
    from ..typed_executor import mark_condition_id

    dated = sorted((int(round_number), int(slot_index)) for round_number, slot_index in deadlines)
    undated = max(0, int(undated))
    wanted = int(count) if count is not None else undated + len(dated)
    data: dict[str, Any] = {"count": wanted, "undated": undated,
                            "label": f"Forge Mark{'s' if wanted > 1 else ''} ({wanted} of {ceiling})"}
    if item_key:
        data['item_key'] = item_key
        from ..carry import carrying_of, item_of
        item = item_of(carrying_of(engine, subject.entity_id), key=item_key)
        if item:
            data['label'] = f"Forge Mark{'s' if wanted > 1 else ''} on {item['name']} ({wanted} of {ceiling}; each lasts 1 minute)"
    if dated:
        data["since_round"], data["since_slot"] = dated[0]
        data["deadlines"] = [[round_number, slot_index] for round_number, slot_index in dated]
    if undated:
        data["undated_until"] = str(undated_until or "UNTIL_REMOVED")
    # One instance carries one ``expires_on``, so a row counting both populations is parked on whichever of the two
    # clocks comes due first and hands the other back afterwards. Parking it on the dated minute alone is what hid a
    # save's own earlier expiry behind a minute that had not started yet.
    engine._apply_condition(subject, item_mark_id(owner_id, item_key), source, owner_id,
                            expires_on=soonest_expiry(engine, data.get("undated_until"),
                                                      clock_token(*dated[0]) if dated else None),
                            data=data)


def clock_token(round_number: int, slot_index: int) -> str:
    """The expiry name for the end of the printed one-minute Forge Mark life counted from one placement."""
    from ..typed_executor import duration_round_count
    from . import effect_durations

    rounds = duration_round_count(ONE_MINUTE) or 10
    return f"{effect_durations.SLOT_AT}:{int(round_number) + rounds}:{int(slot_index)}"


def soonest_expiry(engine: Any, saved_until: str | None, dated_token: str | None, *,
                   ending_id: str | None = None) -> str:
    """Which of a Forge Mark row's two clocks the engine should bring the row down on first.

    A row counting both populations has one ``expires_on``, so it can only be parked on the clock that comes due
    first; the other is kept beside the count as ``undated_until`` and handed back when the parked one has been
    swept (:func:`forge_mark_expires_one_at_a_time`, :func:`retire_saved_forge_mark_expiries}). Which is which has
    to be settled here, because the engine's sweep reads ``expires_on`` and nothing else.

    Three answers, and the two families of name the engine removes are ordered exactly wherever they can be:

      * a saved expiry that has already come due wins outright. An expired mark must not be parked behind a minute
        that is still running, or the save's own clock is never read at all;
      * two round names are the sooner of the two ``(round, slot)`` pairs;
      * otherwise the dated minute stands. A turn name (``END_OF_TURN_AT:<creature>:<n>``) says how many of ONE
        creature's turns to wait for and a round name says which round and slot, so the two cannot be ordered
        without predicting initiative and whether that creature is still acting. Nothing is lost by guessing here:
        :func:`retire_saved_forge_mark_expiries` reads the saved expiry at the same checkpoints the engine sweeps
        at, so the earlier of the two ends first whichever name is returned.

    A name the engine never brings due (``UNTIL_REMOVED``) is never due, so it loses to any dated minute and the
    row keeps standing on the save's terms -- the compatibility policy for historical saves, unchanged.

    The first answer deliberately asks :func:`effect_durations.due` and not :func:`effect_durations.engine_due`. A
    saved name in the engine's OWN family (``END_OF_SOURCE_TURN_AT:<n>`` and the two "next turn" names) is not
    something that can be read at all here: those names are due at one specific kind of turn boundary, and this is
    called from a placement in the middle of a turn, with no boundary to read them against. Parking the row on one
    would hand the whole row -- the mark being placed right now along with the save's -- to the engine's native
    sweep, which takes it at that boundary and takes the fresh mark with it. So a saved name in that family is left
    to :func:`retire_saved_forge_mark_expiries`, which reads it at the boundary it names: the save's marks go first,
    on their own clock, and the mark placed now keeps the full minute it was just given.
    """
    from . import effect_durations

    saved = str(saved_until or "") or None
    if not dated_token:
        return saved or "UNTIL_REMOVED"
    if saved is None:
        return str(dated_token)
    if effect_durations.due(engine, saved, ending_id):
        return saved
    pair = (effect_durations.parse_round(saved), effect_durations.parse_round(dated_token))
    if all(pair):
        return saved if pair[0] <= pair[1] else str(dated_token)
    return str(dated_token)


@hook("effect_expiring")
def forge_mark_expires_one_at_a_time(engine: Any, holder: Any, row: Any) -> None:
    """"a Forge Mark lasts for 1 minute" per mark: the instance's expiry is its soonest deadline, so the engine
    brings it here at that mark's minute. The marks whose own minute has come are retired, and if any are left the
    row is written back with the next deadline; when the last one goes the engine's own removal takes the row, and
    the smith's personal-work declaration lapses with it (:func:`lapse_personal_work`).

    Marks carried over from a save this module cannot date (:func:`stored_populations`) keep the expiry that save was
    saved with, which is read here as well: whichever population's own clock has come is retired, and a population
    still standing is handed back on its own terms. That is what lets a save whose marks were due to go at the
    smith's seventh turn end there even though this row was parked on a minute that had not started yet."""
    owner = engine.state.actors.get(getattr(row, "source_actor_id", None))
    if owner is None or (not holder.active and not (getattr(row, 'data', None) or {}).get('item_key')):
        return
    from ..typed_executor import mark_condition_id

    # effect_expiring also receives modifiers, which have no condition data.
    if getattr(row, "condition_id", None) != item_mark_id(owner.entity_id, (getattr(row, 'data', None) or {}).get('item_key', '')):
        return
    if int((row.data or {}).get("count") or 0) <= 0:
        return
    deadlines, undated, undated_until = stored_populations(row.data, row.expires_on)
    if not deadlines:
        return  # nothing this module dated is waiting; the row stands on the expiry its save was given
    now = (int(engine.state.round_number), int(engine.state.current_slot_index))
    left = [pair for pair in deadlines if deadline_of(pair) > now]
    # The undated population keeps the expiry its save was saved with, which is not always the name this row was
    # parked on, so it is read here too: the earlier of the two has to end first whichever one the sweep brought us
    # to. ``effect_durations.due`` is called without an ending creature because the hook is not given one, so a
    # save whose name waits for the turn ending right now is left to
    # :func:`retire_saved_forge_mark_expiries` on that same boundary, which is passed the ending creature. A saved
    # name in the engine's own family is left there too, and for the same reason: those names name a kind of turn
    # boundary rather than a moment, and the ``effect_expiring`` hook is not given one, so there is nothing here to
    # read them against. :func:`retire_saved_forge_mark_expiries` runs at both of this boundary's edges and is, so
    # whichever order the two run in, that saved population still ends on the boundary it named.
    from . import effect_durations

    undated_due = bool(undated) and effect_durations.due(engine, undated_until)
    if len(left) == len(deadlines) and not undated_due:
        return  # neither population's own clock has come: nothing to retire
    if undated_due:
        undated, undated_until = 0, None
    if not left and not undated:
        # This row is going, but another holder may still stand a mark from the same smith (Field Repair puts
        # one on a creature's equipment), and the printed answer is about any workpiece of theirs.
        if not owner_has_marks(engine, owner, exclude=(holder.entity_id, row.instance_id)):
            lapse_personal_work(engine, owner, row.source_definition_id)
        return
    from .rider_support import remove_instance

    remove_instance(engine, holder, row.instance_id, row.source_definition_id)
    store_marks(engine, holder, owner.entity_id, row.source_definition_id, left, limit(engine, owner),
                undated=undated, undated_until=undated_until, item_key=(row.data or {}).get('item_key', ''))


@hook("turn_start")
def forge_marks_read_a_saved_expiry_at_turn_start(engine: Any, actor: Any) -> None:
    """Read the saved expiry of every Forge Mark row carrying one, at the checkpoint the engine starts each turn at.

    Thin wrapper on :func:`retire_saved_forge_mark_expiries`; see it for what this is for. ``"START_OF_TURN"`` is the
    boundary's own name, which is what a saved ``START_OF_SOURCE_NEXT_TURN`` has to be read against."""
    retire_saved_forge_mark_expiries(engine, "START_OF_TURN")


@hook("turn_end")
def forge_marks_read_a_saved_expiry_at_turn_end(engine: Any, actor: Any) -> None:
    """As :func:`forge_marks_read_a_saved_expiry_at_turn_start`, at the checkpoint the engine ends each turn at.

    ``actor`` is the creature whose turn is ending, which is what lets a saved name of the form
    ``END_OF_TURN_AT:<this creature>:<its nth turn>`` come due on this very boundary: the duration sweep runs while
    that creature is still the current one, so the name is not due until the ending creature is named. It is also
    what lets a saved ``END_OF_SOURCE_TURN_AT:<n>`` or ``END_OF_HOLDER_NEXT_TURN`` come due, both of which the engine
    only brings down on the named creature's own turn boundary."""
    retire_saved_forge_mark_expiries(engine, "END_OF_TURN", actor.entity_id)


def retire_saved_forge_mark_expiries(engine: Any, checkpoint: str, ending_id: str | None = None) -> None:
    """Retire Forge Mark rows whose SAVED expiry has come due, whichever clock the row is currently parked on.

    A Forge Mark row counting both populations has one ``expires_on``, so it can only be handed to the engine on one
    clock at a time (:func:`soonest_expiry`). The engine's own sweep reads that one name, so a saved expiry that came
    due first is never reached by it: a save whose marks were due to go at the smith's seventh turn, resumed and then
    marked again at round 3, was parked on the new mark's minute ten rounds out, and both the save's marks and the
    new one stayed spendable ten rounds past that turn. This reads the saved expiry at the same checkpoints the
    engine sweeps at, so the earlier of the two always ends first, and hands the row back on its remaining clock.

    ``checkpoint`` is the boundary this run is standing at ("START_OF_TURN" / "END_OF_TURN"), because a saved expiry in
    the ENGINE's own family of names can only be read against one: ``END_OF_SOURCE_TURN_AT:<n>``, ``END_OF_HOLDER_NEXT_TURN``
    and ``START_OF_SOURCE_NEXT_TURN`` name a kind of turn boundary rather than a moment in the fight, so
    :func:`effect_durations.engine_due` asks whether that boundary is the one the name was waiting for. Those are the
    names the sealed engine removes for itself (gate2_engine._expire_typed_for_checkpoint), and it only ever saw them
    if the row itself was parked on one -- which it is not, while a mark placed after resuming is keeping it on that
    mark's minute. The save's own expiry therefore has to be read here, at every boundary, or those marks outlive any
    minute at all.

    Order with the engine's sweep does not matter and neither depends on the other: this handler retires a
    population whose own name is due, the sweep retires whatever ``expires_on`` says is due, each re-reads the row
    that is stored when it runs, and both remove the instance before writing a replacement, so a row the other one
    has already rewritten is simply not found again.

    Inert by default. A row is only looked at when its condition id is a Forge Mark row's, which no other creature
    stores unless a smith marked it, and then only when it actually carries an ``undated`` count to retire -- so a
    fight with no Blacksmith in it, and every ordinary mark placed by this build, costs one string comparison each.
    """
    from ..typed_executor import mark_condition_id
    from . import effect_durations
    from .rider_support import remove_instance

    prefix = mark_condition_id(FORGE_MARK, "")
    for holder in list(engine.state.actors.values()):
        if not holder.active:
            continue
        for row in list(holder.conditions.values()):
            if not str(row.condition_id).startswith(prefix):
                continue
            data = row.data or {}
            # Read as the exact integer the writer stores, not through int(): this runs on every turn boundary, so a
            # save carrying something else here must be skipped rather than raise out of the turn.
            if type(data.get("undated")) is not int or data["undated"] <= 0:
                continue
            saved = str(data.get("undated_until") or "") or None
            if saved is None or not effect_durations.engine_due(engine, saved, checkpoint,
                                                               source_id=getattr(row, "source_actor_id", None),
                                                               holder_id=holder.entity_id, ending_id=ending_id):
                continue
            owner = engine.state.actors.get(getattr(row, "source_actor_id", None))
            if owner is None:
                continue
            deadlines, undated, _ = stored_populations(data, row.expires_on)
            if not undated:
                continue
            remove_instance(engine, holder, row.instance_id, row.source_definition_id)
            if deadlines:
                store_marks(engine, holder, owner.entity_id, row.source_definition_id, deadlines,
                            limit(engine, owner), undated=0, undated_until=None, item_key=data.get('item_key', ''))
            # The printed declaration lapses when the smith's last Forge Mark is gone from every holder
            # (:func:`owner_has_marks`), which this removal may have just been.
            if not owner_has_marks(engine, owner):
                lapse_personal_work(engine, owner, row.source_definition_id)


def owner_has_marks(engine: Any, owner: Any, *, exclude: tuple[str, str] | None = None) -> bool:
    """Whether any holder still stands a Forge Mark from this smith, the expiring or spent row apart.

    The printed conditional ("a workpiece you personally forged or prepared") applies to any marked workpiece,
    and Forge Marks do not only sit on the smith: Field Repair places one on a creature's own equipment. So the
    declaration's reset is a question about every holder, not about the one row that just ended -- otherwise one
    ally's mark expiring ends the declaration while the smith's own marked workpiece is still standing, and the
    next revision silently loses its Intelligence modifier.
    """
    from ..typed_executor import mark_condition_id

    wanted = mark_condition_id(FORGE_MARK, owner.entity_id)
    for actor in engine.state.actors.values():
        for row in actor.conditions.values():
            key = (row.data or {}).get('item_key', '')
            if row.condition_id != item_mark_id(owner.entity_id, key) or (exclude and (actor.entity_id, row.instance_id) == exclude):
                continue
            if not actor.active:
                from ..item_uses import carried_item
                if not key or carried_item(engine, actor.entity_id, key) is None:
                    continue
            if int((row.data or {}).get("count") or 0) > 0:
                return True
    return False


def deadline_of(placement: tuple[int, int]) -> tuple[int, int]:
    """The ``(round, slot)`` one printed minute after this placement, in the order :func:`due` compares."""
    from ..typed_executor import duration_round_count

    return (int(placement[0]) + (duration_round_count(ONE_MINUTE) or 10), int(placement[1]))


def held_condition(actor: Any, condition_id: str) -> Any:
    """The stored condition with this id, or None (ActorState.conditions is keyed by instance id)."""
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)


def mark_count(actor: Any, owner_id: str, *, item_key: str = "") -> int:
    row = mark_row(actor, owner_id, item_key=item_key)
    return int((row.data or {}).get("count") or 0) if row is not None else 0


def workpiece_locked(smith: Any, subject: Any, *, item_key: str = "") -> bool:
    """Shared admission/execution query for one smith's physical workpiece lock.

    ``subject`` is the original inventory owner for a nonempty key, otherwise
    the actor workpiece. Carrier changes never relocate this lock's storage.
    """
    return held_condition(subject, item_lock_id(smith.entity_id, item_key)) is not None


def spend_item_marks(ctx: Any, smith: Any, owner_id: str, item_key: str, number: int, source: str) -> int:
    """Pay from a carried physical item and announce its actual current bearer.

    Blacksmith item responses use this instead of the actor-workpiece payment.
    Storage ownership pays the marks; the mark_spent subject is the current
    carrier. The transient typed.spent_workpiece identity preserves both facts
    for subscribers without changing the positional hook or saved state.
    Absent items and nonpositive payments are inert.
    """
    from ..item_uses import carried_item
    item = carried_item(ctx.engine, owner_id, item_key)
    if item is None or int(number) <= 0:
        return 0
    holder = ctx.engine.state.actors[owner_id]
    spent = -set_marks(ctx.engine, smith, holder, -int(number), source, item_key=item_key)
    if spent > 0:
        from dataclasses import replace
        from .. import ext
        notice = replace(ctx, actor=smith, typed={**ctx.typed, 'spent_workpiece': {
            key: item[key] for key in ('owner', 'key', 'carrier', 'kind')}})
        ext.run('mark_spent', notice, FORGE_MARK, ctx.engine.state.actors[item['carrier']])
    return spent


def spend_marks(ctx: Any, smith: Any, number: int, source: str) -> int:
    """Take ``number`` marks off this smith's own workpiece and announce the spend on the documented ``mark_spent``
    seam, returning how many left the count.

    Quench in Breath answers "When you spend a Forge Mark on a workpiece you hold, wear, or touch", but the engine
    only announces a spend it makes itself (typed_executor.block_spend_mark, the "Cost: Spend 1 Forge Mark" rows), so a
    response that pays its own printed cost -- Seven-Hammer Revision's one mark, the Tempering Sequence's "spend all of
    them" -- has to announce it the same way or the printed trigger silently misses it.

    The announcement carries the SPENDING SMITH, not whoever the current resolution belongs to. Seven-Hammer Revision
    is printed for an ally's strike too ("When you or an ally within 30 feet"), and then ``ctx.actor`` is that ally,
    so announcing with it asked the ally whether the ALLY owns Quench in Breath and priced the reduction with the
    ally's Proficiency Bonus -- the smith's own printed answer went missing exactly when a smith revised a partner's
    work. typed_executor.block_spend_mark always announces with the mark's owner as the actor; this matches it.
    """
    spent = -set_marks(ctx.engine, smith, smith, -int(number), source)
    if spent > 0:
        from dataclasses import replace
        from .. import ext

        ext.run("mark_spent", ctx if smith is ctx.actor else replace(ctx, actor=smith), FORGE_MARK, smith)
    return spent


def limit(engine: Any, actor: Any) -> int:
    """The printed per-workpiece limit: your Proficiency Bonus, +2 while Incarnation of the Living Forge lasts
    ("your Forge Mark limit on each current workpiece increases by 2")."""
    base = max(2, int(getattr(actor, "proficiency_bonus", 0) or 0))
    return base + 2 if _incarnated(actor) else base


def _incarnated(actor: Any) -> bool:
    """Whether Incarnation of the Living Forge is standing. It cannot carry a compile_block row of its own (it is
    a Bonus Action, and the compiler drops an action whose feature a plug-in claims), so its own placed state is
    the signal: every effect it applies -- the Forge Mark, the Fire and Lightning Resistance, the save Advantage --
    is filed under its action id."""
    if not actor.active:
        return False
    suffix = f".{INCARNATION}"
    placed = [*actor.conditions.values(), *(getattr(actor, "modifiers", {}) or {}).values()]
    return any(str(getattr(row, "source_definition_id", "") or "").endswith(suffix) for row in placed)


# ------------------------------------------------------------------------------ Forge Mark chassis
@hook("mark_apply")
def place_forge_mark(ctx: Any, row: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    """Place one Forge Mark: the printed per-workpiece limit and the printed one-minute life. block_mark keys one
    instance per mark name, so the number of marks lives in that instance's data."""
    if str(row.get("mark") or "") != FORGE_MARK or not subject.active:
        return None
    smith = ctx.actor
    if not owns(ctx.engine, smith, "forge_marks"):
        return None
    is_hammer = ctx.typed.get("source") == "BLACKSMITH_BASE_HAMMER_THE_MARK" or ctx.source.endswith("BLACKSMITH_BASE_HAMMER_THE_MARK")
    if is_hammer:
        from .blacksmith_second_pass import hammer_item
        if hammer_item(ctx):
            return True
    ceiling = limit(ctx.engine, smith)
    if mark_count(subject, smith.entity_id) >= ceiling:
        ctx.rider(f"A workpiece holds at most {ceiling} Forge Marks from you, so this one is not placed.")
        return True
    # Modifier variants preserve the printed mechanic in typed.source, while
    # their action ids gain suffixes. Do not lose the talent on those variants.
    number = two_beat_count(ctx, subject) if is_hammer else 1
    if set_marks(ctx.engine, smith, subject, number, ctx.source) > 0 and number == 2:
        from .effect_durations import token

        ctx.engine._apply_condition(subject, TWO_BEAT_LOCK + smith.entity_id, TWO_BEAT, smith.entity_id,
                                    expires_on=token("start", smith.entity_id, smith.turns_started + 1),
                                    data={"label": f"Two-Beat Temper: {smith.display_name} cannot place more Forge Marks here until their next turn"})
    return True


@hook("compile_actions")
def two_beat_workshop_actions(info: dict[str, Any]) -> list[Any] | None:
    """Declare a factual workshop/anvil context; AI never invents access.

    The declaration is reversible and scene-scoped, not a new forge or anvil.
    New ownership rows opt in; previously sealed characters keep their actions.
    """
    if TWO_BEAT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.two_beat.workshop.{int(on)}",
        display_name=label, owner_id=info["actor_id"], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"player_only": True, "setting_only": True,
                    "setting_description": "Declare whether you are actually working in a full workshop or at your Apprentice's Anvil. Costs no action. Ends when changed or this fight ends; it does not create a workshop.",
                    "typed": {"effects": [{"type": "blacksmith_workshop", "on": int(on)}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}})
            for on, label in [(True, "Two-Beat Temper: working at a workshop or Apprentice's Anvil"),
                              (False, "Two-Beat Temper: working away from a workshop")]]


@effect("blacksmith_workshop")
def declare_workshop(ctx: Any, row: dict[str, Any]) -> None:
    if not owns(ctx.engine, ctx.actor, "two_beat_temper"):
        return
    ctx.engine._remove_condition(ctx.actor, WORKSHOP, TWO_BEAT)
    if row.get("on"):
        ctx.engine._apply_condition(ctx.actor, WORKSHOP, TWO_BEAT, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED", data={"label": "Two-Beat Temper: workshop access declared for this fight"})


def two_beat_count(ctx: Any, subject: Any, *, item_key: str = "") -> int:
    """Optional doubling, one free scene use away from a workshop, then 1 CP.

    A workshop grants one free use per round; no workshop access is assumed for AI.
    A scene ledger is evented so a cold reload cannot reset the first free use.
    """
    smith, engine = ctx.actor, ctx.engine
    if not owns(engine, smith, "two_beat_temper"):
        return 1
    if held_condition(subject, item_lock_id(smith.entity_id, item_key)) is not None:
        return 1
    if mark_count(subject, smith.entity_id, item_key=item_key) + 2 > limit(engine, smith):
        return 1  # do not offer/pay for doubling when only one mark can fit
    from .needle import ask, checkpoint_id, CHOICE
    from .choice_costs import payable
    from .rider_support import cp_pool

    ledger = held_condition(smith, TWO_BEAT_SCENE)
    data = dict(ledger.data or {}) if ledger else {}
    workshop = held_condition(smith, WORKSHOP) is not None
    free_workshop = workshop and int(data.get("workshop_round", -1)) != engine.state.round_number
    # At a workshop the printed talent grants once per round, not paid extras.
    if workshop and not free_workshop:
        return 1
    price = 0 if workshop or not data.get("used") else 1
    pool = cp_pool(smith)
    if pool is None:
        return 1
    payment = payable(smith, pool, price) if price else None
    if price and payment is None:
        return 1
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "two_beat", smith.entity_id, ctx.source, subject.entity_id),
                 smith, CHOICE + "blacksmith_two_beat", ["two", "one"],
                 labels={"two": "Place 2 Forge Marks" + (f" ({payment.quote()})" if payment else " (no resource cost)"),
                         "one": "Place 1 Forge Mark (no resource cost)"},
                 preferred=["two"], name="Two-Beat Temper", feature_id=TWO_BEAT,
                 target_id=subject.entity_id, payment=payment,
                 prompt=f"Two-Beat Temper during Hammer the Mark on {subject.display_name}'s workpiece: place two Forge Marks instead of one? After choosing two, you cannot add marks here until the start of your next turn. Forge Marks fuel Blacksmith responses and last 1 minute; your normal mark limit still applies.")
    if chosen != ["two"]:
        return 1
    if payment:
        payment.pay(engine, smith, TWO_BEAT)
    engine._remove_condition(smith, TWO_BEAT_SCENE, TWO_BEAT)
    engine._apply_condition(smith, TWO_BEAT_SCENE, TWO_BEAT, smith.entity_id, expires_on="UNTIL_REMOVED",
                            data={"used": 1, "workshop_round": int(engine.state.round_number) if workshop else int(data.get("workshop_round", -1)),
                                  "label": "Two-Beat Temper: first free use spent for this fight"})
    return 2


@hook("candidate_allowed")
def two_beat_locked_workpiece(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Do not offer a placement known to fail the workpiece's current lock."""
    if action is None or not owns(engine, actor, "two_beat_temper"):
        return None
    effects = (action.parameters.get("typed") or {}).get("effects") or []
    if not any(row.get("type") == "mark" and row.get("mark") == FORGE_MARK for row in effects):
        return None
    if (action.parameters.get("typed") or {}).get("source") == 'BLACKSMITH_BASE_HAMMER_THE_MARK':
        from .blacksmith_second_pass import WORKPIECE, current_item
        if held_condition(actor, WORKPIECE):
            item = current_item(engine, actor)
            if item is None:
                return False
            subject = engine.state.actors[item['owner']]
            return False if workpiece_locked(actor, subject, item_key=item['key']) else None
    subjects = [engine.state.actors[key] for key in candidate.target_ids if key in engine.state.actors] or [actor]
    return False if any(workpiece_locked(actor, subject) for subject in subjects) else None


@hook("compile_actions")
def furnace_tool_actions(info: dict[str, Any]) -> list[Any] | None:
    """A held tool is an equipment fact, not assumed from knowing Blacksmith."""
    if FURNACE_DISCIPLINE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.furnace_tool.{int(on)}",
        display_name=label, owner_id=info["actor_id"], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"player_only": True, "setting_only": True,
                    "setting_description": "Declare whether you actually hold a Blacksmith tool. Costs no action and lasts until changed or this fight ends. Furnace Discipline gives Fire Resistance while you hold the tool or your current workpiece has a Forge Mark; it does not equip a tool.",
                    "typed": {"effects": [{"type": "blacksmith_held_tool", "on": int(on)}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}})
            for on, label in [(True, "Furnace Discipline: holding a Blacksmith tool"),
                              (False, "Furnace Discipline: no Blacksmith tool held")]]


@effect("blacksmith_held_tool")
def declare_held_tool(ctx: Any, row: dict[str, Any]) -> None:
    if not owns(ctx.engine, ctx.actor, "furnace_discipline"):
        return
    ctx.engine._remove_condition(ctx.actor, HELD_TOOL, FURNACE_DISCIPLINE)
    if row.get("on"):
        ctx.engine._apply_condition(ctx.actor, HELD_TOOL, FURNACE_DISCIPLINE, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED", data={"label": "Furnace Discipline: held Blacksmith tool declared"})


@hook("damage_defenses")
def furnace_fire_resistance(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: str | None) -> list[dict[str, Any]] | None:
    """Conditional Fire Resistance, queried without mutating marks or tool state."""
    if not target.active or not owns(engine, target, "furnace_discipline"):
        return None
    if mark_count(target, target.entity_id) <= 0 and held_condition(target, HELD_TOOL) is None:
        return None
    return [{"kind": "resistance", "damage_types": ["FIRE"], "feature_id": FURNACE_DISCIPLINE}]


@hook("mark_consume")
def spend_forge_mark(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    """"Cost: Spend 1 Forge Mark": one mark leaves the count, and the instance goes when the last one does."""
    if str(row.get("mark") or "") != FORGE_MARK:
        return None
    smith = ctx.actor
    if not owns(ctx.engine, smith, "forge_marks"):
        return None
    from ..typed_executor import bears_mark

    if not bears_mark(subject, smith.entity_id, FORGE_MARK):
        return False
    set_marks(ctx.engine, smith, subject, -1, ctx.source)
    return True


# ------------------------------------------------------------------------------ Quench in Breath
@hook("mark_spent")
def quench_in_breath(ctx: Any, name: str, subject: Any) -> None:
    """Quench in Breath: "When you spend a Forge Mark on a workpiece you hold, wear, or touch, reduce the next Fire,
    Cold, Lightning, or Acid damage you take before the start of your next turn by your Proficiency Bonus." At CL 5+
    the reduction may be granted to the wearer or holder instead, which on this table is the creature that carries
    the marked workpiece. Item-spend producers pass the current carrier as
    ``subject``, never its original inventory storage owner; the transient
    ``ctx.typed['spent_workpiece']`` retains that physical inventory identity.

    ``ctx.actor`` is the smith who spent the mark (:func:`spend_marks` announces the spender, not the fighter whose
    resolution paid for it), so the talent, the wearer and the reduction are all the smith's. The Proficiency Bonus is
    read from the smith rather than from ``ctx.numbers``, which is the numbers of the action being resolved -- the
    ally's when the smith revised an ally's strike.
    """
    if name != FORGE_MARK or not owns(ctx.engine, ctx.actor, "quench_in_breath"):
        return
    smith = ctx.actor
    wearer = subject if subject.team_id == smith.team_id else smith
    ctx.engine._apply_condition(wearer, QUENCH_BREATH, QUENCH_IN_BREATH, smith.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"by": smith.entity_id, "pb": int(getattr(smith, "proficiency_bonus", 0) or 0),
                                      "label": "Quench in Breath: the next Fire, Cold, Lightning or Acid damage is reduced"})


@hook("incoming_damage")
def quench_breath_reduction(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str,
                            source_actor_id: str | None) -> int | None:
    row = held_condition(target, QUENCH_BREATH) if target.active else None
    if row is None or amount <= 0 or str(damage_type).upper() not in {"FIRE", "COLD", "LIGHTNING", "ACID"}:
        return None
    reduction = int((row.data or {}).get("pb") or 0)
    if reduction <= 0:
        return None
    engine._remove_condition(target, QUENCH_BREATH, QUENCH_IN_BREATH)  # "the next ... damage"
    return min(int(amount), reduction)


# ------------------------------------------------------------------------------ Tempering Sequence
SEQUENCES: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("hardening", "Hardening Sequence", [{"type": "tempering_hardening"}]),
    ("softening", "Softening Sequence", [{"type": "tempering_softening"}]),
    # "Reduce one mundane impurity, rust, poison residue, rot, corrosion, instability, or crafting complication
    # affecting the workpiece. A magical curse or artifact flaw is only reduced if the GM allows it." The printed
    # choice is one of the four a player picks from, so it is a button; what it removes is the GM's to call, because
    # this table keeps no state for an object's impurities, rust or rot.
    ("purifying", "Purifying Sequence", [{"type": "tempering_purifying"}]),
    ("awakening", "Awakening Sequence", [{"type": "tempering_awakening"}]),
]


@hook("compile_actions")
def tempering_sequence_actions(info: dict[str, Any]) -> list[Any] | None:
    """Tempering Sequence (CL 10+), one button per printed sequence: "Choose one: Hardening / Softening / Purifying /
    Awakening". The built-in AI takes the first legal candidate, a player presses the one they want."""
    if TEMPERING_SEQUENCE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    return [ActionDefinition(
        source_definition_id=f"action:typed.{short}.tempering_sequence.{key}",
        display_name=f"Tempering Sequence: {label}", owner_id=actor_id, economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [*effects, {"type": "tempering_spend_all"}],
                              "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0}) for key, label, effects in SEQUENCES]


@hook("candidate_allowed")
def tempering_sequence_needs_three_marks(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The printed precondition: "When a workpiece has at least 3 Forge Marks from you"."""
    if action is None or ".tempering_sequence." not in str(action.source_definition_id) or not actor.active:
        return None
    if not owns(engine, actor, "tempering_sequence"):
        return None
    return mark_count(actor, actor.entity_id) >= 3


@effect("tempering_hardening")
def hardening(ctx: Any, row: dict[str, Any]) -> None:
    """"Hardening Sequence: The workpiece gains a Temporary Temper lasting 10 minutes. If armor or shield, it grants
    +1 AC. If weapon or tool, it gains +1 to attack rolls or relevant checks." This table's workpiece is the smith,
    so the smith gains +1 AC and +1 to attack rolls with it."""
    _temper(ctx, HARDENED, "one_minute", "Temporary Temper (Hardening Sequence, 10 minutes): +1 AC and +1 to attack rolls")


@effect("tempering_softening")
def softening(ctx: Any, row: dict[str, Any]) -> None:
    """"Softening Sequence: The next repair, crafting, modification, or disarm attempt involving it before the end of
    the scene has Advantage." One use: the smith's next check against it."""
    _temper(ctx, SOFTENED, "one_minute", "Softened: the next check to repair, craft, modify or disarm this workpiece has Advantage")


@effect("tempering_purifying")
def purifying(ctx: Any, row: dict[str, Any]) -> None:
    """The printed Purifying Sequence. The Forge Marks are spent like any other sequence's, and the impurity itself
    is the GM's to remove: the table keeps no state for an object's impurities, rust, poison residue, rot, corrosion,
    instability or crafting complications, and "a magical curse or artifact flaw is only reduced if the GM allows it"."""
    ctx.rider("Purifying Sequence: reduce one mundane impurity, rust, poison residue, rot, corrosion, instability, or "
              "crafting complication affecting the workpiece. A magical curse or artifact flaw is only reduced if your "
              "GM allows it. This table keeps no state for an object's condition, so the purification itself is the "
              "GM's to call.")


@effect("tempering_awakening")
def awakening(ctx: Any, row: dict[str, Any]) -> None:
    """"Awakening Sequence: The workpiece gains the first sign of an item spirit seed until the end of the next long
    rest. During that time, once when used for its named purpose, it grants Advantage on one roll." This table cannot
    see a workpiece being used for its named purpose, so the one Advantage lands on the smith's next roll."""
    _temper(ctx, SPIRIT_SIGN, "one_minute", "First sign of an item spirit: Advantage on one roll")


def _temper(ctx: Any, condition_id: str, duration: str, label: str) -> None:
    from ..typed_executor import clock_expiry
    from .choice_prompt import action_context
    from .needle import ai_controlled, ask, checkpoint_id, CHOICE

    smith = ctx.actor
    kind, amount = duration, None
    if _incarnated(smith):
        # Incarnation of the Living Forge: "your Blacksmith Temporary Tempers may
        # last for 10 minutes instead of 1 minute". The printed "may" is the
        # owner's, so the lifetime question rides the shared choice transport:
        # the one-minute option stays in the menu, and a smith nobody answers
        # for keeps the chassis minute -- except the built-in AI, which takes
        # the printed longer lifetime the way it takes Two-Beat Temper's
        # "place two". Only a temper this table places while the Incarnation
        # stands is asked about; the Incarnation's own minute is untouched.
        picked = ask(ctx.engine, ctx.intent,
                     checkpoint_id(ctx.engine, "temper_duration", smith.entity_id, condition_id),
                     smith, CHOICE + "blacksmith_temper_duration", ["one_minute", "ten_minutes"],
                     labels={"one_minute": "Last 1 minute",
                             "ten_minutes": "Last 10 minutes (Incarnation of the Living Forge)"},
                     preferred=["ten_minutes"], allow_decline=True, automatic=True,
                     default="first" if ai_controlled(ctx.engine, smith) else "decline",
                     name="Temporary Temper lifetime", feature_id=INCARNATION,
                     target_id=smith.entity_id,
                     prompt=("Incarnation of the Living Forge: your Blacksmith Temporary Tempers "
                             "may last for 10 minutes instead of 1 minute. How long should this "
                             f"Temporary Temper on {smith.display_name} last?"),
                     prompt_context=action_context(ctx.engine, smith, str(ctx.source), smith))
        if picked == ["ten_minutes"]:
            kind, amount = "minutes", 10
    ctx.engine._apply_condition(smith, condition_id, TEMPERING_SEQUENCE, smith.entity_id,
                                expires_on=clock_expiry(ctx.engine, kind, amount),
                                data={"label": label, **({"lifetime": "ten_minutes"} if amount else {})})


@effect("tempering_spend_all")
def spend_all(ctx: Any, row: dict[str, Any]) -> None:
    """"you may spend all of them to perform a Tempering Sequence": every Forge Mark on the workpiece pays for it."""
    smith = ctx.actor
    held = mark_count(smith, smith.entity_id)
    if held < 3:
        return
    spend_marks(ctx, smith, held, TEMPERING_SEQUENCE)


@hook("ac")
def hardening_ac(engine: Any, target: Any) -> int:
    return 1 if target.active and held_condition(target, HARDENED) is not None else 0


@hook("attack_bonus")
def hardening_attack_bonus(ctx: Any, actor: Any) -> int | None:
    return 1 if actor.active and held_condition(actor, HARDENED) is not None else None


@hook("attack_mode")
def awakening_advantage_on_attacks(ctx: Any, target: Any) -> str | None:
    """Awakening Sequence's "once when used for its named purpose, it grants Advantage on one roll": this table
    cannot see a workpiece being used, so the one Advantage lands on the smith's next attack roll."""
    return _one_roll_advantage(ctx.engine, ctx.actor, SPIRIT_SIGN, "First sign of an item spirit")


@hook("ability_check_mode")
def softening_advantage_on_checks(engine: Any, actor: Any, ability: str, skill: str, against: Any) -> str | None:
    """Softening Sequence's "the next repair, crafting, modification, or disarm attempt involving it ... has
    Advantage" -- an attempt at the workpiece is a check, not an attack, so this answers check rolls."""
    return _one_roll_advantage(engine, actor, SOFTENED, "Softened")


@hook("save")
def awakening_advantage_on_saves(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    """The same one-roll Advantage covers a saving throw."""
    if _one_roll_advantage(ctx.engine, subject, SPIRIT_SIGN, "First sign of an item spirit"):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


def _one_roll_advantage(engine: Any, actor: Any, condition_id: str, label: str) -> str | None:
    row = held_condition(actor, condition_id) if actor.active else None
    if row is None:
        return None
    engine._remove_condition(actor, condition_id, TEMPERING_SEQUENCE)  # "once ... it grants Advantage on one roll"
    engine._append_event("PASSIVE_TRIGGERED", TEMPERING_SEQUENCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"feature_id": TEMPERING_SEQUENCE, "log": f"{label}: Advantage."})
    return "ADVANTAGE"


@hook("status_description")
def temper_status(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    condition_id = str(row.get("condition_id") or "")
    if condition_id not in {SOFTENED, HARDENED, SPIRIT_SIGN}:
        return None
    handling = "A Temporary Temper lasts one minute on this table, as the sphere's Forge Mark chassis prints."
    if str((data or {}).get("lifetime") or "") == "ten_minutes":
        handling = ("This Temporary Temper lasts 10 minutes: Incarnation of the Living Forge "
                    "was standing when it was placed.")
    return {"text": str(data.get("label") or "Temporary Temper"),
            "source_ability": "Tempering Sequence",
            "handling": handling}


# ------------------------------------------------------------------------------ Field Repair
@hook("compile_actions")
def field_repair_actions(info: dict[str, Any]) -> list[Any] | None:
    """Manual trigger declarations for Field Repair, which places 1 Forge Mark on damaged equipment, and at CL 5+ the printed
    Close-the-Crack extension paid for with 1 CP of the fighter's own Path pool. The printed trigger is "a creature
    within reach", which is any creature, not only an ally, so the button aims at ANY_CREATURE.

    Object damage is not tracked by this table. These NONE-economy commands are
    the human's explicit declaration of that trigger, not primary Reaction
    actions. The effect opens the paid Reaction window; candidate_allowed and
    ai_candidate_allowed gate availability and prohibit invented AI triggers.
    """
    if FIELD_REPAIR not in info["owned_ids"]:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    made = [ActionDefinition(
        source_definition_id=f"action:typed.{short}.field_repair",
        display_name="Confirm damaged equipment: Field Repair (uses Reaction)", owner_id=actor_id,
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ANY_CREATURE",
        parameters={"typed": {"effects": [{"type": "field_repair", "heal": False}],
                              "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0})]
    if int(numbers.get("cl") or 1) >= 5:
        pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.field_repair.close_crack",
            display_name="Confirm damaged equipment: Field Repair + Close the Crack (uses Reaction + 1 CP)",
            owner_id=actor_id, economy=EconomyKind.NONE,
            resolution_kind="TYPED", target_kind="ANY_CREATURE", costs=((pool, 1),),
            parameters={"typed": {"effects": [{"type": "field_repair", "heal": True}],
                                  "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0}))
    return made


@hook("candidate_allowed")
def field_repair_requires_reaction(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The manual damaged-equipment confirmation still spends the printed Reaction.

    This button declares an object-damage trigger that the table cannot observe.
    The declaration uses no turn action, but its triggered effect still needs
    the printed Reaction, including any explicit waiver.
    """
    if action is None or action.owner_id != actor.entity_id:
        return None
    effects = (action.parameters.get("typed") or {}).get("effects") or []
    if not any(row.get("type") == "field_repair" for row in effects):
        return None
    from ..typed_executor import condition_rules
    from ..typed_reactions import reaction_waived

    return actor.active and not any(rule.get("no_reactions") for rule in condition_rules(actor)) and (
        actor.reaction_available or reaction_waived(engine, actor, {"feature_id": FIELD_REPAIR}))


@hook("ai_candidate_allowed")
def field_repair_needs_manual_damage_confirmation(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """No object damage is tracked, so the AI cannot establish this printed trigger.

    Keep the existing manual button for a player's damaged-equipment declaration;
    automatic fighters must not invent that event or endlessly recreate marks.
    """
    if action is None or action.owner_id != actor.entity_id:
        return None
    effects = (action.parameters.get("typed") or {}).get("effects") or []
    return False if any(row.get("type") == "field_repair" for row in effects) else None


@effect("field_repair")
def field_repair(ctx: Any, row: dict[str, Any]) -> None:
    """"use your Reaction to Set the Workpiece to that object and place 1 Forge Mark on it." The printed trigger needs
    a creature within reach whose object was just damaged by an attack, hazard or failed check; this table carries no
    damage state for an object, so the damage itself is the GM's to call and the mark is placed on the target's own
    equipment. The CL 5 extension also repairs it ("restore Hit Points to the object equal to 2d6 + Intelligence
    modifier + Proficiency Bonus"), which needs that same object Hit Points."""
    from ..typed_reactions import publish_reaction_used, spend_reaction

    smith = ctx.actor
    target = ctx.target if ctx.target is not None and ctx.target.active else smith
    notice = {"feature_id": FIELD_REPAIR, "name": "Field Repair", "target_ids": (target.entity_id,)}
    # Selecting the human-only declaration confirms the printed object-damage
    # trigger. Pay before publishing, so nested answers cannot reuse this Reaction.
    spend_reaction(ctx.engine, smith, notice)
    ctx.engine._append_event("REACTION_WINDOW_OPENED", FIELD_REPAIR, actor_id=smith.entity_id,
                             target_ids=(target.entity_id,), payload={"checkpoint": "MANUAL_DAMAGED_EQUIPMENT"})
    publish_reaction_used(ctx.engine, smith, notice)
    ctx.engine._append_event("REACTION_RESOLVED", FIELD_REPAIR, actor_id=smith.entity_id, target_ids=(target.entity_id,),
                             payload={"checkpoint": "MANUAL_DAMAGED_EQUIPMENT"})
    set_marks(ctx.engine, smith, target, 1, FIELD_REPAIR)
    ctx.rider(f"Field Repair: 1 Forge Mark placed on {target.display_name}'s equipment.")
    if row.get("heal"):
        ctx.rider("Close the Crack: the damaged object is repaired for 2d6 + Intelligence modifier + Proficiency Bonus "
                  "Hit Points. This table does not track an object's Hit Points, so the repair itself is the GM's.")


# ------------------------------------------------------------------------------ Seven-Hammer Revision
REVISION_RANGE_FT = 30


def _revision_smith(ctx: Any) -> Any | None:
    """The smith whose Forge Mark this damage packet revises, or None.

    Printed: "When you or an ally within 30 feet rolls damage with a weapon, tool, object, or construct attack
    involving a workpiece bearing your Forge Mark, spend 1 Forge Mark to revise the strike." ``ctx.actor`` is the
    creature rolling the damage, so the smith is usually that creature; when an ally is the one attacking, the smith
    is the nearest active ally within the printed 30 feet who owns the talent and still bears a Forge Mark. The 30
    feet are the shared measure (combat/action_geometry.distance, which reads the map's own square size), not a
    hand-counted one, so a smith across the diagonal of the ally's square is inside the printed range.
    """
    from ..action_geometry import distance

    striker = ctx.actor
    if striker is None or not striker.active:
        return None
    if owns(ctx.engine, striker, SEVEN_HAMMER_KEY) and mark_count(striker, striker.entity_id) >= 1:
        return striker
    near = sorted((other for other in ctx.engine.state.actors.values()
                   if other.active and other.team_id == striker.team_id and other.entity_id != striker.entity_id
                   and owns(ctx.engine, other, SEVEN_HAMMER_KEY) and mark_count(other, other.entity_id) >= 1),
                  key=lambda smith: distance(ctx.engine, smith, striker))
    return next((smith for smith in near if distance(ctx.engine, smith, striker) <= REVISION_RANGE_FT), None)


def printed_workpiece_attack(ctx: Any, effect: dict[str, Any] | None) -> bool:
    """Whether this damage packet is the printed "a weapon, tool, object, or construct attack", which is what
    Seven-Hammer Revision may revise. ``effect is None`` is the one set of dice an Attack action shares across every
    strike, and that roll happens inside the sealed gate2 resolver, so the engine never asks about it. An unarmed
    strike or a natural weapon is not one of the printed four, and a packet with no weapon behind it (a technique's
    own damage) is not one either.
    """
    if effect is None:
        return False
    typed = getattr(ctx, "typed", None) or {}
    if not typed.get("weapon"):
        return False
    source = str(getattr(ctx, "source", "") or "").lower()
    return ".natural." not in source and "unarmed" not in source


#: The AI's standing answer to the printed personal-work question, stated here instead of left to the harness.
#: "If the workpiece is one you personally forged or prepared during the current day" is a fact about the fighter's
#: own day that the table cannot see -- no Forge Mark records who forged the workpiece -- and the printed condition
#: failing is the printed default, so an AI smith declares nothing and its revisions reroll dice without the
#: Intelligence modifier. Both buttons stay ``player_only``: a manual fighter, or one on "Ask me", sets the answer.
AI_DECLARES_PERSONAL_WORK = False

_DECLARED_LABEL = ("Seven-Hammer Revision: the workpieces you have marked are ones you personally forged or prepared "
                   "today, so a revision adds your Intelligence modifier")
_NOT_DECLARED_LABEL = ("Seven-Hammer Revision: no personal work is declared, so a revision rerolls damage dice and "
                       "adds no Intelligence modifier")


@hook("compile_actions")
def seven_hammer_personal_work_actions(info: dict[str, Any]) -> list[Any] | None:
    """The fighter's own answer to the printed "If the workpiece is one you personally forged or prepared during the
    current day". The table keeps no record of which workpieces a smith forged or prepared, so this is a standing
    answer in the same shape as combat/ext/ironclad_blacksmith.py's Forge-Fitted benefit pickers and
    combat/ext/blacksmith_rebuke.py's failed-save pick -- and it is reversible, in the same shape as
    combat/ext/oni_blood.py's "End Oni Mask": two free settings, one to declare and one to end the declaration, the
    second offered only while the declaration stands (:func:`personal_work_candidate`).

    "during the current day" has no clock on this table, so the answer has a second, defined end: it lapses when the
    smith's last Forge Mark is spent or expires (:func:`lapse_personal_work`), because there is then no marked
    workpiece for it to describe. Nothing here lasts the rest of a fight by accident, and an AI smith's answer is
    :data:`AI_DECLARES_PERSONAL_WORK`.
    """
    if SEVEN_HAMMER_REVISION not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    printed = ("Seven-Hammer Revision adds your Intelligence modifier to a revision only for a workpiece you personally "
               "forged or prepared during the current day. This costs no action. Your answer ends by itself when your "
               "last Forge Mark is spent or expires, and you can end it at any time with the second button.")
    if not AI_DECLARES_PERSONAL_WORK:
        printed += " A fighter played by the computer does not declare personal work."
    made = []
    for name, label, on, description in (
            ("personal_work", "Seven-Hammer Revision: workpiece personally forged or prepared today", True, printed),
            ("personal_work.end", "Seven-Hammer Revision: end the personal-work declaration", False,
             "Ends your standing answer that the workpieces you marked are ones you personally forged or prepared "
             "today. This costs no action. A revision then rerolls damage dice and adds no Intelligence modifier.")):
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.seven_hammer.{name}",
            display_name=label, owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "setting_description": description,
                        "typed": {"effects": [{"type": "seven_hammer_personal_work", "on": on}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True}))
    return made


@hook("candidate_allowed")
def personal_work_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Each declaration button is offered only while it would change something: declaring is offered while nothing is
    declared, ending the declaration only while it stands."""
    if action is None or ".seven_hammer.personal_work" not in str(action.source_definition_id) or not actor.active:
        return None
    if not owns(engine, actor, SEVEN_HAMMER_KEY):
        return None
    declared = personal_work(actor)
    ending = str(action.source_definition_id).endswith(".personal_work.end")
    return declared if ending else not declared


@effect("seven_hammer_personal_work")
def seven_hammer_personal_work(ctx: Any, row: dict[str, Any]) -> None:
    """Declare, or end the declaration, that the workpieces this fighter marks are ones they personally forged or
    prepared today. One effect for both directions, so the printed answer is stored the same way whichever button
    pressed it."""
    smith = ctx.actor
    if row.get("on") is False:
        if not personal_work(smith):
            return
        ctx.engine._remove_condition(smith, PERSONAL_WORK, SEVEN_HAMMER_REVISION)
        ctx.rider("Seven-Hammer Revision: personal work ended, so a revision rerolls damage dice and adds no "
                  "Intelligence modifier.")
        return
    ctx.engine._remove_condition(smith, PERSONAL_WORK, SEVEN_HAMMER_REVISION)
    ctx.engine._apply_condition(smith, PERSONAL_WORK, SEVEN_HAMMER_REVISION, smith.entity_id, expires_on="UNTIL_REMOVED",
                                data={"declared": 1, "label": _DECLARED_LABEL})


def lapse_personal_work(engine: Any, smith: Any, source: str) -> None:
    """The declaration's defined reset: with no Forge Mark of this smith's standing anywhere there is no marked
    workpiece the printed conditional could apply to, so the answer ends. Callers decide that nothing is left
    (:func:`owner_has_marks`), so one holder's mark ending does not clear the answer while another marked
    workpiece of the same smith is still standing. Recorded as an ordinary removal, so a replay and a save see the
    same thing the sheet does."""
    if not personal_work(smith):
        return
    engine._remove_condition(smith, PERSONAL_WORK, SEVEN_HAMMER_REVISION)


def personal_work(actor: Any) -> bool:
    """Whether the fighter declared the marked workpiece one they personally forged or prepared today.

    A row saved before this answer carried a flag stores only its label, so it reads as declared -- which is what
    that save meant.
    """
    row = held_condition(actor, PERSONAL_WORK) if actor.active else None
    if row is None:
        return False
    return int((row.data or {}).get("declared", 1) or 0) == 1


@hook("damage_dice_reroll")
def seven_hammer_reroll(ctx: Any, row: dict[str, Any], kinds: list[str], dice_count: int) -> dict[str, int] | None:
    """"spend 1 Forge Mark to revise the strike. Reroll a number of damage dice up to your Proficiency Bonus and use
    the new rolls. ... If the workpiece is one you personally forged or prepared during the current day, also add
    your Intelligence modifier to the damage roll." One printed revision, so one answer: the mark is spent here and
    both halves land on this same packet.

    Both numbers are the SMITH's, never the striker's: ``ctx.numbers`` belongs to whoever rolled the damage, so when
    an ally strikes, reading the Proficiency Bonus or the key-ability modifier from there priced the revision with the
    ally's numbers and labelled them the smith's. The reroll is capped by the smith's Proficiency Bonus and the extra
    damage is the smith's own Intelligence modifier, and it is added only when the smith's own declaration says the
    marked workpiece is one they personally forged or prepared today.

    The declaration is read BEFORE the mark is spent, because spending the smith's last Forge Mark ends it
    (:func:`lapse_personal_work`), and the printed sentence is about the workpiece as it was when the revision was
    made.
    """
    if not printed_workpiece_attack(ctx, row):
        return None
    smith = _revision_smith(ctx)
    if smith is None or dice_count <= 0:
        return None
    from ..ability_checks import ability_modifier

    count = min(int(getattr(smith, "proficiency_bonus", 0) or 0), dice_count)
    if count <= 0:
        return None
    declared = personal_work(smith)
    spend_marks(ctx, smith, 1, SEVEN_HAMMER_REVISION)
    # The smith's own Intelligence modifier, read from the smith: passing the packet's numbers would let a striker's
    # ability modifiers answer for them.
    extra = int(ability_modifier(smith, "INT")) if declared else 0
    ctx.rider(f"Seven-Hammer Revision: {count} damage {'die' if count == 1 else 'dice'} rerolled and the new rolls used"
              + (f", plus {smith.display_name}'s {extra:+d} Intelligence modifier." if extra else "."))
    return {"reroll": count, "bonus": extra}
