"""Source sphere automation (AUTO7 2026-10-04, review fixes AUTO7f1 2026-10-04).

The Source sphere's guard talents and its ground sense, made from printed text
(APP/authority/typed_mechanics/rules_text.json) into engine-resolved rules. Typed
data lives in ``authority/typed_mechanics/reviewed_final.d/source.json``; the block
report in ``combat/rules/feature_blocks.d/source.json``. Nothing here names a
creature, an ability id in a core file, or a saved-fight field, and every hook is
inert for a character that does not own the row it reads.

The printed Source guards all limit *where the damage came from*, and the two
guards do not name the same places, so each reads its own list:

- **Mine-Shelter Reflex** -- "damage from a trap, collapse, falling stone, burst
  crystal, mining hazard, or source-stone discharge". The table delivers a Trap
  through the Trap sphere's own buttons and a collapse or a falling stone as a
  fall, and both declare that general class of hazard in the shared delivery
  record (``combat/ext/damage_delivery.py``). Everything else -- a sword, an
  arrow, a fireball -- is left alone.
- **Source Skin** -- "damage from a stone, crystal, sand, earth, or mineral
  environmental hazard". That is narrower: a dart trap's Piercing dart and a
  creature's own fall are neither, so they do not answer it. What does is a
  standing area of mineral ground (Obsidian Terrain's Slashing wound, for
  instance), read from the delivering area's own painted terrain. Source Skin's
  other printed clause ("Advantage on saving throws against being Petrified") is
  standing state and is data, not a hook: a ``defense`` row of kind
  ``save_advantage`` in ``rules/feature_blocks.d/source.json``, the same shape
  Golden Mandate Vessel uses.

- **Old Mine Shelter Scripture** -- "When you use Mine-Shelter Reflex, you may
  choose one willing creature within 5 feet of you. That creature also gains
  Resistance to the same triggering damage." The printed text hangs the whole
  benefit on one *use* of that Reaction, and on the damage that use answered, so an
  accepted and paid Mine-Shelter Reflex stands a mark on its owner naming the hazard,
  the thing delivering, that one activation of it and the wound it answered. The
  shared Resistance answers only that activation, of that same delivery, to one
  accepted creature -- the question is put at the last moment, once the creature's reach
  and its owner's free Reaction have both been checked, so nobody is asked about a
  creature that could not have been sheltered. An accepted creature spends the mark,
  because "one willing creature" is how many creatures one use may protect; passing on
  one creature spends nothing, so the next creature of the same springing may still be
  sheltered. What stops a later springing from inheriting an unanswered mark is the
  activation named in it, which the fight's own journal keeps distinct across a table
  commit and reload, not the question going unanswered.
- **Quarry Walker** -- "You ignore nonmagical difficult terrain caused by loose
  stone, scree, rubble, gravel, broken tile, mine spoil, or uneven worked stone."
  ``difficult_zone_exempt`` excuses the map's difficult squares whose named
  terrain is stony, so mud, ice, water, plant growth and crowding keep costing
  what they cost anyone else, and an area made by an ability keeps costing too
  (the printed "nonmagical"). It is asked about one area at a time, so a
  magical stone area laid over stony ground still costs, which a plain list of
  exempt squares could not tell apart.
- **Source Circuit** -- "the Speed reduction from that Source Pulse becomes 20
  feet instead of 10 feet". Source Pulse's own Speed row is this module's
  ``source_pulse_slow`` effect, which reads the circuit the Source Circuit action
  put on its owner; without a circuit it is exactly the printed 10 feet. The
  printed "ends early if you are Incapacitated" is the shared
  ``ends_if_incapacitated`` marker, in the typed record beside this effect.
"""

from __future__ import annotations

from typing import Any

from . import damage_delivery as delivery, effect, hook, note

BLOCK = "source_ward"
SHELTER = "source_shelter"

REFLEX = "tianxia.talent.source.mine_shelter_reflex"
SKIN = "tianxia.talent.source.source_skin"
SHELTER_FEATURE = "tianxia.talent.source.old_mine_shelter_scripture"
CIRCUIT_FEATURE = "tianxia.talent.source.source_circuit"
PIN = "tianxia.talent.source.heaven_sealing_source_pin"
PIN_SAVED = "source_pin_saved"  # per zone: round/initiative slot of this creature's last save

#: Mine-Shelter Reflex's printed trigger ("a trap, collapse, falling stone, burst crystal, mining
#: hazard, or source-stone discharge") as the table delivers those things: a Trap through the Trap
#: sphere's own buttons, a collapse or falling stone as a fall. Both hazard classes are declared by
#: the delivery sites in combat/ext/damage_delivery.py, not guessed from an id here.
REFLEX_HAZARDS = (delivery.TRAP, delivery.FALLING)

#: Source Skin's printed trigger names only mineral ground -- "a stone, crystal, sand, earth, or
#: mineral environmental hazard" -- so it answers a standing area of that ground and nothing else.
SKIN_HAZARDS = (delivery.AREA,)

#: The printed words of Source Skin's mineral ground and Quarry Walker's stony ground, matched
#: against a named terrain's own name and material (APP/combat/rules/terrain.json).
MINERAL_TERRAIN = ("stone", "rock", "obsidian", "crystal", "jade", "ore", "mineral", "sand",
                   "earth", "dirt", "soil", "gravel", "rubble", "scree", "brick", "tile", "marble", "basalt")
STONY_TERRAIN = ("rubble", "scree", "gravel", "stone", "rock", "ore", "brick", "tile", "crystal", "jade", "spoil")

#: The mark one paid use of Mine-Shelter Reflex leaves on its owner, as
#: "<hazard>|<thing delivering>|<activation>|<damage type>": it answers one activation of one hazard to
#: one accepted creature, and nothing else. A turn flag is cleared for its owner at the start of that
#: owner's next turn (combat/gate2_engine.py), it is a string, so it saves, reloads and stays inside the
#: table's own state, and the activation it carries (combat/ext/damage_delivery.py) is named from the
#: fight's own journalled length, so it cannot be matched by an activation that only begins after the
#: commit that saved the mark.
ARMED = "source_shelter_standing"

#: The printed "for 1 minute" of a circuit, in the round clock's own spelling, and the moment the
#: printed early ending is read.
CIRCUIT = "condition:typed.source_circuit"
CIRCUIT_ROUND = "source_circuit_round"  # "_round_": survives the turn reset (combat/ext/__init__.py)


# --------------------------------------------------------------------------------------- ownership
@hook("compile_block")
def source_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block == BLOCK:
        return [{**row, "block": BLOCK, "kind": spec.get("kind")}]
    if block == SHELTER:
        # "When you use Mine-Shelter Reflex, you may choose one willing creature within 5 feet of you.
        # That creature also gains Resistance to the same triggering damage." One generic
        # ally_damaged row, so the shared Resistance is weighed while the chosen creature's own
        # damage is resolved (typed_reactions._generic_damage_reduction). free=True, because the
        # printed 2 CP and the one Reaction belong to Mine-Shelter Reflex itself and are charged
        # there, once, before this row can answer (see shelter_answers_one_paid_reflex). optional=True
        # plus choice_owner=True, because the printed text is a choice ("you may choose one willing
        # creature"): a player controlling this character is asked which creature the Resistance goes
        # to (shelter_asks_which_creature), and an AI-controlled character answers by itself. ask=True
        # is the same flag the compiler gives any other player-decision row of an Ask-me character
        # (combat/factory_compiler.py); the table still only asks a reactor a player controls, so an
        # AI-driven keeper answers its own questions and is never put on hold for one.
        return [{**row, "block": "generic", "kind": "ally_damaged", "free": True, "optional": True,
                 "choice_owner": True, "ask": True,
                 "name": "Old Mine Shelter Scripture: share Mine-Shelter Reflex's Resistance",
                 "range_ft": int(spec.get("range_ft") or 5), "numbers": dict(numbers),
                 "effects": [{"type": "resistance", "applies_to": "target",
                              "damage_types": [str(kind).upper() for kind in spec.get("damage_types") or []],
                              "flat": 0, "formula": "none", "ability": "none", "condition": "none",
                              "distance_ft": 0, "on": "", "duration": "this_attack",
                              "evidence": str(spec.get("evidence") or "Resistance to the triggering damage")}]}]
    return None


def owned(engine: Any, actor: Any, kind: str) -> bool:
    """Whether ``actor`` compiled the Source feature this module's ``kind`` stands for."""
    from .passive_rows import row_of

    return row_of(engine, getattr(actor, "entity_id", None), BLOCK, kind) is not None


# --------------------------------------------------------------------------------------- deliveries
def hazard_now(engine: Any) -> str:
    """The general class of hazard delivering the damage being committed right now ("" when none is)."""
    return delivery.hazard(engine)


def _terrain_words(zone: Any) -> str:
    """A named terrain's own name, listed terrains and material, in one lowercase string."""
    profile = getattr(zone, "trigger_profile", None) or {}
    named = " ".join(str(row) for row in profile.get("terrain") or ()).lower()
    return f"{named} {(profile.get('visual') or {}).get('material') or ''} {profile.get('name') or ''}".lower()


def _is(words: str, vocabulary: tuple[str, ...]) -> bool:
    return any(word in words for word in vocabulary)


def mineral_area(engine: Any) -> bool:
    """Whether the standing area delivering the damage right now is ground of stone, crystal, sand
    or earth -- Source Skin's printed "a stone, crystal, sand, earth, or mineral environmental hazard"."""
    if delivery.hazard(engine) != delivery.AREA:
        return False
    zone = (getattr(engine, "state", None).zones or {}).get(delivery.area(engine))
    return zone is not None and _is(_terrain_words(zone), MINERAL_TERRAIN)


# --------------------------------------------------------------------------------------- Quarry Walker
@hook("difficult_zone_exempt")
def quarry_walker(engine: Any, actor: Any, zone: Any) -> bool | None:
    """Whether this one area's difficult ground is ground this walker crosses without slowing down.

    Only terrain painted on the map is exempt, because only that is nonmagical
    (combat/zones.py MAP_OWNER is the same test its own nonmagical-terrain branch
    uses): ground an ability leaves behind -- Molten Terrain, Obsidian Terrain,
    a Quarry Walker's own Difficult Terrain -- still costs what it costs anyone
    else, as the printed text requires. Asked about one area at a time, so a
    second, unexcused difficult area over the same square still costs. Per
    square, matched on the painted terrain's own name and material, so no terrain
    identity has to be invented.
    """
    if not owned(engine, actor, "quarry_walker"):
        return None
    from .. import zones

    profile = getattr(zone, "trigger_profile", None) or {}
    if not profile.get("difficult") or zone.owner_id != zones.MAP_OWNER:
        return None
    return True if _is(_terrain_words(zone), STONY_TERRAIN) else False


# --------------------------------------------------------------------------------------- the guard Reactions
def _guard_allows(engine: Any, feature_id: str) -> bool:
    """Whether the damage committing right now is one this guard's printed trigger names."""
    hazard = delivery.hazard(engine)
    if feature_id == REFLEX:
        return hazard in REFLEX_HAZARDS
    if feature_id == SKIN:
        return hazard in SKIN_HAZARDS and mineral_area(engine)
    return False


@hook("row_allowed")
def guard_needs_the_environment(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Keep Source Skin and Mine-Shelter Reflex for the damage their own printed trigger names."""
    if row.get("feature_id") not in (REFLEX, SKIN):
        return None
    return _guard_allows(engine, str(row.get("feature_id")))


# --------------------------------------------------------------------------------------- Old Mine Shelter Scripture
def _armed(reactor: Any) -> str:
    """What this owner's last accepted and paid Mine-Shelter Reflex answered.

    Four fields, "<hazard>|<thing delivering>|<activation>|<damage type>"; a mark written by an
    older build carries no activation name and so answers nothing."""
    return str(reactor.turn_flags.get(ARMED) or "")


def _answers_this_activation(engine: Any, armed: str) -> bool:
    """Whether the damage committing right now is the very damage that paid Reflex.

    "the same triggering damage" names one springing, one crossing, one fall -- not the mechanism that
    springs again later, and not a second creature's separate roll. So all four of the mark's fields
    have to match the delivery committing now: the hazard class, the thing doing the delivering, the
    activation number (combat/ext/damage_delivery.py) and the wound. The table resolves one creature's
    wounds at a time inside one activation, so a creature hurt earlier in that same activation is
    already past the point where Resistance could have answered it; that limit is written on the
    ability's own record (combat/rules/feature_status.d/source.json) rather than hidden.
    """
    if not delivery.event(engine):
        return False  # no hazard is delivering anything right now
    marked_hazard, marked_thing, marked_activation, marked_type = (armed.split("|", 3) + ["", "", "", ""])[:4]
    if marked_hazard not in REFLEX_HAZARDS:
        return False
    current_type = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    return (delivery.key(engine) == (marked_hazard, marked_thing)
            and marked_activation == delivery.event(engine)
            and (not marked_type or marked_type == current_type))


def _willing_ally(owner: Any, subject: Any) -> bool:
    """"one willing creature within 5 feet of you": a creature standing on the same side, which is how
    the table reads willing for someone its owner chose. The printed 5 feet is the row's own range,
    which the engine checks -- which is why the question is only put once that check has passed."""
    return bool(subject is not None and subject.entity_id != owner.entity_id
                and subject.active and subject.team_id == owner.team_id)


@hook("ally_row_allowed")
def shelter_answers_one_paid_reflex(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """Old Mine Shelter Scripture answers exactly one creature, for the one use of Mine-Shelter Reflex that paid for it.

    This hook only answers a question; it never puts one. The table calls it before it has checked
    reach, the wound's type, or whether its owner has a Reaction left at all, so a question asked here
    would stop a game to ask about a creature that could never have been sheltered. It answers yes
    only when its owner compiled that Reaction (the printed prerequisite), that Reaction has already
    been accepted *and paid* -- an accepted use leaves :data:`ARMED` on its owner naming the
    activation and the wound it answered -- the damage committing right now is that same activation,
    and the harmed creature is a willing ally. The question itself is asked afterwards, once every
    other limit has passed (:func:`shelter_asks_which_creature`). The printed 2 CP and the one
    Reaction are charged once, by Mine-Shelter Reflex itself.
    """
    from .ability_source import compiled_feature_rows

    if row.get("feature_id") != SHELTER_FEATURE:
        return None
    if not compiled_feature_rows(engine, reactor.entity_id, REFLEX):
        return False  # the printed prerequisite: without that talent there is no printed use to answer
    armed = _armed(reactor)
    if not armed or not _answers_this_activation(engine, armed):
        return False
    return _willing_ally(reactor, subject)


@hook("reaction_consent")
def shelter_asks_which_creature(engine: Any, row: dict[str, Any], reactor: Any, checkpoint: str) -> bool | None:
    """"you may choose one willing creature": the one question this talent asks, asked at the last moment.

    ``reaction_consent`` is the table's own last-word seam: it runs once its owner has been found, has
    a Reaction left, stands within 5 feet of the creature it would shelter, and the wound is a type it
    answers -- so a creature that could not have been sheltered is never even asked about. The question
    names the ability, the hazard that paid for it and the creature, and it covers one creature only.
    A creature that accepts spends the mark, because "one willing creature" is how many creatures one
    use of the Reaction may protect; a keeper that passes spends nothing and may still be asked about
    the next creature of that same springing. An AI-controlled character, or a fight nobody is
    answering, takes the printed benefit by itself (the preferred option, the same default every other
    optional rider uses through combat/ext/rider_choices.py) without any question at all.
    """
    if row.get("feature_id") != SHELTER_FEATURE:
        return None
    trigger = getattr(engine, "_reaction_trigger", None) or {}
    subject = engine.state.actors.get(str(trigger.get("target_id") or ""))
    if subject is None or not _willing_ally(reactor, subject):
        return None
    return _the_player_picks_this_creature(engine, reactor, subject, _armed(reactor))


@hook("event")
def shelter_follows_a_paid_reflex(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Stand the mark on an accepted, paid Mine-Shelter Reflex, and spend it on the shared Resistance.

    REACTION_RESOLVED is only appended after a reaction has been accepted by its player (or its AI)
    and its printed price has been paid (combat/typed_reactions.py _generic_damage_responses), so it
    is the moment the printed "When you use Mine-Shelter Reflex" has happened. The mark is one turn
    flag on its owner -- a string, so it survives a table commit, a reload and an Ask-me pause -- and
    the engine clears it when its owner's next turn starts. It names the activation as well as the
    wound, and that name is taken from the fight's own journalled length, so it can never shelter a
    later springing of the same trap, not even one that happens after the fight is loaded again.
    """
    if event_type != "REACTION_RESOLVED":
        return
    feature_id = kwargs.get("source_definition_id")
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None or not owner.active:
        return
    if feature_id == SHELTER_FEATURE:
        owner.turn_flags.pop(ARMED, None)  # "one willing creature": the mark is spent with the sharing
        return
    if feature_id != REFLEX or delivery.hazard(engine) not in REFLEX_HAZARDS:
        return
    from .ability_source import compiled_feature_rows

    if not compiled_feature_rows(engine, owner.entity_id, SHELTER_FEATURE):
        return
    owner.turn_flags[ARMED] = "|".join((*delivery.key(engine), delivery.event(engine),
                                        str(getattr(engine, "_typed_pending_damage_type", None) or "")))


def _the_player_picks_this_creature(engine: Any, reactor: Any, subject: Any, armed: str) -> bool:
    """"you may choose one willing creature within 5 feet of you": ask which creature, once.

    The question names the ability, the hazard that paid for it and the creature that would be
    sheltered, and it covers one creature only. The mark is spent on an *accepted* creature and only
    then, so one use of Mine-Shelter Reflex never shelters two creatures. Passing is not spending it:
    "you may choose one willing creature" limits how many creatures a single use may protect, not how
    often its owner may be asked, so a keeper who passes on one wounded creature can still shelter the
    next creature of the very same springing. What stops a later springing from inheriting an unanswered
    mark is the activation named in it (damage_delivery.event, which the fight's own journal keeps
    distinct across a table commit), not a question that went unanswered.

    A player controlling this character is asked -- the row is a ``choice_owner``, so the table pauses
    for the answer on the harmed creature's turn as well as on its owner's -- and an AI-controlled
    character, or a fight nobody is answering, takes the printed benefit by itself (the preferred
    option, the same default every other optional rider uses through combat/ext/rider_choices.py).
    """
    from .rider_choices import pick

    source = {"trap": "the trap", "falling": "the fall"}.get(armed.partition("|")[0], "this hazard")
    chosen = pick(engine, reactor, "source_shelter", "Old Mine Shelter Scripture", ["shelter"],
                  subject=subject,
                  trigger=f"{source} your Mine-Shelter Reflex just answered",
                  labels={"shelter": f'Give {subject.display_name} Resistance to the damage {source} is about to do '
                                     f'(one creature, within 5 feet of you; your Mine-Shelter Reflex already paid '
                                     f'for it, and this covers that damage only)'},
                  preferred=["shelter"])
    if chosen:
        reactor.turn_flags.pop(ARMED, None)   # "one willing creature": one accepted creature spends the mark
    return bool(chosen)


# --------------------------------------------------------------------------------------- Source Circuit
def circuit(engine: Any, actor: Any) -> bool:
    return any(c.condition_id == CIRCUIT for c in actor.conditions.values())


@effect("source_circuit")
def awaken_circuit(ctx: Any, eff: dict[str, Any]) -> None:
    """Awaken the printed 1-minute circuit on its owner; the Speed change reads it.

    ``round_token(engine, 10)`` is the table's own spelling of the printed "for 1 minute"
    (combat/ext/effect_durations.py), the same one Bojutsu's Heavenly Staff Barrier uses.
    The printed "ends early if you are Incapacitated" is the shared ``ends_if_incapacitated``
    marker, carried by the same typed record beside this effect: it takes the circuit off with
    everything else that ability put on, through the engine's own ended-Concentration path. The
    printed "or no longer touching a mineral surface" stays the GM's, and stays written down as
    such in combat/rules/feature_status.d/source.json -- the map records no surface materials, so
    no table state can test it.
    """
    from .effect_durations import round_token

    ctx.engine._apply_condition(ctx.actor, CIRCUIT, ctx.source, ctx.actor.entity_id,
                                expires_on=round_token(ctx.engine, 10),
                                data={"label": "Source circuit (1 minute; its Source Pulse slows a creature "
                                               "by 20 feet; ends early if you are Incapacitated)"})


@effect("source_pulse_slow")
def pulse_slow(ctx: Any, eff: dict[str, Any]) -> None:
    """Source Pulse's Speed reduction: 20 feet while its user's circuit is awake, else the printed 10."""
    from .. import motion
    from ..typed_executor import effect_expiry

    target = ctx.target
    if target is None or motion.floors_speed(ctx.engine, target):
        return
    feet = 20 if circuit(ctx.engine, ctx.actor) else 10
    ctx.engine._apply_condition(target, "condition:typed.source_pulse_slow", ctx.source,
        ctx.actor.entity_id, expires_on=effect_expiry(ctx, eff, target),
        data={"speed_penalty_group": "source_pulse", "speed_penalty_ft": feet,
              "suppress_speed_penalty_if_floor": True, "label": f"Source Pulse: Speed reduced by {feet} feet until the start of its user's next turn"})


# --------------------------------------------------------------------------------------- Heaven-Sealing Source Pin
@effect("heaven_sealing_teleport_save")
def pin_teleport_save(ctx: Any, eff: dict[str, Any]) -> None:
    """The printed Constitution save before a teleport out of the area: made by :func:`pin_holds_teleport`, not at cast time."""
    return None


def _typed_source(engine: Any, source_id: str) -> str:
    action = engine.action_catalog.get(source_id)
    return str((((getattr(action, "parameters", None) or {}).get("typed")) or {}).get("source") or "") if action is not None else ""


@hook("teleport_gate")
def pin_holds_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Heaven-Sealing Source Pin: "A creature of your choice that starts in the area or enters it must make a Constitution
    saving throw against your Source Save DC before teleporting out of the area. On a failed save, that teleport fails and
    the use of the teleport effect is spent. On a successful save, the creature teleports normally. A creature makes this
    saving throw at most once per turn."

    Contact checks the occupied horizontal footprint at both endpoints, using the existing solid-surface model at
    the declared area's altitude; mineral material still needs GM adjudication. Every recipient, including the owner,
    is the owner's choice. AI chooses perceived enemies only.
    A recorded round/initiative slot scopes the save to the current fight turn, including off-turn teleports.
    Returning False spends the already-paid teleport without moving its user.
    """
    from .. import falling, senses, zones
    from .needle import save_dc
    from .rider_choices import pick

    engine, actor = ctx.engine, ctx.actor
    for zone in zones.typed_zones(engine):
        if not zone.active or _typed_source(engine, zone.source_definition_id) != PIN:
            continue
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        def touching(position: Any) -> bool:
            return (position.z == zone.center.z and falling.supported(engine, actor, position)
                    and any(cell in cells for cell in engine._actor_cells(actor, position)))

        if not touching(start) or touching(destination):
            continue  # not teleporting out of this area
        # Some typed actions spell the same hop in both teleport and movement rows.
        # A failed hop stays failed throughout this resolution; it is not a second use
        # of the ability that may benefit from the once-per-turn save limit.
        attempt = ("source_pin_failed_hop", zone.zone_id, actor.entity_id, ctx.source,
                   start.x, start.y, start.z, destination.x, destination.y, destination.z)
        if ctx.damage_cache.get(attempt):
            return False
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active:
            continue
        key = f"{PIN_SAVED}|{zone.zone_id}"
        turn = f"{engine.state.round_number}:{engine.state.current_slot_index}"
        if actor.turn_flags.get(key) == turn:
            continue  # already made this turn's save
        hold = actor.team_id != owner.team_id and senses.perceives(engine, owner, actor)
        name = str(ctx.action.display_name)
        chosen = pick(engine, owner, "source_pin", "Heaven-Sealing Source Pin", ["hold"], subject=actor, automatic=hold,
                      preferred=["hold"] if hold else [],
                      labels={"hold": f"Require {actor.display_name}'s Constitution save; failure spends {name} without teleporting"},
                      trigger=f"{actor.display_name} uses {name} to leave the pinned surface",
                      prompt=(f"Heaven-Sealing Source Pin: {actor.display_name} uses {name} to teleport off the pinned surface. "
                              "Require a Constitution save against your Source Save DC? On a failed save, this teleport "
                              "fails and its use, action and resource costs stay spent. Decline to let it teleport normally. "
                              "This choice costs you no action or resource."))
        if not chosen:
            continue
        dc = save_dc(engine, owner)
        roll = engine._roll_save(actor, "CON", dc, zone.source_definition_id)
        actor.turn_flags[key] = turn
        if roll is not None and int(roll.total) < dc:
            ctx.damage_cache[attempt] = True
            note(engine, zone.source_definition_id, owner, f"Heaven-Sealing Source Pin: {actor.display_name} fails its Constitution save "
                 f"({roll.total} against {dc}); its teleport fails and is spent, and it stays where it was.", (actor,))
            return False
    return None


@hook("candidate_allowed")
def pulse_object_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (((getattr(action, "parameters", None) or {}).get("typed")) or {}).get("source") != "SOURCE_BASE_SOURCE_PULSE":
        return None
    if (candidate.metadata or {}).get("object_target"):
        from .source_locks import MINERALS
        obj = engine.state.objects.get(next(iter(candidate.target_ids), ""))
        return obj is not None and obj.unattended and str((obj.component or {}).get("material") or "").lower() in MINERALS
    return None
