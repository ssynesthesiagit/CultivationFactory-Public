"""Movement passives (owner 2026-09-28: "still a bunch of stuff thats getting skipped" -- Tabik Damu's Athletics, Flowing
River and Shinobi features).

Each is a "motion" row in the bundle's typed_passives (combat/rules/feature_blocks.json, compiled by
combat/typed_reactions.py compile_blocks); the engine asks this module at the moments below. A fight saved before these
rows existed has none, so it replays unchanged.

  speed_bonus       +ft to its Speed (Swift Movement, "while holding Martial Focus")
  ignore_difficult  nonmagical difficult terrain costs it nothing extra (Unimpeded Positioning, while holding Martial
                    Focus; Silent Step, while obscured) -- the map's own difficult squares and painted terrain, never an
                    area made by an ability; with ``"magical": true`` (Juggernaut: "ignore difficult terrain", no
                    "nonmagical" in the text) an area's difficult ground costs it nothing extra either
  difficult_exempt  an AREA-scoped benefit publishes the squares it ignores here (the ext hook of the same name, ext/
                    formations' Court of the Ninefold Array, Sand Step, Death's Court of the Ninth Grave), so a servant
                    that walked out of the area pays again on its next step
  oa_disadvantage   opportunity attacks against it for leaving reach have Disadvantage (Mobility)
  no_oa_unseen      no opportunity attack against it from a creature that can't see it (Silent Step)
  regain_focus      taking one of these as its Action regains Martial Focus (Coordinated Movement: Dash, Disengage;
                    Gather the Current: Dodge, Disengage)
  hide_advantage    Advantage on checks to Hide while obscured (Silent Step)
  afterimage        compiled ownership consumed by ext.athletics at committed movement steps; shared condition
                    queries/removal remain here. The legacy moved_ft total is bookkeeping, not image production.
  disengage_hex     when it Disengages, the first creature whose reach it leaves has Disadvantage on its next melee
                    attack against it before its next turn (Current Between Steps)
  speed_floor       ordinary effects cannot reduce its Speed below its normal value (Juggernaut): a typed Speed penalty or
                    "halve its Speed" is not applied to it (typed_executor _modifier); an effect that sets its Speed to 0,
                    and the Grappled / Restrained conditions, still work

"While" conditions: "martial_focus" (it holds Martial Focus), "obscured" (it stands in darkness, smoke, fog or an area
that is lightly or heavily obscured) and "condition:<id>" (it bears that condition: Juggernaut's Adrenaline marker,
"condition:typed.body_adrenaline_juggernaut").
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, NamedTuple

FOCUS = "resource:core.martial_focus"
AFTERIMAGE = "condition:typed.afterimage"
HEX = "condition:typed.current_between_steps"
ACTIONS = {"system:combat.dash": "dash", "system:combat.disengage": "disengage", "system:combat.dodge": "dodge"}


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    from .movement_sequences import enabled
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "motion" and row.get("kind") == kind
            and enabled(engine, actor, row.get('feature_id'))]


def obscured(engine: Any, actor: Any) -> bool:
    from . import zones

    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        visual = profile.get("visual") or {}
        if profile.get("wall"):
            continue
        if (profile.get("obscured") in ("light", "heavy") or visual.get("darkness") or visual.get("material") in ("darkness", "smoke", "fog")) \
                and zones._inside(engine, actor, zone):
            return True
    return False


def obscured_at(engine: Any, position: Any) -> bool:
    """Whether a square lies in darkness, smoke, fog or an obscured area (Step Through Darkness's destination)."""
    from . import zones

    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        visual = profile.get("visual") or {}
        if profile.get("wall"):
            continue
        if (profile.get("obscured") in ("light", "heavy") or visual.get("darkness") or visual.get("material") in ("darkness", "smoke", "fog")) \
                and any(cell.x == position.x and cell.y == position.y for cell in zone.affected_cells):
            return True
    return False


def resource_gate(row: dict[str, Any], resources: dict[str, int]) -> bool | None:
    """Shared combat/journey motion gate; None requires encounter context.

    Pure query over compiled ownership and current resources. Travel must not
    treat obscurity or a combat condition it cannot establish as satisfied.
    """
    need = row.get("while")
    if not need:
        return True
    if need == "martial_focus":
        return resources.get(FOCUS, 0) >= 1
    return None


def resource_motion_rows(rows, resources, kind):
    """Owned motion rows usable without encounter context (journey consumer)."""
    return [row for row in rows if row.get("block") == "motion" and row.get("kind") == kind
            and resource_gate(row, resources) is True]


def _holds(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    gate = resource_gate(row, actor.resources)
    if gate is not None:
        return gate
    need = row.get("while")
    if need == "obscured":
        return obscured(engine, actor)
    if isinstance(need, str) and need.startswith("condition:"):
        return any(condition.condition_id == need for condition in actor.conditions.values())
    return True


def _active(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in _rows(engine, actor, kind) if _holds(engine, actor, row)]


def grouped_speed_penalty(engine: Any, actor: Any, condition: Any) -> int:
    """One live grouped Speed contribution, before the group's maximum is taken.

    Shared by speed_adjustment and end_effect's speed/movement selectors. A
    weaker live contribution remains selectable: removing a stronger instance
    must leave it intact. Suppressed conditions and contributions ignored by a
    live ordinary Speed floor contribute zero and are not eligible reductions.
    No ability identity, mutation, rolls or Speed hooks are consulted.
    """
    from .typed_executor import is_active_typed_condition

    data = condition.data
    group = data.get("speed_penalty_group")
    if group is None:
        return 0
    feet = data.get("speed_penalty_ft")
    if not isinstance(group, str) or not group or type(feet) is not int or feet < 0:
        raise ValueError("Speed penalty groups require a name and nonnegative integer feet")
    if not is_active_typed_condition(condition):
        return 0
    if data.get("suppress_speed_penalty_if_floor") and floors_speed(engine, actor):
        return 0
    return feet


def speed_adjustment(engine: Any, actor: Any, *, replacing_source: str | None = None, excluded_speed_groups=()) -> int:
    """Live fixed Speed adjustments, before zero floors, halving and passive bonuses.

    Shared by base Speed, Speed-setting effects and bonuses derived from walking
    Speed. ADD speed_ft modifiers and condition speed_delta sum normally. Negative
    Speed rows from one activation combine; across activations only that
    source's strongest (most negative) application contributes. Named
    speed_penalty_group conditions contribute only their strongest unsuppressed
    speed_penalty_ft; distinct groups add. A contribution opting into ordinary
    Speed-floor suppression is ignored while that floor is active.

    A setting effect may pass replacing_source to omit the integer ADD modifiers
    its first effect is about to refresh. Conditions still count. This query does
    not apply grapple/life-state/Speed-zero overrides or call Speed hooks: deriving
    an adjustment must not bake temporary immobilization into a later bonus, or
    recursively ask a bonus for itself. No state, events or rolls are changed.
    """
    speed_modifiers = [m for m in actor.modifiers.values()
                        if m.target_field == "speed_ft" and m.operation == "ADD"
                        and not (replacing_source is not None and m.source_definition_id == replacing_source
                                 and isinstance(m.value, int))]
    # Negative Speed rows from one source definition are non-stacking across
    # activations: keep that source's strongest active application, while
    # retaining every row for independent expiry. Rows created by one typed
    # activation share an application identity and applier and combine first,
    # as required by typed_executor._modifier. One activation is identified
    # by its application identity *and* its applier, because one table intent
    # can carry deliveries from several owners -- each arriving area runs its
    # own save under the movement intent that brought the creature in
    # (combat/zones.py) -- so two owners failing under that one intent are
    # two independent activations, not one doubled penalty. Rows with no
    # identity fall back to the applier alone, which keeps directly applied
    # rows owned by different creatures from merging as well.
    applications: dict[tuple[str, str | None, str | None], int] = {}
    for modifier in speed_modifiers:
        value = int(modifier.value)
        if value < 0:
            key = (modifier.source_definition_id, modifier.application_id, modifier.source_actor_id)
            if modifier.application_id is None:
                applications[key] = min(applications.get(key, value), value)
            else:
                applications[key] = applications.get(key, 0) + value
    source_penalties: dict[str, int] = {}
    for (source, _application, _applier), value in applications.items():
        source_penalties[source] = min(source_penalties.get(source, value), value)
    delta = sum(int(m.value) for m in speed_modifiers
                if int(m.value) >= 0) + sum(source_penalties.values())
    penalties = {}
    for condition in actor.conditions.values():
        data = condition.data
        delta += int(data.get("speed_delta", 0))
        group = data.get("speed_penalty_group")
        if group is None or group in excluded_speed_groups:
            continue
        feet = grouped_speed_penalty(engine, actor, condition)
        if feet:
            penalties[group] = max(penalties.get(group, 0), feet)
    return delta - sum(penalties.values())


def all_mode_speed_penalties(engine, actor):
    """Live opt-in grouped penalties, shared by native independent Speeds.

    A condition with speed_penalty_all_modes=True uses the existing named
    speed_penalty_group/speed_penalty_ft contract. Same-group rows contribute
    only their largest live amount, with the existing suppression/floor rules.
    No matching condition returns an empty mapping and changes no old Speed.
    """
    penalties={}
    for condition in actor.conditions.values():
        if condition.data.get('speed_penalty_all_modes') is not True:
            continue
        group=condition.data.get('speed_penalty_group')
        feet=grouped_speed_penalty(engine,actor,condition)
        if feet:penalties[group]=max(penalties.get(group,0),feet)
    return penalties


def independent_speed_blocked(engine, actor):
    """Preserve immobilization while flooring an opted-in mode independently.

    Only the actual all-mode grouped penalties are omitted from the walking
    gate. Every unrelated modifier, root, life state and global restriction
    remains authoritative. With no opt-in this is the historical gate.
    """
    groups=all_mode_speed_penalties(engine,actor)
    return engine._effective_speed(actor,excluded_speed_groups=tuple(groups))<=0 if groups else engine._effective_speed(actor)<=0


def speed_bonus(engine: Any, actor: Any) -> int:
    from . import carry

    if any(condition.condition_id == carry.ENCUMBERED for condition in actor.conditions.values()):
        return 0  # over its carrying capacity: Speed at most 5 feet
    return sum(int(row.get("ft") or 0) for row in _active(engine, actor, "speed_bonus"))


def ignores_difficult(engine: Any, actor: Any) -> bool:
    if _active(engine, actor, "ignore_difficult"):
        return True
    # Echoing Step: "Until the end of your turn: ignore nonmagical difficult terrain" (combat/ext/echoing_step.py).
    if actor.turn_flags.get("echoing_step") and engine.state.current_actor_id == actor.entity_id:
        return True
    from . import typed_executor

    # A temporary effect ("until the end of your turn, ignore nonmagical difficult terrain": Lotus Step) is a typed condition
    # whose rule carries ``ignore_difficult`` (combat/rules/typed_conditions.json).  The engine is passed so an ability
    # that RETIRED such a condition may keep a stale saved instance from granting it: a save written during the actor's own
    # turn resumes before the next turn start that would have removed it, and this read is what resumed movement asks
    # (combat/typed_executor.py condition_rules, ``condition_excluded``).
    return any(row.get("ignore_difficult") for row in typed_executor.condition_rules(actor, engine=engine))


def ignores_area_difficult(engine: Any, actor: Any) -> bool:
    """Whether difficult ground made by an ability (a zone) costs ``actor`` nothing extra as well (Juggernaut)."""
    return any(row.get("magical") for row in _active(engine, actor, "ignore_difficult"))


class TerrainExemption(NamedTuple):
    """What one ``difficult_exempt`` subscriber publishes: the squares, and how much terrain they cover.

    ``nonmagical_only`` separates the two printed scopes the rules distinguish.  "move through nonmagical Difficult
    Terrain without extra movement" (Death's Court of the Ninth Grave) covers ordinary ground only; "ignore difficult
    terrain" with no "nonmagical" in the text (Juggernaut, whose condition rule carries ``magical``) also covers ground an
    ability made.  A subscriber returns this instead of a bare set to say which one it is; a bare set keeps the original
    meaning (both), so every existing subscriber is unchanged.
    """
    cells: frozenset[tuple[int, int]] = frozenset()
    nonmagical_only: bool = False


def _published(row: Any) -> tuple[frozenset[tuple[int, int]], bool]:
    """One ``difficult_exempt`` answer as (squares, nonmagical_only).  A bare iterable of squares is the original
    unrestricted scope; a TerrainExemption says so itself; anything else is read as no squares."""
    if isinstance(row, TerrainExemption):
        return frozenset(row.cells), bool(row.nonmagical_only)
    if row is None:
        return frozenset(), False
    cells = frozenset((int(cell[0]), int(cell[1])) for cell in row if len(cell) >= 2)
    return cells, False


def exempt_cells(engine: Any, actor: Any, terrain: str = "nonmagical") -> set[tuple[int, int]]:
    """The squares this creature does not pay extra movement to enter, published square by square by an ability whose
    benefit is scoped to an AREA (the ``difficult_exempt`` subscribers).

    ``terrain`` says which ground is being priced, because the printed scopes differ: ``"nonmagical"`` (the default --
    the map's own painted terrain, which is never magic) returns every published square, while ``"magical"`` (ground an
    ability made) returns only the squares published by an ability whose benefit ignores ALL difficult terrain.  A
    subscriber that says "nonmagical" therefore stops granting inside a Domain, a burning field or a spell's own rough
    ground, while Juggernaut and the Ninefold Array keep working there.

    A live per-call query, so the squares follow the creature: a Death servant that stepped out of its master's Domain
    is charged again on its next step, and one that walked back in is not.  Used by combat/zones.py ``difficult_cells``
    and combat/spatial_areas.py ``difficult_at`` (an ability's or the map's own terrain areas), by
    ``mover_exempt_cells``/``repriced`` below for the map's own difficult squares, and therefore by every reader of
    those two.  No subscriber, no squares, no change.
    """
    from . import ext
    from .read_queries import memo
    from .space import point

    def collect():
        answers = [scoped for scoped in (_published(row) for row in ext.run("difficult_exempt", engine, actor))
                   if scoped[0]]
        if terrain == "magical":
            answers = [scoped for scoped in answers if not scoped[1]]
        return frozenset(cell for cells, _ in answers for cell in cells)

    # Route search keeps the actor at its real origin while pricing hypothetical
    # edges. Real movement has no read frame, so every actual step still asks
    # again. Projected actors/origins and terrain scopes have distinct keys.
    return set(memo(engine, ('movement_exempt', id(actor), point(actor.position), terrain),
                    lambda: (actor, collect()))[1])


def mover_exempt_cells(engine: Any, actor: Any) -> frozenset[tuple[int, int]] | None:
    """The squares on which ``actor``'s map terrain costs are stripped while it moves: every square (``None``) for an
    ordinary whole-creature exemption, only the published squares for an area-scoped one, and an empty set when neither
    applies.  ``None`` and an empty set are different answers, so callers that only strip "named squares" test for None.
    """
    if actor is None:
        return None
    if ignores_difficult(engine, actor):
        return None
    return frozenset(exempt_cells(engine, actor))


def floors_speed(engine: Any, actor: Any) -> bool:
    """Whether ordinary effects cannot reduce ``actor``'s Speed below its normal value (Juggernaut, while Adrenaline)."""
    return bool(_active(engine, actor, "speed_floor"))


@contextmanager
def terrain_for(engine: Any, actor: Any) -> Iterator[None]:
    """While ``actor`` moves or its moves are listed: the map's difficult squares cost it nothing extra where it ignores
    nonmagical difficult terrain (painted map terrain is left out in combat/zones.py difficult_cells).

    An ordinary whole-creature exemption strips every square for the length of the move.  An AREA-scoped one strips only
    the squares that ability published (mover_exempt_cells), which are re-read by ``repriced`` at every step so the
    benefit starts and stops with the area.  Under an AREA-scoped one a wall an ability raised keeps its own price to
    cross (``wall_traversal_cost``); under a whole-creature one the printed reach is the whole map and still takes that
    price with it, which is the long-standing behaviour this change deliberately leaves alone.
    """
    cells = mover_exempt_cells(engine, actor)
    if cells is not None and not cells:
        yield
        return
    grid = engine.grid
    if "unimpeded_full_costs" in grid.__dict__:
        yield  # already inside a mover's unimpeded move (a listing made during it): the outer one restores the costs
        return
    # The map's own costs are kept on the grid while this mover's squares are stripped: combat/zones.py sync_walls runs
    # during the move (each step, a zone appearing or ending) and rebuilds the costs, so it re-strips them from these
    # (fight audit 2026-09-29: the move was listed at 5 feet a square, a mid-move sync put the map's x4 square back and the
    # fight crashed with "The movement budget changed before the next path step").
    grid.unimpeded_full_costs = grid.base_movement_cost
    grid.unimpeded_cells = cells
    grid.unimpeded_mover = getattr(actor, "entity_id", None)
    grid.base_movement_cost = unimpeded(grid.unimpeded_full_costs, cells, wall_traversal_cost(grid) if cells is not None else None)
    try:
        yield
    finally:
        full = grid.__dict__.pop("unimpeded_full_costs", None)
        grid.__dict__.pop("unimpeded_cells", None)
        grid.__dict__.pop("unimpeded_mover", None)
        if full is not None:
            grid.base_movement_cost = full


@contextmanager
def repriced(engine: Any, actor: Any) -> Iterator[None]:
    """While ONE step is priced: an area-scoped terrain exemption is re-read at the mover's CURRENT position, so a step
    that leaves the area is charged and a step that enters it is not.  Nothing happens for the ordinary whole-creature
    exemption (combat/terrain_for already stripped every square for the whole move), and the grid is left exactly as it
    was found.
    """
    grid = engine.grid
    if actor is None or ignores_difficult(engine, actor):
        yield  # not an area-scoped mover: terrain_for owns its costs for the whole move
        return
    live = frozenset(exempt_cells(engine, actor))
    full = grid.__dict__.get("unimpeded_full_costs")
    if full is None:
        # The move stripped nothing, because this creature had no exempt square where it started: a step that reaches
        # into the area is priced with the squares it now ignores, and only for this step.
        if not live:
            yield
            return
        held = grid.base_movement_cost
        grid.base_movement_cost = unimpeded(held, live, wall_traversal_cost(grid))
        try:
            yield
        finally:
            grid.base_movement_cost = held
        return
    installed = grid.__dict__.get("unimpeded_cells")
    if installed is None or live == installed:
        yield  # every square stripped for the whole move, or the squares it ignores did not change while it walked
        return
    held = grid.base_movement_cost
    grid.base_movement_cost = unimpeded(full, live, wall_traversal_cost(grid))
    try:
        yield
    finally:
        grid.base_movement_cost = held


def wall_traversal_cost(grid: Any) -> dict:
    """The squares an ability-raised wall charges its own extra movement cost for, and how much each one costs to
    cross: Dune Wall's "4 feet of movement for every 1 foot moved", a humble wall's double.  combat/zones.py sync_walls
    rebuilds this on every zone change, and ``unimpeded`` keeps these prices out of a terrain exemption's discount.

    A wall is not ground.  The AREA-scoped terrain benefits ("nonmagical Difficult Terrain costs no extra movement", "ignore
    difficult terrain", each limited to the area that published it) are about the floor a creature walks over; a wall's
    price is what climbing or wading through it costs, and no area-scoped exemption claims to remove that.  Kept as its own
    layer rather than folded into the map's costs so the two can be discounted independently.  A whole-creature exemption,
    whose reach is the entire map, still takes the wall's price with it -- that pre-existing behaviour is untouched here.

    Shared by every reader of ``unimpeded``: ``terrain_for``, ``repriced`` and combat/zones.py ``sync_walls``.
    """
    return getattr(grid, "wall_traversal_cost", None) or {}


def unimpeded(costs: dict, cells: frozenset | None = None, preserved: dict | None = None) -> dict:
    """The costs an unimpeded mover pays: the map's difficult squares cost it nothing extra on ``cells`` (every square
    when ``cells`` is None).

    With ``cells`` a set of squares (an AREA-scoped exemption) ``preserved`` is a second layer the discount does not
    reach -- the walls' own traversal prices, ``wall_traversal_cost`` above.  Each COVERED square then costs 1, or the
    wall's own price where one is raised on it; every square OUTSIDE ``cells`` keeps the price the map gave it, wall or
    not, because this exemption says nothing about it.  Pass ``preserved`` only in that AREA-scoped case: a
    whole-creature "ignore difficult terrain" benefit (``cells`` None) keeps its printed reach over everything, walls
    included, which is the pre-existing behaviour.
    """
    kept = {} if preserved is None else {cell: int(cost) for cell, cost in preserved.items() if int(cost) > 1}
    if cells is None:
        return {cell: cost for cell, cost in costs.items() if int(cost) <= 1}
    # Only a square the exemption actually covers is repriced.  A square outside ``cells`` keeps exactly the price the map
    # built, which is already the greater of its ground and its wall (combat/zones.py sync_walls): a cheap wall overlapping
    # dearer ground must not make an UNCOVERED square cheaper merely by being underfoot -- x2 ground under a Humble Wall's
    # x4 stays x2 out here, and x4 ground under a Humble Wall's x2 stays x4 (AUTO22r4 review finding 1).
    return {cell: (kept[cell] if cell in kept else 1) if cell in cells else cost for cell, cost in costs.items()}


def hide_mode(engine: Any, actor: Any) -> str | None:
    return "ADVANTAGE" if _active(engine, actor, "hide_advantage") else None


def allows_opportunity_attack(engine: Any, reactor: Any, mover: Any) -> bool:
    if not _rows(engine, mover, "no_oa_unseen"):
        return True
    from . import stealth

    return stealth.sees(engine, reactor, mover)


def focus_regain_source(rows: Any, resources: dict, economy: str, source_definition_id: str) -> str | None:
    """Owned Action-triggered Focus provider for combat and persisted map actions.

    Pure query: callers must invoke it only after real completion and commit the
    returned source with the actual resource gain. No row, missing pool, held
    Focus or Bonus Action means no grant. Meridian's combat receipt stays intact.
    """
    action = ACTIONS.get(source_definition_id)
    if not action or economy != "ACTION" or FOCUS not in resources or resources[FOCUS] >= 1:
        return None
    row = next((row for row in rows if row.get("block") == "motion" and row.get("kind") == "regain_focus"
                and action in (row.get("actions") or [])), None)
    if row is not None:
        return f"passive:{row['feature_id']}"
    return None


def after_action(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    source = focus_regain_source(_rows(engine, actor, "regain_focus"), actor.resources, economy, source_definition_id)
    if source is not None:
        engine._gain_resource(actor, FOCUS, 1, source)


def after_move(engine: Any, mover: Any, moved_ft: int) -> None:
    """After a willing move has been recorded.  Runs for any creature, summoned or not."""
    from . import ext

    if mover is not None and moved_ft > 0:
        # The general seam for a printed benefit that depends on where its creature now stands: a plug-in reconciles
        # its own area-membership effects (a servant that walked into or out of its master's Domain), or says what
        # it just gained. Default-inert: no subscriber, no state, no event.
        ext.run("after_move", engine, mover, int(moved_ft))
    rows = _rows(engine, mover, "afterimage")
    if not rows or moved_ft <= 0:
        return
    mover.turn_flags["moved_ft"] = int(mover.turn_flags.get("moved_ft") or 0) + int(moved_ft)
    # Threshold creation belongs to the owned committed-step provider. Keep
    # this historical whole-route total for readers, without a second dispatch.


def has_afterimage(target: Any) -> bool:
    return any(condition.condition_id == AFTERIMAGE for condition in target.conditions.values())


def strike_afterimage(engine: Any, target: Any, source: str) -> None:
    engine._remove_condition(target, AFTERIMAGE, source)


def leaving_reach(engine: Any, mover: Any, previous: Any, nxt: Any) -> None:
    rows = _rows(engine, mover, "disengage_hex")
    if not rows or not mover.turn_flags.get("disengaged") or mover.turn_flags.get("hexed"):
        return
    from . import typed_reactions

    for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not other.active or other.team_id == mover.team_id:
            continue
        reach = typed_reactions.opportunity_reach(engine, other) or 5
        if engine.grid.distance_ft(other.position, previous) <= reach < engine.grid.distance_ft(other.position, nxt):
            mover.turn_flags["hexed"] = True
            engine._apply_condition(other, HEX, f"passive:{rows[0]['feature_id']}", mover.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"against": mover.entity_id, "label": f"Disadvantage on its next melee attack against {mover.display_name}"})
            return


def attack_mode(engine: Any, attacker: Any, target: Any, *, melee: bool, source: str) -> str | None:
    """Disadvantage from the target's passives: Mobility on an opportunity attack; Current Between Steps on the next melee
    attack (spent)."""
    if getattr(engine, "_typed_oa_attacker", None) == attacker.entity_id and _rows(engine, target, "oa_disadvantage"):
        return "DISADVANTAGE"
    if melee:
        for condition in attacker.conditions.values():
            if condition.condition_id == HEX and (condition.data or {}).get("against") == target.entity_id:
                engine._remove_condition(attacker, HEX, source)
                return "DISADVANTAGE"
    return None
