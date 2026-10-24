"""Living Painting forms (Painting Cultivator, CL6; Qi Subpath Compendium R19, "Living Painting Forms").

The forms are summoned creatures (combat/summons.py, combat/rules/summons.json: one creature per form, sharing the family
"living_painting" -- "You may maintain one Living Painting"); what each form adds to Painted Strike or does instead of it is here.

  Tiger, Pouncing Stroke: "If the Tiger moves at least 20 feet straight toward a creature before hitting it with Painted Strike,
    the target makes a Strength saving throw. Failed Save: Knocked Prone. A creature is tested once per turn."  Worked out as:
    a continuous straight approach of at least 20 feet toward that creature, using the committed movement paths.
    The save DC is the summoner's Cultivation Save DC.
  Serpent, Coiling Stroke: "After hitting a Large or smaller creature, it makes a Strength saving throw. Failed Save: Grappled
    by the Serpent until the start of your next turn. While Grappling: the Serpent cannot use Painted Strike against another
    target. The target may use its Action to repeat the saving throw, ending the Grapple on a success."  The grip is a Grappled
    condition that ends at the start of the summoner's next turn and is escaped with a Strength saving throw
    (typed_executor.block_escape_grapple reads its ``escape_save``).
  Tortoise, Shell Ward: the summon row's innate reaction (ally_damaged) reduces the damage by the summoner's Proficiency Bonus;
    the ``shell_ward_cover`` effect gives the ally Half Cover until the start of its next turn (the ``cover`` hook: like every
    cover on this table it counts against ranged attacks only, Gate4ControllerEngine._cover_bonus_actor_to_actor).
  Crane, Painted Passage: see ``painted_passage`` below.

The Serpent's Swim Speed (40 feet) uses the native authored-water movement mode: it moves only through water squares
authored on the battlefield map (combat/swimming.py). Its Climb Speed is a native capability hook ('climbing').
Painted Strike's damage type is chosen by the owner on creation and retained in the summon record until replaced.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FAMILY = "living_painting"
GRAPPLED = "condition:typed.grappled"
SHELL_WARD = "condition:typed.shell_ward"
POUNCE_FEET = 20
DAMAGE_TYPES = ("BLUDGEONING", "PIERCING", "SLASHING", "FORCE")


@hook("compile_bundle")
def creation_choices(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    """Advertise the existing transactional choice transport on owned painting actions.

    No ownership is inferred from names or the live authority: the compiler has
    already produced the exact owned family. No other summon opts in.
    """
    import copy

    if not any((row.get("summon") or {}).get("family") == FAMILY for row in bundle.get("summons") or []):
        return None
    out = copy.deepcopy(bundle)
    for row in out.get("action_catalog") or []:
        if str((row.get("parameters") or {}).get("summon_group") or "").startswith(FAMILY + "_"):
            row["parameters"]["typed"]["manual_inline_choice"] = True
    for creature in out.get("summons") or []:
        if (creature.get("summon") or {}).get("family") != FAMILY:
            continue
        form = creature["summon"]["group"].rsplit("_", 1)[-1]
        template = creature["actor_template"]
        # Shared Qi Subpath Rules R4: an Asset has only profile-granted
        # Reactions. Shell Ward is granted; a generic Opportunity Attack is not.
        creature["typed_reactions"] = [row for row in creature.get("typed_reactions") or []
                                       if row.get("block") != "opportunity"]
        creature["action_catalog"] = [row for row in creature.get("action_catalog") or []
                                      if not row["source_definition_id"].endswith(".opportunity_attack")]
        help_id = "action:typed." + template["entity_id"].removeprefix("actor:factory.") + ".help"
        creature["action_catalog"].append({
            "source_definition_id": help_id, "display_name": "Help", "owner_id": template["entity_id"],
            "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 5,
            "parameters": {"expected_damage": 0, "description": "Action: distract an enemy within 5 feet. "
                "Choose an ally; its next attack against that enemy has Advantage before this painting's next turn.",
                "typed": {"source": creature["summon"]["source"], "weapon": None, "numbers": {},
                          "duration": {"kind": "instant"}, "riders": [], "manual_inline_choice": True,
                          "effects": [{"type": "painting_help"}]}}})
        template["action_ids"] = [*template["action_ids"], help_id]
        if form == "tortoise":
            template["size_category"] = "Large"
            creature["summon"]["size"] = "large"  # native occupied-square authority
            for reaction in creature.get("typed_reactions") or []:
                if reaction.get("name") == "Shell Ward":
                    reaction["once"] = "round"
                    reaction["painting_shell_ward"] = 1
        elif form == "crane":
            template["speed_ft"] = 40
        for row in creature.get("action_catalog") or []:
            typed = (row.get("parameters") or {}).get("typed") or {}
            if typed.get("weapon"):
                typed["creation_damage_choice"] = True
            if any(eff.get("type") == "painted_passage" for eff in typed.get("effects") or []):
                row["parameters"].pop("player_only", None)
                # Its destination is an empty cell by design; the AI must be allowed to aim it.
                row["parameters"]["ai_allow_empty_area"] = True
                typed["manual_inline_choice"] = True
    return out


@hook("summon_appeared")
def choose_painted_strike(engine: Any, owner: Any, creature: Any, source_id: str) -> None:
    """Choose once per actual creation, including re-creation of the same form.

    Only the painter chooses; no target defenses or unseen creatures inform the
    automatic preference. The string is saved with the native summon state.
    """
    from .needle import ask, checkpoint_id

    if _form(creature) is None or (creature.summon or {}).get("owner") != owner.entity_id:
        return
    picked = ask(engine, None, checkpoint_id(engine, "painted_strike", creature.entity_id), owner,
                 "choice:needle.living_painting_damage", list(DAMAGE_TYPES),
                 labels={kind: kind.title() + " damage" for kind in DAMAGE_TYPES},
                 preferred=["FORCE"], name="Living Painting — Painted Strike", target_id=creature.entity_id,
                 prompt=f"Living Painting: {owner.display_name} creates {creature.display_name}. Choose its Painted Strike "
                        "damage type for this painting's lifetime (up to 1 minute with Concentration). Creation costs an Action and 4 Qi; this choice adds no cost.")
    if len(picked) != 1 or picked[0] not in DAMAGE_TYPES:
        raise ValueError("Living Painting requires one creation damage type")
    creature.summon["painted_strike_damage_type"] = picked[0]
    engine._apply_condition(creature, "condition:typed.sense", source_id, owner.entity_id,
                            expires_on=creature.summon.get("expires_on") or "UNTIL_REMOVED",
                            data={"sense": "darkvision", "range_ft": 60,
                                  "label": "Living Painting: Darkvision 60 feet"})
    engine._append_event("PASSIVE_TRIGGERED", source_id, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                         payload={"text": f"{creature.display_name}'s Painted Strike deals {picked[0].lower()} damage until this painting ends.",
                                  "painted_strike_damage_type": picked[0]})


@hook("damage_type_choice")
def painted_strike_damage(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    """Read the creation choice for this summon's own strike, never reselect on a hit."""
    if _form(ctx.actor) is None or not ctx.typed.get("creation_damage_choice"):
        return None
    selected = (ctx.actor.summon or {}).get("painted_strike_damage_type")
    return selected if selected in kinds else None


def _form(actor: Any) -> str | None:
    record = getattr(actor, "summon", None) or {}
    return str(record["group"]).rsplit("_", 1)[-1] if record.get("family") == FAMILY else None


@effect("painting_help")
def help_an_attack(ctx: Any, eff: dict) -> None:
    """The printed Help command's ordinary combat assistance, no extra payment."""
    from ..target_knowledge import actors_for
    from .help_policy import allowed
    from .needle import ask, checkpoint_id
    from .effect_durations import token

    if _form(ctx.actor) is None or ctx.target is None:
        return
    allies = {a.entity_id: a for a in actors_for(ctx.engine, ctx.actor) if a.active
              and a.team_id == ctx.actor.team_id and a.entity_id != ctx.actor.entity_id
              and allowed(ctx.engine, ctx.actor, a)}
    owner = ctx.engine.state.actors.get(ctx.actor.summon["owner"])
    if not allies or owner is None:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "painted_help"), owner,
                 "choice:needle.painted_help", list(allies),
                 labels={key: a.display_name for key, a in allies.items()}, name="Living Painting — Help",
                 prompt=f"{ctx.actor.display_name} uses its Action to distract {ctx.target.display_name}. "
                        "Choose an ally whose next attack against this enemy has Advantage before the painting's next turn. No Qi cost.")
    if picked:
        ally = allies[picked[0]]
        ctx.engine._add_modifier(ally, ctx.source, "attack_mode_vs", "SET", f"ADVANTAGE:{ctx.target.entity_id}",
            "NEXT_ATTACK", expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1))
        ctx.rider(f"Help: {ally.display_name}'s next attack against {ctx.target.display_name} has Advantage "
                  f"before {ctx.actor.display_name}'s next turn.")


@hook("flight")
def crane_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    """Native flight capability of the actual manifested Crane, including Hover."""
    if actor.active and _form(actor) == "crane":
        return {"fly_speed_ft": 70, "flight_hover": 1}
    return None


@hook("climbing")
def serpent_climbing(engine: Any, actor: Any) -> dict[str, int] | None:
    """Native Climb Speed; this does not waive checks for difficult surfaces."""
    if actor.active and _form(actor) == "serpent":
        return {"climb_speed_ft": 40}
    return None


@hook("swimming")
def serpent_swimming(engine: Any, actor: Any) -> dict[str, int] | None:
    """Only the actual active Serpent supplies its printed Swim Speed."""
    if actor.active and _form(actor) == "serpent":
        return {"swim_speed_ft": 40}
    return None


# What each form's own rider does, in the words the player reads on a button. Also used by
# combat/ext/summon_ability_costs.py, which rewrites a summon button's whole help text and must not
# drop the form's effect when it does: the rider is part of what the attack does on a hit.
RIDER_TEXT = {
    "tiger": ("Pouncing Stroke: if it moved at least 20 feet straight toward the target before this hit, the "
              "target makes a Strength saving throw; on a failure the target is knocked Prone. Each target is "
              "tested only once per turn."),
    "serpent": ("Coiling Stroke: after hitting a Large or smaller creature, that creature makes a Strength saving "
                "throw; on a failure it is Grappled by the Serpent until the start of your next turn, and it may "
                "use its Action to repeat the saving throw to escape. While it Grapples one creature, the "
                "Serpent cannot use Painted Strike against another."),
}


def rider_text(form: str) -> str | None:
    """The plain sentence for a form's on-hit rider, or None when the form has none."""
    return RIDER_TEXT.get(str(form or "").strip().lower())


def closed_ft(engine: Any, actor: Any, target: Any) -> int:
    """Length of the final continuous straight voluntary approach toward ``target`` this turn."""
    from ..gate2_runtime_models import Position
    from math import gcd

    paths = []
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id:
            if payload.get("forced") or payload.get("teleport"):
                break  # a displacement interrupts the voluntary approach
            path = [Position(**cell) for cell in payload.get("path") or [] if isinstance(cell, dict)]
            if path:
                paths.append(path)
    if not paths:
        return 0
    # Walk backward from the hit along the final straight run. Comparing only
    # start/end distances wrongly counted a bent 25-foot approach as a pounce.
    end = actor.position
    direction = None
    distance = 0
    for path in paths:
        if path[-1] != end:
            break
        for start, stop in reversed(list(zip(path, path[1:]))):
            vector = (stop.x - start.x, stop.y - start.y, stop.z - start.z)
            divisor = gcd(gcd(abs(vector[0]), abs(vector[1])), abs(vector[2]))
            if divisor == 0:
                continue
            step = tuple(value // divisor for value in vector)
            if direction is not None and step != direction:
                return distance
            if engine.grid.distance_ft(start, target.position) <= engine.grid.distance_ft(stop, target.position):
                return distance
            direction = step
            distance += engine.grid.distance_ft(start, stop)
            end = start
    return distance


def grappling(engine: Any, actor: Any) -> list[Any]:
    """The creatures this one grips with Coiling Stroke."""
    return sorted((other for other in engine.state.actors.values() if other.active and other.entity_id != actor.entity_id
                   and any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id and c.data.get("escape_save")
                           for c in other.conditions.values())), key=lambda other: other.entity_id)


@effect("form_rider")
def form_rider(ctx: Any, eff: dict[str, Any]) -> None:
    """What a form adds when its Painted Strike hits (summons.py puts it on the strike's hit effects)."""
    from .. import typed_executor

    target, form = ctx.target, str(eff.get("form") or "")
    if target is None or not target.active:
        return
    if form == "tiger":
        key = f"pounce_tested:{target.entity_id}"
        if ctx.actor.turn_flags.get(key) or closed_ft(ctx.engine, ctx.actor, target) < POUNCE_FEET:
            return
        ctx.actor.turn_flags[key] = True  # "A creature is tested once per turn"
        ctx.rider("Pouncing Stroke: the Tiger moved at least 20 feet toward the target before it hit.")
        typed_executor.block_save(ctx, {"type": "save", "ability": "STR", "on_success": [],
                                        "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}]})
    elif form == "serpent":
        if grappling(ctx.engine, ctx.actor):
            return  # already holding one (and it cannot strike another: candidate_allowed)
        typed_executor.block_save(ctx, {"type": "save", "ability": "STR", "max_size_larger": 1, "on_success": [],
                                        "on_fail": [{"type": "coiling_grip"}]})


@effect("coiling_grip")
def coiling_grip(ctx: Any, eff: dict[str, Any]) -> None:
    """Grappled by the Serpent until the start of the summoner's next turn."""
    from .. import typed_executor, typed_reactions
    from . import effect_durations

    subject = ctx.target
    owner = ctx.engine.state.actors.get((getattr(ctx.actor, "summon", None) or {}).get("owner") or "")
    if subject is None or owner is None or typed_executor.condition_immune(ctx.engine, subject, "grappled"):
        return
    if typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, "grappled"):
        return
    ctx.engine._apply_condition(
        subject, GRAPPLED, ctx.source, ctx.actor.entity_id,
        expires_on=effect_durations.token("start", owner.entity_id, int(owner.turns_started) + 1),
        data={"escape_dc": int(ctx.numbers.get("save_dc") or 10), "reach_ft": int(ctx.action.range_ft or 10), "escape_save": "STR",
              "label": "Grappled by the Serpent"})


@hook("candidate_allowed")
def serpent_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"While Grappling, the Serpent cannot use Painted Strike against another target.\""""
    if (_form(actor) != "serpent" or action is None or getattr(action, "target_kind", "") != "HOSTILE_ENTITY"
            or getattr(action, "display_name", "") != "Painted Strike"):
        return None  # Help and other hostile-target actions are not restricted by the grip
    held = grappling(engine, actor)
    if held and any(target_id not in {other.entity_id for other in held} for target_id in getattr(candidate, "target_ids", ())):
        return False
    return None


@effect("shell_ward_cover")
def shell_ward_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """The Tortoise's Shell Ward: Half Cover for the ally it shielded, until the start of that ally's next turn."""
    from . import effect_durations

    ally = ctx.engine.state.actors.get(ctx.typed.get("protects") or "")
    if ally is None or not ally.active:
        return
    for iid, old in list(ally.conditions.items()):
        if old.condition_id == SHELL_WARD and old.source_actor_id == ctx.actor.entity_id:
            ctx.engine._remove_condition(ally, SHELL_WARD, old.source_definition_id)  # a fresh one replaces it
    ctx.engine._apply_condition(ally, SHELL_WARD, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_durations.token("start", ally.entity_id, int(ally.turns_started) + 1),
                                data={"label": "Shell Ward (Half Cover)", "cover": 2})


@hook("cover")
def shell_ward_cover_bonus(engine: Any, attacker: Any, target: Any) -> int | None:
    for condition in target.conditions.values():
        if condition.condition_id == SHELL_WARD:
            return int(condition.data.get("cover") or 2)
    return None


@hook("ally_row_allowed")
def shell_ward_attack_only(engine: Any, reactor: Any, subject: Any, row: dict) -> bool | None:
    """Only a triggering attack hit, not an arbitrary damage packet, offers Ward."""
    if _form(reactor) != "tortoise" or not row.get("painting_shell_ward"):
        return None
    packet = engine.damage_context()
    return packet is not None and packet.target_id == subject.entity_id


def passage_subjects(engine: Any, crane: Any) -> list[Any]:
    """Eligible creatures, without treating proximity or allegiance as consent.

    The printed passage has no passenger size limit. A large passenger must
    still fit through every square of its physical route and at its landing.
    """
    from ..target_knowledge import located

    if not crane.active or _form(crane) != "crane":
        return []
    return sorted((other for other in engine.state.actors.values() if other.active
                   and other.entity_id != crane.entity_id
                   and engine._distance_actor_to_actor(crane, other) <= 5
                   and located(engine, crane, other)), key=lambda other: other.entity_id)


def _landing_ok(engine: Any, subject: Any, destination: Any) -> bool:
    """A passenger lands only on support (ground or a solid column top), or if it can fly itself.

    Shared by the route check and the AI consent decision, so nobody is
    offered or carried into open air it cannot stay in.
    """
    from ..falling import supported
    from ..flight import profile

    return supported(engine, subject, destination) or bool(profile(engine, subject).speed_ft)


def passage_path(engine: Any, crane: Any, subject: Any, destination: Any, feet: int) -> tuple:
    """A bounded three-dimensional physical route, checked for the whole body.

    No teleport or unseen passenger facts are used. Intervening solids, roof
    slabs, occupied volumes and diagonal corner collisions retain the native
    geometry rules. A route may bend around an obstacle within the printed
    distance; unlike the Tiger's pounce, this form has no straight-line clause.
    """
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell
    from ..transport_boundaries import cells
    from heapq import heappop, heappush
    from itertools import product

    if (destination is None or destination == subject.position
            or engine.grid.distance_ft(subject.position, destination) > feet
            or not perceives_cell(engine, crane, destination)
            or not _landing_ok(engine, subject, destination)):
        return ()
    start = subject.position
    occupied = engine._occupied_volumes_except(subject.entity_id)
    footprint = engine._footprint(subject)
    barriers = cells(engine, {"sealed_formation", "spatial_lock"})
    if set(engine._actor_volume(subject, start)) & barriers:
        return ()
    origin = (start.x, start.y, start.z)
    queue = [(engine.grid.distance_ft(start, destination), 0, origin)]
    paths, costs = {origin: (start,)}, {origin: 0}
    offsets = tuple(delta for delta in product((-1, 0, 1), repeat=3) if delta != (0, 0, 0))
    while queue:
        _, spent, cell = heappop(queue)
        if spent != costs[cell]:
            continue
        here = paths[cell][-1]
        if here == destination:
            return paths[cell]
        for delta in offsets:
            nxt = tuple(a + b for a, b in zip(cell, delta))
            if min(nxt) < 0 or not engine.grid.in_bounds(nxt[:2]):
                continue
            point = Position(x=nxt[0], y=nxt[1], z=nxt[2])
            price = spent + engine.grid.square_size_ft
            estimate = price + engine.grid.distance_ft(point, destination)
            if estimate > feet or price >= costs.get(nxt, feet + 1):
                continue
            if (set(engine._actor_volume(subject, point)) & barriers
                    or not engine.grid.volume_step_legal(here, point, footprint=footprint, occupied_cells=occupied)
                    or not engine.grid.line_of_physical_transmission(here, point)):
                continue
            paths[nxt], costs[nxt] = (*paths[cell], point), price
            heappush(queue, (estimate, price, nxt))
    return ()


def _passage_legal(engine: Any, crane: Any, destination: Any, feet: int) -> Any | None:
    """The creature the Crane could carry to ``destination`` ("a legal unoccupied space", up to ``feet`` from it, that the
    Crane can perceive, the way there open air or floor and not a solid barrier), or None."""
    return next((subject for subject in passage_subjects(engine, crane)
                 if passage_path(engine, crane, subject, destination, feet)), None)


@hook("candidate_allowed")
def passage_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feet = int(((getattr(action, "parameters", None) or {}) if action is not None else {}).get("painted_passage") or 0)
    if not feet or _form(actor) != "crane":
        return None
    destination = getattr(candidate, "destination", None)
    return False if destination is None or _passage_legal(engine, actor, destination, feet) is None else None


@hook("button_description")
def passage_description(row: dict[str, Any]) -> str | None:
    if any(eff.get("type") == "painted_passage" for eff in ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []):
        return "Instead of Painted Strike, carry one willing creature within 5 feet up to 20 feet to a legal space, without opportunity attacks or crossing solid barriers."
    return None


def passage_preference(engine: Any, subject: Any, owner: Any, destination: Any) -> str:
    """The passenger's AI decision, using its own knowledge rather than allegiance.

    Humans always receive both answers. An automatic passenger accepts an
    explicitly self-selected safe ride, or a visible move that improves its
    own approach/retreat; team membership is never a willingness receipt.
    """
    from ..target_knowledge import actors_for
    from ..senses import perceives_cell
    if not perceives_cell(engine, subject, destination) or not _landing_ok(engine, subject, destination):
        return "refuse"
    if subject.entity_id == owner.entity_id:
        return "accept"
    enemies = [a for a in actors_for(engine, subject) if a.active and a.team_id != subject.team_id]
    if not enemies:
        return "refuse"
    before = min(engine.grid.distance_ft(subject.position, a.position) for a in enemies)
    after = min(engine.grid.distance_ft(destination, a.position) for a in enemies)
    improves = after > before if subject.current_hp * 2 <= subject.maximum_hp else after < before
    return "accept" if improves else "refuse"


@effect("painted_passage")
def painted_passage(ctx: Any, eff: dict[str, Any]) -> None:
    """Painted Passage: move a willing creature within 5 feet up to 20 feet, without Opportunity Attacks."""
    from .needle import ask, checkpoint_id
    from .rider_movement import volume_route

    destination = getattr(ctx.intent, "destination", None)  # the cell the Crane was aimed at (as zones.py reads it)
    feet = int(eff.get("distance_ft") or 20)
    subjects = {subject.entity_id: subject for subject in passage_subjects(ctx.engine, ctx.actor)
                if passage_path(ctx.engine, ctx.actor, subject, destination, feet)}
    if not subjects:
        ctx.rider("Painted Passage: no willing creature within 5 feet could be carried to that space.")
        return
    owner = ctx.engine.state.actors.get(ctx.actor.summon["owner"])
    if owner is None:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "painted_passage_subject"), owner,
                 "choice:needle.painted_passage_subject", list(subjects),
                 labels={key: subject.display_name for key, subject in subjects.items()},
                 preferred=[owner.entity_id] if owner.entity_id in subjects else [], name="Painted Passage",
                 prompt=f"Painted Passage: choose a creature within 5 feet of {ctx.actor.display_name} to carry "
                        "up to 20 feet. This uses the Crane's Action instead of Painted Strike; the passenger must agree.")
    subject = subjects[picked[0]]
    accepted = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "painted_passage_consent", subject.entity_id), subject,
                   "choice:needle.painted_passage_consent", ["accept", "refuse"],
                   labels={"accept": "Accept the ride", "refuse": "Stay here"}, name="Painted Passage",
                   target_id=subject.entity_id,
                   preferred=[passage_preference(ctx.engine, subject, owner, destination)], default="decline",
                   prompt=f"Painted Passage: {ctx.actor.display_name} offers to carry {subject.display_name} "
                          f"to a space {ctx.engine.grid.distance_ft(subject.position, destination)} feet away"
                          + (f", {destination.z * 5} feet up" if destination.z else " on the ground") + ". "
                          "Accept? The ride costs you no action or movement and provokes no Opportunity Attacks.")
    if accepted != ["accept"]:
        ctx.rider(f"Painted Passage: {subject.display_name} declines the ride and stays here.")
        return
    path = passage_path(ctx.engine, ctx.actor, subject, destination, feet)
    arrived = bool(path) and volume_route(ctx.engine, subject, path, ctx.source)
    ctx.rider(f"Painted Passage: {subject.display_name} " +
              ("arrives at the chosen space (no Opportunity Attacks)." if arrived else
               "could not finish the ride; movement stopped at its actual space."))
