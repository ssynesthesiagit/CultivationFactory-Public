"""Source sphere automation (AUTO7, review fixes AUTO7f1).

Every printed effect here is quoted from APP/authority/typed_mechanics/rules_text.json. The bugs this
file guards showed on the table, so the regressions run at the level they showed: a real Trap sphere
character sets a real Razor Wire, a real creature walks into it through a real Move action, a real named
terrain lays real ground under a real move, and the Source Circuit is really pressed on a real table and
then reloaded from disk.

The printed Source guards limit where the damage came from, and each reads its own list:

* Mine-Shelter Reflex -- "damage from a trap, collapse, falling stone, burst crystal, mining hazard, or
  source-stone discharge while touching a mineral surface". A Trap and a fall answer it.
* Source Skin -- "damage from a stone, crystal, sand, earth, or mineral environmental hazard". A dart's
  Piercing dart and a creature's own fall are neither, so a standing area of mineral ground is what it
  answers, and nothing else.
* Old Mine Shelter Scripture -- "When you use Mine-Shelter Reflex, you may choose one willing creature
  within 5 feet of you. That creature also gains Resistance to the same triggering damage." One accepted,
  paid use of that Reaction, one chosen creature, and the mark is spent with an accepted creature only:
  passing on one creature spends nothing, so the next creature of that same springing may still be
  sheltered, while a later springing cannot be, in the same fight or after the fight is loaded again.
"""

from typing import Any

from combat import pressure, zones
from combat.gate5_service import CombatService
from combat.ext import damage_delivery as delivery
from combat.factory_compiler import RESOURCE_IDS
from combat.typed_reactions import compile_blocks
from combat.gate2_runtime_models import ActionIntent, Position, ZoneState
from tests.h48_table_support import FOE, OWNER, assert_reload_verify_replay, candidate, fixture

QUARRY = "tianxia.talent.source.quarry_walker"
SOURCE_SKIN = "tianxia.talent.source.source_skin"
MINE_SHELTER = "tianxia.talent.source.mine_shelter_reflex"
OLD_SHELTER = "tianxia.talent.source.old_mine_shelter_scripture"
SOURCE_CIRCUIT = "tianxia.talent.source.source_circuit"
DRAGON_PIN = "tianxia.talent.source.dragon_pin"
STONE_BONE = "tianxia.talent.source.stone_bone_source_scripture"
SOURCE_PULSE = "SOURCE_BASE_SOURCE_PULSE"
TRAPPER = "actor:factory.auto7_trapper"
KEEPER = "actor:factory.auto7_keeper"
ALLY = "actor:factory.auto7_ally"
THIRD = "actor:factory.auto7_third"
TRAP_BASE = "TAL_TRAP_TRAPPED_SHIELD"
TRIPWIRE = "TAL_TRAP_RAZOR_WIRE"
PLAIN = "ASH_TAL_ASHEN_BURIAL"


def source_sphere() -> Any:
    """The plug-in, imported lazily so each case below still runs (and fails) without it."""
    from combat.ext import source_sphere as module
    return module


def _pulse_row() -> dict:
    return {"type": "source_pulse_slow", "applies_to": "target", "flat": -10, "distance_ft": 10,
            "duration": "until_start_of_next_turn", "applies": "next_turn"}


def _zone(zone_id: str, owner_id: str, name: str, material: str, cells: tuple[tuple[int, int], ...] = ((1, 2),),
          *, difficult: Any = None, triggers: list | None = None, move_through: Any = None,
          numbers: dict | None = None) -> ZoneState:
    """A named terrain laid on the map, as combat/zones.py carries one."""
    profile: dict[str, Any] = {"kind": zones.KIND, "name": name, "terrain": [name.lower()],
                               "visual": {"material": material}, "numbers": numbers or {"save_dc": 15, "pb": 4, "cl": 10}}
    if difficult is not None:
        profile["difficult"] = difficult
    if triggers is not None:
        profile["triggers"] = triggers
    if move_through is not None:
        profile["move_through"] = move_through
    positions = tuple(Position(x=x, y=y) for x, y in cells)
    return ZoneState(zone_id=zone_id, source_definition_id="action:test.auto7_area", owner_id=owner_id, active=True,
                     center=positions[0], radius_cells=0, affected_cells=positions, concentration_link=False,
                     created_round=1, trigger_profile=profile)


# --------------------------------------------------------------------------------------------------- deliveries
def test_each_guard_reads_its_own_printed_list_of_deliveries():
    """Both guards limit where the damage came from, and they do not name the same places.

    Mine-Shelter Reflex: "a trap, collapse, falling stone, burst crystal, mining hazard, or source-stone
    discharge". Source Skin: "a stone, crystal, sand, earth, or mineral environmental hazard" -- so a
    trap's dart and a creature's own fall are not its answer, and a standing area of mineral ground is.
    """
    from tests.test_typed_executor import _reactor

    module, engine, _attacker, victim = source_sphere(), *_reactor("DELIVERY", [])
    mineral = _zone("zone:auto7:obsidian", "actor:auto7.magma", "Obsidian Terrain", "rubble")
    fire = _zone("zone:auto7:fire", "actor:auto7.magma", "Fire Terrain", "fire")

    def asks(feature_id: str, hazard: str = "", zone: ZoneState | None = None, identity: str = "") -> bool:
        engine.__dict__.pop(delivery.ATTR, None)
        engine.state.zones.clear()
        if zone is not None:
            engine.state.zones[zone.zone_id] = zone
        with delivery.delivering(engine, identity or f"action:test.{hazard or 'sword'}",
                                 hazard=hazard, area=zone.zone_id if zone else None):
            return module.guard_needs_the_environment(engine, victim, {"feature_id": feature_id}) is True

    assert asks(MINE_SHELTER, delivery.TRAP, identity="trap:zone:1")
    assert asks(MINE_SHELTER, delivery.FALLING, identity="system:combat.falling")
    assert not asks(MINE_SHELTER, delivery.AREA, mineral), "an area is not one of its printed hazards"
    assert not asks(MINE_SHELTER), "a sword is not a falling stone"

    assert asks(SOURCE_SKIN, delivery.AREA, mineral)
    assert not asks(SOURCE_SKIN, delivery.AREA, fire), "fire is not a stone, crystal, sand, earth or mineral hazard"
    assert not asks(SOURCE_SKIN, delivery.TRAP, identity="trap:zone:1"), "a dart's piercing is not a mineral hazard"
    assert not asks(SOURCE_SKIN, delivery.FALLING, identity="system:combat.falling"), "a creature's own fall is not one"

    # No frame at all (engine-internal damage): both stay off rather than firing blind.
    engine.__dict__.pop(delivery.ATTR, None)
    assert module.guard_needs_the_environment(engine, victim, {"feature_id": MINE_SHELTER}) is False
    assert module.guard_needs_the_environment(engine, victim, {"feature_id": SOURCE_SKIN}) is False
    # Any other row is untouched: the hook reads its own two feature ids and nothing else.
    assert module.guard_needs_the_environment(engine, victim, {"feature_id": "tianxia.talent.body.iron_fist"}) is None


# --------------------------------------------------------------------------------------------------- Quarry Walker
def _owner_row(block: str, kind: str) -> dict:
    return {"feature_id": QUARRY, "block": block, "kind": kind}


def test_quarry_walker_walks_over_stony_ground_and_still_pays_for_a_magical_stone_area():
    """"ignore nonmagical difficult terrain caused by loose stone, scree, rubble, gravel, broken tile,
    mine spoil, or uneven worked stone" -- and the second line: not mud, ice, water, plant growth, crowds,
    restraints, or ground an ability made."""
    from tests.test_typed_executor import _reactor

    module, engine, _attacker, walker = source_sphere(), *_reactor("QUARRY", [])
    engine.state.zones["zone:auto7:rubble"] = _zone("zone:auto7:rubble", zones.MAP_OWNER, "Loose Rubble", "rubble",
                                                    difficult="all")
    assert zones.difficult_cells(engine, walker) == {(1, 2)}  # inert without the talent
    engine.typed_passive_rows[walker.entity_id] = [_owner_row("source_ward", "quarry_walker")]
    assert module.owned(engine, walker, "quarry_walker") is True
    assert zones.difficult_cells(engine, walker) == set(), "loose rubble costs this walker nothing extra"

    for name, material in (("Deep Water", "water"), ("Mud", "mud"), ("Ice", "ice"), ("Bamboo Thicket", "bamboo")):
        engine.state.zones.clear()
        engine.state.zones["zone:auto7:rubble"] = _zone("zone:auto7:rubble", zones.MAP_OWNER, name, material,
                                                        difficult="all")
        assert zones.difficult_cells(engine, walker) == {(1, 2)}, name

    # Ground an ABILITY leaves behind is not nonmagical, so it keeps costing (Magma's Obsidian Terrain:
    # material "rubble", but its owner is its caster).
    engine.state.zones.clear()
    engine.state.zones["zone:auto7:rubble"] = _zone("zone:auto7:rubble", walker.entity_id, "Obsidian Terrain", "rubble",
                                                    difficult="all")
    assert zones.difficult_cells(engine, walker) == {(1, 2)}

    # The overlap a plain list of exempt squares cannot see: stony ground the walker ignores, with a
    # magical stone area over the same square, which keeps costing.
    engine.state.zones.clear()
    engine.state.zones["zone:auto7:rubble"] = _zone("zone:auto7:rubble", zones.MAP_OWNER, "Loose Rubble", "rubble",
                                                    difficult="all")
    engine.state.zones["zone:auto7:obsidian"] = _zone("zone:auto7:obsidian", "actor:auto7.magma", "Obsidian Terrain",
                                                      "rubble", difficult="all")
    assert zones.difficult_cells(engine, walker) == {(1, 2)}, "the magical area's cost stands over exempt ground"


def test_source_skin_grants_advantage_against_being_petrified():
    """"You have Advantage on saving throws against being Petrified" -- the generic defense block, data only."""
    blocks = compile_blocks([SOURCE_SKIN], pb=4, key_mod=0, saves={}, resource_ids=RESOURCE_IDS)
    rows = [row for row in blocks["passives"] if row.get("block") == "defense"]
    assert [(row["kind"], row["abilities"], row["against"]) for row in rows] == [("save_advantage", [], ["petrified"])]

    from tests.test_typed_executor import _reactor

    engine, _attacker, victim = _reactor("PETRIFIED", [])
    for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        assert pressure.save_advantage(engine, victim, ability, {"petrified"}) is False  # inert without the talent
    engine.typed_passive_rows[victim.entity_id] = rows
    for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        assert pressure.save_advantage(engine, victim, ability, {"petrified"}) is True, ability
    assert pressure.save_advantage(engine, victim, "CON", {"frightened"}) is False


# --------------------------------------------------------------------------------------------------- the fight harness
def _sheet(mids: tuple[str, ...] | str, *, cl: int = 17, name: str | None = None) -> dict:
    """A real Factory character owning exactly the named talents."""
    from tests.h1_support import sheet

    document = sheet(list(mids) if isinstance(mids, tuple) else mids, cl=cl, dc=16)
    document["identity"]["display_name"] = name or ("Auto7 " + str(mids).replace("tianxia.talent.", "").replace("_", " ")[:28])
    document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
    return document


def _fight(roster: list[tuple[str, dict, str, tuple[int, int]]], *, seed: str = "AUTO7F1",
           order: list[str] | None = None, ask: str | None = None):
    """A real four-actor Factory fight from real compiled bundles, with a chosen initiative order."""
    from combat.factory_compiler import compile_character
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.hunt24_support import finish_direct_setup
    from tests.test_auto_lane1 import ROOT

    ids = [actor_id for actor_id, _document, _team, _at in roster]
    bundles = [compile_character(document, actor_id=actor_id,
                                 reaction_plan={"mode": "ask", "ask": True} if actor_id == ask else None)
               for actor_id, document, _team, _at in roster]
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": ids,
                                                 "team_by_actor": {actor_id: team for actor_id, _d, team, _a in roster},
                                                 "starting_positions": {actor_id: {"x": at[0], "y": at[1]}
                                                                        for actor_id, _d, _t, at in roster}})
    finish_direct_setup(engine)
    engine.state.initiative_order = list(order or ids)
    engine.state.current_slot_index = 0
    engine.state.current_actor_id = engine.state.initiative_order[0]
    engine._system_start_turn()
    return engine


def _turn_to(engine: Any, actor_id: str) -> None:
    order = engine.state.initiative_order
    for _ in range(len(order) + 1):
        if engine.state.current_actor_id == actor_id:
            return
        engine.state.current_actor_id = order[(order.index(engine.state.current_actor_id) + 1) % len(order)]
        engine._system_start_turn()
    raise AssertionError(f"{actor_id} never became the current actor")


def _press(engine: Any, display_name: str, *, actor_id: str, at: tuple[int, int] | None = None) -> None:
    chosen = next(row for row in engine.legal_candidates() if row.actor_id == actor_id
                  and (row.display_name == display_name or row.display_name.startswith(display_name + " at"))
                  and (at is None or (row.destination is not None
                                      and (row.destination.x, row.destination.y) == at)))
    engine.execute_intent(ActionIntent(intent_id=f"auto7f1:{display_name}:{actor_id}", decision_id=chosen.decision_id,
                                       candidate_id=chosen.candidate_id, state_version=chosen.state_version,
                                       actor_id=actor_id, target_ids=chosen.target_ids or (),
                                       destination=chosen.destination))


def _wire_the_map(engine: Any) -> None:
    """A real Razor Wire tripwire on the square beside the trapper."""
    _press(engine, "Trap form: Tripwire + Razor Wire", actor_id=TRAPPER)
    _press(engine, "Set Trap", actor_id=TRAPPER, at=(3, 5))


def _spring(engine: Any, actor_id: str, home: tuple[int, int]) -> tuple[int, int]:
    """Walk into the wired square and back out again, through real Move actions.

    Razor Wire is a real Tripwire form and a Tripwire is not destroyed when it springs ("unless a
    talent says otherwise, a trap is destroyed after it triggers"), so the one trap wounds every
    creature that enters that square -- the printed "the same triggering damage" the shared Resistance
    hangs on. Returns what the creature lost and what the trap rolled for it.
    """
    actor = engine.state.actors[actor_id]
    before, mark = actor.current_hp, len(engine.events)
    _turn_to(engine, actor_id)
    _press(engine, "Move to 3,5", actor_id=actor_id)
    taken, rolled = before - actor.current_hp, _rolls_since(engine, mark)
    _press(engine, f"Move to {home[0]},{home[1]}", actor_id=actor_id)
    assert rolled, "the wired square rolled no damage at all"
    return taken, rolled[-1]


def _traps(engine: Any) -> int:
    from combat.ext import placed
    return len(placed.of(engine, "trap"))


def _resolved(engine: Any, feature_id: str) -> list[Any]:
    return [event for event in engine.events if event.event_type == "REACTION_RESOLVED"
            and event.source_definition_id == feature_id]


def _rolls_since(engine: Any, mark: int) -> list[int]:
    return [event.payload["total"] for event in engine.events[mark:]
            if event.event_type == "DAMAGE_ROLLED"]


def _rolled_since(engine: Any, mark: int) -> list[dict[str, Any]]:
    """What each damage commit after ``mark`` rolled, what was left of it, and what it actually took."""
    return [event.payload for event in engine.events[mark:] if event.event_type == "DAMAGE_COMMITTED"]


def _hurt_since(engine: Any, mark: int) -> int:
    """How much damage the events after ``mark`` actually took off Hit Points (after Reduction)."""
    return sum(int(payload.get("hp_damage") or 0) for payload in _rolled_since(engine, mark))


def _mine_fight(*, with_scripture: bool = True, ask: str | None = None, seed: str = "AUTO7F1-TRAP"):
    """A real Trap character, a real Source keeper, and two more creatures on the keeper's team.

    The two neighbours stand one square from the wired square, each with a free square to step back
    onto, so each of them springs the same tripwire with one real step in and one real step back out.
    """
    talents = (MINE_SHELTER, OLD_SHELTER) if with_scripture else (MINE_SHELTER,)
    return _fight([(TRAPPER, _sheet((TRAP_BASE, TRIPWIRE)), "team:a", (4, 6)),
                   (KEEPER, _sheet(talents), "team:b", (2, 5)),
                   (ALLY, _sheet((PLAIN,)), "team:b", (2, 6)),
                   (THIRD, _sheet((PLAIN,)), "team:b", (3, 4))],
                  seed=seed, order=[TRAPPER, KEEPER, ALLY, THIRD], ask=ask)


def test_a_real_trap_mechanism_is_answered_by_mine_shelter_reflex():
    """'damage from a trap' -- a real Razor Wire tripwire, sprung by a real move, halved for its owner.

    Before the delivery record existed this row was a generic 'damaged' reaction, and the review found
    the opposite fault too: typed as ``resistance_next`` it granted Resistance to the NEXT damage and
    left the triggering wound whole.
    """
    engine = _mine_fight()
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50  # the Razor Wire save fails
    _wire_the_map(engine)
    assert _traps(engine) == 1
    taken, rolled = _spring(engine, KEEPER, (2, 5))
    assert taken, "the real trap must wound somebody, or this proves nothing"
    assert taken == rolled // 2, (taken, rolled)
    assert _resolved(engine, MINE_SHELTER), "the printed guard did not answer a real trap"
    keeper = engine.state.actors[KEEPER]
    assert keeper.resources.get(RESOURCE_IDS["qi"]) == 28, "the printed 2 CP were spent"
    assert keeper.reaction_available is False, "the printed Reaction was spent"


def _springing_intent(engine: Any, dealer: str) -> Any:
    """The intent a springing happens under: the engine only weighs a creature's own reactions to a
    damage commit that carries one (combat/gate2_engine._commit_damage_packet)."""
    return ActionIntent(intent_id=f"auto7r1f1:springing:{dealer}", decision_id="", candidate_id="",
                        state_version=engine.state.state_version, actor_id=dealer, target_ids=())


def _wound(engine: Any, actor_id: str, amount: int, source: str, dealer: str, *, reaction_depth: int = 0) -> int:
    """What one real damage commit costs a creature: the sealed engine's own commit, the same one
    combat/falling.py and combat/ext/trap.py make, with every reaction and rider it triggers.

    The wound's TYPE is stashed beside the commit exactly as combat/falling.py does it, because the
    sealed commit does not pass it on and a printed "that kind of damage" limit could not answer."""
    actor = engine.state.actors[actor_id]
    before = actor.current_hp
    previous_type = getattr(engine, "_typed_pending_damage_type", None)
    previous_intent = getattr(engine, "_active_intent", None)
    engine._typed_pending_damage_type = "SLASHING"
    engine._active_intent = previous_intent or _springing_intent(engine, dealer)
    try:
        engine._commit_damage(actor, amount, "SLASHING", source, dealer, engine._active_intent,
                              reaction_depth=reaction_depth)
    finally:
        engine._typed_pending_damage_type = previous_type
        engine._active_intent = previous_intent
    return before - actor.current_hp


RETURNED_BLADE = "talent:test.auto7_returned_blade"


def _answers_a_wound_with_its_own_blade(engine: Any, reactor_id: str, amount: int = 12) -> None:
    """Give one creature a real reaction that answers a wound with a strike of its own.

    A reaction row in exactly the shape the compiler gives a printed guard, so the engine's own
    dispatch weighs it, accepts it, charges its Reaction and journals it: while a hazard frame is
    open a *reaction* really resolves and its damage really commits. That is the case the delivery
    record has to get right -- a reaction's own damage is a delivery of its own -- and it cannot be
    shown by calling the executor by hand, because nothing then weighs it as a reaction at all.

    The strike lands on the creature that did the hurting, which is what a reaction's own target is
    (combat/typed_reactions._generic_context), so the creature that dealt the damage here is the one
    whose wound has to stay whole.
    """
    engine.typed_reaction_rows[reactor_id] = [
        *engine.typed_reaction_rows.get(reactor_id, []),
        {"feature_id": RETURNED_BLADE, "block": "generic", "name": "Returned blade", "kind": "damaged",
         "melee_only": False, "ranged_only": False, "range_ft": None, "min_move_ft": 0,
         "includes_self": False, "any_subject": False, "allies_only": False, "self_only": False,
         "mark_on": "", "opportunity_only": False, "teleport_only": False, "source_within_reach": False,
         "requires_hearing_technique": False, "rolls": [], "outcome": None, "toward": False, "reading": None,
         "economies": [], "natural": [], "action": None, "source_name": None, "min_cost": 0,
         "grappling": False, "costs": [], "save_abilities": [], "damage_types": [], "conditions": [],
         "requires_resource": None, "requires_mark": None, "numbers": {"cl": 17}, "use_limit": None,
         "free": True, "once": None, "once_group": None, "requires_self_mark": None, "after": None,
         "effects": [{"type": "damage", "applies_to": "target", "flat": amount, "dice": {"count": 0, "sides": 6},
                      "formula": "none", "damage_types": ["slashing"],
                      "evidence": "A creature's own answer to being hurt, not the hazard's damage."}]},
    ]


def _dealt_by(engine: Any, source_id: str, mark: int) -> list[dict[str, Any]]:
    """What each commit after ``mark`` that came from ``source_id`` actually took off its victim."""
    return [{"victim": (event.target_ids or ("",))[0], "taken": int((event.payload or {}).get("hp_damage") or 0)}
            for event in engine.events[mark:]
            if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == source_id]


def _resolved_by(engine: Any, feature_id: str, actor_id: str) -> list[Any]:
    """The resolutions of one printed guard by one named creature. A guard answering some other
    creature's damage says nothing about whether it answered this one's, which is exactly the
    confusion the earlier version of these cases walked into."""
    return [event for event in engine.events if event.event_type == "REACTION_RESOLVED"
            and event.source_definition_id == feature_id and event.actor_id == actor_id]


def _returned_fight(*, seed: str = "AUTO7R2F1-RETURN"):
    """A trap whose setter is also a Source keeper, so the trap's own damage and a creature's own return
    both land on creatures the printed guard is watching.

    The setter standing in reach of its own wire is what lets both halves of the case be real: the
    springing is answered by Mine-Shelter Reflex, and the strike a wounded creature deals back while
    that springing is still open lands on a Source keeper whose Reaction is still free. A case whose
    return fell on the keeper that had already paid for its own guard would pass with the delivery
    record broken.
    """
    return _fight([(TRAPPER, _sheet((TRAP_BASE, TRIPWIRE, MINE_SHELTER, OLD_SHELTER)), "team:a", (4, 6)),
                   (KEEPER, _sheet((MINE_SHELTER, OLD_SHELTER)), "team:b", (2, 5)),
                   (ALLY, _sheet((PLAIN,)), "team:b", (2, 6)),
                   (THIRD, _sheet((PLAIN,)), "team:b", (3, 4))],
                  seed=seed, order=[TRAPPER, KEEPER, ALLY, THIRD])


def test_a_reaction_that_answers_inside_a_springing_is_not_the_springings_own_damage():
    """A trap's block surrounds its whole resolution, including what a wounded creature answers with.

    Before this fix the returned damage inherited the trap's hazard, so a Source keeper could spend
    Mine-Shelter Reflex against damage from a creature's own talent. Every part of it is real here: a
    real Razor Wire sprung by a real move, the printed guard really answering one teammate's wound, and
    the wounded ally's own reaction really resolving while that springing is still open. The keeper
    the return lands on has a Reaction still free, so a leak would halve that strike and journal a
    resolution of its own -- no exhausted keeper standing in for the missing check.
    """
    engine = _returned_fight(seed="AUTO7R2F1-RETURN")
    for actor_id in (TRAPPER, KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    # The setter only stands here to be the creature a wounded creature's return lands on. Its own
    # Opportunity Attack would fire as teammates walk past its square and spend the very Reaction this
    # case needs still free, so it is stood down: what is under test is what the trap's frame does to
    # the damage resolving inside it, not who attacks whom afterwards.
    engine.typed_reaction_rows[TRAPPER] = [row for row in engine.typed_reaction_rows[TRAPPER]
                                           if row.get("block") != "opportunity"]
    _wire_the_map(engine)
    _answers_a_wound_with_its_own_blade(engine, ALLY, 12)

    # The positive control: this trap's own Slashing IS answered by the printed guard, so the row is
    # really being weighed in this fight and a leak below would have somewhere to show.
    keeper_taken, keeper_rolled = _spring(engine, KEEPER, (2, 5))
    assert keeper_taken == keeper_rolled // 2, (keeper_taken, keeper_rolled)
    assert _resolved_by(engine, MINE_SHELTER, KEEPER), "the printed guard did not answer a real trap"

    trapper = engine.state.actors[TRAPPER]
    assert trapper.reaction_available, "the creature the return lands on must still be able to answer"
    mark = len(engine.events)
    ally_taken, _ally_rolled = _spring(engine, ALLY, (2, 6))
    blades = _dealt_by(engine, RETURNED_BLADE, mark)

    assert ally_taken, "the real trap must wound the ally, or its return proves nothing"
    assert blades and all(blade["victim"] == TRAPPER for blade in blades), blades
    assert all(blade["taken"] == 12 for blade in blades), \
        f"a creature's own blade is not the trap's damage and must not be halved: {blades}"
    assert not _resolved_by(engine, MINE_SHELTER, TRAPPER), \
        "Mine-Shelter Reflex answered damage that merely happened while a trap was resolving"


def test_a_reaction_that_answers_inside_an_area_is_not_that_areas_damage():
    """The same limit on the other hazard: an area's own trigger is its own delivery.

    Source Skin answers "a stone, crystal, sand, earth, or mineral environmental hazard" by reading
    the area that is delivering, and it is answered once, for the ground itself. The strike the
    wounded creature deals back while that ground is still standing lands on a second Source keeper
    with a free Reaction, so a leak would halve it and journal a second resolution of its own.
    """
    module = source_sphere()
    engine = _fight([(KEEPER, _sheet((SOURCE_SKIN,)), "team:a", (2, 5)),
                     (ALLY, _sheet((SOURCE_SKIN, PLAIN)), "team:b", (3, 5))],
                    seed="AUTO7R2F1-AREA", order=[KEEPER, ALLY])
    zone = _zone("zone:auto7:obsidian", zones.MAP_OWNER, "Obsidian Terrain", "rubble", ((3, 5),))
    engine.state.zones[zone.zone_id] = zone
    _answers_a_wound_with_its_own_blade(engine, ALLY, 12)
    assert engine.state.actors[KEEPER].reaction_available, \
        "the creature the return lands on must still be able to answer"
    mark = len(engine.events)
    with delivery.delivering(engine, "system:test.auto7_ground", hazard=delivery.AREA, area=zone.zone_id):
        assert module.mineral_area(engine) is True, "the area really is standing mineral ground"
        ground = _wound(engine, ALLY, 12, "system:test.auto7_ground", KEEPER)

    assert ground < 12, ground  # Source Skin answers the area's own Slashing
    assert _resolved_by(engine, SOURCE_SKIN, ALLY), "the printed guard did not answer the area"
    blades = _dealt_by(engine, RETURNED_BLADE, mark)
    assert blades and all(blade["victim"] == KEEPER and blade["taken"] == 12 for blade in blades), \
        f"a creature's own blade is not a mineral hazard and must not be halved: {blades}"
    assert not _resolved_by(engine, SOURCE_SKIN, KEEPER), \
        "Source Skin answered damage that merely happened while an area was standing"
    assert len(_resolved(engine, SOURCE_SKIN)) == 1, \
        "one area activation is answered once, for the ground itself and not for what was dealt back"


def _the_wire(engine: Any) -> Any:
    """The wired square's own trap zone, as combat/ext/trap.py carries it."""
    from combat.ext import placed

    zones = placed.of(engine, "trap")
    assert zones, "the map carries no trap: this proves nothing"
    return zones[0]


def _one_springing(engine: Any, victims: list[str], amount: int = 12,
                   between: Any = None) -> dict[str, int]:
    """One springing of the wired square, wounding several creatures.

    This is the trap module's own block (combat/ext/trap.py:372): one delivery frame naming the trap
    and its zone, every victim committed inside it, each commit the sealed engine's own. A printed
    trap pattern wounds only the creature that triggered it, so the table reaches a springing with
    several creatures in it only by handing the trap its own list of victims -- which is what the
    trap's own multi-victim branch (_snare) does, and what makes the printed "the same triggering
    damage" a real question rather than a theoretical one.

    ``between(index, engine)`` runs between two victims of the same springing, so a case can change
    the table mid-activation -- a creature that becomes Incapacitated after the one whose wound paid
    for the guard, say -- and still be asking about the activation that paid, not a later one.
    """
    zone = _the_wire(engine)
    taken: dict[str, int] = {}
    with delivery.delivering(engine, f"trap:{zone.zone_id}", hazard=delivery.TRAP, area=zone.zone_id):
        for index, actor_id in enumerate(victims):
            if between is not None:
                between(index, engine)
            taken[actor_id] = _wound(engine, actor_id, amount, f"trap:{zone.zone_id}", TRAPPER)
    return taken


def test_a_later_springing_of_the_same_wire_is_not_the_damage_that_paid_for_the_shelter():
    """"Resistance to the same triggering damage": the springing the Reflex answered, not the wire.

    The review's finding was that a keeper could spring the wire, pay its Reflex and leave, and an
    ally walking into that same wire on its own turn was sheltered against a roll that had nothing to
    do with the one the Reflex paid for. Two later springings of the very same trap are two events.
    """
    module = source_sphere()
    engine = _mine_fight(seed="AUTO7R1F1-LATER")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50  # the Razor Wire save fails
    _wire_the_map(engine)
    assert _spring(engine, KEEPER, (2, 5))[0] > 0, "the real trap must wound the keeper, or this proves nothing"
    keeper = engine.state.actors[KEEPER]
    assert keeper.turn_flags.get(module.ARMED), "a paid use of the guard must stand the mark"

    for actor_id, home in ((ALLY, (2, 6)), (THIRD, (3, 4))):
        taken, rolled = _spring(engine, actor_id, home)
        assert taken == rolled, (actor_id, taken, rolled)
    assert not _resolved(engine, OLD_SHELTER), \
        "a springing the keeper's Reflex never answered is not the same triggering damage"


def test_the_shared_resistance_answers_one_creature_of_the_springing_that_paid_for_it():
    """'When you use Mine-Shelter Reflex, you may choose one willing creature within 5 feet of you.'

    One springing wounds three creatures. The keeper pays for the Reflex on its own wound, the next
    creature of that same springing is sheltered, and the third is not: "one willing creature".
    """
    module = source_sphere()
    engine = _mine_fight(seed="AUTO7R1F1-SAME")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    _wire_the_map(engine)
    taken = _one_springing(engine, [KEEPER, ALLY, THIRD])

    assert taken[KEEPER] == 6, taken  # rolled 12, halved by the Reflex the owner paid for itself
    assert _resolved(engine, MINE_SHELTER), "the printed guard did not answer the springing"
    assert taken[ALLY] == 6, taken    # the shared Resistance answers that same springing
    assert len(_resolved(engine, OLD_SHELTER)) == 1, "one use shelters one creature, whoever answers"
    assert module.ARMED not in engine.state.actors[KEEPER].turn_flags, \
        "the mark is spent with the one creature it reached"
    assert taken[THIRD] == 12, taken  # "you may choose one willing creature"


def test_the_shared_resistance_needs_the_printed_use_of_mine_shelter_reflex():
    """No paid use, no sharing: the review's first finding was that the row was free and unlimited."""
    module = source_sphere()
    engine = _mine_fight(with_scripture=False, seed="AUTO7F1-NOUSE")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    keeper = engine.state.actors[KEEPER]
    assert not [row for row in engine.typed_passive_rows[KEEPER] if row.get("feature_id") == OLD_SHELTER], \
        "without the printed prerequisite talent the Scripture does not compile at all"

    engine = _mine_fight(with_scripture=True, seed="AUTO7F1-ALONE")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    row = next(row for row in engine.typed_passive_rows[KEEPER] if row.get("feature_id") == OLD_SHELTER)
    assert (row["kind"], row["free"], row["optional"], row["range_ft"]) == ("ally_damaged", True, True, 5), \
        "the row is free (the printed 2 CP belong to the Reflex) but optional, so a player is asked"
    assert row["choice_owner"] is True, \
        "without choice_owner the service does not treat this manual character as a chooser, and nobody is asked"
    assert row["name"].startswith("Old Mine Shelter Scripture"), "the prompt must name the ability"
    keeper = engine.state.actors[KEEPER]
    keeper.resources[RESOURCE_IDS["qi"]] = 0  # "spend 2 CP": the printed use of the Reflex cannot happen
    _wire_the_map(engine)
    keeper_taken, _rolled = _spring(engine, KEEPER, (2, 5))
    assert keeper_taken > 0, "without its price the guard cannot answer, and the wound is whole"
    assert not _resolved(engine, MINE_SHELTER), "the guard answered without being paid for"
    assert keeper.turn_flags.get(module.ARMED) is None, "no paid use, so nothing stands the mark"
    ally_taken, ally_rolled = _spring(engine, ALLY, (2, 6))
    assert ally_taken == ally_rolled, "the Scripture answered without the printed use of the Reflex"
    assert not _resolved(engine, OLD_SHELTER)


def test_a_real_mineral_area_answers_source_skin_and_shattered_glass_does_not():
    """Source Skin's printed "a stone, crystal, sand, earth, or mineral environmental hazard".

    A real named terrain's own move-through rule is such a hazard: Obsidian Terrain (Magma sphere, ground of
    rubble) makes a hostile creature moving more than 10 feet through it make a Dexterity saving throw and,
    on a failure, take Slashing damage equal to its Proficiency Bonus. Shattered Glass Terrain (Glass sphere)
    has the same printed shape but its ground is glass, which the printed limit does not name.
    """
    def fight(terrain_name: str, seed: str):
        engine = _fight([(KEEPER, _sheet((SOURCE_SKIN,)), "team:a", (1, 6)), (ALLY, _sheet((PLAIN,)), "team:b", (9, 6))],
                        seed=seed, order=[KEEPER, ALLY])
        engine.state.actors[KEEPER].saving_throws["DEX"] = -50  # every save fails
        terrain = zones.terrain_rules()["terrains"][terrain_name]
        cells = tuple((x, y) for x in range(1, 7) for y in range(5, 8))
        zone = _zone("zone:auto7:ground", zones.MAP_OWNER, terrain_name, terrain["material"], cells,
                     move_through=terrain["move_through"], difficult=terrain.get("difficult"))
        engine.state.zones[zone.zone_id] = zone
        return engine

    engine = fight("obsidian terrain", "AUTO7F1-MINERAL")
    keeper = engine.state.actors[KEEPER]
    mark = len(engine.events)
    _press(engine, "Move to 4,6", actor_id=KEEPER)
    committed = _rolled_since(engine, mark)
    assert committed and committed[-1]["rolled_or_pending_damage"] > 0, \
        "the real terrain dealt no damage at all, or this proves nothing"
    assert committed[-1]["hp_damage"] == 0 and committed[-1]["reduced_to"] == 0, \
        f"Obsidian Terrain deals your Proficiency Bonus in Slashing damage and Source Skin takes it back: {committed[-1]}"
    assert _resolved(engine, SOURCE_SKIN), "Source Skin did not answer a mineral hazard"
    assert keeper.reaction_available is False, "its printed Reaction was spent"

    glass = fight("shattered glass terrain", "AUTO7F1-GLASS")
    keeper = glass.state.actors[KEEPER]
    mark = len(glass.events)
    _press(glass, "Move to 4,6", actor_id=KEEPER)
    committed = _rolled_since(glass, mark)
    assert committed and committed[-1]["hp_damage"] > 0, \
        "the real glass terrain dealt no damage, or this proves nothing"
    assert not _resolved(glass, SOURCE_SKIN), \
        "shattered glass is not a stone, crystal, sand, earth or mineral environmental hazard"


def test_source_skin_does_not_answer_a_real_trap():
    """The review's second guard finding: a dart is not a stone, crystal, sand, earth or mineral hazard."""
    engine = _fight([(TRAPPER, _sheet((TRAP_BASE, TRIPWIRE)), "team:a", (4, 6)),
                     (KEEPER, _sheet((SOURCE_SKIN,)), "team:b", (2, 5))],
                    seed="AUTO7F1-SKINTRAP", order=[TRAPPER, KEEPER])
    engine.state.actors[KEEPER].saving_throws["DEX"] = -50
    _wire_the_map(engine)
    taken, rolled = _spring(engine, KEEPER, (2, 5))
    assert taken == rolled, (taken, rolled)
    assert not _resolved(engine, SOURCE_SKIN), "Source Skin answered a trap's piercing"


# --------------------------------------------------------------------------------------------------- typed data
def test_dragon_pin_asks_for_a_dexterity_save():
    """'it must make a Dexterity saving throw against your Source Save DC'.

    The typed record said ``ability: "none"``, which combat/factory_compiler.py copies into the zone
    trigger and combat/typed_executor.py uppercases to NONE, so the save was rolled as no ability at
    all: no Dexterity modifier, no proficiency, no defense that keys on it.
    """
    from combat import typed_executor
    from combat.typed_numbers import authority_mechanics
    from tests.test_typed_executor import _reactor

    record = authority_mechanics()[DRAGON_PIN]
    save = next(row for row in record["effects"] if row.get("type") == "save")
    assert save["ability"] == "dex", save
    assert "Dexterity saving throw" in save["evidence"]

    engine, _attacker, victim = _reactor("DEXPIN", [])
    victim.saving_throws["DEX"] = 5
    zone = _zone("zone:auto7:pin", "actor:auto7.pin", "Dragon Pin", "", triggers=[
        {"id": "pin:start", "name": "Dragon Pin", "on": ["start"], "who": "any",
         "effects": [{**save, "dc": 15, "numbers": {"save_dc": 15}}]}])
    engine.state.zones[zone.zone_id] = zone
    action = engine.action_catalog[next(key for key, row in engine.action_catalog.items()
                                        if row.source_definition_id == zone.source_definition_id)] \
        if zone.source_definition_id in engine.action_catalog else next(iter(engine.action_catalog.values()))
    mark = len(engine.events)
    typed_executor.run_effects(
        typed_executor.Context(engine, victim, action, None,
                               {"source": "zone:auto7:pin:start", "effects": [], "numbers": {"save_dc": 15}},
                               [victim], victim, {}),
        [{"type": "save", **{key: value for key, value in save.items() if key != "type"}}])
    rolled = [event.payload for event in engine.events[mark:] if event.event_type == "SAVE_ROLLED"]
    assert rolled, "the zone's trigger rolled no save at all"
    assert rolled[-1]["modifier"] == 5 and rolled[-1]["dc"] == 15, \
        f"the save ignored the victim's Dexterity bonus: {rolled[-1]}"


def test_stone_bone_source_scripture_adds_its_proficiency_bonus_once_and_only_when_paid_for():
    """'you MAY spend 1 Stamina. On a hit, add your Proficiency Bonus.' The optional, Stamina-priced bonus
    lives in the modifier only; carrying it in ``effects`` as well paid it out on every hit for free."""
    from combat.typed_numbers import authority_mechanics

    record = authority_mechanics()[STONE_BONE]
    assert record["effects"] == [], "the paid-for bonus must not also be an unconditional effect"
    modifier = record["modifier"]
    assert (modifier["targets"], modifier["optional"], modifier["limit"]) == (["Source Pulse"], True, "once_per_turn")
    assert modifier["cost"] == [[{"resource": "stamina", "amount": 1}]]
    assert [(eff["type"], eff["formula"]) for eff in modifier["effects"]] == [("extra_damage", "pb")]


def test_source_circuit_lasts_the_printed_minute_and_ends_early_when_incapacitated():
    """"awaken a source circuit for 1 minute" -- not one turn -- and "ends early if you are Incapacitated".

    The bare ten-round token the lane left did neither: its docstring claimed
    combat/ext/condition_lifecycle.py swept it, and that module only ends Concentration. The printed
    early ending is the shared ``ends_if_incapacitated`` marker, carried by the same typed record.
    """
    from combat.ext import effect_durations
    from combat.typed_numbers import authority_mechanics

    module = source_sphere()
    effects = authority_mechanics()[SOURCE_CIRCUIT]["effects"]
    marker = [row for row in effects if row.get("type") == "ends_if_incapacitated"]
    assert marker and "Incapacitated" in marker[0]["evidence"], \
        "the printed early ending needs the shared marker beside the circuit"

    engine = _circuit_fight()
    keeper = engine.state.actors[KEEPER]
    assert module.circuit(engine, keeper) is False
    assert keeper.resources[RESOURCE_IDS["qi"]] == 30

    _press(engine, "Source Circuit", actor_id=KEEPER)
    assert keeper.resources[RESOURCE_IDS["qi"]] == 28, "the printed 2 CP were not spent"
    assert keeper.bonus_action_available is False, "the printed Bonus Action was not spent"
    condition = next(row for row in keeper.conditions.values() if row.condition_id == module.CIRCUIT)
    assert condition.expires_on == effect_durations.round_token(engine, 10), condition.expires_on
    assert condition.data["label"].startswith("Source circuit (1 minute"), condition.data["label"]
    assert "Incapacitated" in condition.data["label"], "the printed early ending belongs on what the player reads"
    assert module.circuit(engine, keeper) is True

    engine._apply_condition(keeper, "condition:incapacitated", "test:auto7f1", KEEPER, expires_on="UNTIL_REMOVED")
    assert module.circuit(engine, keeper) is False, "the printed early ending did not take the circuit off"
    assert not [row for row in keeper.conditions.values() if row.condition_id == module.CIRCUIT]


def _circuit_fight(seed: str = "AUTO7F1-CIRCUIT"):
    """A real Source Circuit user and a real neighbour, on a real Gate 4 engine (whose root events the
    shared cleanup hooks are dispatched from)."""
    return _fight([(KEEPER, _sheet((SOURCE_CIRCUIT,)), "team:a", (1, 6)), (ALLY, _sheet((PLAIN,)), "team:a", (4, 6))],
                  seed=seed, order=[KEEPER, ALLY])


def test_source_circuit_widens_source_pulse_s_speed_reduction_to_twenty_feet():
    """'the Speed reduction from that Source Pulse becomes 20 feet instead of 10 feet'."""
    from combat import typed_executor
    from tests.test_typed_executor import _engine_with, _intent

    row = _pulse_row()
    engine, caster_id = _engine_with({"effects": [row], "numbers": {"cl": 5}}, "CIRCUIT")
    caster = engine.state.actors[caster_id]
    victim = next(actor for actor in engine.state.actors.values() if actor.entity_id != caster_id)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")

    def pulse() -> None:
        context = typed_executor.Context(engine, caster, engine.action_catalog["action:typed.test"], _intent(candidate),
                                        {"source": SOURCE_PULSE, "effects": [row]}, [victim], victim, {})
        victim.modifiers.clear()
        typed_executor.run_effects(context, [row])

    module = source_sphere()
    base = engine._effective_speed(victim)
    pulse()
    assert module.circuit(engine, caster) is False
    assert engine._effective_speed(victim) == base - 10

    typed_executor.run_effects(
        typed_executor.Context(engine, caster, engine.action_catalog["action:typed.test"], _intent(candidate),
                               {"source": SOURCE_CIRCUIT, "effects": []}, [], None, {}),
        [{"type": "source_circuit", "applies_to": "self"}])
    assert module.circuit(engine, caster) is True
    pulse()
    assert engine._effective_speed(victim) == base - 20


# --------------------------------------------------------------------------------------------------- the table
def test_on_the_table_the_source_guard_is_scoped_and_the_fight_still_plays(tmp_path):
    """Table level: the guard compiles for its owner only, its printed standing clause is live, and the
    owner's turn still reaches the table with the guard in place."""
    combat, table, match_id, _send, commit_turn = fixture(tmp_path, [MINE_SHELTER, SOURCE_SKIN], seed="7")
    engine = combat._load_session(match_id).engine
    owner = next(actor for actor in engine.state.actors.values() if actor.entity_id == OWNER)
    foe = next(actor for actor in engine.state.actors.values() if actor.entity_id == FOE)

    assert [row["feature_id"] for row in engine.typed_reaction_rows.get(OWNER, []) if row.get("feature_id") == MINE_SHELTER]
    assert not [row for row in engine.typed_passive_rows.get(FOE, []) if row.get("feature_id") == SOURCE_SKIN]
    assert pressure.save_advantage(engine, owner, "CON", {"petrified"}) is True
    assert pressure.save_advantage(engine, foe, "CON", {"petrified"}) is False

    module = source_sphere()
    with delivery.delivering(engine, "trap:zone:auto7", hazard=delivery.TRAP, area="zone:auto7"):
        assert module.guard_needs_the_environment(engine, owner, {"feature_id": MINE_SHELTER}) is True
        assert module.guard_needs_the_environment(engine, owner, {"feature_id": SOURCE_SKIN}) is False
    assert module.guard_needs_the_environment(engine, owner, {"feature_id": MINE_SHELTER}) is False

    commit_turn(table.state(match_id)["menu"]["end_turn"])
    after = combat._load_session(match_id).engine.state
    assert after.current_actor_id != owner.entity_id
    assert table.state(match_id)["menu"] is not None


def test_source_circuit_is_pressed_on_the_table_and_survives_a_commit_and_a_fresh_reload(tmp_path):
    """The printed 1-minute circuit is real state on its owner, paid for and reloaded from disk.

    The review found the lane's own test called the effect directly, bypassing the button and the price,
    and asserted against the pre-reload engine. This presses the real menu entry, then rebuilds the
    service so the state comes back off disk.
    """
    module = source_sphere()
    combat, table, match_id, _send, commit_turn = fixture(tmp_path, [SOURCE_CIRCUIT], seed="11")
    engine = combat._load_session(match_id).engine
    owner = next(actor for actor in engine.state.actors.values() if actor.entity_id == OWNER)
    assert module.circuit(engine, owner) is False
    qi = RESOURCE_IDS["qi"]
    assert owner.resources.get(qi) == 30

    commit_turn(candidate(table, match_id, "Source Circuit"))
    fresh = CombatService(combat.source_root, combat.userdata_root)._load_session(match_id).engine
    reloaded = fresh.state.actors[OWNER]
    assert reloaded.resources.get(qi) == 28, "the printed 2 CP were not spent"
    assert module.circuit(fresh, reloaded) is True, "the circuit is not standing on its owner"
    condition = next(row for row in reloaded.conditions.values() if row.condition_id == module.CIRCUIT)
    assert isinstance(condition.expires_on, str) and condition.data["label"].startswith("Source circuit (1 minute")

    # ... and its printed Speed change: Source Pulse takes 20 feet off, not 10, while it stands.
    from combat import typed_executor
    from tests.test_typed_executor import _intent

    victim = fresh.state.actors[FOE]
    base = fresh._effective_speed(victim)
    row = _pulse_row()
    action = fresh.action_catalog[next(key for key, entry in fresh.action_catalog.items()
                                        if entry.display_name == "Source Circuit")]
    typed_executor.run_effects(
        typed_executor.Context(fresh, reloaded, action, None, {"source": SOURCE_PULSE, "effects": [row]},
                               [victim], victim, {}), [row])
    assert fresh._effective_speed(victim) == base - 20
    assert_reload_verify_replay(combat, match_id, combat.userdata_root)
    assert fresh.state.round_number == combat._load_session(match_id).engine.state.round_number


# --------------------------------------------------------------------------------------------------- expiry
def test_the_source_circuit_is_taken_off_when_its_printed_minute_is_up():
    """"awaken a source circuit for 1 minute" -- the condition must actually END, not merely carry a token.

    The review found the lane's duration test only read the token. This runs real turns until the clock
    has moved a full ten rounds and asserts the circuit is gone from its owner, on a live engine whose
    turn reset clears the same condition.
    """
    from combat.ext import effect_durations

    module = source_sphere()
    engine = _circuit_fight(seed="AUTO7F1-EXPIRES")
    keeper = engine.state.actors[KEEPER]
    _press(engine, "Source Circuit", actor_id=KEEPER)
    condition = next(row for row in keeper.conditions.values() if row.condition_id == module.CIRCUIT)
    assert condition.expires_on == effect_durations.round_token(engine, 10), condition.expires_on

    for _ in range(12 * len(engine.state.initiative_order)):
        current = engine.state.current_actor_id
        chosen = next(row for row in engine.legal_candidates()
                      if row.actor_id == current and row.display_name == "End turn")
        engine.execute_intent(ActionIntent(intent_id=f"auto7f1:end:{current}", decision_id=chosen.decision_id,
                                           candidate_id=chosen.candidate_id, state_version=chosen.state_version,
                                           actor_id=current, target_ids=()))
        if not module.circuit(engine, keeper):
            break
    assert module.circuit(engine, keeper) is False, \
        "the printed minute elapsed and the circuit is still standing: it never ends"
    assert not [row for row in keeper.conditions.values() if row.condition_id == module.CIRCUIT]
    assert engine.state.round_number >= 11, "the circuit ended before its printed minute was up"


# --------------------------------------------------------------------------------------------------- Ask me on the table
KEEPER_NAME, TRAPPER_NAME, ALLY_NAME = "Shelter Keeper", "Trapper", "Shelter Ally"
WIRE = (3, 5)


def _table_fight(tmp_path, *, ask: bool, seed: str):
    """A real persisted table fight: a Trap character wires a square, a Source keeper and an ally stand
    beside it. With ``ask`` the keeper is a player-controlled Ask-me character; without it the same
    keeper is the AI's, so its optional decisions answer themselves.

    Written out here rather than reused from a shared helper because it needs three named fighters at
    chosen squares with one of them owning the printed pair of talents, which the two-place shared
    fixture does not offer.
    """
    import json as _json
    import zipfile as _zipfile

    from combat.factory_compiler import compile_character
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    roster = [(KEEPER, _sheet((MINE_SHELTER, OLD_SHELTER), name=KEEPER_NAME), "team:a", (2, 5)),
              (TRAPPER, _sheet((TRAP_BASE, TRIPWIRE), name=TRAPPER_NAME), "team:b", (4, 6)),
              (ALLY, _sheet((PLAIN,), name=ALLY_NAME), "team:a", (2, 6))]
    ids = [actor_id for actor_id, _d, _t, _p in roster]
    bundles = []
    for actor_id, document, _team, _at in roster:
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with _zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", _json.dumps(document))
        bundles.append(compile_character(document, actor_id=actor_id,
                                         reaction_plan={"mode": "ask", "ask": True}
                                         if ask and actor_id == KEEPER else None))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    match_id = combat._finish_factory_match(
        bundles, ids,
        {actor_id: team for actor_id, _d, team, _p in roster},
        {actor_id: {"x": at[0], "y": at[1]} for actor_id, _d, _t, at in roster},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ids[0]], ids[1:],
        control_modes={actor_id: ("MANUAL" if ask or actor_id != KEEPER else "LOCAL_AUTO") for actor_id in ids},
        match_seed=seed, display_name="AUTO7f1 Ask me", maximum_rounds=6)["match_id"]

    def state():
        return table.state(match_id)

    def menu_for(entity: str) -> dict:
        for _ in range(30):
            current = state()
            if current["menu"].get("manual") and current["menu"].get("actor_id") == entity:
                return current
            table.act(match_id, current["menu"]["end_turn"], current["menu"]["decision_id"],
                      current["menu"]["state_version"], current["last_sequence"], [])
        raise AssertionError(f"{entity} never received a turn")

    def press(label: str, *, to: tuple[int, int] | None = None,
              through: tuple[int, int] | None = None, plan: tuple[str, ...] = ()) -> list[dict]:
        """Press one real menu entry; answer each reaction prompt from ``plan`` (USE/DECLINE per prompt)."""
        current = state()
        menu = current["menu"]
        if to is not None:
            chosen = next(row for row in menu["moves"]
                          if row["destination"]["x"] == to[0] and row["destination"]["y"] == to[1])
        elif through is not None:
            chosen = next(row for row in menu["moves"]
                          if any(step["x"] == through[0] and step["y"] == through[1] for step in row["path"]))
        else:
            chosen = next(option for group in menu["actions"] for option in group["options"]
                          if option.get("label") == label)
        answers: list[dict] = []
        prompts: list[dict] = []
        for step in range(12):
            response = table.act(match_id, chosen["candidate_id"], menu["decision_id"], menu["state_version"],
                                 current["last_sequence"], list(answers))
            if response["status"] == "COMMITTED":
                return prompts
            prompt = response["reaction"]
            prompts.append(prompt)
            reply = plan[step] if step < len(plan) else "DECLINE"
            answer = {**prompt["context"], "selection": "DECLINE"}
            if reply == "USE":
                answer = {**prompt["context"], "selection": "USE"}
                if prompt.get("choice"):
                    answer["option_ids"] = list((prompt["choice"].get("preferred")
                                                 or [prompt["choice"]["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("too many reaction prompts")

    def wire() -> None:
        menu_for(TRAPPER)
        press("Trap form: Tripwire + Razor Wire")
        press(f"Set Trap at {WIRE[0]},{WIRE[1]}")

    def actor(entity: str):
        return combat._load_session(match_id).engine.state.actors[entity]

    return combat, match_id, wire, menu_for, press, actor


def test_an_activation_name_is_not_repeated_after_a_commit_and_reload():
    """The name a paid guard's mark carries cannot be the name of a later activation.

    The review's finding was that the activation was an engine-only counter starting at zero, and a
    loaded fight gets a fresh engine that never restores it: so the first hazard delivered after every
    table commit was "1", exactly like a springing paid for before the commit, and a mark that outlived
    the commit answered a springing it had nothing to do with. Dropping the counter is what a reload
    does (combat/gate4_persistence._engine_from_loaded rebuilds the engine and copies state and events,
    never this attribute), so this is the same situation the service load path puts the table in.
    """
    module = source_sphere()
    engine = _mine_fight(seed="AUTO7R2F1-RELOAD")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    _wire_the_map(engine)
    assert _spring(engine, KEEPER, (2, 5))[0] > 0, "the real trap must wound the keeper, or this proves nothing"
    keeper = engine.state.actors[KEEPER]
    armed = keeper.turn_flags.get(module.ARMED)
    assert armed, "a paid use of the guard must stand the mark"
    marked = armed.split("|")[2]

    engine.__dict__.pop(delivery.SERIAL_ATTR, None)   # what loading the fight again does to the engine
    zone = _the_wire(engine)
    with delivery.delivering(engine, f"trap:{zone.zone_id}", hazard=delivery.TRAP, area=zone.zone_id):
        later = delivery.event(engine)

    assert later and later != marked, \
        f"the first activation after a reload must not repeat the name a saved mark carries: {marked} == {later}"
    assert int(later.split(".")[0]) > int(marked.split(".")[0]), (
        f"an activation name has to be taken from how much the fight has journalled, which grows across "
        f"the commit, or a loaded engine numbers its first hazard the same way it numbered one before: "
        f"{marked} then {later}")


def test_a_later_springing_after_a_table_commit_is_not_the_damage_that_paid_for_the_shelter(tmp_path):
    """"Resistance to the same triggering damage" across a real table commit and reload.

    The review's finding was that a keeper who sprang the wire, paid for it and then let the fight be
    saved and loaded again had a mark the next springing could answer: the loaded engine restarted its
    activation counter, so the ally's own springing of the same wire, in reach and of the same Slashing
    kind, was read as the one that paid. Here the ally really stands within 5 feet, the keeper's paid
    mark really is standing after the commit, and the ally's wound really is its own springing, so
    nothing but the activation name can keep that mark off it.
    """
    module = source_sphere()
    combat, match_id, wire, menu_for, press, actor = _table_fight(tmp_path, ask=True, seed="AUTO7R2F1-S1")
    wire()

    menu_for(KEEPER)
    guard = press("", to=WIRE, plan=("USE",))
    assert [prompt["reaction"] for prompt in guard] == ["Mine-Shelter Reflex"], guard
    assert actor(KEEPER).turn_flags.get(module.ARMED), "the paid use stands the mark"
    # Step clear of the wired square (which the keeper is standing in) but no further: the ally has to
    # still be within the printed 5 feet, or reach and not the activation would be what keeps the mark
    # off it. The square the keeper started on is free and is beside the ally.
    press("", to=(2, 5))

    menu_for(ALLY)                        # its own turn, still beside the keeper: the mark really is in reach
    assert actor(KEEPER).turn_flags.get(module.ARMED), "the mark must still be standing and in reach"
    asked = press("", to=WIRE)
    assert asked == [], \
        f"a springing the keeper's Reflex never answered must not stop the table for an answer: {asked}"
    session = combat._load_session(match_id).engine
    rolled = [int(event.payload.get("total") or 0) for event in session.events
              if event.event_type == "DAMAGE_ROLLED" and ALLY in (event.target_ids or ())]
    taken = [int((event.payload or {}).get("hp_damage") or 0) for event in session.events
             if event.event_type == "DAMAGE_COMMITTED" and ALLY in (event.target_ids or ())]
    assert taken and taken[-1] > 0, f"the wire must really wound the ally: {rolled} {taken}"
    assert taken[-1] == rolled[-1], \
        f"the ally took the whole wound of its own springing, unshared: {rolled} {taken}"


def test_a_player_is_never_asked_about_a_creature_the_keeper_cannot_reach(tmp_path):
    """The question is asked only once the printed "within 5 feet of you" has actually been checked.

    Before this fix the eligibility hook asked the question itself, and the table called it before
    reach, wound type and the owner's own Reaction had been checked -- so a manual game stopped to ask
    about an ally 10 feet away, and answering "yes" produced no Resistance at all.
    """
    module = source_sphere()
    combat, match_id, wire, menu_for, press, actor = _table_fight(tmp_path, ask=True, seed="AUTO7F1-ASKME")
    wire()

    menu_for(KEEPER)
    guard = press("", to=WIRE, plan=("USE",))
    assert [prompt["reaction"] for prompt in guard] == ["Mine-Shelter Reflex"], guard
    assert actor(KEEPER).turn_flags.get(module.ARMED), "the paid use stands the mark"
    press("", to=(1, 5))                      # step two squares clear of the wire before the ally enters

    menu_for(ALLY)
    asked = press("", to=WIRE)
    assert asked == [], f"a creature out of reach must not stop the table for an answer: {asked}"
    assert actor(ALLY).current_hp == 200 - 10, actor(ALLY).current_hp  # the whole wound, unshared
    assert module.ARMED in actor(KEEPER).turn_flags, "an unanswered question leaves the mark alone"


def test_a_keeper_out_of_reach_is_not_asked_within_the_springing_that_paid_for_it():
    """"within 5 feet of you": no question about a creature the keeper cannot reach, asked or not.

    This is the printed reach limit on its own, with nothing else holding it back: the keeper's wound
    pays for its Reflex in the very same springing (so the mark really is standing, names this
    activation and is not retired by the time the ally is hurt), the ally really is its own team's
    willing creature, and the ally is then hurt 20 feet away. Correct activation matching cannot be
    what silences this question, because there is only one activation in the case.
    """
    module = source_sphere()
    engine = _mine_fight(ask=KEEPER, seed="AUTO7R2F1-REACH")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    engine.typed_ask_reactors = frozenset({KEEPER})
    asked: list[dict[str, Any]] = []
    engine.set_reaction_provider(_recording_provider(
        engine.typed_ask_reactors, {REFLEX_DECISION: "USE", SHELTER_CHOICE: "USE"}, asked))
    _wire_the_map(engine)
    keeper, ally = engine.state.actors[KEEPER], engine.state.actors[ALLY]
    ally.position = Position(x=2, y=9)  # 20 feet from the keeper, its own team's creature
    assert module._willing_ally(keeper, ally), "the ally is willing: it is the printed reach that stops it"

    taken = _one_springing(engine, [KEEPER, ALLY], amount=12)
    assert keeper.turn_flags.get(module.ARMED), "the paid use of the guard must stand its mark"
    assert [row for row in asked if row["reaction_source_id"] == SHELTER_CHOICE] == [], \
        "a creature out of reach must not stop the table for an answer"
    assert taken[ALLY] == 12, taken     # and nothing is shared with it
    assert module.ARMED in keeper.turn_flags, "a question never asked spends nothing"


def test_an_incapacitated_keeper_is_never_asked_who_the_shared_resistance_goes_to():
    """A keeper that cannot react at all is not asked who it would shelter.

    The same gate as the reach limit, one step further on, and reached with the mark already paid:
    the keeper's own wound spends its Reflex inside this very springing, so there is a real mark
    naming this activation, and only then does the keeper fall Incapacitated before its ally's wound
    resolves. Incapacitating the keeper first would leave no paid mark at all and the question would
    never be reached, which is not the gate under test.
    """
    module = source_sphere()
    engine = _mine_fight(ask=KEEPER, seed="AUTO7R2F1-OUT")
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    engine.typed_ask_reactors = frozenset({KEEPER})
    asked: list[dict[str, Any]] = []
    engine.set_reaction_provider(_recording_provider(
        engine.typed_ask_reactors, {REFLEX_DECISION: "USE", SHELTER_CHOICE: "USE"}, asked))
    _wire_the_map(engine)
    keeper = engine.state.actors[KEEPER]
    assert module._willing_ally(keeper, engine.state.actors[ALLY]), \
        "the ally is a willing creature: it is the keeper's own state that stops it"

    def fall_asleep(index: int, engine: Any) -> None:
        if index == 1:  # after the wound that paid for the guard, before the ally's own
            engine._apply_condition(engine.state.actors[KEEPER], "condition:typed.incapacitated",
                                    "system:test.auto7", KEEPER, expires_on=None)

    taken = _one_springing(engine, [KEEPER, ALLY], amount=12, between=fall_asleep)
    assert [row for row in asked if row["reaction_source_id"] == REFLEX_DECISION], \
        "the keeper's own guard must really have been paid for, or this proves nothing"
    assert [row for row in asked if row["reaction_source_id"] == SHELTER_CHOICE] == [], \
        "an Incapacitated keeper cannot be asked to shelter anyone: it cannot react at all"
    assert taken[ALLY] == 12, taken     # nothing is shared with it
    assert module.ARMED in keeper.turn_flags, "a question never asked spends nothing"


SHELTER_CHOICE = "choice:needle.source_shelter"
REFLEX_DECISION = "reaction:typed." + MINE_SHELTER


def _recording_provider(ask_reactors: frozenset[str], answers: dict[str, str], seen: list[dict[str, Any]]):
    """A stand-in for the table's reaction provider, and it decides the same way the real one does
    (combat/gate5_service.py CombatService._ask_reactors and its provider): a question is only put to a
    player for a reactor the service considers player-controlled; for anyone else the controller answers
    for itself and nothing is recorded. Only the named questions get an answer, so nothing else in the
    fight changes."""
    from combat.gate2_runtime_models import ReactionDecision

    def provider(request: dict[str, Any]):
        if str(request["reactor_id"]) not in ask_reactors:
            return None, None
        seen.append(request)
        wanted = answers.get(str(request["reaction_source_id"]))
        if isinstance(wanted, list):  # one answer per question, in the order the table asks them
            wanted = wanted.pop(0) if wanted else None
        if wanted is None:
            return None, None
        return ReactionDecision(checkpoint=str(request["checkpoint"]), reactor_id=str(request["reactor_id"]),
                                reaction_source_id=str(request["reaction_source_id"]), selection=wanted,
                                option_ids=() if wanted == "DECLINE" else ("shelter",)), None

    return provider


def _one_sheltered(*, answer: str | list[str], seed: str, ask: bool = True, victims: list[str] | None = None):
    """One springing of a real wired square wounding the keeper and its allies, with the keeper's optional
    decisions routed to a recorded provider.

    ``ask`` False builds the same keeper as an automatic character -- no Ask-me reaction plan and nobody
    in ``typed_ask_reactors`` -- which is exactly what the table does with a character the AI drives, and
    the provider (still installed) records that it is then never consulted. A list of answers is taken
    one question at a time, so a case can answer the keeper differently about each creature of the
    same springing.
    """
    module = source_sphere()
    engine = _mine_fight(ask=KEEPER if ask else None, seed=seed)
    for actor_id in (KEEPER, ALLY, THIRD):
        engine.state.actors[actor_id].saving_throws["DEX"] = -50
    engine.typed_ask_reactors = frozenset({KEEPER}) if ask else frozenset()
    asked: list[dict[str, Any]] = []
    engine.set_reaction_provider(_recording_provider(
        engine.typed_ask_reactors, {REFLEX_DECISION: "USE", SHELTER_CHOICE: answer}, asked))
    _wire_the_map(engine)
    # One springing, one frame: the keeper's own wound is what pays for the Reflex, and each ally's is
    # the same activation of the same trap. No printed trap pattern wounds more than the creature that
    # triggered it, so this drives the trap module's own block with the creatures it wounded.
    order = victims or [KEEPER, ALLY]
    taken = _one_springing(engine, order, amount=12)
    keeper = engine.state.actors[KEEPER]
    assert _resolved(engine, MINE_SHELTER), \
        "the keeper's own wound must be answered and paid for, or there is no printed use to answer"
    return module, engine, keeper, taken, 12, asked


def _one_unanswered():
    return _one_sheltered(answer="DECLINE", seed="AUTO7F1-AIASK", ask=False)


def test_a_player_asked_the_keeper_which_creature_the_shared_resistance_covers_and_can_pass():
    """"you may choose one willing creature": a player controlling the keeper is asked, and may pass.

    The review's checklist item 9 was that the row sheltered every victim silently because nothing ever
    asked. The question names the keeper (it owns the printed talent), names the creature it is about,
    and passing costs the creature the whole wound -- while an accepted creature still spends the mark.
    """
    module, engine, keeper, taken, _rolled, asked = _one_sheltered(
        answer="USE", seed="AUTO7R1F1-ASKYES")
    questions = [row for row in asked if row["reaction_source_id"] == SHELTER_CHOICE]
    assert len(questions) == 1, f"the player was asked {len(questions)} times about the shared Resistance"
    assert questions[0]["reactor_id"] == KEEPER, questions[0]           # the keeper owns the printed talent
    assert questions[0]["protected_target_id"] == ALLY, questions[0]    # and the question names the creature
    assert questions[0]["checkpoint"].startswith("NEEDLE:source_shelter"), questions[0]["checkpoint"]
    assert taken[ALLY] == 6, taken
    assert module.ARMED not in keeper.turn_flags, "the mark is spent with the one creature it reached"

    _module, _engine, _keeper, passed, _rolled, _asked = _one_sheltered(
        answer="DECLINE", seed="AUTO7R1F1-ASKNO")
    assert passed[ALLY] == 12, "the player passed, so the creature took the whole wound"


def test_a_keeper_who_passes_on_one_creature_may_still_shelter_the_next_of_the_same_springing():
    """"you may choose one willing creature": passing is not spending the one use.

    The review's finding was that the mark was spent whatever the player answered, so a keeper who
    passed on the first creature of a springing could not choose the second -- and the printed text
    limits how many creatures one use may protect, not how often its owner may be asked. One springing
    wounds the keeper and two of its own creatures; the player passes on the first and shelters the
    second, which must still be asked about and must still be spared the wound.
    """
    module, _engine, keeper, taken, rolled, asked = _one_sheltered(
        answer=["DECLINE", "USE"], seed="AUTO7R2F1-PASS", victims=[KEEPER, ALLY, THIRD])
    questions = [row for row in asked if row["reaction_source_id"] == SHELTER_CHOICE]

    assert [row["protected_target_id"] for row in questions] == [ALLY, THIRD], questions
    assert taken[ALLY] == rolled, f"a creature the player passed on took the whole wound: {taken}"
    assert taken[THIRD] == rolled // 2, f"the next creature of the same springing is sheltered: {taken}"
    assert module.ARMED not in keeper.turn_flags, "the accepted creature spends the mark"


def test_one_use_of_the_guard_shelters_one_creature_even_when_the_player_answers_twice():
    """The control for the case above: "one willing creature" is a limit, and it is the accepting that
    spends the mark.

    A player who says yes about every creature of one springing is asked about each of them and still
    protects only the first: the printed text allows one creature per use of the Reaction, so the mark
    is spent by the first acceptance and no later creature of that springing can be sheltered.
    """
    module, _engine, keeper, taken, rolled, asked = _one_sheltered(
        answer=["USE", "USE"], seed="AUTO7R2F1-TWICE", victims=[KEEPER, ALLY, THIRD])
    accepted = [row for row in asked if row["reaction_source_id"] == SHELTER_CHOICE]

    assert [row["protected_target_id"] for row in accepted] == [ALLY], \
        f"only the first creature can be sheltered by one use of the guard: {accepted}"
    assert taken[ALLY] == rolled // 2, taken
    assert taken[THIRD] == rolled, f"one use shelters one creature, not two: {taken}"
    assert keeper.turn_flags.get(module.ARMED) is None, "the first acceptance spent the mark"


def test_a_keeper_nobody_is_asking_shares_the_resistance_by_itself():
    """An AI-driven keeper: the provider is never consulted, and the printed benefit still happens -- the
    preferred option is the shelter, exactly as every other optional rider in
    combat/ext/rider_choices.py behaves. The one-creature limit is unchanged either way."""
    module, _engine, keeper, taken, _rolled, asked = _one_unanswered()
    assert asked == [], \
        f"an AI-controlled character must not stop the fight for an answer it makes itself: {asked}"
    assert taken[ALLY] == 6, taken
    assert module.ARMED not in keeper.turn_flags, "the mark is spent with the one creature it reached"
