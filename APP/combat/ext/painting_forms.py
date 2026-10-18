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

Not modeled here: the Serpent's Swim Speed (the movement model has no swim mode).
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
        if form == "tortoise":
            template["size_category"] = "Large"
            creature["summon"]["size"] = "large"  # native occupied-square authority
        elif form == "crane":
            template["speed_ft"] = 40
        for row in creature.get("action_catalog") or []:
            typed = (row.get("parameters") or {}).get("typed") or {}
            if typed.get("weapon"):
                typed["creation_damage_choice"] = True
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
    if _form(actor) != "serpent" or action is None or getattr(action, "target_kind", "") != "HOSTILE_ENTITY":
        return None
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


def _passage_subject(engine: Any, crane: Any) -> Any | None:
    """The willing creature the Crane carries: an ally within 5 feet of it (its summoner first, then by name)."""
    owner_id = (getattr(crane, "summon", None) or {}).get("owner")
    near = [other for other in engine.state.actors.values() if other.active and other.entity_id != crane.entity_id
            and other.team_id == crane.team_id and engine._distance_actor_to_actor(crane, other) <= 5]
    return min(near, key=lambda other: (other.entity_id != owner_id, other.entity_id), default=None)


def _passage_legal(engine: Any, crane: Any, destination: Any, feet: int) -> Any | None:
    """The creature the Crane could carry to ``destination`` ("a legal unoccupied space", up to ``feet`` from it, that the
    Crane can perceive, the way there open air or floor and not a solid barrier), or None."""
    ally = _passage_subject(engine, crane)
    if ally is None or destination == ally.position or engine.grid.distance_ft(ally.position, destination) > feet:
        return None
    if not engine.grid.placement_legal(destination, footprint=engine._footprint(ally), occupied_cells=engine._occupied_cells_except(ally.entity_id)):
        return None
    if any(cell in engine.grid.blocked for cell in engine.grid.ray_cells(ally.position, destination)[1:]):
        return None  # cannot cross solid barriers (Total Cover, sealed Formations and spatial locks are for the GM)
    return ally


@hook("candidate_allowed")
def passage_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feet = int(((getattr(action, "parameters", None) or {}) if action is not None else {}).get("painted_passage") or 0)
    if not feet:
        return None
    destination = getattr(candidate, "destination", None)
    return False if destination is None or _passage_legal(engine, actor, destination, feet) is None else None


@hook("button_description")
def passage_description(row: dict[str, Any]) -> str | None:
    if any(eff.get("type") == "painted_passage" for eff in ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []):
        return "Instead of Painted Strike, carry one willing creature within 5 feet up to 20 feet to a legal space, without opportunity attacks or crossing solid barriers."
    return None


@effect("painted_passage")
def painted_passage(ctx: Any, eff: dict[str, Any]) -> None:
    """Painted Passage: move a willing creature within 5 feet up to 20 feet, without Opportunity Attacks."""
    from .. import zones

    destination = getattr(ctx.intent, "destination", None)  # the cell the Crane was aimed at (as zones.py reads it)
    ally = _passage_legal(ctx.engine, ctx.actor, destination, int(eff.get("distance_ft") or 20)) if destination is not None else None
    if ally is None:
        ctx.rider("Painted Passage: no willing creature within 5 feet could be carried to that space.")
        return
    start = ally.position
    ally.position = destination
    ctx.engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=ally.entity_id,
                             payload={"destination": destination.model_dump(mode="json"),
                                      "path": [start.model_dump(mode="json"), destination.model_dump(mode="json")], "cost_ft": 0,
                                      "teleport": True, "forced": True})
    zones.on_moved(ctx.engine, ally, start, destination, forced=True)
    ctx.rider(f"Painted Passage: {ally.display_name} is carried to that space (no Opportunity Attacks).")
