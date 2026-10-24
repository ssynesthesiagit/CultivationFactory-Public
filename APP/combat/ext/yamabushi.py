"""Yamabushi riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Yamabushi (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "yamabushi", "role": "ascetic"}``; Waterfall Stance and Avatar of the Mountain are the named states
"waterfall_stance" and "avatar_of_the_mountain" (Stone Skin's AC and Resistance are feature-block defense rows gated on Unarmored
Defense; Mountain's Wrath is typed with an object row).

Waterfall Stance    while it lasts: Advantage on saves against forced movement, Prone, Frightened and Exhaustion; it ends when you
                    fall Unconscious (with its ignore-difficult-terrain condition).
Ascetic Body        Advantage on saves against Exhaustion, possession and forced bodily transformation (Petrified, Polymorphed);
                    Still as the Peak: at the start of your turn, if you have not willingly moved since your last turn ended, the
                    first Body Refining Path or Subpath activation this turn that spends 2+ Stamina gets 1 back (once per round).
Avatar of the Mountain  while it lasts: Advantage on Strength and Constitution saves, no difficult terrain at all (hook
                    difficult_exempt), a lower Source CL cannot push, pull or knock you Prone (an equal or higher one needs an opposed
                    Cultivation Check, a tie leaving you in place), and once per turn + 2d8 Bludgeoning or Force on an unarmed or
                    integrated Staff hit.
Every hook returns early for a creature without the row or state.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

PREFIX = "tianxia.subpath.body.yamabushi.feature."
WATERFALL = "waterfall_stance"
AVATAR = "avatar_of_the_mountain"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "yamabushi"}


def _state(engine: Any, actor: Any, name: str) -> Any:
    from .states import active

    return active(engine, actor, name) if actor is not None else None


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _cl(engine: Any, actor_id: str) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


@hook("save")
def mountain_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None:
        return None
    engine = ctx.engine
    names = {str(n).lower() for n in named or ()}
    advantage = (_state(engine, subject, WATERFALL) is not None and bool(names & {"forced_movement", "prone", "frightened", "exhaustion"})) \
        or ("ascetic" in _roles(engine, subject) and bool(names & {"exhaustion", "possessed", "polymorphed", "petrified"})) \
        or (_state(engine, subject, AVATAR) is not None and str(ability).upper()[:3] in ("STR", "CON"))
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if advantage else None


@hook("event")
def yamabushi_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").endswith("unconscious"):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and _state(engine, actor, WATERFALL) is not None:
            from .states import PREFIX as STATE, slug

            for iid, held in list(actor.conditions.items()):  # "The stance ends if you become Unconscious"
                if held.condition_id == STATE + slug(WATERFALL) or (held.condition_id == "condition:typed.ignore_difficult"
                                                                    and str(held.source_definition_id).endswith("waterfall_stance")):
                    del actor.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", PREFIX + WATERFALL, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                         payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "UNCONSCIOUS"})
        return
    if event_type == "RESOURCE_SPENT" and payload.get("resource_id") == STAMINA and int(payload.get("amount") or 0) >= 2:
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        source = str(engine.events[-1].source_definition_id if engine.events else "")
        if actor is None or actor.turn_flags.get("_round_still_peak") != _stamp(engine) or not ("tianxia.subpath.body." in source or "tianxia.path.body_refining" in source):
            return
        actor.turn_flags["_round_still_peak"] = "spent"
        engine._gain_resource(actor, STAMINA, 1, PREFIX + "ascetic_body")
        note(engine, PREFIX + "ascetic_body", actor, f"Still as the Peak: that cost {actor.display_name} 1 Stamina less.")


@hook("turn_start")
def still_as_the_peak(engine: Any, actor: Any) -> None:
    """At the start of your turn, if you are touching earth, stone or worked masonry and have not willingly moved since the
    end of your previous turn (once per round). Without authored surface metadata the grid's floor is the stable ground."""
    if "ascetic" not in _roles(engine, actor) or not actor.active:
        return
    from .surface_contact import contact
    if not contact(engine, actor, PEAK_MATERIALS, stable=False, standing=False):
        return
    for event in reversed(engine.events[:-1]):
        if event.event_type == "TURN_ENDED" and event.actor_id == actor.entity_id:
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("placed"):
            return
    actor.turn_flags["_round_still_peak"] = _stamp(engine)


# ------------------------------------------------------------------------------------------------- Avatar of the Mountain
@hook("sense_grant_allowed")
def avatar_solid_sense(engine: Any, actor: Any, grant: Any, seen: Any) -> bool | None:
    if grant.get("feature_id") != PREFIX + AVATAR or grant.get("sense") != "tremorsense":
        return None
    from .surface_contact import solid_contact
    return _state(engine, actor, AVATAR) is not None and solid_contact(engine, actor)


@hook("difficult_exempt")
def avatar_ignores_terrain(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    if _state(engine, actor, AVATAR) is None:
        return None
    return {(x, y) for x in range(engine.grid.width) for y in range(engine.grid.height)}  # "Ignore difficult terrain"


def _opposed(engine: Any, mover: Any, source: Any, source_numbers: Any = None) -> bool:
    from .cultivation_contests import holds_position
    return holds_position(engine, mover, source, PREFIX + AVATAR, source_numbers=source_numbers)


@hook("forced_distance")
def avatar_holds_ground(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if mover is None or source is None or source.entity_id == mover.entity_id or _state(engine, mover, AVATAR) is None:
        return None
    if _cl(engine, source.entity_id) < _cl(engine, mover.entity_id) or _opposed(engine, mover, source):
        note(engine, PREFIX + AVATAR, mover, f"Avatar of the Mountain: {source.display_name} cannot move {mover.display_name}.", (mover.entity_id,))
        return distance_ft
    return None


@hook("condition_attempt")
def avatar_stays_up(ctx: Any, subject: Any, effect: Any) -> bool | None:
    if str((effect or {}).get("condition") or "").lower() != "prone" or subject is None or _state(ctx.engine, subject, AVATAR) is None:
        return None
    if ctx.actor is subject:
        return None
    if int(ctx.numbers.get("cl") or 0) < _cl(ctx.engine, subject.entity_id) or _opposed(ctx.engine, subject, ctx.actor, ctx.numbers):
        return False
    return None


@hook("subject_teleport_attempt")
def avatar_resists_teleport(ctx: Any, subject: Any, start: Any, destination: Any) -> bool | None:
    if subject is ctx.actor or subject.team_id == ctx.actor.team_id or _state(ctx.engine, subject, AVATAR) is None:
        return None
    if int(ctx.numbers.get("cl") or 0) < _cl(ctx.engine, subject.entity_id) or _opposed(ctx.engine, subject, ctx.actor, ctx.numbers):
        note(ctx.engine, PREFIX + AVATAR, subject, f"Avatar of the Mountain: {subject.display_name} resists the teleport.")
        return False
    return None


@hook("falling_damage")
def waterfall_cushions_fall(engine: Any, target: Any, amount: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    if _state(engine, target, WATERFALL) is None:
        return None
    return {"amount": max(0, amount - 5 * _cl(engine, target.entity_id)), "land_prone": True}


@hook("after_hit")
def avatar_blow(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if _state(engine, actor, AVATAR) is None or target is None or not target.active or target.team_id == actor.team_id:
        return
    from .integrated_weapons import in_group

    staff = in_group(ctx.typed or {}, "staff") and any("#bojutsu" in a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == actor.entity_id)
    if (kind != "unarmed" and not staff) or actor.turn_flags.get("_round_avatar_blow") == _stamp(engine):
        return
    actor.turn_flags["_round_avatar_blow"] = _stamp(engine)
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["bludgeoning", "force"],
                     "evidence": "Avatar of the Mountain: + 2d8"}])


# ------------------------------------------------------------------------------------------------- Ascetic Body (travel)
REST_SECONDS = 4 * 3600
MEDITATION = "meditative_rest"
PEAK_MATERIALS = frozenset({"earth", "stone", "masonry"})
FOOD_CATEGORIES = frozenset({"hunger", "thirst"})
HUNGER_SPHERE = "tianxia.sphere.hunger"


def _ascetic_traveller(session: Any, actor_id: str) -> bool:
    return any(row.get("block") == "path_rider" and row.get("kind") == "yamabushi" and row.get("role") == "ascetic"
               for row in session.state["actors"][actor_id]["bundle"].get("typed_passives", ()))


@hook("journey_properties")
def ascetic_travel(session: Any, actor_id: str) -> dict[str, Any] | None:
    """"No requirement for ordinary food or drink": the journey's ordinary travel exhaustion from food, water and exposure
    (travel_exhaustion with ``ordinary``) does not accrue. Other Exhaustion sources are unaffected."""
    return {"ignore_ordinary_travel_exhaustion": 1} if _ascetic_traveller(session, actor_id) else None


@hook("journey_options")
def ascetic_rest_options(session: Any, actor_id: str) -> list[dict[str, Any]] | None:
    actor = session.state["actors"][actor_id]
    if session.state["phase"] != "travel" or actor["incapacitated"] or not _ascetic_traveller(session, actor_id):
        return None
    return [{"id": MEDITATION, "kind": MEDITATION, "source": PREFIX + "ascetic_body", "auto_select": 0, "payload": {},
             "label": f"{actor['name']}: Ascetic Body — complete a Long Rest in 4 hours of meditation "
                      "(remaining aware of your surroundings; confirm the other Long Rest requirements are met)."}]


@hook("journey_command")
def ascetic_rest(session: Any, actor_id: str, kind: str, payload: dict[str, Any]) -> bool | None:
    """"The ability to complete a long rest through 4 hours of meditation": the ordinary Long Rest in half the time."""
    from ..journey import require

    if kind != MEDITATION:
        return None
    require(_ascetic_traveller(session, actor_id), "Only a character with Ascetic Body can complete a Long Rest by meditating.")
    require(not payload, "Meditating for a Long Rest takes no parameters.")
    actor = session.state["actors"][actor_id]
    require(not actor["incapacitated"], "An incapacitated creature cannot start this rest.")
    session.complete_long_rest(actor_id, REST_SECONDS, f"{actor['name']} finishes a Long Rest in four hours of meditation (Ascetic Body).")
    return True


# ------------------------------------------------------------------------------------------------- Ascetic Body: immunities
def _supernatural_hunger(engine: Any, typed: Any) -> bool:
    """Whether the save comes from a Hunger-sphere ability: a supernatural appetite, not ordinary food or drink. Read from
    the packet's own provenance (compiled sphere, else the source ids), like combat/ext/disease.py caused_by_disease."""
    from ..pending_damage import current

    row = typed if isinstance(typed, dict) else {}
    if row.get("sphere"):
        return str(row["sphere"]) == HUNGER_SPHERE
    ids = [row.get("source")]
    packet = current(engine)
    if packet is not None:
        ids.append(packet.source_id)
    return any(HUNGER_SPHERE in text or text.startswith("tianxia.talent.hunger.")
               for text in (str(value).lower() for value in ids if value))


@hook("automatic_save_success")
def ascetic_immunities(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """"Immunity to mundane disease." "Immunity to environmental cold (not Cold damage)." and "No requirement for ordinary food
    or drink." An Ascetic's save against one of these succeeds automatically (no die; its failed branch does not run).

    Disease: a save tagged "disease" or whose failure (at any nesting depth) makes the creature Sickened, unless its source is
    a Disease-sphere ability (combat/ext/disease.py caused_by_disease) -- a supernatural disease is not mundane.
    Environmental cold: a save tagged "environmental_cold" with no Cold damage row at any depth.
    Food and drink: a save tagged "hunger" or "thirst" (the deprivation vocabulary of combat/ext/background_origins.py), unless
    its source is a Hunger-sphere ability. Exposure, forced march and sleep are not food or drink and still roll.
    """
    if ctx is None or subject is None or not isinstance(effect, dict) or "ascetic" not in _roles(ctx.engine, subject):
        return None
    from .disease import caused_by_disease
    from ..typed_executor import _walk_rows

    typed = getattr(ctx, "typed", None)
    rows = list(_walk_rows([*(effect.get("on_fail") or []), *(effect.get("on_success") or [])]))
    categories = {str(tag) for tag in effect.get("save_categories") or ()}
    cold = "environmental_cold" in categories and not any(
        row.get("type") == "damage" and "cold" in {str(kind).lower() for kind in row.get("damage_types") or ()} for row in rows)
    sickens = any(row.get("type") == "condition" and str(row.get("condition") or "").lower() == "sickened"
                  for row in _walk_rows(effect.get("on_fail")))
    disease = ("disease" in categories or sickens) and not caused_by_disease(ctx.engine, typed)
    food = bool(categories & FOOD_CATEGORIES) and not _supernatural_hunger(ctx.engine, typed)
    if not (cold or disease or food):
        return None
    what = "environmental cold" if cold else "mundane disease" if disease else "ordinary food or drink"
    note(ctx.engine, PREFIX + "ascetic_body", subject, f"Ascetic Body: {subject.display_name} is immune to {what}.", (subject.entity_id,))
    return True
