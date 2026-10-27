"""Wax sphere: White Wax Edict of Stillness, the wax that will not let a hostile creature slip away (auto lane AUTO15, round 24).

Rules text (authority/typed_mechanics/rules_text.json, the owner's Wax entry) is the source:

* **White Wax Edict of Stillness** -- "Choose a 30-foot radius area within 120 feet. White wax seals spread across the
  ground, walls, weapons, and thresholds. Hostile creatures treat the area as Difficult Terrain. The first time each round a
  hostile creature attempts to teleport, become invisible, change shape, or pass through a sealed threshold inside the
  area, it must succeed on a Charisma saving throw or the attempt fails and the creature becomes impressed by the wax
  until the end of its next turn. On a successful save, the attempt works, but the creature still leaves a visible wax
  Impression at the point of departure."

The compiled area already carries the printed Difficult Terrain for hostiles (the typed zone's ``difficult: hostile``).
This module answers the four attempts the engine can see, all through existing seams:

* a **teleport** that begins inside the area -- ``teleport_check`` (combat/typed_executor.py ``_teleport``; the action and
  Cultivation Point are already spent, and returning False is exactly "the attempt fails");
* a typed attempt to **become invisible** or to **change shape** -- ``condition_attempt``, the seam every typed condition
  passes before it is applied. The engine has no separate shape-shift action, so a change of shape reaches this hook as the
  Polymorphed (or Petrified) condition it produces;
* **passing through a sealed threshold**: the wax covers the ground and the exits of its own area, so crossing out of the
  edict's wax is that crossing -- ``movement_attempt``, the same boundary veto gravity_boundary.py uses.

Every one of them is answered once per creature per round ("the first time each round"), against the owner's Cultivation
Save DC. A failure stops the attempt and leaves the creature impressed by the wax until the end of its next turn; a success
lets it go, and the printed wax Impression is left at the point of departure.

Three readings the review of this module (AUTO15f1) pinned down, because the hook contracts make them easy to get backwards:

* ``teleport_check`` answers **False** when the teleport fails (the contract in combat/ext/__init__.py), so a refused
  teleport has to return ``not <the save failed>``. Answering the save-failed flag itself lets the creature teleport away
  exactly when the wax stopped it, and blocks every later teleport of that round (whose answer is "already answered").
* The printed Impressed mark lasts "until the end of **its** next turn" -- the hostile creature's turn, not the wax
  owner's. The ``until_end_of_your_next_turn`` spelling is filed under the *placer* (typed_executor.marker_expiry ->
  END_OF_MARKER_NEXT_TURN, "until the end of its placer's next turn" in combat/status_text.py), which outlives the printed
  window by a round.
* The wax Impression is left on the square the creature left, as an inert one-square wax marker that lasts exactly as long
  as the edict area that made it.

A fourth clock came out of the AUTO15r1 review, and it is the reason this Edict's Impressed mark is placed here rather
than left to the sealed engine. ``until_end_of_next_turn`` is the rules table's name for the marked creature's own next
turn, but the engine can only *approximate* it: ``combat/gate2_engine.py`` takes END_OF_HOLDER_NEXT_TURN off at the end
of whichever turn the marked creature is currently taking, with no record of the turn it was marked on. Every attempt this
wax answers is an attempt the creature makes **on its own turn** (its own teleport, its own step out of the wax, its own
turn to go invisible), so the approximation took the mark off at the end of that very turn: the creature was "impressed
until the end of its next turn" for no time at all. ``holder_turn_impression`` below places the same mark through the
documented ``mark_apply`` seam with the exact deadline ``effect_durations.token("end", <the creature>, <its next
turn>)``, which the shared sweep removes at the end of that creature's Nth turn whether or not it is the one acting. It
answers only this Edict's own sentence (``st.feature_of(ctx.action) == EDICT``); any other ability's Impressed mark keeps
the ordinary mark path, so no future plug-in is captured by the wax.

The Sovereign's sentence counts a different creature's turn ("your Wax ... until the end of its next turn"), so
``impressed(owner, OWNER_TURN)`` hands the ordinary marker clock to it instead and no interception is needed.

Shared helper module (consumers: ``wax_reactions.py``, whose Thousand-Faced Wax Sovereign places the same printed Impressed
mark with the marker's own clock): ``impressed`` (with its two anchors, ``HOLDER_TURN`` and ``OWNER_TURN``) and the
``HOLDER_TURN``/``OWNER_TURN`` names.

Hooks used: ``teleport_check``, ``condition_attempt``, ``movement_attempt``, ``mark_apply``. Nothing here runs for a
creature that owns no Wax talent: each hook first asks whether the creature is hostile and standing inside one of the
actor's own edicts, and ``holder_turn_impression`` only answers this Edict's own marked row. Shared helpers used: ``zones``
(typed_zones/_inside/_hostile), ``spirit_traditions`` (feature_of/feature_action/context/numbers/save), ``effect_durations``,
``typed_reactor`` note. The only things stored are one integer round number per creature in its turn flags and the mark's
expiry name (a string the shared sweep already removes).
"""

from __future__ import annotations

from typing import Any

from . import hook, note, run_strict
from . import spirit_traditions as st

EDICT = "TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"
EDICT_ROUND = "wax_edict_round"
IMPRESSION = "system:combat.wax_impression"
IMPRESSED = "Impressed"
HOLDER_END = "END_OF_HOLDER_NEXT_TURN"
HOLDER_TURN = "until_end_of_next_turn"
OWNER_TURN = "until_end_of_your_next_turn"
SHAPE_CONDITIONS = ("polymorphed", "petrified")


def _edict_for(engine: Any, creature: Any) -> tuple[Any, Any] | None:
    """The (owner, edict area) pair this hostile creature is standing in, if any."""
    from .. import zones

    for owner_id, owner in sorted(engine.state.actors.items()):
        if owner is creature or not owner.active or creature.team_id == owner.team_id:
            continue
        for zone in zones.typed_zones(engine):
            if zone.owner_id != owner.entity_id or EDICT not in str(zone.source_definition_id):
                continue
            if zones._inside(engine, creature, zone):
                return owner, zone
    return None


def _already_answered(engine: Any, creature: Any) -> bool:
    return creature.turn_flags.get(EDICT_ROUND) == engine.state.round_number


def impressed(owner: Any, anchor: str = HOLDER_TURN) -> list[dict[str, Any]]:
    """The printed outcome of a failed save: the creature is impressed by the wax until the end of its next turn.

    ``anchor`` says whose next turn the printed sentence counts, because the wax prints two:

    * ``HOLDER_TURN`` ("until_end_of_next_turn") -- the creature that carries the mark. This is the White Wax Edict's
      "the creature becomes impressed by the wax until the end of **its** next turn", and every attempt the edict
      answers happens on the creature's own turn.
    * ``OWNER_TURN`` ("until_end_of_your_next_turn") -- the marker's own next turn, which the rules table already
      names and the ordinary mark path keeps (typed_executor.marker_expiry -> END_OF_MARKER_NEXT_TURN, swept by
      typed_executor.expire_marks). This is the Thousand-Faced Wax Sovereign's "the attacker becomes impressed by your
      Wax until the end of your next turn" -- the printed sentence says *your*, so the Wax owner's turn is the one counted,
      and the Sovereign is answered on the attacker's turn, so the attacker's clock is not the printed one. (This Edict's
      own sentence above says *its*; the two are different sentences and keep different anchors.)

    Soft Spread's own "impressed by the wax until the end of **your** next turn" is typed ``OWNER_TURN`` as well, which
    is why the wax spells its own pronoun the way it does.
    """
    whose = "your" if anchor == OWNER_TURN else "its own"
    return [{"type": "mark", "mark": IMPRESSED, "applies_to": "target",
             "duration": {"kind": anchor},
             "evidence": f"{owner.display_name}'s wax leaves it impressed until the end of {whose} next turn"}]


@hook("mark_apply")
def holder_turn_impression(ctx: Any, effect: dict[str, Any], subject: Any, expires: str, data: Any) -> bool | None:
    """"becomes impressed by the wax until the end of its next turn" -- the marked creature's own next turn, counted from
    the turn it was marked on.

    The rules table's "until_end_of_next_turn" becomes the sealed engine's END_OF_HOLDER_NEXT_TURN, which the engine takes off
    at the end of whichever turn the marked creature is taking *now*: a mark placed on a creature's own turn is gone before
    that turn ends. Every attempt this wax answers happens on the creature's own turn, so the approximation left the mark
    lasting no time at all. This places it with the exact turn number instead -- END_OF_TURN_AT:<creature>:<its next turn> --
    which combat/ext/effect_durations.py sweeps at the end of that creature's Nth turn.

    Only this Edict's and Melting Rebuke's printed recipient-next-turn sentences are answered: the mark name and the duration kind are checked first, then the
    ability the mark is being placed for. Another ability's Impressed mark -- a future plug-in, or a reviewed row outside
    this sphere -- keeps the ordinary mark path and its capacity, family and marker handling.
    """
    if str(effect.get("mark") or "") != IMPRESSED or expires != HOLDER_END:
        return None
    if str((effect.get("duration") or {}).get("kind") or "") != HOLDER_TURN or subject is None or not subject.active:
        return None
    if st.feature_of(ctx.action) not in (EDICT, "TAL_WAX_MELTING_REBUKE"):
        return None
    from .. import typed_executor
    from .effect_durations import token

    engine, owner = ctx.engine, ctx.actor.entity_id
    condition_id = typed_executor.mark_condition_id(IMPRESSED, owner)
    engine._remove_condition(subject, condition_id, ctx.source)  # re-marking refreshes rather than stacking
    engine._apply_condition(subject, condition_id, ctx.source, owner,
                            expires_on=token("end", subject.entity_id, int(subject.turns_started) + 1), data=data)
    run_strict("mark_applied", ctx, IMPRESSED, subject)
    return True


def _square(where: Any) -> str:
    """The square the creature stood on, in the table's usual "(x, y)" map notation."""
    return f" ({where.x}, {where.y})" if getattr(where, "x", None) is not None else ""


def _impression(engine: Any, owner: Any, edict: Any, where: Any) -> None:
    """"On a successful save, the attempt works, but the creature still leaves a visible wax Impression at the point of
    departure." One inert square of wax where the creature stood, on the edict's own clock. It carries no terrain policy,
    no triggers and no inside effects, so it is a mark on the battlefield to look at, nothing more."""
    from .. import zones
    from ..gate2_runtime_models import ZoneState

    if getattr(where, "x", None) is None:
        return
    zone_id = f"zone:wax:impression:{owner.entity_id}:{engine.state.event_sequence + 1}"
    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id=IMPRESSION, owner_id=owner.entity_id, center=where,
        radius_cells=0, affected_cells=(where,), concentration_link=False,
        duration_rounds=int(edict.duration_rounds or 0) or None, created_round=int(edict.created_round),
        trigger_profile={"kind": zones.KIND, "name": "Wax Impression", "difficult": None,
                         "visual": {"material": "wax"}, "follows_owner": False, "triggers": [], "inside": [],
                         "numbers": {}, "evidence": "White Wax Edict of Stillness: the creature leaves a visible wax Impression where it left the wax"})
    engine._append_event("ZONE_CREATED", EDICT, actor_id=owner.entity_id,
                         payload={"zone": engine.state.zones[zone_id].model_dump(mode="json")})
    zones.sync_inside(engine, EDICT)


def _ask_the_wax(engine: Any, creature: Any, owner: Any, action: Any, attempt: str, where: Any,
                 edict: Any = None) -> bool:
    """Roll the printed Charisma save. Returns True when the attempt fails (the creature is held) and the round is spent."""
    if _already_answered(engine, creature):
        return False  # "the first time each round": later attempts that round go through unanswered
    creature.turn_flags[EDICT_ROUND] = int(engine.state.round_number)
    numbers = st.numbers(engine, owner)
    ctx = st.context(engine, owner, action, [creature], numbers=numbers)
    failed = st.save(ctx, creature, "cha", on_fail=impressed(owner))
    if failed:
        note(engine, EDICT, owner,
             f"White Wax Edict of Stillness: {creature.display_name} fails the save and cannot {attempt}.", (creature,))
        return True
    note(engine, EDICT, owner,
         f"White Wax Edict of Stillness: {creature.display_name} slips free, but leaves a wax mark behind"
         f"{_square(where)}.", (creature,))
    if edict is not None:
        _impression(engine, owner, edict, where)
    return False


def _action(engine: Any, owner: Any) -> Any:
    return st.feature_action(engine, owner, EDICT)


# ------------------------------------------------------------------------------- "attempts to teleport"
@hook("teleport_check")
def teleport_refused(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    """"The first time each round a hostile creature attempts to teleport ... it must succeed on a Charisma saving throw or the
    attempt fails" -- the teleport does not happen when the wax wins the roll.

    teleport_check answers False for a self-teleport that fails (combat/ext/__init__.py), so refusing the creature is the
    negation of "the save failed". Answering the save-failed flag itself did the opposite of both printed lines: a creature
    the wax stopped teleported away, and every later teleport of that round -- whose answer is "already answered" -- was
    blocked.
    """
    found = _edict_for(engine, actor)
    if found is None or not actor.active:
        return None
    owner, zone = found
    return not _ask_the_wax(engine, actor, owner, _action(engine, owner), "teleport away", start, zone)


# ------------------------------------------------------------- "become invisible, change shape"
@hook("condition_attempt")
def shapes_refused(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """"... become invisible, change shape ..." -- a typed attempt at either, by the creature itself, is stopped before it
    applies when the wax wins the save."""
    engine = ctx.engine
    name = str(effect.get("condition") or "").lower()
    if name != "invisible" and name not in SHAPE_CONDITIONS:
        return None
    if ctx.actor is not subject or not subject.active:
        return None  # only the creature's own attempt; someone else transforming it is not this clause
    found = _edict_for(engine, subject)
    if found is None:
        return None
    owner, zone = found
    attempt = "become invisible" if name == "invisible" else "change shape"
    # condition_attempt vetoes by answering False, so the printed "the attempt fails" is the answer to withhold.
    return not _ask_the_wax(engine, subject, owner, _action(engine, owner), attempt, subject.position, zone)


# ----------------------------------------------------------------- "pass through a sealed threshold"
@hook("movement_attempt")
def threshold_refused(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """"... or pass through a sealed threshold inside the area": the wax seals the ground and the exits of its own area, so a
    hostile creature trying to step out of it stops at the wax when the save fails."""
    from .. import zones

    if not mover.active:
        return None
    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or mover.team_id == owner.team_id or EDICT not in str(zone.source_definition_id):
            continue
        if not zones._inside(engine, mover, zone, position=previous) or zones._inside(engine, mover, zone, position=nxt):
            continue
        if _ask_the_wax(engine, mover, owner, _action(engine, owner), "step out of the edict", previous, zone):
            return {"stop": True, "source_id": EDICT,
                    "label": "White Wax Edict of Stillness: the wax seals this threshold and the creature cannot pass"}
        return None
    return None
