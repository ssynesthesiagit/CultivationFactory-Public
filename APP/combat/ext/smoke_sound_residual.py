"""The A2R04 residual contract: the Smoke and Sound residual rows (2026-10-12).

Every effect below is registered under its own typed effect type or a documented
hook, and is inert for characters that do not own the row: a plug-in's own effect
types dispatch only from the typed rows that carry them, and the Smoke Mirror Trail
hook asks combat/ext/fight_ownership.py ``owns_feature`` before it does anything, so
no other character, ability or old saved fight changes.

Rows resolved here (docs/plans/AUTOMATION_TRUTH_R1.json, mechanics-007.json):

  Ten-Thousand Echoes Field, "Failed Save: The creature must choose either lose its
  Reaction until the start of its next turn or treat all spaces more than 30 feet
  away as lightly obscured by echo confusion until the start of its next turn."
  The failed-save ``echoes_save_choice`` effect is the creature's own choice -- a
  player is asked, an AI answers for itself -- and applies exactly one of the two
  printed results, expiring at the start of the affected creature's next turn.

  Resonant Note, "the target cannot benefit from ordinary sound-based hiding until
  the start of your next turn." The ``sound_hiding_denied`` rider marks the target
  with a scoped hiding denial. Native Hide records its supporting senses;
  sound-only attempts fail and existing sound-only Hidden benefits are masked
  in perception and attacks. Independent visual hiding and check bonuses remain.

  Smoke Mirror Trail, "When one creature inside your Smoke Veil becomes Invisible,
  successfully Hides, teleports, or leaves the veil without using normal movement,
  you may place a Smoke Trace on it without using your once-per-round Smoke Trace.
  Until that trace ends, you know the direction to the target while it remains
  within 120 feet." The strict ``state_event`` hook answers the printed triggers
  from the engine's own records -- a creature inside the owner's veil turning
  Invisible, a successful Hide, or teleporting out of the veil -- and places the
  Smoke Trace after each eligible owner accepts (the owner's own mark id, so it
  does not spend the once-per-round placement). Direction knowledge links to that
  exact trace instance and is removed on its native removal receipt.
  A forced move that ends outside the veil is the same "leaves the veil without
  using normal movement" trigger. The one printed trigger this table cannot observe
  from a committed record -- a creature walking out of the veil, which is ordinary
  movement and therefore not a trigger at all -- needs no hook, and no trigger
  fires for it.

  Forbidden Silence Field, "Inside the area: ordinary sound cannot be created or
  pass through." The ``sound_path_allowed`` hook answers the transmission half of
  that line: the engine's hearing routes (combat/speech.can_hear_from) ask it,
  so a creature on one side of the Field never hears a creature on the other,
  and ordinary sound whose path crosses the Field's own squares never reaches
  either bank. The "created" half is the Field's own ``silenced`` inside rule
  (a voice-needing ability fails inside), and every creature inside is already
  Deafened by the Field's ``cant_hear`` inside rule, so nothing is created that
  could be heard from inside either.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from ..typed_executor import CONDITION_PREFIX, mark_condition_id

#: The printed rows this module resolves, named for the evidence a reader needs.
ECHOES_FIELD_ID = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
RESONANT_NOTE_ID = "TAL_SOUND_RESONANT_NOTE"
MIRROR_TRAIL_ID = "TAL_SMOKE_SMOKE_MIRROR_TRAIL"

#: The two results the failed Ten-Thousand Echoes save chooses between.
LOSE_REACTION = "lose_reaction"
ECHO_CONFUSION = "echo_confusion"

#: The direction knowledge Smoke Mirror Trail records on its tracer, naming the
#: traced creature and the printed 120-foot reach. It is owned state like
#: Soot-Scent Trail's, and expires with the trace it describes.
MIRROR_TRACE_CONDITION = "condition:typed.mirror_trail"
MIRROR_RANGE_FT = 120

#: Smoke Mirror Trail's own feature-block row (combat/rules/feature_blocks.d/
#: auto43_smoke.json). The printed trigger compiles to no action or reaction
#: row of its own, so the row exists to record ownership: the mirror_trail
#: event hook asks combat/ext/fight_ownership.py owns_feature, which reads
#: this row from this fight's own compiled passives.
MIRROR_BLOCK = "smoke_mirror_trail"


@hook("compile_block")
def mirror_trail_block(block: str, spec: dict[str, Any], row: dict[str, Any],
                       numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Smoke Mirror Trail's ownership row (see MIRROR_BLOCK).

    One row per owner, carrying nothing but the block: the trigger itself is
    answered by the :func:`mirror_trail` event hook from the engine's own
    committed records, so the row holds no numbers and no effects of its own."""
    if block != MIRROR_BLOCK:
        return None
    return [{**row, "block": MIRROR_BLOCK, "choice_owner": True}]


@effect("echoes_save_choice")
def echoes_save_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """Ten-Thousand Echoes Field's failed-save choice.

    The creature that failed the Wisdom save chooses one of the two printed
    results. The choice is the creature's own: a player is asked, an AI answers
    for itself (``needle.ask`` with ``automatic=True``). The printed choice is
    mandatory, so a creature nobody answers for takes the first result -- losing
    its Reaction -- rather than neither."""
    subject = ctx.target
    if subject is None or not subject.active:
        return
    engine = ctx.engine
    from .needle import ask, checkpoint_id

    chosen = ask(engine, getattr(engine, "_active_intent", None),
                    checkpoint_id(engine, "echoes_save_choice", ctx.actor.entity_id, subject.entity_id),
                    subject, "choice:needle.echoes_save_choice",
                    [LOSE_REACTION, ECHO_CONFUSION],
                    automatic=True, target_id=subject.entity_id,
                    name="Ten-Thousand Echoes Field", feature_id=ECHOES_FIELD_ID,
                    labels={
                        LOSE_REACTION: ("Lose your Reaction until the start of your next turn "
                                        "(you cannot take Reactions)"),
                        ECHO_CONFUSION: ("Treat all spaces more than 30 feet away as lightly "
                                          "obscured by echo confusion until the start of "
                                          "your next turn"),
                    },
                    prompt=(f"Ten-Thousand Echoes Field: {subject.display_name} failed its Wisdom save. "
                            f"Choose one: lose your Reaction until the start of your next turn, or treat "
                            f"all spaces more than 30 feet away as lightly obscured by echo confusion "
                            f"until the start of your next turn."))
    from .effect_durations import holder_next_turn

    expires = holder_next_turn(subject)
    source = f"passive:{ECHOES_FIELD_ID}"
    if ECHO_CONFUSION in chosen:
        # The typed condition is the source of the distance-conditioned
        # obscurement read by echoes_search_mode below. Keep the printed range
        # with the condition so the rule remains data-driven and expires with
        # the affected creature's turn.
        engine._apply_condition(subject, CONDITION_PREFIX + ECHO_CONFUSION, source, ctx.actor.entity_id,
                                    expires_on=expires,
                                    data={"label": "Echo Confusion",
                                          "reading": ("Treat all spaces more than 30 feet away as "
                                                      "lightly obscured by echo confusion until the "
                                                      "start of the creature's next turn."),
                                          "obscured_beyond_ft": 30})
    else:
        # "lose its Reaction until the start of its next turn": the typed
        # reaction_denied condition (combat/rules/typed_conditions.json:
        # {"no_reactions": true}), applied exactly the way the core
        # reaction_denied effect applies it (combat/typed_executor.py
        # block_condition), so the creature really cannot take Reactions.
        engine._apply_condition(subject, CONDITION_PREFIX + "reaction_denied", source, ctx.actor.entity_id,
                                    expires_on=expires,
                                    data={"label": "Echoes: Reaction Denied"})
        subject.reaction_available = False


@effect("sound_hiding_denied")
def sound_hiding_denied(ctx: Any, eff: dict[str, Any]) -> None:
    """Resonant Note's sound-hiding rider.

    "The target cannot benefit from ordinary sound-based hiding until the start
    of your next turn." Deny auditory hiding rather than penalizing the check.
    The native procedure and shared perception/attack mask read the same held
    rule. Independent visual concealment and unrelated Stealth bonuses remain.
    The mark lasts until the start of the Resonance owner's next turn."""
    subject = ctx.target
    if subject is None or not subject.active:
        return
    engine = ctx.engine
    source = f"passive:{RESONANT_NOTE_ID}"
    engine._apply_condition(subject, CONDITION_PREFIX + "sound_hiding_denied", source, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"rule": {"hiding_denied": ["sound_reliance"]},
                                      "label": (f"Resonant Note: {subject.display_name} cannot benefit from "
                                                f"ordinary sound-based hiding until the start of "
                                                f"{ctx.actor.display_name}'s next turn.")})


@hook("masked_conditions")
def sound_hiding_masks(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]]:
    """Deny existing auditory Hidden benefits in both perception and attacks.

    The native Hide producer records its supporting senses. An independent
    visual hiding basis or an ordinary Invisible condition remains effective.
    """
    from ..stealth import HIDDEN, hiding_denied

    return {actor.entity_id: {iid for iid, condition in actor.conditions.items()
                             if condition.condition_id == HIDDEN
                             and hiding_denied(actor, tuple((condition.data or {}).get("hiding_basis", "").split(",")))}
            for actor in (attacker, target)}


def _veil_owners(engine: Any) -> list[Any]:
    """Every active creature that owns Smoke Mirror Trail in this fight."""
    from .fight_ownership import owns_feature

    return [owner for owner in engine.state.actors.values()
            if owner.active and owns_feature(engine, owner, MIRROR_TRAIL_ID)]


def _inside_owner_veil(engine: Any, owner: Any, creature: Any, at: Any = None) -> Any | None:
    """The owner's Smoke Veil that contains ``creature`` (at ``at``, else its square)."""
    from .smoke_veil import veils
    from ..spatial_areas import zone_contains

    if not creature.active:
        return None
    for zone in veils(engine, owner):
        if zone_contains(engine, creature, zone, at=at):
            return zone
    return None


def _place_mirror_trace(engine: Any, owner: Any, creature: Any) -> None:
    """Smoke Mirror Trail's placement: a Smoke Trace on ``creature`` that does not
    spend the owner's once-per-round Smoke Trace, plus the direction knowledge on
    the tracer. The ordinary placement executor controls duration; direction
    knowledge has no independent deadline and ends with that exact trace.
    Re-marking refreshes the
    trace exactly as the engine's own mark placement does (combat/typed_executor
    ``block_mark`` removes the prior instance first), so a creature that triggers
    twice keeps one trace, and ``expire_marks`` removes both through the engine
    so the removals replay."""
    source = f"passive:{MIRROR_TRAIL_ID}"
    marker_turn = int(owner.turns_started)
    mark_id = mark_condition_id("Smoke Trace", owner.entity_id)
    from ..typed_executor import Context, block_mark
    from .rider_choices import intent_for

    action = next((a for a in engine.action_catalog.values()
                   if a.owner_id == owner.entity_id
                   and a.source_definition_id.endswith(".smoke.place_trace")), None)
    if action is None:
        return
    typed = action.parameters.get("typed") or {}
    ctx = Context(engine, owner, action, intent_for(engine), typed, [creature],
                  target=creature, effect_source=source)
    # Share duration/cap/family/application/notification handling; only the
    # separate smoke_trace_round_use effect is exempted by the printed trigger.
    placement = next(e for e in typed["effects"] if e.get("type") == "mark")
    block_mark(ctx, placement)
    trace = next((c for c in creature.conditions.values() if c.condition_id == mark_id), None)
    if trace is None:
        return  # an application override may decline or redirect placement
    engine._apply_condition(owner, MIRROR_TRACE_CONDITION, source, owner.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"marker_turn": marker_turn, "target_id": creature.entity_id,
                                      "trace_instance_id": trace.instance_id,
                                      "range_ft": MIRROR_RANGE_FT,
                                      "label": (f"Smoke Mirror Trail: you know the direction to "
                                                f"{creature.display_name} while it remains within "
                                                f"{MIRROR_RANGE_FT} feet, until the trace ends.")})


def _position_from_json(cell: Any) -> Any | None:
    """Rebuild a Position from a committed movement path cell (a JSON dict)."""
    from ..gate2_runtime_models import Position

    if isinstance(cell, Position):
        return cell
    if isinstance(cell, dict) and "x" in cell and "y" in cell:
        return Position(x=int(cell["x"]), y=int(cell["y"]), z=int(cell.get("z") or 0))
    return None


@hook("state_event")
def mirror_trail(engine: Any, event: Any) -> None:
    """Smoke Mirror Trail's triggers, answered from the engine's own committed records.

    The printed trigger is a creature inside the owner's Smoke Veil becoming
    Invisible, successfully Hiding, teleporting, or leaving the veil without using
    normal movement. The first two are the Invisible and successful Hide conditions
    the engine already records; the last two are committed moves that did not use
    the creature's own walking allowance -- a teleport (``payload.teleport``) or a
    forced move (``payload.forced``) that began inside the veil and ended outside
    it. A walk out of the veil is ordinary movement, which the printed line does
    not count, so it never triggers."""
    event_type = event.event_type
    payload = event.payload or {}
    if event_type == "CONDITION_REMOVED":
        # An exact-instance link keeps independent targets and later replacements
        # separate. Spending, expiry and explicit removal use the same native seam.
        for owner in engine.state.actors.values():
            for iid, direction in list(owner.conditions.items()):
                if (direction.condition_id == MIRROR_TRACE_CONDITION
                        and direction.data.get("trace_instance_id") == payload.get("instance_id")):
                    engine._remove_condition_instance(owner, iid, f"passive:{MIRROR_TRAIL_ID}")
        return
    creature_id: str | None = None
    start: Any = None
    leaving: bool = False

    if event_type == "CONDITION_APPLIED" and payload.get("condition_id") in {
            "condition:typed.invisible", "condition:typed.hidden"}:
        # Native Hide applies Hidden only after its successful check. A successful
        # Stealth check for Soot-Scent escape never applies this condition.
        creature_id = (event.target_ids or (None,))[0]
    elif event_type == "MOVEMENT_COMMITTED":
        creature_id = event.actor_id
        path = payload.get("path") or []
        if path:
            start = _position_from_json(path[0])
        # Only a committed move that did not use the creature's own
        # walking allowance counts: a teleport, or a forced move.
        leaving = bool(payload.get("teleport")) or bool(payload.get("forced"))
    else:
        return
    if creature_id is None:
        return
    if event_type == "MOVEMENT_COMMITTED" and not leaving:
        return  # ordinary walking, which the printed line does not count

    creature = engine.state.actors.get(creature_id)
    if creature is None or not creature.active:
        return
    for owner in _veil_owners(engine):
        # Invisible, Hide and teleport read the square the creature was on
        # when the trigger fired; a forced exit reads the square it left.
        at = start if start is not None else creature.position
        if _inside_owner_veil(engine, owner, creature, at=at) is None:
            continue
        # A forced move that is still inside the veil did not leave it.
        # A teleport triggers on the teleport itself, wherever it lands.
        if (start is not None and not payload.get("teleport")
                and _inside_owner_veil(engine, owner, creature, at=creature.position) is not None):
            continue
        from .needle import ask, checkpoint_id
        from .rider_choices import intent_for

        trigger = ("successfully hid" if payload.get("condition_id") == "condition:typed.hidden"
                   else "became Invisible" if event_type == "CONDITION_APPLIED"
                   else "teleported" if payload.get("teleport") else "left the veil by forced movement")
        picked = ask(engine, intent_for(engine),
                     checkpoint_id(engine, "mirror_trail", owner.entity_id,
                                   creature.entity_id, str(event.sequence)),
                     owner, "choice:needle.mirror_trail", ["place_trace"],
                     automatic=True, allow_decline=True, target_id=creature.entity_id,
                     name="Smoke Mirror Trail", feature_id=MIRROR_TRAIL_ID,
                     labels={"place_trace": f"Place a free Smoke Trace on {creature.display_name}"},
                     prompt=(f"Smoke Mirror Trail: {creature.display_name} {trigger} inside your Smoke Veil. "
                             "Place a Smoke Trace for no action or resource cost, without using your "
                             "once-per-round placement, or decline. Until this trace ends, you know "
                             "the target's direction while it is within 120 feet."))
        if picked:
            _place_mirror_trace(engine, owner, creature)


#: The source id the post-sound step's granted movement is stamped with.
ECHOES_STEP = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
ECHOES_STEP_FT = 5  # "may move 5 feet without provoking opportunity attacks"


def _echoes_field_owners(engine: Any) -> list[Any]:
    """Every active creature that owns Ten-Thousand Echoes Field in this fight."""
    from .fight_ownership import owns_feature

    return [owner for owner in engine.state.actors.values()
            if owner.active and owns_feature(engine, owner, ECHOES_FIELD_ID)]


def _inside_echoes_field(engine: Any, owner: Any, ally: Any) -> Any | None:
    """The owner's Ten-Thousand Echoes Field that contains ``ally``.

    The printed line is for allies inside, so a creature hostile to the
    Field's owner (an enemy) never earns the step, matching the engine's
    own "ally" recipient rule for the Field's other inside effects."""
    from .. import zones
    from ..spatial_areas import zone_contains

    if not ally.active:
        return None
    for zone in zones.typed_zones(engine):
        if zone.owner_id != owner.entity_id:
            continue
        if ECHOES_FIELD_ID not in str(zone.source_definition_id or ""):
            continue
        if (zone.trigger_profile or {}).get("name") != "Ten-Thousand Echoes Field":
            continue
        if not zone.active:
            continue
        if zones._hostile(engine, zone, ally):
            continue  # an enemy of the Field's owner, not an ally
        if zone_contains(engine, ally, zone):
            return zone
    return None


@hook("stealth_search_mode")
def echoes_search_mode(engine: Any, searcher: Any, hidden_foe: Any) -> str | None:
    """Echo Confusion lightly obscures spaces more than 30 feet from its holder.

    Search is a Wisdom (Perception) check made using sight and hearing. When a
    creature chose Echo Confusion, a hidden creature beyond the printed range
    is lightly obscured from that searcher, giving the check Disadvantage. The
    existing target-specific Search hook keeps creatures at or within 30 feet
    and every other kind of check unchanged.
    """
    from ..typed_executor import CONDITION_PREFIX

    condition = next((row for row in searcher.conditions.values()
                      if row.condition_id == CONDITION_PREFIX + ECHO_CONFUSION), None)
    if condition is None or not searcher.active or not hidden_foe.active:
        return None
    distance_limit = (condition.data or {}).get("obscured_beyond_ft")
    if type(distance_limit) is not int or distance_limit < 0:
        return None
    if engine.grid.distance_ft(searcher.position, hidden_foe.position) > distance_limit:
        return "DISADVANTAGE"
    return None


@hook("action_completed")
def echoes_step(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """Ten-Thousand Echoes Field's post-sound step.

    "Allies inside: may move 5 feet without provoking opportunity attacks
    after using a Sound talent, once per turn." The step is offered after
    the ally's own Sound talent resolves: a player is asked for the
    destination (and may decline), an AI answers for itself. The five
    feet are a granted budget of their own (combat/granted_movement
    .resolve_path with ``provokes=False``: the engine exempts every
    reactor for exactly those five feet), so the ally's ordinary movement
    keeps provoking normally afterwards."""
    from .. import granted_movement
    from .needle import ask, checkpoint_id
    from .rider_choices import intent_for

    action = engine.action_catalog.get(source_definition_id)
    if action is None:
        return
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("sphere") != "tianxia.sphere.sound":
        return  # only a Sound talent earns the step
    if not actor.active:
        return
    for owner in _echoes_field_owners(engine):
        if _inside_echoes_field(engine, owner, actor) is None:
            continue
        # Once per turn for this ally: the flag is a plain string (the
        # persistence rule keeps fight state to integers and strings), so
        # the once-per-turn guard survives a table commit and a cold reload.
        key = f"{engine.state.round_number}:{actor.entity_id}:{actor.turns_started}"
        if actor.turn_flags.get("echoes_step_round_") == key:
            return  # already stepped this turn
        intent = intent_for(engine)
        if intent is None:
            return
        paths = granted_movement.candidates(engine, actor, ECHOES_STEP_FT, intent, ECHOES_STEP)
        if not paths:
            return
        picked = ask(engine, intent,
                        checkpoint_id(engine, "echoes_step", owner.entity_id, actor.entity_id),
                        actor, "choice:needle.echoes_step", list(paths),
                        automatic=True, allow_decline=True, default="decline",
                        target_id=actor.entity_id,
                        name="Ten-Thousand Echoes Field", feature_id=ECHOES_FIELD_ID,
                        labels={key_: f"Move 5 feet to {cell} without provoking opportunity attacks"
                                 for key_, cell in _path_labels(engine, paths).items()},
                        prompt=(f"Ten-Thousand Echoes Field: {actor.display_name} used {action.display_name} "
                                f"inside the Field and may move 5 feet without provoking "
                                f"opportunity attacks. Choose a destination, or decline."))
        if not picked:
            return  # declined: no step, and the printed "once per turn" is not spent
        actor.turn_flags["echoes_step_round_"] = key
        granted_movement.resolve_path(engine, actor, paths[picked[0]].canonical_path,
                                       ECHOES_STEP, feet=ECHOES_STEP_FT, intent=intent,
                                       provokes=False)
        return


#: The printed name of the Forbidden Silence Field's area, and its mechanic id.
SILENCE_FIELD_ID = "TAL_SOUND_FORBIDDEN_SILENCE_FIELD"
SILENCE_FIELD_NAME = "Forbidden Silence Field"


def _silence_fields(engine: Any) -> list[Any]:
    """Every active Forbidden Silence Field on the map."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.active
            and (zone.trigger_profile or {}).get("name") == SILENCE_FIELD_NAME]


@hook("sound_path_allowed")
def silence_field_path(engine: Any, speaker: Any, listener: Any, source: str) -> bool | None:
    """Forbidden Silence Field's transmission rule: ordinary sound cannot be
    created inside the Field or pass through it.

    The engine's hearing routes ask this hook (combat/speech.can_hear_from,
    shared by the recipient routes), so a creature on one side of the Field
    never hears a creature on the other, and ordinary sound whose path
    crosses the Field's own squares never reaches either bank. A creature
    inside the Field is already Deafened by the Field's ``cant_hear`` inside
    rule, so the inside bank needs no separate answer: the hook answers the
    path itself, for every speaker and listener, and for every Field on the
    map. Other areas and every other path answer exactly as before."""
    from .. import zones
    from ..gate2_runtime_models import Position
    from ..space import ray
    from ..typed_executor import in_area

    for zone in _silence_fields(engine):
        inside_speaker = zones._inside(engine, speaker, zone)
        inside_listener = zones._inside(engine, listener, zone)
        if inside_speaker != inside_listener:
            return False  # opposite banks of the Field: sound cannot cross it
        if not inside_speaker:
            # Neither is inside: ordinary sound still cannot pass through it.
            radius_ft = int(zone.radius_cells) * int(engine.grid.square_size_ft)
            if any(in_area(engine, zone.center, zone.center,
                                Position(x=x, y=y, z=z),
                                {"shape": "sphere", "size_ft": radius_ft})
                   for x, y, z in ray(speaker.position, listener.position)[1:-1]):
                return False
    return None


def _path_labels(engine: Any, paths: dict[str, Any]) -> dict[str, str]:
    """Readable destination labels for the offered step cells."""
    labels: dict[str, str] = {}
    for key, candidate in paths.items():
        destination = getattr(candidate, "destination", None)
        if destination is None:
            labels[key] = key
            continue
        labels[key] = f"{destination.x},{destination.y}" + (
            f",{destination.z}" if getattr(destination, "z", 0) else "")
    return labels
