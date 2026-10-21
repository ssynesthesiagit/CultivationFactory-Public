"""Compass-Breaking Hand (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "31. Compass-Breaking Hand": Pole, Bearings, CL3 Three-Bearing Footwork, CL6
Turn the Compass, CL10 Break the Four Directions, CL14 No Fixed Compass, CL18 Heaven Has No Fixed North, Normalized Execution Notes).
No Spheres 5e or D&D 5.5e counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json;
every hook returns early for a creature without them.

The shared system (tradition text):
  * Pole -- "Choose Pole" (Bonus Action, 1 Resonance, 60 feet, the scene): a perceived creature (including an ally), an object /
    Cultivation Asset / Anchor ("Choose Pole: an object") or a fixed 5-foot space ("Choose Pole: a space"). One at a time;
    a creature Pole that leaves the same scene (inactive, sealed boundary, domain contact denial or planar separation) is
    dormant and resumes if the contradiction ends before the scene does. While it bears your Resonance Mark within 120 feet
    you learn its direction and a coarse distance band, never its exact concealed square.
  * Bearing -- at the start of your turn a manual/Ask-me seat is asked Approach / Orbit / Depart / none; an AI seat decides
    from distance and its own mark (Depart when adjacent to its marked Pole, else Approach when far, else Orbit). The Pole's
    space then is the reference. Your voluntary movement completes it once you have moved at least 10
    feet and end 5+ feet closer (Approach), within 5 feet of your starting distance (Orbit) or 5+ feet farther (Depart); straight-line
    distances, the path ignored. Forced movement neither counts nor completes.
  * Bearing tokens -- one of each kind (``resource:named.bearing_approach`` / ``_orbit`` / ``_depart``, maximum 1, the scene).

What runs:
  * Three-Bearing Footwork (CL3): completing your Bearing gains its token and your Compass Strike -- at once if you already damaged
    your Pole with a Martial Strike (Mind Spike, an unarmed strike or a proficient weapon attack) this turn, else with the next one
    that does: Approach +1d8 Psychic or Force and the Pole cannot make Opportunity Attacks against you until the start of your next
    turn; Orbit a 5-foot step that the Pole cannot answer with an Opportunity Attack and +2 AC against its attacks until the start of
    your next turn; Depart a 10-foot step away from it (no Opportunity Attack from it) or, against a Resonance Marked Pole, a Strength
    or Wisdom saving throw (the practitioner chooses) or be pushed 5 feet. Once per turn. No Blind Side to the Soul: the first attack
    a Pole Resonance Marked by you makes while Hidden from you and within 60 feet loses only Hidden's unseen Advantage; Invisible,
    total cover, perfect spiritual concealment and every other perception effect still apply.
  * Turn the Compass (CL6 Reaction, 2 Resonance + a token): when your Pole attacks you or a willing creature within 15 feet of you,
    before the roll -- Approach: move up to 10 feet toward the Pole or the protected creature (no Opportunity Attack from the Pole);
    ending next to the protected creature or within the attack's reach you become the target, with +2 AC against it (else the
    protected creature gets +2 AC); Orbit: the protected creature moves up to 10 feet staying within 5 feet of its distance from the
    Pole, and the attack has Disadvantage; Depart: it moves up to 10 feet farther; if it is still a legal target, +2 AC. Asked; the AI
    departs when that escapes the reach, else orbits, else approaches. Read Their Bearing: once per round, when your Pole voluntarily
    moves 10+ feet in its turn and completes a category relative to where you stood when its turn began, you gain that token.
  * Break the Four Directions (CL10 Action, 5 Resonance): spend one to three different tokens (asked; the AI spends all); for each, a
    10-foot segment that completes its category relative to the Pole's space at activation (no Opportunity Attack from the Pole; a
    segment that cannot be completed is skipped and its token kept); then one attack against the Pole with your best unarmed strike or
    weapon using your Cultivation Attack bonus: on a hit its normal damage + 2d8 + 1d8 per token Psychic or Force, and each spent
    token's rider (Approach: pull 10 feet and Resonance Mark until the end of your next turn -- a creature two sizes larger makes a
    Strength save to stay; Orbit: no Reactions and Disadvantage on its next attack until the end of its next turn; Depart: a Strength
    or Wisdom save or pushed 15 feet, then you may step 10 feet away from it). On a miss you may step 5 feet in one spent category.
  * No Fixed Compass (CL14): +10 feet Speed; the map's difficult terrain costs nothing extra while you are completing a declared
    Bearing; Break the Restraining Direction (free, once per turn, 2 Resonance): while Grappled or Restrained with a Bearing declared,
    a Cultivation Check against the hold's DC ends it (a failure bars another try this turn).
  * Heaven Has No Fixed North (CL18 Bonus Action, 10 Resonance, Concentration, 1 minute, a 40-foot aura that moves with you): at the
    start of an ally's turn in it, it may declare a Chosen Bearing (asked) -- completing it gives 2 x Proficiency Bonus Temporary HP
    (Approach), +2 AC against Opportunity Attacks and Reaction attacks until the start of its next turn (Orbit) or 10 more feet of
    movement this turn (Depart); False North: at the start of your turn one hostile creature in it (asked) and a temporary token of
    each kind until the start of your next turn; Turn the Whole Field (Bonus Action, once per turn): a Resonance Marked hostile in it
    makes a Wisdom save and is moved 15 feet (5 on a success, keeping its Reactions) in the chosen category, losing its Reactions until
    the start of its next turn on a failure; Compass-Breaking Procession: once on each of your turns Break the Four Directions against
    the False North for no Resonance, spending up to two temporary tokens (not with a paid Break the same turn).

Plug-in surface: effects compass_pole, compass_break, compass_restraint, compass_turn_field, compass_approach_rider,
compass_depart_rider, compass_miss_step; hooks
compile_actions, compile_resources, turn_start_choice, turn_start, turn_end, event, damage_dealt, masked_conditions, retarget_attack,
before_attack, hit_response, speed, difficult_exempt, candidate_allowed. Shared helpers used: spirit_traditions (row/context/
pick_creature/can_react/routes/choose_route/plain_difficult), rider_movement (step/forced_route), needle.ask.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.compass_breaking_hand.feature."
FOOTWORK = TRADITION + "three_bearing_footwork"
TURN = TRADITION + "turn_the_compass"
BREAK = TRADITION + "break_the_four_directions"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
NO_OPPORTUNITY = "condition:typed.no_opportunity_attacks"
NO_FIXED = TRADITION + "no_fixed_compass"
HEAVEN = TRADITION + "heaven_has_no_fixed_north"
KINDS = ("approach", "orbit", "depart")
LABEL = {"approach": "Approach", "orbit": "Orbit", "depart": "Depart"}
TOKEN = {kind: f"resource:named.bearing_{kind}" for kind in KINDS}
POLE = "condition:typed.compass_pole"
BEARING = "condition:typed.compass_bearing"
TEMP = "condition:typed.compass_false_north"
ORBIT_GUARD = "condition:typed.compass_orbit_guard"
CHOSEN = "condition:typed.compass_chosen_bearing"
CHOSEN_ORBIT = "condition:typed.compass_chosen_orbit"
RESONANCE = "resource:core.resonance"
_TURN = "_c8_turn_the_compass"
_READ = "_c8_read_their_bearing"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _owns(engine: Any, actor: Any, kind: str) -> bool:
    return st.row(engine, actor, kind) is not None


def _remove(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    for iid, held in list(holder.conditions.items()):
        if held is condition:
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


def _mine(actor: Any, condition_id: str) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id and c.source_actor_id == actor.entity_id), None)


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") if action is not None else None) or {}
        if numbers.get("save_dc"):
            return dict(numbers)
    return {"pb": 2, "save_dc": 10, "attack_bonus": 2, "key_mod": 0, "cl": 1}


def _feature_action(engine: Any, actor: Any, feature: str) -> Any:
    # Three-Bearing Footwork is a passive rider: its Compass Strike must not
    # borrow the Choose Pole action's identity (that would journal every rider
    # damage packet and save under the Bonus Action instead of the feature).
    if feature != FOOTWORK:
        for action_id in actor.action_ids:
            action = engine.action_catalog.get(action_id)
            if action is not None and st.feature_of(action) == feature:
                return action
    base = next(iter(engine.action_catalog.values()))
    return base.model_copy(update={"source_definition_id": feature, "display_name": feature.rsplit(".", 1)[-1].replace("_", " ").title(),
                                   "parameters": {"typed": {"numbers": _numbers(engine, actor), "effects": [], "riders": []}}})


def _ctx(engine: Any, actor: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, actor, _feature_action(engine, actor, feature), targets, _numbers(engine, actor), intent)


def _xy(position: Any) -> list[int]:
    return [int(position.x), int(position.y)]


def _pos(xy: Any) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=int(xy[0]), y=int(xy[1]))


def _dist(engine: Any, a: Any, b: Any) -> int:
    return int(engine.grid.distance_ft(a, b))


def _centre(engine: Any, creature: Any) -> tuple[float, float]:
    """The printed "centre of its current space" for a creature footprint, in cells."""
    footprint = engine._footprint(creature)
    width = int(getattr(footprint, "width_cells", 1) or 1)
    height = int(getattr(footprint, "height_cells", 1) or 1)
    return creature.position.x + width / 2.0, creature.position.y + height / 2.0


def centre_distance_ft(engine: Any, a: Any, b: Any) -> int:
    """Pole-relative distance from the centres of the two creatures' current spaces."""
    ax, ay = _centre(engine, a)
    bx, by = _centre(engine, b)
    return int(max(abs(ax - bx), abs(ay - by)) * engine.grid.square_size_ft)


def category(engine: Any, start: Any, end: Any, ref: Any) -> set[str]:
    """The categories a finished movement from ``start`` to ``end`` completes relative to ``ref`` (the 10-foot minimum is checked by
    the caller)."""
    before, after = _dist(engine, start, ref), _dist(engine, end, ref)
    out = set()
    if after <= before - 5:
        out.add("approach")
    if after >= before + 5:
        out.add("depart")
    if abs(after - before) <= 5:
        out.add("orbit")
    return out


# ----------------------------------------------------------------------------------------------------------------- Pole
def _pole_object(engine: Any, actor: Any) -> Any:
    """The object/Cultivation Asset/Anchor currently chosen as this actor's Pole, if any."""
    held = _mine(actor, POLE)
    object_id = str(((held.data or {}).get("object")) or "") if held is not None else ""
    if not object_id:
        return None
    obj = engine.state.objects.get(object_id)
    if obj is None or obj.destroyed:
        return None  # the subject no longer exists/participates; nothing to measure from
    return obj


_SCENE_DENIALS = frozenset({"sealed_boundary", "domain_contact_denial", "planar_separation"})


def _contact(engine: Any, actor: Any, creature: Any) -> bool:
    """Whether the printed same-scene relation still holds for a creature Pole.

    Reuses the shared source-record classifications for sealed boundaries,
    domain contact denial and planar separation (a higher-authority generic
    separation denies only above this practitioner's Source CL). Perfect
    spiritual concealment is deliberately not a scene denial: the printed No
    Blind Side rule says such concealment still applies to the attack while the
    creature remains the Pole. A dormant Pole keeps its record and resumes as
    soon as this query is true again; nothing is removed.
    """
    from . import source_records

    level = source_records.effective_level(engine, actor)
    for holder in (actor, creature):
        for _condition, row in source_records.live(engine, holder, scope="spiritual_contact"):
            category = row.get("category")
            if category in _SCENE_DENIALS:
                return False
            if category == "separation" and int(row.get("source_cl") or 0) > level:
                return False
    return True


def pole_dormant(engine: Any, actor: Any) -> bool:
    """True while the chosen Pole cannot participate in the same scene (printed "dormant")."""
    held = _mine(actor, POLE)
    if held is None:
        return True
    data = held.data or {}
    if data.get("object"):
        return _pole_object(engine, actor) is None
    creature = engine.state.actors.get(str(data.get("pole") or ""))
    if creature is not None:
        return not creature.active or not _contact(engine, actor, creature)
    if data.get("space"):
        space = _pos(data["space"])
        return not (0 <= space.x < engine.grid.width and 0 <= space.y < engine.grid.height)
    return True


def pole(engine: Any, actor: Any) -> tuple[Any, Any]:
    """(the Pole creature or None, the Pole's reference space or None)."""
    held = _mine(actor, POLE)
    if held is None:
        return None, None
    data = held.data or {}
    if data.get("object"):
        obj = _pole_object(engine, actor)
        return None, (obj.position if obj is not None else None)
    creature = engine.state.actors.get(str(data.get("pole") or ""))
    if creature is not None:
        return (creature, creature.position) if not pole_dormant(engine, actor) else (None, None)
    if data.get("space"):
        space = _pos(data["space"])
        # A fixed-space Pole is a relation to that battlefield space; an effect
        # that removes the space from the battlefield ends it.
        if 0 <= space.x < engine.grid.width and 0 <= space.y < engine.grid.height:
            return None, space
    return None, None


def _object_options(engine: Any, actor: Any) -> list[Any]:
    """Objects (including Cultivation Assets and Anchors) the owner can perceive within 60 feet."""
    from .. import senses

    out = []
    for obj in engine.state.objects.values():
        if obj.destroyed or getattr(obj, "suppressed", False):
            continue
        if _dist(engine, actor.position, obj.position) > 60:
            continue
        if not senses.perceives_object(engine, actor, obj):
            continue
        out.append(obj)
    return sorted(out, key=lambda obj: (_dist(engine, actor.position, obj.position), obj.object_id))


def _object_label(obj: Any) -> str:
    from .. import object_rules

    return object_rules.label(obj)


@effect("compass_pole")
def choose_pole(ctx: Any, row: dict[str, Any]) -> None:
    held = _mine(ctx.actor, POLE)
    if held is not None:
        _remove(ctx.engine, ctx.actor, held, "REPLACED")  # "Choosing another ends the previous Pole"
    if row.get("picks_object"):
        options = _object_options(ctx.engine, ctx.actor)
        if not options:
            return
        from . import needle

        by_id = {obj.object_id: obj for obj in options}
        chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "COMPASS_POLE_OBJECT", ctx.actor.entity_id),
                            ctx.actor, "choice:needle.compass.pole_object", list(by_id),
                            labels={key: _object_label(obj) for key, obj in by_id.items()}, preferred=list(by_id)[:1],
                            name="Choose Pole: an object", feature_id=FOOTWORK,
                            prompt="Choose one object, Cultivation Asset or Anchor you can perceive within 60 feet as your Pole. "
                                   "It is not harmed, marked, moved or revealed.")
        obj = by_id.get(chosen[0]) if chosen else None
        if obj is None:
            return
        ctx.engine._apply_condition(ctx.actor, POLE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"object": obj.object_id, "label": f"Pole: {_object_label(obj)} (the scene)"})
        return
    target = ctx.target if ctx.target is not None and ctx.target is not ctx.actor else None
    space = ctx.destination if target is None else None
    if target is None and space is None:
        space = getattr(ctx.intent, "destination", None)
    data = {"pole": target.entity_id} if target is not None else {"space": _xy(space)} if space is not None else None
    if data is None:
        return
    name = target.display_name if target is not None else f"the space {space.x},{space.y}"
    ctx.engine._apply_condition(ctx.actor, POLE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={**data, "label": f"Pole: {name} (the scene)"})


# ----------------------------------------------------------------------------------------------------------- resources, actions
@hook("compile_resources")
def bearing_tokens(info: dict[str, Any]) -> list[Any] | None:
    if FOOTWORK not in (info.get("owned_ids") or []):
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=TOKEN[kind], initial=0, maximum=1) for kind in KINDS]


@hook("compile_actions")
def compass_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    if FOOTWORK not in owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = info["numbers"]
    short = info["short"]
    base = {"numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": FOOTWORK}
    out = [
        ActionDefinition(source_definition_id=f"action:typed.{short}.compass_pole", display_name="Choose Pole", owner_id=info["actor_id"],
                         economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ANY_CREATURE", range_ft=60,
                         costs=(("resource:core.resonance", 1),),
                         parameters={"typed": {**base, "effects": [{"type": "compass_pole", "applies_to": "target"}]}, "expected_damage": 0,
                                     "description": "Compass-Breaking Hand (Bonus Action, 1 Resonance, 60 feet, the scene): this creature becomes "
                                                    "your Pole -- the point your Bearings (Approach, Orbit, Depart) are measured from. Choosing another "
                                                    "ends the first. It is not harmed, marked or moved."}),
        ActionDefinition(source_definition_id=f"action:typed.{short}.compass_pole_space", display_name="Choose Pole: a space", owner_id=info["actor_id"],
                         economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=60,
                         costs=(("resource:core.resonance", 1),),
                         parameters={"typed": {**base, "effects": [{"type": "compass_pole", "applies_to": "self", "picks_destination": True,
                                                                    "distance_ft": 60}]}, "expected_damage": 0,
                                     "description": "Compass-Breaking Hand (Bonus Action, 1 Resonance): a fixed 5-foot space within 60 feet becomes "
                                                    "your Pole for the scene."}),
        ActionDefinition(source_definition_id=f"action:typed.{short}.compass_pole_object", display_name="Choose Pole: an object", owner_id=info["actor_id"],
                         economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=60,
                         costs=(("resource:core.resonance", 1),),
                         parameters={"typed": {**base, "effects": [{"type": "compass_pole", "applies_to": "self", "picks_object": True}]},
                                     "expected_damage": 0,
                                     "description": "Compass-Breaking Hand (Bonus Action, 1 Resonance, 60 feet, the scene): an object, Cultivation "
                                                    "Asset or Anchor you can perceive becomes your Pole. Choosing another ends the first; it is not "
                                                    "harmed, marked, moved or revealed."}),
    ]
    if NO_FIXED in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.compass_restraint", display_name="Break the Restraining Direction", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=(("resource:core.resonance", 2),),
            parameters={"typed": {**base, "source": NO_FIXED, "effects": [{"type": "compass_restraint"}]}, "expected_damage": 0, "compass_restraint": True,
                        "description": "No Fixed Compass (once on each of your turns, 2 Resonance): while a Grapple or restraint stops the Bearing "
                                       "you declared, a Cultivation Check against its escape DC ends one ordinary Grapple or Restrained effect."}))
    if HEAVEN in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.compass_procession", display_name="Break the Four Directions (Procession, free)",
            owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            parameters={"typed": {**base, "source": HEAVEN, "effects": [{"type": "compass_break", "procession": True, "applies_to": "target"}]},
                        "expected_damage": 18, "compass_procession": True,
                        "description": "Compass-Breaking Procession (Heaven Has No Fixed North, once on each of your turns): Break the Four "
                                       "Directions against your False North for no Resonance, spending up to two temporary Bearing tokens "
                                       "(2d8 + 1d8 per token). Not with a paid Break the Four Directions the same turn."}))
        for kind in KINDS:
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.compass_turn_field.{kind}", display_name=f"Turn the Whole Field: {LABEL[kind]}",
                owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=40,
                parameters={"typed": {**base, "source": HEAVEN, "effects": [{"type": "compass_turn_field", "kind": kind, "applies_to": "target"}]},
                            "expected_damage": 0, "compass_turn_field": kind,
                            "description": f"Heaven Has No Fixed North (Bonus Action, once per turn): a Resonance Marked hostile creature in your Compass "
                                           f"Domain makes a Wisdom save and is moved ({LABEL[kind]} relative to you) 15 feet and loses its Reactions until "
                                           "the start of its next turn, or 5 feet on a success."}))
    return out


@hook("candidate_allowed")
def compass_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    typed = params.get("typed") or {}
    if any(isinstance(row, dict) and row.get("picks_object") for row in typed.get("effects") or []):
        return None if _object_options(engine, actor) else False
    if any(isinstance(row, dict) and row.get("type") == "compass_pole" and row.get("applies_to") == "target"
           for row in typed.get("effects") or []):
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        if target is not None and target is not actor and centre_distance_ft(engine, actor, target) > 60:
            return False  # printed 60 feet from the moving subject's centre
    feature = st.feature_of(action)
    if feature == BREAK or params.get("compass_procession"):
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        free = bool(params.get("compass_procession"))
        if free:
            north = _false_north(engine, actor)
            if (north is None or _domain(engine, actor) is None or (target is not None and target is not north)
                    or actor.turn_flags.get("compass_break_used") or not _temp_tokens(actor)):
                return False
            return None
        creature, _space = pole(engine, actor)
        if creature is None or (target is not None and target is not creature) or creature.team_id == actor.team_id:
            return False  # "Requirement: Your Pole is a meaningful hostile creature ... within 60 feet"
        if actor.turn_flags.get("compass_break_used") or not any(actor.resources.get(TOKEN[k], 0) for k in KINDS):
            return False
        return None
    if params.get("compass_restraint"):
        from ..typed_executor import CONDITION_PREFIX

        gripped = any(c.condition_id in (CONDITION_PREFIX + "grappled", CONDITION_PREFIX + "restrained") for c in actor.conditions.values())
        bearing = _mine(actor, BEARING)
        return None if gripped and bearing is not None and not actor.turn_flags.get("compass_restraint") else False
    kind = params.get("compass_turn_field")
    if kind:
        domain = _domain(engine, actor)
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        if domain is None or actor.turn_flags.get("compass_turn_field"):
            return False
        if target is not None and (not engine._footprint_intersects(target, domain.affected_cells)
                                   or not _te().bears_mark(target, actor.entity_id, "Resonance")):
            return False
    return None


# ---------------------------------------------------------------------------------------------------------------- Bearings
@hook("turn_start_choice")
def declare(engine: Any, actor: Any) -> None:
    if not actor.active:
        return
    if _owns(engine, actor, "three_bearing_footwork"):
        _declare_own(engine, actor)
        if _owns(engine, actor, "heaven_has_no_fixed_north") and _domain(engine, actor) is not None:
            _false_north_pick(engine, actor)
    _declare_chosen(engine, actor)


def _declare_own(engine: Any, actor: Any) -> None:
    held = _mine(actor, BEARING)
    if held is not None:
        _remove(engine, actor, held, "EXPIRED")
    creature, ref = pole(engine, actor)
    if ref is None:
        return
    from . import needle

    pole_distance = centre_distance_ft(engine, actor, creature) if creature is not None else _dist(engine, actor.position, ref)
    far = pole_distance > 5
    marked = creature is not None and _te().bears_mark(creature, actor.entity_id, "Resonance")
    near = creature is not None and pole_distance <= 5
    # A computer-controlled practitioner decides from what it lawfully knows:
    # the distance to its Pole, whether it holds the mark, and the printed
    # options. A manual or Ask-me seat is asked (checklist item 9), which also
    # keeps Depart reachable for people -- the printed choice, not an AI hint.
    pole_name = creature.display_name if creature is not None else "your Pole"
    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "COMPASS_BEARING", actor.entity_id), actor, "choice:needle.compass.bearing",
                        list(KINDS), labels={"approach": "Approach: end 5+ feet closer to your Pole after moving 10+ feet",
                                             "orbit": "Orbit: move 10+ feet and end within 5 feet of your current distance from your Pole",
                                             "depart": "Depart: end 5+ feet farther from your Pole after moving 10+ feet"},
                        preferred=["depart" if (near and marked) else "approach" if far else "orbit"],
                        automatic=not needle.ai_controlled(engine, actor),
                        allow_decline=True, name="Declare a Bearing", feature_id=FOOTWORK,
                        prompt=f"{actor.display_name}: declare a Bearing relative to {pole_name} for this turn?")
    if not chosen:
        return
    engine._apply_condition(actor, BEARING, FOOTWORK, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"kind": chosen[0], "start": _xy(actor.position), "ref": _xy(ref), "moved": 0, "done": 0,
                                  "label": f"Bearing declared: {LABEL[chosen[0]]} (relative to your Pole)"})


def _update(engine: Any, holder: Any, condition: Any, data: dict[str, Any]) -> None:
    from .effect_durations import apply_condition_preserving_clock
    _remove(engine, holder, condition, "UPDATED")
    apply_condition_preserving_clock(engine, holder, condition, condition.condition_id, condition.source_definition_id, condition.source_actor_id,
                            expires_on=condition.expires_on, data=data)


def _direction(engine: Any, viewer: Any, seen: Any) -> str:
    ax, ay = _centre(engine, viewer)
    bx, by = _centre(engine, seen)
    dx, dy = bx - ax, by - ay
    if not dx and not dy:
        return "here"
    north = "north" if dy < 0 else "south" if dy > 0 else ""
    east = "east" if dx > 0 else "west" if dx < 0 else ""
    if north and east and abs(dx) != abs(dy):
        # A clearly longer axis wins; a near-equal one is diagonal.
        if abs(dx) >= 2 * abs(dy):
            north = ""
        elif abs(dy) >= 2 * abs(dx):
            east = ""
    return "-".join(part for part in (north, east) if part)


def _band(engine: Any, viewer: Any, seen: Any) -> str:
    distance = centre_distance_ft(engine, viewer, seen)
    if distance < 30:
        return "closer than 30 feet"
    if distance <= 60:
        return "30 to 60 feet away"
    return "farther than 60 feet"


def pole_sense(engine: Any, owner: Any, creature: Any) -> None:
    """The printed direction bands: direction and coarse distance only, never an exact square."""
    if owner is None or creature is None or not _te().bears_mark(creature, owner.entity_id, "Resonance"):
        return
    if centre_distance_ft(engine, owner, creature) > 120:
        return
    note(engine, FOOTWORK, owner, f"Pole sense: {creature.display_name} is {_direction(engine, owner, creature)}, "
                                  f"{_band(engine, owner, creature)}. (Direction and distance band from your Resonance Mark; "
                                  f"not its exact space.)", (creature,))


@hook("event")
def movement_seen(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "OBJECT_UPDATED":
        _object_pole_damaged(engine, kwargs)
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    payload = kwargs.get("payload") or {}
    if mover is None or payload.get("forced") or payload.get("dragged_by") or payload.get("exchange"):
        return
    path = payload.get("path") or []
    moved = max(0, len(path) - 1) * engine.grid.square_size_ft
    if not moved:
        return
    own = _mine(mover, BEARING)
    if own is not None and not (own.data or {}).get("done"):
        _progress(engine, mover, own, moved, own_bearing=True)
    chosen = next((c for c in mover.conditions.values() if c.condition_id == CHOSEN), None)
    if chosen is not None and not (chosen.data or {}).get("done"):
        _progress(engine, mover, chosen, moved, own_bearing=False)
    for walker_id, record in list((engine.__dict__.get(_READ) or {}).items()):
        if record.get("pole") == mover.entity_id:
            record["moved"] = int(record.get("moved") or 0) + moved
    for owner in engine.state.actors.values():
        if owner.active and owner is not mover and _owns(engine, owner, "three_bearing_footwork"):
            creature, _ref = pole(engine, owner)
            if creature is mover:
                pole_sense(engine, owner, creature)


def _progress(engine: Any, mover: Any, held: Any, moved: int, *, own_bearing: bool) -> None:
    data = dict(held.data or {})
    # Completion is a one-time award. Later movement or damage callbacks may
    # revisit this evaluator during the same turn, but must not regrant it.
    if data.get("done"):
        return
    data["moved"] = int(data.get("moved") or 0) + moved
    # A return to the starting square is allowed when the Bearing advanced its
    # hostile objective. For a creature Pole, a successful Martial Strike is
    # that observable progress; other objective types remain GM adjudication.
    advanced = _pos(data["start"]) != mover.position or bool(data.get("objective_advanced"))
    done = advanced and data["moved"] >= 10 and data["kind"] in category(engine, _pos(data["start"]), mover.position, _pos(data["ref"]))
    if done:
        data["done"] = 1
    _update(engine, mover, held, data)
    if not done:
        return
    if own_bearing:
        _complete(engine, mover, data["kind"])
    else:
        _chosen_benefit(engine, mover, data)


def _complete(engine: Any, actor: Any, kind: str) -> None:
    if actor.resources.get(TOKEN[kind], 0) < 1:
        engine._gain_resource(actor, TOKEN[kind], 1, FOOTWORK)
    note(engine, FOOTWORK, actor, f"{actor.display_name} completes its {LABEL[kind]} Bearing and holds its token.")
    if actor.turn_flags.get("compass_strike_used"):
        return
    if actor.turn_flags.get("compass_pole_struck"):
        _compass_strike(engine, actor, kind)
    else:
        actor.turn_flags["compass_strike_pending"] = kind


@hook("damage_dealt")
def bearing_hostile_progress(ctx: Any, target: Any, amount: int) -> None:
    """Track observable hostile progress for Chosen Bearings and owned Pole strikes."""
    engine, actor = ctx.engine, ctx.actor
    if amount <= 0 or engine.state.current_actor_id != actor.entity_id:
        return
    # Chosen Bearings belong to the ally who declared them, not to the aura
    # owner. A damaging hit on an active hostile creature is observable hostile
    # objective progress for that ally; it must not depend on personal Footwork
    # or a personal Pole. The shared evaluator still requires the declared route
    # and 10 feet of voluntary movement before granting the chosen benefit.
    chosen = next((c for c in actor.conditions.values() if c.condition_id == CHOSEN), None)
    if (chosen is not None and not (chosen.data or {}).get("done")
            and target is not None and target.team_id != actor.team_id):
        data = dict(chosen.data or {})
        data["objective_advanced"] = 1
        _update(engine, actor, chosen, data)
        current = next((c for c in actor.conditions.values()
                        if c.condition_id == CHOSEN
                        and c.source_actor_id == chosen.source_actor_id), None)
        if current is not None:
            _progress(engine, actor, current, 0, own_bearing=False)

    if not _owns(engine, actor, "three_bearing_footwork"):
        return
    creature, _ref = pole(engine, actor)
    object_pole = _pole_object(engine, actor)
    hostile = target is not None and target.team_id != actor.team_id
    own = _mine(actor, BEARING)
    # "Moving repeatedly between the same spaces does not complete a Bearing
    # unless the movement advanced a meaningful hostile objective." Any
    # damaging hit this turn on a creature that is not on the owner's team is
    # such observable progress (the out-and-back route itself is unchanged).
    if own is not None and not (own.data or {}).get("done") and hostile:
        _advance(engine, actor, own)
    if object_pole is not None or target is None or target is not creature:
        return
    row = getattr(ctx, "attack_effect", None) or {}
    source = str(ctx.source or "")
    # Printed: "a Martial Strike needs a weapon you are proficient with". The compiled row records the owner's own
    # training, so a non-proficient weapon no longer counts. Mind Spike is a Martial Strike in Spirit Awakening core.
    mind = source.split("#")[0] == MIND_SPIKE or str((ctx.typed or {}).get("source") or "").split("#")[0] == MIND_SPIKE
    if not (mind or row.get("attack_kind") in ("unarmed", "natural_weapon") or ".natural." in source
            or st.proficient_weapon(ctx.typed)):
        return
    # Record strike progress before reevaluating completion. This lets a
    # qualifying hit finish an already valid out-and-back Bearing without
    # adding movement a second time, and lets completion see the strike once.
    actor.turn_flags["compass_pole_struck"] = True
    bearing = _mine(actor, BEARING)
    if bearing is not None and not (bearing.data or {}).get("done"):
        _advance(engine, actor, bearing)
    pending = actor.turn_flags.pop("compass_strike_pending", None)
    if pending and not actor.turn_flags.get("compass_strike_used"):
        _compass_strike(engine, actor, pending, ctx.intent)


def _advance(engine: Any, actor: Any, bearing: Any) -> None:
    """Mark a hostile objective met, then re-evaluate completion with no new movement."""
    data = dict(bearing.data or {})
    data["objective_advanced"] = 1
    _update(engine, actor, bearing, data)
    current = next((c for c in actor.conditions.values()
                    if c.condition_id == bearing.condition_id
                    and c.source_actor_id == bearing.source_actor_id), None)
    if current is not None:
        _progress(engine, actor, current, 0, own_bearing=bearing.condition_id == BEARING)


def _compass_strike(engine: Any, actor: Any, kind: str, intent: Any = None) -> None:
    creature, _ref = pole(engine, actor)
    if creature is None:
        obj = _pole_object(engine, actor)
        if obj is not None:
            _object_compass_strike(engine, actor, kind, intent, obj)
        return
    actor.turn_flags["compass_strike_used"] = True  # "Compass Strike is one once-per-turn rider"
    ctx = _ctx(engine, actor, FOOTWORK, [creature], intent)
    te = _te()
    if kind == "approach":
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["psychic", "force"],
                              "evidence": "Enter the Line: an additional 1d8 Psychic or Force damage"}])
        # Printed: only Opportunity Attacks *against you* are denied, not every
        # Reaction. The engine's scoped no_opportunity_attacks condition is the
        # native way to say exactly that (2026-09-29 fight-audit scoping rule).
        engine._apply_condition(creature, NO_OPPORTUNITY, FOOTWORK, actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"against": actor.entity_id,
                                      "label": f"Enter the Line: {creature.display_name} cannot make Opportunity Attacks against "
                                               f"{actor.display_name} until the start of your next turn"})
    elif kind == "orbit":
        # Printed: "Move 5 feet to a legal space" -- a move, not an optional
        # stay; with no legal space there is nothing to move to and the guard
        # below still applies.
        step(engine, actor, 5, creature, intent, label="Step Beyond the Angle", stay=False)
        guard = _mine(actor, ORBIT_GUARD)
        if guard is not None:
            _remove(engine, actor, guard, "REPLACED")
        engine._apply_condition(actor, ORBIT_GUARD, FOOTWORK, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"against": creature.entity_id, "label": f"+2 AC against {creature.display_name}'s attacks"})
    else:
        pushed = False
        if te.bears_mark(creature, actor.entity_id, "Resonance"):
            from . import needle

            chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "COMPASS_DEPART", creature.entity_id), actor,
                                "choice:needle.compass.depart", ["save", "step"],
                                labels={"save": f"{creature.display_name} makes a Strength or Wisdom save or is pushed 5 feet away",
                                        "step": "Step up to 10 feet farther from it without provoking its Opportunity Attack"},
                                preferred=["save"], name="Leave the Needle Behind", feature_id=FOOTWORK, target_id=creature.entity_id)
            if chosen and chosen[0] == "save":
                pushed = True
                ability = _depart_save_ability(engine, intent, actor, creature)
                te.run_effects(ctx, [{"type": "save", "applies_to": "target", "ability": ability,
                                      "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away",
                                                   "evidence": "On a failure, move it 5 feet away from you"}], "on_success": []}])
        if not pushed:
            step(engine, actor, 10, creature, intent, label="Leave the Needle Behind", farther_from=creature.position)
    note(engine, FOOTWORK, actor, f"Compass Strike ({LABEL[kind]}) against {creature.display_name}.", (creature,))


def _object_compass_strike(engine: Any, actor: Any, kind: str, intent: Any, obj: Any) -> None:
    """The same three expressions against an object, Cultivation Asset or Anchor Pole.

    Objects have no Reactions, no Resonance Mark and no attacks of their own, so
    the Approach damage is the only expression with a target; Orbit and Depart
    still move the practitioner and apply their printed guard where it can apply.
    """
    actor.turn_flags["compass_strike_used"] = True
    te = _te()
    if kind == "approach":
        ctx = _ctx(engine, actor, FOOTWORK, [], intent)
        amount, damage_type = te._damage_roll(ctx, {"dice": {"count": 1, "sides": 8},
                                                    "damage_types": ["psychic", "force"]})
        from . import objects

        objects.deal(engine, actor, obj, [(int(amount), str(damage_type).upper())], FOOTWORK)
    elif kind == "orbit":
        step(engine, actor, 5, None, intent, label="Step Beyond the Angle", stay=False)
        guard = _mine(actor, ORBIT_GUARD)
        if guard is not None:
            _remove(engine, actor, guard, "REPLACED")
        engine._apply_condition(actor, ORBIT_GUARD, FOOTWORK, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"against": obj.object_id, "label": f"+2 AC against {_object_label(obj)}'s attacks"})
    else:
        step(engine, actor, 10, None, intent, label="Leave the Needle Behind", farther_from=obj.position)
    note(engine, FOOTWORK, actor, f"Compass Strike ({LABEL[kind]}) against {_object_label(obj)}.", (obj.object_id,))


def _object_martial_strike(engine: Any, actor: Any, action: Any, source: str) -> bool:
    """Whether this action is a Martial Strike aimed at an object.

    The table's "Attack an object" action is built from the character's own
    weapon or unarmed rows and carries ``object_attack`` effects instead of a
    creature ``attack`` row, so the creature check in damage_dealt never sees
    it. Its group names the weapon; an unarmed/natural group qualifies, and a
    weapon group qualifies only when the owner's own compiled row is proficient.
    """
    typed = (action.parameters or {}).get("typed") or {}
    effects = [row for row in typed.get("effects") or [] if isinstance(row, dict)]
    if not any(row.get("type") == "object_attack" for row in effects):
        return False
    group = str(typed.get("object_weapon_group") or "")
    if group == "unarmed" or ".natural." in source:
        return True
    weapon = typed.get("object_weapon") or {}
    if not weapon:
        return False
    for action_id in actor.action_ids:
        candidate = engine.action_catalog.get(action_id)
        other = ((candidate.parameters or {}).get("typed") or {}) if candidate is not None else {}
        if other.get("weapon") == weapon and any(isinstance(row, dict) and row.get("type") == "attack"
                                                 for row in other.get("effects") or []):
            return other.get("proficient") is not False
    return False


def _object_pole_damaged(engine: Any, kwargs: dict[str, Any]) -> None:
    """A Martial Strike that actually took hit points off an object Pole."""
    payload = kwargs.get("payload") or {}
    record = payload.get("object") or {}
    object_id = str(record.get("object_id") or "")
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if not object_id or actor is None or engine.state.current_actor_id != actor.entity_id:
        return
    if not _owns(engine, actor, "three_bearing_footwork"):
        return
    obj = _pole_object(engine, actor)
    if obj is None or obj.object_id != object_id:
        return
    current = kwargs.get("originating_event")
    sequence = int(getattr(current, "sequence", 0) or 0)
    earlier = [event for event in engine.events
               if int(event.sequence) < sequence and event.event_type == "OBJECT_UPDATED"
               and object_id in event.target_ids]
    old = (earlier[-1].payload or {}).get("object") if earlier else None
    before, after = (old or {}).get("current_hp"), record.get("current_hp")
    if before is None or after is None or int(after) >= int(before):
        return
    source = str(kwargs.get("source_definition_id") or "")
    action = engine.action_catalog.get(source)
    if action is None or not _object_martial_strike(engine, actor, action, source):
        return
    actor.turn_flags["compass_pole_struck"] = True
    bearing = _mine(actor, BEARING)
    if bearing is not None and not (bearing.data or {}).get("done"):
        _advance(engine, actor, bearing)
    pending = actor.turn_flags.pop("compass_strike_pending", None)
    if pending and not actor.turn_flags.get("compass_strike_used"):
        _compass_strike(engine, actor, pending, engine._active_intent)


def _depart_save_ability(engine: Any, intent: Any, actor: Any, creature: Any) -> str:
    """The printed "Strength or Wisdom saving throw", chosen by the ability's user.

    This is a player decision on the user's own turn (checklist item 9), so it
    goes through ``needle.ask`` with both legal abilities. A computer-controlled
    user takes the first printed option: it has no lawful knowledge of the
    Pole's saving-throw modifiers, and reading them would be information the
    creature's controller was never given.
    """
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "COMPASS_DEPART_SAVE", creature.entity_id), actor,
                        "choice:needle.compass.depart_save", ["str", "wis"],
                        labels={"str": f"{creature.display_name} makes a Strength saving throw (5 feet away on a failure)",
                                "wis": f"{creature.display_name} makes a Wisdom saving throw (5 feet away on a failure)"},
                        preferred=["str"], name="Leave the Needle Behind: saving throw", feature_id=FOOTWORK,
                        target_id=creature.entity_id,
                        prompt=f"Leave the Needle Behind: {actor.display_name} requires which saving throw from "
                               f"{creature.display_name}? On a failure it moves 5 feet away from you.")
    return chosen[0] if chosen and chosen[0] in ("str", "wis") else "str"


def _weaker(creature: Any, *abilities: str) -> str:
    return min(abilities, key=lambda a: (int((creature.saving_throws or {}).get(a, 0)), a)).lower()


def step(engine: Any, actor: Any, feet: int, pole_creature: Any, intent: Any, *, label: str, farther_from: Any = None,
         closer_to: Any = None, keep_band: tuple[Any, int] | None = None, stay: bool = True, min_ft: int = 0) -> bool:
    """A free step of up to ``feet`` through the ordinary movement resolver: the Pole cannot answer it with an Opportunity Attack
    (others still can), squares filtered to the requested direction. True when the creature moved."""
    from . import needle
    from .rider_helpers import cell_choice_id

    if not actor.active or engine._effective_speed(actor) <= 0:
        return False
    before, prior = actor.movement_remaining_ft, actor.turn_flags.get("spark_step_ignore_oa_from")
    try:
        actor.movement_remaining_ft = feet
        if pole_creature is not None:
            actor.turn_flags["spark_step_ignore_oa_from"] = pole_creature.entity_id
        here = actor.position

        def keeps(cell: Any) -> bool:
            if min_ft and _dist(engine, here, cell) < min_ft:
                return False  # a Bearing segment must move at least 10 feet
            if farther_from is not None and _dist(engine, cell, farther_from) <= _dist(engine, here, farther_from):
                return False
            if closer_to is not None and _dist(engine, cell, closer_to) >= _dist(engine, here, closer_to):
                return False
            if keep_band is not None and abs(_dist(engine, cell, keep_band[0]) - keep_band[1]) > 5:
                return False
            return True

        options = {cell_choice_id(c.destination): c for c in engine._movement_candidates(actor)
                   if c.destination is not None and c.destination != here and keeps(c.destination)}
        if not options:
            return False
        stay_id = cell_choice_id(here)
        ids = ([stay_id] if stay else []) + list(options)
        preferred = [stay_id] if stay else [max(options, key=lambda k: (_dist(engine, options[k].destination, farther_from) if farther_from is not None else 0,
                                                                         -_dist(engine, options[k].destination, closer_to) if closer_to is not None else 0, k))]
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "COMPASS_STEP", actor.entity_id), actor, "choice:needle.compass.step", ids,
                            labels={stay_id: "Stay where you are", **{k: c.display_name for k, c in options.items()}}, preferred=preferred,
                            allow_decline=True, name=label, feature_id=FOOTWORK,
                            prompt=f"{label}: {actor.display_name} may move up to {feet} feet" + (" (the Pole cannot make an Opportunity Attack)" if pole_creature else "") + ".")
        if chosen and chosen[0] in options:
            engine._resolve_movement(actor, options[chosen[0]], intent if intent is not None else engine._active_intent)
            return True
        return False
    finally:
        actor.movement_remaining_ft = before
        if prior is None:
            actor.turn_flags.pop("spark_step_ignore_oa_from", None)
        else:
            actor.turn_flags["spark_step_ignore_oa_from"] = prior


# ------------------------------------------------------------------------------------------------- No Blind Side, guards
def _first_unseen_attack(engine: Any, attacker: Any, target: Any, hidden: set[str]) -> set[str]:
    """The Hidden instances this Pole has not yet attacked ``target`` under.

    The printed rule suppresses only the *first* attack made while unseen. This
    is read from the persisted journal instead of consuming a marker during a
    query: a menu or tooltip that asks for the attack mode cannot spend the
    suppression, and a cold reload/mechanical replay reaches the same answer
    because ATTACK_ROLLED and condition application are both journaled events.
    """
    if not hidden:
        return set()
    rolls = [int(event.sequence) for event in engine.events
             if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker.entity_id
             and target.entity_id in event.target_ids]
    fresh = set()
    for iid in hidden:
        condition = attacker.conditions.get(iid)
        if condition is None:
            continue
        applied = int(getattr(condition, "applied_sequence", 0) or 0)
        if not any(sequence > applied for sequence in rolls):
            fresh.add(iid)
    return fresh


@hook("masked_conditions")
def no_blind_side(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """No Blind Side to the Soul: the Pole's first attack loses only Hidden's unseen Advantage.

    Runs for the owner/Pole pair only and in the attack-mode direction (the
    owner is the ``target``). Other perception queries pass the owner as the
    attacker, so this mask never makes a concealed Pole visible. It masks only
    the Hidden condition instance: Invisible, total cover, perfect spiritual
    concealment and every other unseen/perception effect are untouched.
    """
    if attacker is None or target is None or not _owns(engine, target, "three_bearing_footwork"):
        return None
    creature, _ref = pole(engine, target)
    if (creature is not attacker or not _te().bears_mark(attacker, target.entity_id, "Resonance")
            or centre_distance_ft(engine, attacker, target) > 60):
        return None
    hidden = {iid for iid, c in attacker.conditions.items() if c.condition_id == "condition:typed.hidden"}
    fresh = _first_unseen_attack(engine, attacker, target, hidden)
    return {attacker.entity_id: fresh} if fresh else None


@hook("hit_response")
def compass_guards(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    if natural == 20 or attacker is None:
        return None
    bonus = 0
    guard = _mine(target, ORBIT_GUARD)
    if guard is not None and (guard.data or {}).get("against") == attacker.entity_id:
        bonus += 2
    chosen = next((c for c in target.conditions.values() if c.condition_id == CHOSEN_ORBIT), None)
    if chosen is not None and engine.state.current_actor_id != attacker.entity_id:
        bonus += 2  # "+2 AC against opportunity attacks and attacks made as Reactions"
    held = engine.__dict__.get(_TURN)
    if held and held.get("attacker") == attacker.entity_id and held.get("ac_for") == target.entity_id:
        # only the answered attack: its own roll, the first one after Turn the Compass
        rolled = [e for e in engine.events[int(held.get("events") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id]
        preserve_pending(engine, _TURN)
        engine.__dict__.pop(_TURN, None)
        if len(rolled) == 1 and (not held.get("roll") or str((rolled[0].payload or {}).get("reason") or "") == held["roll"]):
            bonus += 2
    if not bonus or total >= effective_ac + bonus:
        return None
    note(engine, FOOTWORK, target, f"+{bonus} AC turns {attacker.display_name}'s attack into a miss (Compass-Breaking Hand).", (attacker,))
    return effective_ac + bonus, False


# ---------------------------------------------------------------------------------------------------------- Turn the Compass
def _turn_walker(engine: Any, attacker: Any, protected: Any) -> Any:
    for walker in engine.state.actors.values():
        if not walker.active or walker.team_id == attacker.team_id or not _owns(engine, walker, "turn_the_compass"):
            continue
        creature, _ref = pole(engine, walker)
        north = _false_north(engine, walker)
        if attacker is not creature and attacker is not north:
            continue
        if _dist(engine, walker.position, attacker.position) > 60:
            continue
        if protected is not walker and (protected.team_id != walker.team_id or _dist(engine, walker.position, protected.position) > 15):
            continue
        if not st.can_react(walker) or walker.resources.get(RESONANCE, 0) < 2 or not any(walker.resources.get(TOKEN[k], 0) for k in KINDS):
            continue
        return walker
    return None


@hook("retarget_attack")
def turn_the_compass(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if attacker is None or defender is None or attacker.team_id == defender.team_id:
        return None
    walker = _turn_walker(engine, attacker, defender)
    if walker is None:
        return None
    reach = int(context.get("range_ft") or 5)
    held = [k for k in KINDS if walker.resources.get(TOKEN[k], 0)]
    from . import needle

    labels = {"approach": f"Approach: move toward {attacker.display_name} or {defender.display_name}; become the target (+2 AC)",
              "orbit": f"Orbit: {defender.display_name} slips around the attack (Disadvantage on it)",
              "depart": f"Depart: {defender.display_name} moves 10 feet farther from {attacker.display_name} (a miss if out of reach, else +2 AC)"}
    escape = any(_dist(engine, cell, attacker.position) > reach for cell in st.routes(engine, defender, 10)) if reach <= 10 else False
    preferred = ["depart"] if "depart" in held and escape else ["orbit"] if "orbit" in held else held[:1]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "TURN_THE_COMPASS", attacker.entity_id, context.get("attack_index", 1)), walker,
                        "choice:needle.compass.turn_the_compass", held, labels={k: labels[k] for k in held}, preferred=preferred,
                        allow_decline=True, name="Turn the Compass", feature_id=TURN, target_id=attacker.entity_id,
                        prompt=f"Turn the Compass (Reaction, 2 Resonance and a Bearing token): your Pole {attacker.display_name} attacks "
                               f"{defender.display_name}. Spend which token?")
    if not chosen:
        return None
    kind = chosen[0]
    with activation(engine, walker, TURN):
        engine._spend_resource(walker, RESONANCE, 2, TURN)
        engine._spend_resource(walker, TOKEN[kind], 1, TURN)
        kind = bearing_without_name(engine, walker, [kind], intent, context="turn_compass",
                                    target_name=defender.display_name, target_id=defender.entity_id)[0]
        walker.reaction_available = False
        engine._append_event("REACTION_RESOLVED", TURN, actor_id=walker.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": f"Turn the Compass ({LABEL[kind]})"})
        if kind == "approach":
            step(engine, walker, 10, attacker, intent, label="Intercept the Line", stay=True)
            close = _dist(engine, walker.position, defender.position) <= 5 or _dist(engine, walker.position, attacker.position) <= reach
            if defender is not walker and close:
                preserve_pending(engine, _TURN)
                engine.__dict__[_TURN] = {"attacker": attacker.entity_id, "ac_for": walker.entity_id, "events": len(engine.events),
                                          "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
                note(engine, TURN, walker, f"Turn the Compass: {walker.display_name} steps into the line and becomes the target.", (attacker,))
                return {"source_id": str(context.get("source_id") or ""), "target_id": walker.entity_id, "cover_bonus": 0}
            preserve_pending(engine, _TURN)
            engine.__dict__[_TURN] = {"attacker": attacker.entity_id, "ac_for": defender.entity_id, "events": len(engine.events),
                                      "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
            return None
        preserve_pending(engine, _TURN)
        engine.__dict__[_TURN] = {"attacker": attacker.entity_id, "pending": kind, "for": defender.entity_id, "events": len(engine.events)}
        retain(engine, _TURN, capture(engine))
        return None


@hook("before_attack")
def turn_the_compass_moves(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    held = engine.__dict__.get(_TURN)
    if not held or held.get("attacker") != getattr(attacker, "entity_id", None) or held.get("for") != getattr(defender, "entity_id", None):
        return None
    with causal_scope(engine, take(engine, _TURN)):
        kind = held.get("pending")
        if kind == "orbit":
            preserve_pending(engine, _TURN)
            engine.__dict__.pop(_TURN, None)
            step(engine, defender, 10, attacker, intent, label="Leave the Attack Facing Empty Air",
                 keep_band=(attacker.position, _dist(engine, defender.position, attacker.position)))
            return {"mode": "DISADVANTAGE"}
        if kind == "depart":
            step(engine, defender, 10, attacker, intent, label="Put Distance Inside the Blow", farther_from=attacker.position, stay=False)
            preserve_pending(engine, _TURN)
            engine.__dict__[_TURN] = {"attacker": attacker.entity_id, "ac_for": defender.entity_id, "events": len(engine.events),
                                      "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
            return {}
        return None


@hook("turn_start")
def compass_pole_sense(engine: Any, actor: Any) -> None:
    """A marked creature Pole within 120 feet is known by direction and distance band, not square."""
    if _owns(engine, actor, "three_bearing_footwork"):
        creature, _ref = pole(engine, actor)
        pole_sense(engine, actor, creature)


@hook("turn_start")
def pole_turn_starts(engine: Any, actor: Any) -> None:
    """Read Their Bearing: note where each Compass walker stands as its Pole's turn begins."""
    records = engine.__dict__.setdefault(_READ, {})
    for walker in engine.state.actors.values():
        if walker.active and _owns(engine, walker, "turn_the_compass") and pole(engine, walker)[0] is actor and walker.team_id != actor.team_id:
            records[walker.entity_id] = {"pole": actor.entity_id, "start": _xy(actor.position), "ref": _xy(walker.position), "moved": 0}


@hook("turn_end")
def pole_turn_ends(engine: Any, actor: Any) -> None:
    records = engine.__dict__.get(_READ) or {}
    for walker_id, record in list(records.items()):
        if record.get("pole") != actor.entity_id:
            continue
        records.pop(walker_id, None)
        walker = engine.state.actors.get(walker_id)
        if walker is None or not walker.active or int(record.get("moved") or 0) < 10:
            continue
        key = "compass_round_read_bearing"
        if walker.turn_flags.get(key) == engine.state.round_number:
            continue
        done = category(engine, _pos(record["start"]), actor.position, _pos(record["ref"]))
        kind = next((k for k in ("approach", "depart", "orbit") if k in done), None)
        if kind is None:
            continue
        walker.turn_flags[key] = engine.state.round_number
        if walker.resources.get(TOKEN[kind], 0) < 1:
            engine._gain_resource(walker, TOKEN[kind], 1, TURN)
        note(engine, TURN, walker, f"Read Their Bearing: {actor.display_name} completed {LABEL[kind]}; {walker.display_name} holds that token.", (actor,))


# ---------------------------------------------------------------------------------------------------- Break the Four Directions
def _best_strike(engine: Any, actor: Any, target: Any, reach_needed: int) -> Any:
    best = None
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
        if action is None or action.economy.value != "ACTION" or "#" in action_id or typed.get("proficient") is False:
            continue
        attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
        if attack is None or not (typed.get("weapon") is not None or attack.get("attack_kind") in ("unarmed", "natural_weapon")):
            continue
        reach = int(action.reach_ft or action.range_ft or 5)
        if reach < reach_needed or int((action.parameters or {}).get("expected_damage") or 0) <= 0:
            continue  # a strike that deals its normal damage (not a Grapple or a Shove)
        if best is None or int((action.parameters or {}).get("expected_damage") or 0) > int((best.parameters or {}).get("expected_damage") or 0):
            best = action
    return best


@effect("compass_break")
def break_four(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    procession = bool(row.get("procession"))
    target = ctx.target
    if target is None or not target.active:
        return
    actor.turn_flags["compass_break_used"] = True
    temp = _temp_tokens(actor) if procession else {}
    held = [k for k in KINDS if (temp.get(k) if procession else actor.resources.get(TOKEN[k], 0))]
    if not held:
        return
    from . import needle

    limit = 2 if procession else 3
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "COMPASS_BREAK", target.entity_id), actor, "choice:needle.compass.break",
                        held, labels={k: f"{LABEL[k]} token: a 10-foot {LABEL[k]} segment first" for k in held},
                        preferred=held[:limit], minimum=1, maximum=min(limit, len(held)), default="all", default_count=min(limit, len(held)),
                        name="Break the Four Directions", feature_id=BREAK, target_id=target.entity_id,
                        prompt=f"Break the Four Directions against {target.display_name}: spend which Bearing tokens (one segment of up to 10 feet each)?")
    ref = target.position
    spent: list[str] = []
    for kind in [k for k in KINDS if k in chosen][:limit]:
        start = actor.position
        before = len(engine.events)
        moved = step(engine, actor, 10, target, ctx.intent, label=f"Break the Four Directions: {LABEL[kind]} segment", stay=False, min_ft=10,
                     closer_to=ref if kind == "approach" else None, farther_from=ref if kind == "depart" else None,
                     keep_band=(ref, _dist(engine, start, ref)) if kind == "orbit" else None)
        travelled = sum(max(0, len((e.payload or {}).get("path") or []) - 1) for e in engine.events[before:]
                        if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor.entity_id) * engine.grid.square_size_ft
        if moved and travelled >= 10 and kind in category(engine, start, actor.position, ref):
            spent.append(kind)
        elif moved:
            note(engine, BREAK, actor, f"The {LABEL[kind]} segment did not complete its Bearing; that token is kept.")
    for kind in spent:
        if procession:
            _spend_temp(engine, actor, kind)
        else:
            engine._spend_resource(actor, TOKEN[kind], 1, BREAK)
    if not target.active:
        return
    expressions = bearing_without_name(engine, actor, spent, ctx.intent, context="break_four",
                                       target_name=target.display_name, target_id=target.entity_id)
    riders = []
    if "approach" in expressions:
        riders.append({"type": "compass_approach_rider", "applies_to": "target"})
    if "orbit" in expressions:
        riders += [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_end_of_next_turn"}, "evidence": "The Pole cannot take Reactions"},
                   {"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": {"kind": "until_end_of_next_turn"},
                    "evidence": "has Disadvantage on its next attack roll before the end of its next turn"}]
    if "depart" in expressions:
        riders.append({"type": "compass_depart_rider", "applies_to": "target"})
    dice = 2 + len(spent)
    extra = {"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8}, "damage_types": ["psychic", "force"],
             "evidence": f"plus 2d8 + 1d8 for each Bearing spent ({dice}d8) Psychic or Force damage"}
    strike = _best_strike(engine, actor, target, _dist(engine, actor.position, target.position))
    bonus = int(ctx.numbers.get("attack_bonus") or 0)  # "Use your Cultivation Attack Modifier instead of the normal attack modifier"
    miss = [{"type": "compass_miss_step", "kinds": spent}] if spent else []
    if strike is not None:
        import copy

        typed = copy.deepcopy((strike.parameters or {}).get("typed") or {})
        typed["numbers"] = {**(typed.get("numbers") or {}), "attack_bonus": bonus}
        attack = copy.deepcopy(next(r for r in typed["effects"] if isinstance(r, dict) and r.get("type") == "attack"))
        attack["on_hit"] = [*(attack.get("on_hit") or []), extra, *riders]
        attack["on_miss"] = [*(attack.get("on_miss") or []), *miss]
        attack["count"] = 1
        sub = _te().Context(engine, actor, strike, ctx.intent, typed, [target], target, {})
        _te().run_effects(sub, [attack])
        return
    if _dist(engine, actor.position, target.position) > 5:
        note(engine, BREAK, actor, f"Break the Four Directions: {target.display_name} is out of reach after the movement; no attack.", (target,))
        return
    _te().run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [extra, *riders], "on_miss": miss}])


@effect("compass_approach_rider")
def approach_rider(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    te = _te()
    larger = ctx.engine._footprint(subject).width_cells >= ctx.engine._footprint(ctx.actor).width_cells + 2
    moves = True
    if larger:
        before = len(ctx.engine.events)
        te.block_save(ctx, {"type": "save", "applies_to": "target", "ability": "str", "on_fail": [], "on_success": []})
        rolled = [e for e in ctx.engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
        moves = not (rolled and (rolled[-1].payload or {}).get("success"))
    rows = ([{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "toward",
              "evidence": "Move the Pole up to 10 feet toward you"}] if moves else []) + [
        {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
         "evidence": "Resonance Mark it until the end of your next turn"}]
    te.run_effects(ctx, rows)


@effect("compass_depart_rider")
def depart_rider(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    te = _te()
    te.block_save(ctx, {"type": "save", "applies_to": "target", "ability": _weaker(subject, "STR", "WIS"),
                        "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away",
                                     "evidence": "Move the Pole up to 15 feet away from you on a failed Strength or Wisdom saving throw"}],
                        "on_success": []})
    step(ctx.engine, ctx.actor, 10, subject, ctx.intent, label="Depart", farther_from=subject.position)


@effect("compass_miss_step")
def miss_step(ctx: Any, row: dict[str, Any]) -> None:
    kinds = [k for k in row.get("kinds") or [] if k in KINDS]
    target = ctx.target
    if not kinds or target is None:
        return
    from . import needle

    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "COMPASS_MISS", ctx.actor.entity_id), ctx.actor,
                        "choice:needle.compass.miss", kinds, labels={k: f"Step 5 feet ({LABEL[k]})" for k in kinds}, preferred=[],
                        allow_decline=True, default="decline", name="Break the Four Directions", feature_id=BREAK,
                        prompt="Break the Four Directions missed: you may move 5 feet in the category of one Bearing spent.")
    if not chosen:
        return
    kind = chosen[0]
    step(ctx.engine, ctx.actor, 5, None, ctx.intent, label=f"{LABEL[kind]} step", stay=False,
         closer_to=target.position if kind == "approach" else None, farther_from=target.position if kind == "depart" else None,
         keep_band=(target.position, _dist(ctx.engine, ctx.actor.position, target.position)) if kind == "orbit" else None)


# ------------------------------------------------------------------------------------------------------------ No Fixed Compass
@hook("speed")
def direction_without_footing(engine: Any, actor: Any) -> int | None:
    return 10 if _owns(engine, actor, "no_fixed_compass") else None


@hook("difficult_exempt")
def bearing_footing(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    if not _owns(engine, actor, "no_fixed_compass"):
        return None
    held = _mine(actor, BEARING)
    if held is None or (held.data or {}).get("done"):
        return None
    return st.plain_difficult(engine)  # "Nonmagical difficult terrain does not cost you extra movement while completing a Bearing"


@effect("compass_restraint")
def restraining_direction(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import CONDITION_PREFIX

    engine, actor = ctx.engine, ctx.actor
    actor.turn_flags["compass_restraint"] = True
    grip = next((c for c in actor.conditions.values() if c.condition_id in (CONDITION_PREFIX + "grappled", CONDITION_PREFIX + "restrained")), None)
    if grip is None:
        return
    dc = int((grip.data or {}).get("escape_dc") or (grip.data or {}).get("dc") or ctx.numbers.get("save_dc") or 10)
    bonus = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0)
    roll = engine.roll_check(modifier=bonus, actor_id=actor.entity_id, reason=f'CHECK:{ctx.source}')
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id,
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Cultivation Check (Break the Restraining Direction)"})
    if success:
        _remove(engine, actor, grip, "ESCAPED")
        note(engine, NO_FIXED, actor, f"{actor.display_name} breaks the restraining direction and is free (Cultivation Check {roll.total} against DC {dc}).")
    else:
        note(engine, NO_FIXED, actor, f"{actor.display_name} cannot break the restraining direction this turn (Cultivation Check {roll.total} against DC {dc}).")


# ------------------------------------------------------------------------------------------------ Heaven Has No Fixed North
def _domain(engine: Any, owner: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id
                 and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == HEAVEN), None)


def _false_north(engine: Any, actor: Any) -> Any:
    held = _mine(actor, TEMP)
    return engine.state.actors.get(str((held.data or {}).get("north") or "")) if held is not None else None


def _temp_tokens(actor: Any) -> dict[str, int]:
    held = _mine(actor, TEMP)
    return {k: int(v) for k, v in ((held.data or {}).get("tokens") or {}).items() if int(v) > 0} if held is not None else {}


def _spend_temp(engine: Any, actor: Any, kind: str) -> None:
    held = _mine(actor, TEMP)
    if held is None:
        return
    data = dict(held.data or {})
    tokens = dict(data.get("tokens") or {})
    tokens[kind] = 0
    _update(engine, actor, held, {**data, "tokens": tokens})


def _false_north_pick(engine: Any, actor: Any) -> None:
    held = _mine(actor, TEMP)
    if held is not None:
        _remove(engine, actor, held, "EXPIRED")
    domain = _domain(engine, actor)
    hostiles = [c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and engine._footprint_intersects(c, domain.affected_cells)]
    north = st.pick_creature(engine, None, actor, hostiles, checkpoint="FALSE_NORTH", choice_id="choice:needle.compass.false_north",
                             prompt="False North: which hostile creature in your Compass Domain counts as your Pole until the start of your next turn?",
                             name="False North", feature_id=HEAVEN,
                             preferred=min(hostiles, key=lambda c: (_dist(engine, actor.position, c.position), c.entity_id), default=None))
    if north is None:
        return
    engine._apply_condition(actor, TEMP, HEAVEN, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"north": north.entity_id, "tokens": {k: 1 for k in KINDS},
                                  "label": f"False North: {north.display_name}; a temporary Approach, Orbit and Depart token"})


def _declare_chosen(engine: Any, actor: Any) -> None:
    """Chosen Bearings: an ally starting its turn in a Compass Domain may declare one."""
    old = next((c for c in actor.conditions.values() if c.condition_id == CHOSEN), None)
    if old is not None:
        _remove(engine, actor, old, "EXPIRED")
    owner = next((o for o in engine.state.actors.values() if o.active and o is not actor and o.team_id == actor.team_id
                  and _owns(engine, o, "heaven_has_no_fixed_north") and (d := _domain(engine, o)) is not None
                  and engine._footprint_intersects(actor, d.affected_cells)), None)
    if owner is None:
        return
    from . import needle

    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "CHOSEN_BEARING", actor.entity_id), actor, "choice:needle.compass.chosen",
                        list(KINDS), labels={"approach": f"Approach {owner.display_name}: Temporary Hit Points",
                                             "orbit": f"Orbit {owner.display_name}: +2 AC against Opportunity Attacks and Reaction attacks",
                                             "depart": f"Depart from {owner.display_name}: 10 more feet of movement this turn"},
                        preferred=["approach"], allow_decline=True, name="Chosen Bearing", feature_id=HEAVEN,
                        prompt=f"{actor.display_name} starts its turn in {owner.display_name}'s Compass Domain: declare a Chosen Bearing?")
    if not chosen:
        return
    engine._apply_condition(actor, CHOSEN, HEAVEN, owner.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"kind": chosen[0], "start": _xy(actor.position), "ref": _xy(owner.position), "moved": 0, "done": 0,
                                  "owner": owner.entity_id, "pb": int(_numbers(engine, owner).get("pb") or 2),
                                  "label": f"Chosen Bearing: {LABEL[chosen[0]]} relative to {owner.display_name}"})


def _chosen_benefit(engine: Any, mover: Any, data: dict[str, Any]) -> None:
    kind = data["kind"]
    owner_id = str(data.get("owner") or "")
    if kind == "approach":
        engine._grant_temp_hp(mover, 2 * int(data.get("pb") or 2), HEAVEN, owner_id)
    elif kind == "orbit":
        engine._apply_condition(mover, CHOSEN_ORBIT, HEAVEN, owner_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"label": "Chosen Bearing (Orbit): +2 AC against Opportunity Attacks and Reaction attacks"})
    else:
        mover.movement_remaining_ft += 10
        engine._append_event("MOVEMENT_GRANTED", HEAVEN, actor_id=mover.entity_id, payload={"distance_ft": 10})
    note(engine, HEAVEN, mover, f"{mover.display_name} completes its Chosen Bearing ({LABEL[kind]}).")


@effect("compass_turn_field")
def turn_the_whole_field(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor, subject = ctx.engine, ctx.actor, ctx.target
    actor.turn_flags["compass_turn_field"] = True
    if subject is None or not subject.active:
        return
    kind = str(row.get("kind") or "approach")
    before = len(engine.events)
    _te().block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis", "on_fail": [], "on_success": []})
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    failed = bool(rolled) and (rolled[-1].payload or {}).get("success") is False
    feet = 15 if failed else 5
    start_dist = _dist(engine, subject.position, actor.position)
    options = {cell: v for cell, v in st.routes(engine, subject, feet).items() if cell != subject.position and (
        (kind == "approach" and _dist(engine, cell, actor.position) < start_dist)
        or (kind == "depart" and _dist(engine, cell, actor.position) > start_dist)
        or (kind == "orbit" and abs(_dist(engine, cell, actor.position) - start_dist) <= 5))}
    if options:
        best = (min if kind == "approach" else max)(options, key=lambda c: (_dist(engine, c, actor.position), c.y, c.x)) if kind != "orbit" else \
            max(options, key=lambda c: (options[c][1], c.y, c.x))
        path = st.choose_route(engine, actor, options, ctx.intent, checkpoint="TURN_THE_WHOLE_FIELD",
                               prompt=f"Turn the Whole Field ({LABEL[kind]}): move {subject.display_name} up to {feet} feet.",
                               name="Turn the Whole Field", feature=HEAVEN, preferred=best, stay=False)
        if path is not None:
            from .rider_movement import forced_route

            forced_route(engine, subject, list(path), ctx.source, actor)
    if failed:
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
                                 "evidence": "it cannot take Reactions until the start of its next turn"}])


def bearing_without_name(engine: Any, actor: Any, spent: list[str], intent: Any, *, context: str,
                         target_name: str, target_id: str) -> list[str]:
    """Change one rider once in the current turn, retaining movement and paid tokens."""
    from ..turn_uses import current_turn_key
    turn_key = current_turn_key(engine)
    if (not spent or not _owns(engine, actor, "no_fixed_compass")
            or actor.turn_flags.get("bearing_without_name") == turn_key):
        return list(spent)
    from . import needle
    options = [f"{old}:{new}" for old in spent for new in KINDS if new != old]
    if context == "turn_compass":
        labels_by_kind = {
            "approach": f"Step into {target_name}'s attack line and take the hit instead; gain +2 AC against this attack",
            "orbit": f"Make this attack against {target_name} have Disadvantage",
            "depart": f"Move {target_name} up to 10 feet away; if still in reach, gain +2 AC against this attack",
        }
    else:
        labels_by_kind = {
            "approach": f"Pull {target_name} up to 10 feet toward you and mark it with Resonance until the end of your next turn",
            "orbit": f"Deny {target_name} Reactions and give its next attack Disadvantage before the end of its next turn",
            "depart": f"On a failed Strength or Wisdom save, push {target_name} up to 15 feet away",
        }
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BEARING_WITHOUT_NAME"), actor,
                        "choice:needle.compass.bearing_without_name", options,
                        labels={v: f"{labels_by_kind[v.split(':')[1]]} (paid {LABEL[v.split(':')[0]]} token)" for v in options},
                        preferred=[], allow_decline=True, default="decline", name="Bearing Without Name", feature_id=NO_FIXED,
                        target_id=target_id,
                        prompt=f"Change one effect against {target_name} this turn? The Bearing token and its cost stay the same; only the effect changes.")
    if not chosen:
        return list(spent)
    old, new = chosen[0].split(":")
    result = list(spent)
    result[result.index(old)] = new
    actor.turn_flags["bearing_without_name"] = turn_key
    effect = labels_by_kind[new]
    note(engine, NO_FIXED, actor, f"Bearing Without Name: paid with the {LABEL[old]} token, but instead: {effect[0].lower()}{effect[1:]}.")
    return result
