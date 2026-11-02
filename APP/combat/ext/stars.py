"""Stars sphere (rider lane C2, 2026-09-30: "i want everything we can automated").  Rules text: the owner's Sphere Compendium,
"Sphere of Stars" (authority/typed_mechanics/rules_text.json and the sphere's Core Stars Rules).

Shared helper ``aligned`` is used by d20_rewrite_rules for Star-Soul Guidance's
owner-qualified reroll bonus; this module owns Stars mark and Domain semantics.

Stellar Mark is the ordinary typed mark named "Stellar Mark" (typed_executor.mark_condition_id), or an ongoing condition carrying that
mark.  The sphere's own rule "A target bearing your Stellar Mark cannot benefit from ordinary Invisible against you" is the
``masked_conditions`` hook below, for every Stellar Mark (Starbolt, Stable Stellar Mark, Guiding Star, the Domains...).

Aligned (Core Stars Rules): beneath Open Sky, within 30 feet of your Star Anchor, holding your star map, inside a Stars Domain you
created, or "the target bears your Stellar Mark".  The table models the last two (``aligned``); Open Sky, Star Anchors and star maps
are not on the map, so an Aligned Benefit that needs them stays the GM's.

Owned rows: combat/rules/feature_blocks.d/riders_c2.json, block "stars", one ``kind`` per ability; every hook returns early for a
creature without the row or one of this module's conditions, so other characters and older saved fights are unchanged.

  starbolt              Aligned Benefit: +30 feet of range against a creature bearing your Stellar Mark (a sibling action,
                        "Starbolt (Aligned, marked target)", offered only against such a creature).
  falling_spark         Aligned Benefit: one creature bearing your Stellar Mark in the area has Disadvantage on the save (``save``).
  comet_spear           ``stars_no_half_cover`` around its attack: a creature bearing your Stellar Mark gets no Half Cover.
  guiding_star          one ally's attack roll against the Guiding Star's marked creature adds 1d4 (``attack_bonus``), once per round
                        per creature, one ally per Guiding Star.
  constellation_guard   seven stars: damage from a hostile creature puts one out; the +2 AC lasts while one burns (``ac``); an Aligned
                        start of turn (inside your Stars Domain) relights one.
  cold_star_mantle      the mantled creature adds your Proficiency Bonus to one Radiant, Force or Cold damage roll once per turn.
  seven_star_step       passing within 5 feet of a creature bearing your Stellar Mark: it makes a Charisma save or loses its Reactions
                        until the start of your next turn.
  stars_domain / world_beneath_the_constellations   an ally (or you) that hits a creature bearing your Stellar Mark inside the area
                        may step 5 feet without Opportunity Attacks, once per turn; enemies inside cannot benefit from ordinary
                        Invisible against you; World Beneath: an enemy inside teleports only after a Charisma save.
  star_shadow           Guiding Light: the Star Shadow's hit puts your Stellar Mark on the creature (the creature itself is in
                        combat/rules/summons.json).
  star_sovereign_incarnation  Starbolt deals 6d10 (``stars_starbolt_damage`` around Starbolt's damage row); a free 60-foot Starpath
                        Step once per turn (a sibling action).  Its Sovereign Constellation is typed data (a 20-foot aura).
  star_needle_aim       the next Starbolt or ranged weapon attack this turn: no Half Cover for a marked target, +1 to hit otherwise.
Constellation Prison and Star Name Seal: the creature they hold cannot benefit from ordinary Invisible against anyone.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .owned_effects import remove_conditions

BLOCK = "stars"
MARK = "Stellar Mark"
MANTLE = "condition:typed.stars_cold_mantle"
GUARD_STARS = "stars_round_guard_stars"
GUIDE_USED = "stars_round_guiding_die"
MANTLE_TURN = "stars_round_mantle"
DOMAIN_STEP = "stars_round_domain_step"
INVISIBLE = "condition:typed.invisible"
# Constellation Prison and Star Name Seal: "cannot benefit from ordinary Invisible" (against anyone), for as long as the effect holds.
NO_INVISIBLE = {"condition:typed.constellation_prison", "condition:typed.star_name_seal"}
STAR_TYPES = {"radiant", "force", "cold"}


def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


def bears_mark(creature: Any, owner_id: str) -> bool:
    """Whether ``creature`` bears ``owner_id``'s Stellar Mark (a placed mark or an ongoing effect carrying it)."""
    from ..typed_executor import mark_condition_id

    wanted = mark_condition_id(MARK, owner_id)
    return any(c.condition_id == wanted and c.source_actor_id == owner_id for c in creature.conditions.values())


def _turn(engine: Any) -> int:
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


def domains(engine: Any, owner: Any) -> list[Any]:
    """The owner's Stars Domain and World Beneath the Constellations areas now standing."""
    from .. import zones

    out = []
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        source = str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) or "") if action is not None else ""
        if zone.owner_id == owner.entity_id and source in ("tianxia.talent.stars.stars_domain", "tianxia.talent.stars.world_beneath_the_constellations"):
            out.append(zone)
    return out


def _inside(engine: Any, creature: Any, zone: Any) -> bool:
    return engine._footprint_intersects(creature, {(cell.x, cell.y) for cell in zone.affected_cells})


def aligned(engine: Any, actor: Any, target: Any = None, *, recipient: bool = False) -> bool:
    """Known alignment: your target's Stellar Mark or your Stars Domain.

    Existing attack benefits test the caster's Domain position. Recipient
    benefits (d20_rewrite_rules) explicitly test the helped creature's position.
    """
    if target is not None and bears_mark(target, actor.entity_id):
        return True
    creature = target if recipient and target is not None else actor
    return any(_inside(engine, creature, zone) for zone in domains(engine, actor))


# ------------------------------------------------------------------------------------------------ compile
ALIGNED_FEET = 30   # Starbolt's printed "Aligned Benefit: ... range increases by 30 feet"

@hook("compile_actions")
def star_choice_owners(info: dict[str, Any]) -> None:
    """Seven-Star Step's optional pass-by effect belongs to its manual user."""
    for passive in info.get("passives") or ():
        if passive.get("block") == BLOCK and passive.get("kind") == "seven_star_step":
            passive["choice_owner"] = True


@hook("compile_block")
def stars_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "keeps_compiling": True}]


@hook("compile_actions")
def aligned_starbolt(info: dict[str, Any]) -> list[Any] | None:
    """Starbolt's Aligned Benefit: a sibling with 30 more feet of range, offered only against a creature bearing your Stellar Mark.

    Star-Drawn Projectile's printed "increase range by 60 feet" is the same kind of benefit on the same attack, so the
    character that owns both gets the composed sibling too (both printed bonuses, 180 feet). Composition happens here
    rather than by suffixing the aligned sibling, because compile_actions hands every subscriber the same snapshot of the
    fighter's own actions (factory_compiler) and appends what they return afterwards: a subscriber never sees another's
    output.
    """
    import copy

    owned = set(info.get("owned_ids") or ())
    if "STARS_BASE_STARBOLT" not in owned:
        return None
    out = []
    for action in info.get("actions") or ():
        typed = (action.parameters or {}).get("typed") or {}
        if typed.get("source") != "STARS_BASE_STARBOLT" or action.range_ft is None or "#" in action.source_definition_id.split("STARS_BASE_STARBOLT")[-1]:
            continue
        parameters = copy.deepcopy(action.parameters)
        parameters["typed"] = {**parameters["typed"], "range_ft": int(action.range_ft) + ALIGNED_FEET}
        parameters.update(_aligned_marks(action, reach=int(action.range_ft)))
        out.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "#aligned",
                                             "display_name": f"{action.display_name} (Aligned: marked target, +30 ft)",
                                             "range_ft": int(action.range_ft) + ALIGNED_FEET, "parameters": parameters}))
        if DRAWN in owned:
            drawn = _drawn_range_clone(out[-1], DRAWN_FEET, suffix="#drawn_range",
                                       label=f"{action.display_name} (Aligned: marked target, +30 ft; Star-Drawn Projectile: "
                                             f"next ranged attack a further +60 ft; no extra cost)")
            drawn.parameters.update(_aligned_marks(action, reach=int(action.range_ft) + DRAWN_FEET))
            out.append(drawn)
    return out or None


def _aligned_marks(action: Any, *, reach: int) -> dict[str, Any]:
    """The metadata ``aligned_only`` reads: which printed Starbolt this sibling came from, and the range a marked target must
    be beyond for the sibling to be the right one to offer (the ordinary or the drawn sibling already covers closer)."""
    return {"stars_aligned_only": True, "stars_aligned_source_id": action.source_definition_id,
            "stars_aligned_min_reach_ft": int(reach)}


@hook("candidate_allowed")
def aligned_only(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    if not parameters.get("stars_aligned_only"):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    targets = [t for t in targets if t is not None]
    if not targets:
        return None
    base = engine.action_catalog.get(str(parameters.get("stars_aligned_source_id") or "").strip()
                                     or action.source_definition_id.removesuffix("#aligned"))
    reach = int(parameters.get("stars_aligned_min_reach_ft") or getattr(base, "range_ft", 0) or 0)
    # Offered for a marked (Aligned) target beyond the range the ordinary sibling already covers: nearer than that the
    # ordinary Starbolt (or its drawn +60 feet sibling) is the same attack.
    return all(aligned(engine, actor, t) and engine._distance_actor_to_actor(actor, t) > reach for t in targets)


# ------------------------------------------------------------------------------------------------ Stellar Mark and Invisible
@hook("masked_conditions")
def marked_not_invisible(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """"A target bearing your Stellar Mark ... cannot benefit from ordinary Invisible against you"; inside your Stars Domain or World
    Beneath the Constellations, no enemy can."""
    # The engine's square probe (senses.perceives_cell) is not a creature: an empty square bears no Stellar Mark,
    # stands in no Stars Domain and has no team, so it can never be the marked target or the attacker this rule is
    # about. Ask first, before any attribute of a full creature is read (MMX105/HUNT110: the live service logged
    # this hook on every fog square that projected an ordinary-Invisible creature).
    from ..senses import is_creature

    if not is_creature(attacker) or not is_creature(target):
        return None
    out: dict[str, set[str]] = {}
    for who, other in ((target, attacker), (attacker, target)):
        invisible = {c.instance_id for c in who.conditions.values() if c.condition_id == INVISIBLE}
        if not invisible:
            continue
        if bears_mark(who, other.entity_id) or any(c.condition_id in NO_INVISIBLE for c in who.conditions.values()) or \
                (who.team_id != other.team_id and any(_inside(engine, who, zone) for zone in domains(engine, other))):
            out.setdefault(who.entity_id, set()).update(invisible)
    return out or None


# ------------------------------------------------------------------------------------------------ Falling Spark, Comet Spear
@hook("save")
def spark_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Falling Spark, Aligned Benefit: "One creature bearing your Stellar Mark in the area has Disadvantage on the save"."""
    if ctx.typed.get("source") != "STARS_TAL_FALLING_SPARK" or row(ctx.engine, ctx.actor, "falling_spark") is None:
        return None
    selected = ctx.damage_cache.get('_stars_spark_target')
    # Pre-AUTO42 sealed lists start directly with the save. Preserve their
    # historical first-marked-recipient benefit without changing the catalogue
    # or asking a choice its saved action never declared.
    legacy = not any(e.get('type') == 'stars_spark_pick' for e in ctx.typed.get('effects') or [])
    if legacy and selected is None and bears_mark(subject, ctx.actor.entity_id):
        selected = subject.entity_id
    if selected != subject.entity_id or ctx.damage_cache.get("_stars_spark") or not bears_mark(subject, ctx.actor.entity_id):
        return None
    ctx.damage_cache["_stars_spark"] = subject.entity_id
    return {"modes": ["DISADVANTAGE"]}


NO_HALF_COVER = "condition:an_eui.break_guard.no_half_cover"  # the engine's own "cannot benefit from half cover" (gate2_engine)
PIERCED = "condition:typed.stars_pierced_cover"


@effect("stars_no_half_cover")
def no_half_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """Around one attack (``end`` false before, true after): a target bearing your Stellar Mark gets no Half Cover from it (Comet
    Spear); ``until`` names a longer printed deadline instead (Star-Piercing Line's failed save), with no ``end`` row."""
    engine, target = ctx.engine, ctx.target
    if target is None:
        return
    if eff.get("end"):
        for condition in list(target.conditions.values()):
            if condition.condition_id == PIERCED and condition.source_actor_id == ctx.actor.entity_id and condition.source_definition_id == ctx.source:
                engine._remove_condition(target, PIERCED, ctx.source)
                engine._remove_condition(target, NO_HALF_COVER, ctx.source)
        return
    if not target.active or (eff.get("if_marked") and not bears_mark(target, ctx.actor.entity_id)):
        return
    if any(c.condition_id == NO_HALF_COVER for c in target.conditions.values()):
        return
    from ..typed_executor import effect_expiry

    expires = effect_expiry(ctx, eff, target, condition=True) if eff.get("duration") else "END_OF_CURRENT_TURN"
    engine._apply_condition(target, NO_HALF_COVER, ctx.source, ctx.actor.entity_id, expires_on=expires,
                            data={"label": "Cannot benefit from Half Cover"})
    if not eff.get("duration"):
        engine._apply_condition(target, PIERCED, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Stellar line (no Half Cover for this attack)"})


# ------------------------------------------------------------------------------------------------ Guiding Star
@hook("technique_used")
def guide_target(ctx: Any) -> None:
    """Bind the harmless star to the selected creature, and expose its allies'
    optional shared-die decisions through the generic condition ownership seam.
    """
    if ctx.typed.get("source") != "tianxia.talent.stars.guiding_star" or ctx.target is None:
        return
    from .states import PREFIX, active

    engine, guide = ctx.engine, ctx.actor
    state = active(engine, guide, "guiding_star")
    if state is None or row(engine, guide, "guiding_star") is None:
        return
    engine._remove_condition(guide, state.condition_id, state.source_definition_id)
    engine._apply_condition(guide, state.condition_id, state.source_definition_id, guide.entity_id,
                            expires_on=state.expires_on, data={**state.data, "guide_target_id": ctx.target.entity_id,
                                "label": f"Guiding Star over {ctx.target.display_name}: one ally who sees it may add 1d4 to an attack against it until your next turn"})
    for ally in engine.state.actors.values():
        if ally.active and ally.team_id == guide.team_id and ally is not guide:
            engine._remove_condition(ally, PREFIX + "guiding_star_choice", ctx.source)
            engine._apply_condition(ally, PREFIX + "guiding_star_choice", ctx.source, guide.entity_id,
                                    expires_on=state.expires_on, data={"choice_owner": 1,
                                        "label": f"Guiding Star: you may use the shared +1d4 against {ctx.target.display_name} if you see its star, until {guide.display_name}'s next turn"})


@hook("attack_bonus")
def guiding_die(ctx: Any, actor: Any) -> int | None:
    """Guiding Star: "one ally who can see the guiding star may add 1d4 to one attack roll ... to strike the marked target. A creature
    can benefit from only one Guiding Star die per round" -- the first ally attack against it; one ally per Guiding Star."""
    from .states import PREFIX

    engine, target = ctx.engine, ctx.target
    if target is None:
        return None
    for guide in engine.state.actors.values():
        if guide is actor or not guide.active or guide.team_id != actor.team_id or row(engine, guide, "guiding_star") is None:
            continue
        state = next((c for c in guide.conditions.values() if c.condition_id == PREFIX + "guiding_star"), None)
        if state is None or state.data.get("guide_target_id") != target.entity_id or not bears_mark(target, guide.entity_id):
            continue
        from ..stealth import sees

        if not sees(engine, actor, target):
            continue
        if actor.turn_flags.get(GUIDE_USED) == int(engine.state.round_number) or guide.turn_flags.get(GUIDE_USED + "_given") == state.instance_id:
            continue
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        if not ask(engine, ctx.intent, checkpoint_id(engine, "Guiding Star", actor.entity_id, target.entity_id), actor,
                   "choice:needle.stars_guiding_die", ["add_die"], allow_decline=True, default="first",
                   labels={"add_die": "Add 1d4 to this attack roll (no action or resource cost)"}, name="Guiding Star",
                   target_id=target.entity_id, prompt_context=action_context(engine, actor, ctx.source, target),
                   prompt=f"Guiding Star: {actor.display_name}'s {ctx.action.display_name} targets {target.display_name}. Use the shared +1d4? "
                          f"Only one ally may use this star before {guide.display_name}'s next turn, and you may use one Guiding Star die per round."):
            continue
        from ..gate2_runtime_models import DiceSpec

        roll = engine.roller.roll(DiceSpec(count=1, sides=4, modifier=0), actor_id=actor.entity_id, reason=f"GUIDING_STAR:{state.source_definition_id}")
        engine._record_roll(roll)
        actor.turn_flags[GUIDE_USED] = int(engine.state.round_number)
        guide.turn_flags[GUIDE_USED + "_given"] = state.instance_id
        from . import note

        note(engine, state.source_definition_id, guide, f"Guiding Star: {actor.display_name} adds {roll.total} (1d4) to its attack roll "
             f"against {target.display_name}.", (actor, target))
        return int(roll.total)
    return None


# ------------------------------------------------------------------------------------------------ Constellation Guard
def _guard(engine: Any, actor: Any) -> Any:
    from .states import PREFIX

    return next((c for c in actor.conditions.values() if c.condition_id == PREFIX + "constellation_guard"), None)


def guard_stars(engine: Any, actor: Any) -> int:
    """The stars still burning: seven when the guard is raised (a flag keyed to the guard's instance)."""
    guard = _guard(engine, actor)
    if guard is None:
        return 0
    held, _, count = str(actor.turn_flags.get(GUARD_STARS) or "").rpartition(":")
    return int(count) if held == guard.instance_id and count.isdigit() else 7


@hook("ac")
def guard_ac(engine: Any, target: Any) -> int | None:
    """Constellation Guard's +2 AC, while at least one of its seven stars burns."""
    if row(engine, target, "constellation_guard") is None or _guard(engine, target) is None:
        return None
    return 2 if guard_stars(engine, target) > 0 else None


@hook("event")
def guard_star_out(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"One visible star extinguishes whenever you take damage from a hostile creature.\""""
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    source = engine.state.actors.get(kwargs.get("actor_id"))
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is None or source is None or source.team_id == holder.team_id or row(engine, holder, "constellation_guard") is None:
            continue
        guard = _guard(engine, holder)
        if guard is None:
            continue
        left = max(0, guard_stars(engine, holder) - 1)
        holder.turn_flags[GUARD_STARS] = f"{guard.instance_id}:{left}"


@hook("turn_start")
def guard_relight(engine: Any, actor: Any) -> None:
    """"At the start of each of your turns, restore one extinguished star if you are Aligned.\""""
    guard = _guard(engine, actor)
    if guard is None or row(engine, actor, "constellation_guard") is None or not aligned(engine, actor):
        return
    stars = guard_stars(engine, actor)
    if stars < 7:
        actor.turn_flags[GUARD_STARS] = f"{guard.instance_id}:{stars + 1}"


# ------------------------------------------------------------------------------------------------ Cold Star Mantle
@hook("condition_choice_owner")
def mantle_choice_owner(engine: Any, actor: Any, condition: Any) -> bool | None:
    """Old saved Mantles also belong to their bearer; no saved-data migration."""
    return True if condition.condition_id == MANTLE else None


@effect("stars_cold_mantle")
def cold_mantle(ctx: Any, eff: dict[str, Any]) -> None:
    """The mantled creature: its once-a-turn Proficiency Bonus on a Radiant, Force or Cold damage roll."""
    from ..typed_executor import effect_subjects, effect_expiry

    for subject in effect_subjects(ctx, eff, harmful=False):
        ctx.engine._remove_condition(subject, MANTLE, ctx.source)
        ctx.engine._apply_condition(subject, MANTLE, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, eff, subject, condition=True),
                                    data={"label": f"Cold Star Mantle: once per turn you may add {int(ctx.numbers.get('pb') or 2)} to Radiant, Force or Cold damage; "
                                                   "lasts up to 1 minute while the caster concentrates, with no extra cost for the bonus. "
                                                   "Weapon and technique damage share this allowance; choose after a hit. "
                                                   "Advantage on saves against being lost, disoriented or magically misdirected",
                                          "pb": int(ctx.numbers.get("pb") or 2), "choice_owner": 1})


def _mantle_bonus(ctx: Any, kinds: Any, target: Any = None) -> int | None:
    engine, actor = ctx.engine, ctx.actor
    mantle = next((c for c in actor.conditions.values() if c.condition_id == MANTLE), None)
    if mantle is None or actor.turn_flags.get(MANTLE_TURN) == _turn(engine):
        return None
    if not STAR_TYPES & {str(kind).lower() for kind in kinds or ()}:
        return None
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    target = target or ctx.target or actor
    bonus = int((mantle.data or {}).get("pb") or 0)
    if not ask(engine, ctx.intent, checkpoint_id(engine, "Cold Star Mantle", actor.entity_id, target.entity_id), actor,
               "choice:needle.stars_cold_mantle", ["add_bonus"], allow_decline=True, default="first",
               labels={"add_bonus": f"Add {bonus} damage to this roll (no action or resource cost)"},
               name="Cold Star Mantle", target_id=target.entity_id,
               prompt_context=action_context(engine, actor, ctx.source, target, action=ctx.action),
               prompt=f"Cold Star Mantle: {actor.display_name}'s {ctx.action.display_name} damages {target.display_name}. "
                      f"Add {bonus} to this damage roll? This uses the once-per-turn bonus, with no action or resource cost."):
        return None
    actor.turn_flags[MANTLE_TURN] = _turn(engine)
    return bonus or None


@hook("confirmed_hit_roll_bonus")
def mantle_attack(engine: Any, attacker: Any, target: Any, spec: dict[str, Any],
                  intent: Any, source: str) -> int | None:
    """Consent for the actual confirmed packet, using its resolved damage type."""
    from .attack_scope import current
    from ..gate2_runtime_models import DiceSpec, ActionDefinition, EconomyKind

    frame = current(engine)
    if (not any(c.condition_id == MANTLE for c in attacker.conditions.values())
            or not isinstance(spec.get('damage'), DiceSpec) or spec['damage'].count <= 0):
        return None
    if frame and frame['actor_id'] == attacker.entity_id and frame['source'] == source:
        ctx = frame['context']
    else:
        # Native attacks and independent reaction attacks have no typed frame.
        # Build only a transient decision context for this actual beneficiary.
        from ..typed_executor import Context
        from ..technique_interception import frame as declared_frame

        # A reaction's declared action can be transient and absent from the
        # catalog. Use the public activation frame, scoped to this actor/source,
        # so its native follow-up retains the actual reaction's readable name.
        action = (declared_frame(engine, attacker.entity_id, source).get('action')
                  or engine.action_catalog.get(source) or ActionDefinition(
            source_definition_id=source, display_name=spec.get('action_name') or 'Reaction attack',
            owner_id=attacker.entity_id, economy=EconomyKind.NONE,
            resolution_kind='ATTACK', target_kind='HOSTILE_ENTITY'))
        ctx = Context(engine, attacker, action, intent, {}, [target], target, {})
    return _mantle_bonus(ctx, [spec.get('damage_type')], target)


@hook('save')
def mantle_orientation_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Printed orientation defenses use actual consequences or explicit save provenance."""
    if not any(c.condition_id == MANTLE for c in subject.conditions.values()):
        return None
    categories = {'lost', 'disoriented', 'misdirected', 'magical_misdirection'}
    tags = {str(tag).lower().removeprefix('category:') for tag in named or ()}
    return {'modes': ['ADVANTAGE']} if tags & categories else None


@hook("damage_roll_bonus")
def mantle_damage_roll(ctx: Any, eff: dict[str, Any], kinds: Any = None) -> int | None:
    if eff is None or not any(c.condition_id == MANTLE for c in ctx.actor.conditions.values()):
        return None
    # A row can offer Cold or Fire; only the type actually selected qualifies.
    resolved = getattr(ctx.engine, '_typed_pending_damage_type', None)
    return _mantle_bonus(ctx, [resolved] if resolved else kinds or (eff or {}).get("damage_types") or ())


# ------------------------------------------------------------------------------------------------ Seven-Star Step
@hook("event")
def seven_star_pass(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Seven-Star Step: "If you pass within 5 feet of a creature bearing your Stellar Mark, you may end its Reactions until the start of
    your next turn unless it succeeds on a Charisma saving throw" -- the step this turn's Seven-Star Step allowed (its state)."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id"))
    if mover is None or payload.get("forced") or row(engine, mover, "seven_star_step") is None:
        return
    from .states import active

    if not active(engine, mover, "seven_star_step"):
        return
    from ..gate2_runtime_models import Position

    path = [Position(**cell) for cell in payload.get("path") or [] if isinstance(cell, dict)]
    done = set(str(mover.turn_flags.get("stars_seven_star_done") or "").split(",")) - {""}
    for other in list(engine.state.actors.values()):
        if not other.active or other.team_id == mover.team_id or other.entity_id in done or not bears_mark(other, mover.entity_id):
            continue
        if not any(engine._distance_actor_to_actor(mover, other) <= 5 or
                   any(engine.grid.distance_ft(cell, spot) <= 5 for spot in _cells(engine, other)) for cell in path):
            continue
        from .. import typed_executor as te
        from .states import context
        from .needle import numbers_of

        action = next((a for a in engine.action_catalog.values() if a.owner_id == mover.entity_id
                       and ((a.parameters or {}).get("typed") or {}).get("source") == "tianxia.talent.stars.seven_star_step"), None)
        if action is None:
            continue
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        intent = getattr(engine, "_active_intent", None)
        source = str(getattr(intent, "source_definition_id", "") or "")
        if not source and intent is not None:
            accepted = next((e for e in reversed(engine.events) if e.event_type == "MOVEMENT_COMMITTED"), None)
            source = accepted.source_definition_id if accepted else action.source_definition_id
        if not ask(engine, intent, checkpoint_id(engine, "Seven-Star Step", mover.entity_id, other.entity_id), mover,
                   "choice:needle.stars_seven_star", ["suppress"], allow_decline=True, default="first",
                   name="Seven-Star Step", target_id=other.entity_id,
                   labels={"suppress": "Charisma save or no Reactions until your next turn (no extra cost)"},
                   prompt_context=action_context(engine, mover, source, other),
                   prompt=f"Seven-Star Step: {mover.display_name} passes {other.display_name}, who bears your Stellar Mark. "
                          "Have it make a Charisma save or lose Reactions until the start of your next turn? No extra action or resource cost."):
            continue
        done.add(other.entity_id)
        mover.turn_flags["stars_seven_star_done"] = ",".join(sorted(done))
        ctx = te.Context(engine, mover, action, None, {**(action.parameters.get("typed") or {}), "effects": [],
                                                       "numbers": {**numbers_of(engine, mover), **((action.parameters.get("typed") or {}).get("numbers") or {})}},
                         [other], other, {})
        te.run_effects(ctx, [{"type": "save", "ability": "cha", "dc": "technique_save_dc", "applies_to": "target",
                              "on_fail": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                           "evidence": "Seven-Star Step: it cannot take Reactions until the start of your next turn"}],
                              "evidence": "Seven-Star Step: Charisma saving throw"}])


def _cells(engine: Any, actor: Any) -> list[Any]:
    from ..gate2_runtime_models import Position

    size = engine._footprint(actor).width_cells
    return [Position(x=actor.position.x + dx, y=actor.position.y + dy) for dx in range(size) for dy in range(size)]


# ------------------------------------------------------------------------------------------------ the Domains
@hook("after_hit")
def domain_step(ctx: Any, target: Any, kind: str) -> None:
    """Stars Domain / World Beneath the Constellations: "once per turn, after hitting a creature bearing your Stellar Mark, the attacker
    may move 5 feet without provoking Opportunity Attacks" -- you and your allies inside the area."""
    engine, attacker = ctx.engine, ctx.actor
    if not attacker.active or not target.active:
        return
    for owner in engine.state.actors.values():
        if owner.team_id != attacker.team_id or not bears_mark(target, owner.entity_id):
            continue
        if not any(_inside(engine, attacker, zone) for zone in domains(engine, owner)):
            continue
        if attacker.turn_flags.get(DOMAIN_STEP) == _turn(engine):
            return
        attacker.turn_flags[DOMAIN_STEP] = _turn(engine)
        from .. import typed_executor as te

        te.run_effects(te.Context(engine, attacker, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                       [{"type": "rider_step", "distance_ft": 5, "no_oa": True, "label": "Stars Domain"}])
        return


@hook("teleport_gate")
def world_beneath_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """World Beneath the Constellations: enemies inside "cannot teleport unless they succeed on a Charisma saving throw\"."""
    engine, actor = ctx.engine, ctx.actor
    for owner in engine.state.actors.values():
        if owner.team_id == actor.team_id or not owner.active:
            continue
        for zone in domains(engine, owner):
            action = engine.action_catalog.get(zone.source_definition_id)
            if (((action.parameters or {}).get("typed") or {}).get("source")) != "tianxia.talent.stars.world_beneath_the_constellations":
                continue
            if not _inside(engine, actor, zone):
                continue
            dc = int(((zone.trigger_profile.get("numbers") or {}).get("save_dc")) or 10)
            roll = engine._roll_save(actor, "CHA", dc, zone.source_definition_id)
            if roll is not None and int(roll.total) < dc:
                from . import note

                note(engine, zone.source_definition_id, owner, f"World Beneath the Constellations: {actor.display_name} fails its Charisma save "
                     f"({roll.total} against {dc}) and cannot teleport.", (actor,))
                return False
    return None


# ------------------------------------------------------------------------------------------------ Star Shadow
@hook("after_hit")
def star_shadow_mark(ctx: Any, target: Any, kind: str) -> None:
    """Guiding Light: "When the shadow hits a creature, apply Stellar Mark until the start of your next turn\"."""
    summon = getattr(ctx.actor, "summon", None) or {}
    if summon.get("source") != "tianxia.talent.stars.star_shadow" or not target.active:
        return
    owner = ctx.engine.state.actors.get(summon.get("owner"))
    if owner is None or not owner.active:
        return
    from .. import typed_executor as te

    te.run_effects(te.Context(ctx.engine, owner, ctx.action, ctx.intent, {**ctx.typed, "effects": []}, [target], target, {}),
                   [{"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                     "evidence": "Guiding Light: the Star Shadow's hit applies your Stellar Mark"}])


# ------------------------------------------------------------------------------------------------ Star-Sovereign Incarnation
SOVEREIGN = "condition:typed.state.star_sovereign_incarnation"
FREE_STARPATH = "stars_free_starpath"


@effect("stars_starbolt_damage")
def starbolt_damage(ctx: Any, eff: dict[str, Any]) -> None:
    """Starbolt's damage: its own row, or 6d10 of the same types while Star-Sovereign Incarnation is on ("Starbolt deals 6d10 Radiant,
    Force, or Cold damage")."""
    from .. import typed_executor as te

    rows = eff.get("effects") or []
    if any(c.condition_id == SOVEREIGN for c in ctx.actor.conditions.values()):
        rows = [{**row, "dice": {"count": 6, "sides": 10}, "dice_by_cl": None} if row.get("type") == "damage" else row for row in rows]
    te.run_effects(ctx, rows)


@hook("compile_actions")
def sovereign_starpath(info: dict[str, Any]) -> list[Any] | None:
    """"Starpath Step range becomes 60 feet; you may use Starpath Step once per turn without spending CP"."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or ())
    if "tianxia.talent.stars.star_sovereign_incarnation" not in owned or "tianxia.talent.stars.starpath_step" not in owned:
        return None
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.stars.sovereign_starpath", display_name="Starpath Step (Star-Sovereign: 60 feet, no cost)",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "movement", "applies_to": "self", "distance_ft": 60, "no_opportunity_attacks": True,
                                           "evidence": "Starpath Step: 60 feet of movement that does not provoke Opportunity Attacks"},
                                          {"type": "condition", "condition": "ignore_difficult", "applies_to": "self", "expires_on": "END_OF_CURRENT_TURN",
                                           "evidence": "This movement ignores nonmagical difficult terrain."},
                                          {"type": "stars_free_starpath"}],
                              "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": "tianxia.talent.stars.starpath_step"},
                    "expected_damage": 0, "requires_condition": SOVEREIGN, "blocked_by_turn_flag": FREE_STARPATH})]


@effect("stars_free_starpath")
def free_starpath(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.actor.turn_flags[FREE_STARPATH] = 1




# ------------------------------------------------------------------------------------------------ Star-Needle Aim
NEEDLE = "condition:typed.state.star_needle_aim"
NEEDLE_PLUS = "stars_needle_plus_one"
NEEDLE_COVER = "stars_needle_cover"


@hook("attack_sequence_start")
def needle_line(ctx: Any) -> None:
    """Star-Needle Aim: "Your next Starbolt or ranged weapon attack this turn ... If the target bears your Stellar Mark, the attack
    ignores Half Cover. If the target does not bear your Stellar Mark, the attack gains +1 to hit" -- used up by that attack."""
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    state = next((c for c in actor.conditions.values() if c.condition_id == NEEDLE), None)
    if state is None or target is None:
        return
    ranged = bool(ctx.typed.get("weapon")) and ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5
    if not ranged and ctx.typed.get("source") != "STARS_BASE_STARBOLT":
        return
    engine._remove_condition(actor, NEEDLE, state.source_definition_id)
    if bears_mark(target, actor.entity_id):
        if not any(c.condition_id == NO_HALF_COVER for c in target.conditions.values()):
            engine._apply_condition(target, NO_HALF_COVER, state.source_definition_id, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                    data={"label": "Cannot benefit from Half Cover (Star-Needle Aim)"})
            actor.turn_flags[NEEDLE_COVER] = f"{target.entity_id}|{state.source_definition_id}"
    else:
        actor.turn_flags[NEEDLE_PLUS] = 1


@hook("attack_bonus")
def needle_plus_one(ctx: Any, actor: Any) -> int | None:
    """The +1 to hit that Star-Needle Aim left for this attack (cleared when the attack's roll is done)."""
    return 1 if ctx.actor is actor and actor.turn_flags.get(NEEDLE_PLUS) else None


@hook("attack_roll_finished")
def needle_done(ctx: Any, target: Any, eff: Any, roll_id: str) -> None:
    ctx.actor.turn_flags.pop(NEEDLE_PLUS, None)
    held = str(ctx.actor.turn_flags.pop(NEEDLE_COVER, "") or "")
    if held:
        who, _, source = held.partition("|")
        creature = ctx.engine.state.actors.get(who)
        if creature is not None:
            ctx.engine._remove_condition(creature, NO_HALF_COVER, source)  # only for that one attack


@hook('flight')
def stellar_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    """Owned stellar incarnation and the actual Star Shadow supply native flight."""
    if not actor.active:
        return None
    if any(c.condition_id == SOVEREIGN for c in actor.conditions.values()):
        return {'fly_speed_ft': 80, 'flight_hover': 1}
    summon = actor.summon or {}
    if summon.get('source') == 'tianxia.talent.stars.star_shadow':
        owner = engine.state.actors.get(str(summon.get('owner') or ''))
        if owner is not None and owner.active:
            return {'fly_speed_ft': 30, 'flight_hover': 1}
    return None


@effect('stars_starbolt_mark')
def starbolt_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """Starbolt's perceived hit may mark once per turn, without another payment."""
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import run_effects
    owner, target = ctx.actor, ctx.target
    if target is None or row(ctx.engine, owner, 'starbolt') is None:
        return
    if owner.turn_flags.get('stars_round_starbolt_mark') == _turn(ctx.engine):
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'STARBOLT_MARK', owner.entity_id, target.entity_id),
                 owner, CHOICE + 'starbolt_mark', ['MARK'], allow_decline=True, preferred=['MARK'],
                 labels={'MARK': 'Apply your Stellar Mark until your next turn starts'}, target_id=target.entity_id,
                 prompt=f'Starbolt hits {target.display_name}: {owner.display_name} may mark this target until their next turn starts. '
                 'Stellar Mark lets your Stars techniques use their marked-target benefits: Starbolt gains 30 feet of range '
                 'and Comet Spear ignores Half Cover. The target cannot benefit from ordinary Invisibility against you. '
                 'Once per turn; no extra cost.')
    if picked:
        owner.turn_flags['stars_round_starbolt_mark'] = _turn(ctx.engine)
        run_effects(ctx, [{'type': 'mark', 'mark': MARK, 'applies_to': 'target', 'duration': {'kind': 'until_start_of_your_next_turn'}}])


@effect('stars_impact_terrain')
def impact_terrain(ctx: Any, eff: dict[str, Any]) -> None:
    """A qualifying falling star leaves evented, non-Concentration difficult ground."""
    from . import placed
    source = ctx.typed.get('source')
    if source not in {'STARS_TAL_FALLING_STAR', 'STARS_TAL_HEAVEN_FALLING_STAR'}:
        return
    aim = getattr(ctx.intent, 'destination', None)
    if aim is None or (source == 'STARS_TAL_FALLING_STAR' and not aligned(ctx.engine, ctx.actor)):
        return
    area = placed.area(ctx.engine, aim, 'sphere', 20) if source == 'STARS_TAL_FALLING_STAR' else [aim]
    cells = [aim, *(cell for cell in area if cell != aim)]
    placed.place(ctx.engine, ctx.actor, source=ctx.source, tag='stellar_impact', cells=cells,
                 name='Fallen-star rubble: difficult terrain', placed={'creator': ctx.actor.entity_id},
                 difficult='all', numbers=ctx.numbers, duration_rounds=None)


@hook('compile_actions')
def aligned_meteor(info: dict[str, Any]) -> list[Any] | None:
    """Meteor Shower's Aligned Benefit as a second button: the printed 20-foot radius instead of 15, offered only while you
    stand inside your own Stars Domain (the Aligned position this sphere can see). Its action, Cultivation Point cost and
    duration are the ordinary Meteor Shower ones."""
    import copy
    if 'STARS_TAL_METEOR_SHOWER' not in (info.get('owned_ids') or []):
        return None
    out = []
    for action in info.get('actions') or []:
        typed = (action.parameters or {}).get('typed') or {}
        if typed.get('source') != 'STARS_TAL_METEOR_SHOWER' or '#' in action.source_definition_id:
            continue
        params = copy.deepcopy(action.parameters)
        params['typed']['area'] = {**params['typed']['area'], 'size_ft': 20}
        if params['typed'].get('zone_spec'):
            params['typed']['zone_spec'] = {**params['typed']['zone_spec'], 'size_ft': 20}
        params['stars_aligned_meteor'] = 1
        out.append(action.model_copy(update={'source_definition_id': action.source_definition_id + '#aligned_area',
            'display_name': 'Meteor Shower (20-foot radius, only while you stand inside your own Stars Domain)',
            'radius_ft': 20, 'parameters': params}))
    return out or None


@hook('candidate_allowed')
def aligned_meteor_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, 'parameters', None) or {}).get('stars_aligned_meteor'):
        return aligned(engine, actor)
    return None


@hook('save')
def heaven_star_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx.typed.get('source') == 'STARS_TAL_HEAVEN_FALLING_STAR' and aligned(ctx.engine, ctx.actor, subject) and bears_mark(subject, ctx.actor.entity_id):
        return {'modes': ['DISADVANTAGE']}
    return None


# ------------------------------------------------------------------------------------------------ Star-Drawn Projectile
# "The next ranged weapon attack, thrown weapon attack, Starbolt, Comet Spear, or similar line attack you make this turn is drawn
# along a constellation path. Choose one benefit: ignore Half Cover; increase range by 60 feet; if the target bears your Stellar
# Mark and the attack hits, push it 10 feet; if the attack misses a marked target, you may reroll the attack once, but must use the
# new result."
#
# One effect asks which of the four printed benefits this Bonus Action buys and leaves that one standing for the single line attack
# that spends it, the same way Star-Needle Aim leaves one state for the next attack. The reroll benefit is not re-implemented here:
# it is the one shared d20 rewrite owned by d20_rewrite_attacks.py for every Sphere, so this effect asks the fighter that rewrite to
# take the roll through its own registered effect.
DRAWN = "tianxia.talent.stars.star_drawn_projectile"
WARD = "tianxia.talent.stars.starlight_ward"
DRAWN_FEET = 60    # Star-Drawn Projectile's printed "increase range by 60 feet"
DRAWN_COVER = "condition:typed.stars_drawn_cover"
DRAWN_RANGE = "condition:typed.stars_drawn_range"
DRAWN_PUSH = "condition:typed.stars_drawn_push"
DRAWN_STATES = {"COVER": DRAWN_COVER, "RANGE": DRAWN_RANGE, "PUSH": DRAWN_PUSH}
DRAWN_LABELS = {
    "COVER": "Your next ranged attack ignores Half Cover",
    "RANGE": "Your next ranged attack reaches 60 feet further",
    "PUSH": "Push a marked target 10 feet if your next ranged attack hits",
    "REROLL": "Reroll your next ranged attack once, if it misses a marked target (you must use the new result)",
}


@hook("damage_reduction_bonus")
def ward_aligned_bonus(engine: Any, owner: Any, protected: Any, attacker: Any, reaction_row: dict[str, Any]) -> int | None:
    """"Aligned Benefit: Add your Proficiency Bonus to the reduction." (Starlight Ward) -- the general damage-reduction query
    Ash Ward already uses; Aligned is the protected creature's position or its Stellar Mark, not the caster's."""
    if str((reaction_row or {}).get("feature_id") or "") != WARD or protected is None:
        return None
    if not aligned(engine, owner, protected, recipient=True):
        return None
    return max(1, int(getattr(owner, "proficiency_bonus", 0) or 2))


@effect("stars_drawn_state")
def drawn_state(ctx: Any, eff: dict[str, Any]) -> None:
    """One of Star-Drawn Projectile's chosen benefits: it stands until the next line attack this turn spends it. The printed
    "Choose one benefit" is the table's own four-action menu, so the row arrives here already chosen."""
    from ..typed_executor import effect_expiry

    chosen = str(eff.get("state") or "").upper()
    if chosen not in DRAWN_STATES:
        return
    owner = ctx.actor
    for condition in list(owner.conditions.values()):   # one chosen benefit at a time
        if condition.condition_id in DRAWN_STATES.values():
            ctx.engine._remove_condition(owner, condition.condition_id, condition.source_definition_id)
    ctx.engine._apply_condition(owner, DRAWN_STATES[chosen], ctx.source, owner.entity_id,
                                expires_on=effect_expiry(ctx, eff, owner, condition=True) or "END_OF_CURRENT_TURN",
                                data={"label": f"Star-Drawn Projectile: {DRAWN_LABELS[chosen]}. "
                                               "It lasts until the end of your turn and costs no more Cultivation Points."})


def _drawn_line_attack(ctx: Any) -> bool:
    """The printed "ranged weapon attack, thrown weapon attack, Starbolt, Comet Spear, or similar line attack": any attack that
    carries a ranged delivery in its typed row, rather than a melee weapon's action reach."""
    reach = ctx.typed.get("range_ft")
    return reach is not None and int(reach or 0) > 0


_DRAWN_RECEIPT = "_stars_drawn_benefits"


def _ordinary_drawn_range(ctx: Any) -> None:
    """Restore this resolution's ordinary normal/long ranges after its one boosted strike."""
    original = (ctx.action.parameters or {}).get("stars_drawn_original_range")
    if not original:
        return
    ctx.action = ctx.action.model_copy(update={"range_ft": original["action"]})
    ctx.typed.update(range_ft=original["normal"], long_range_ft=original["long"])


def _pending(ctx: Any) -> dict[str, Any] | None:
    """The chosen benefits still waiting for the creature this attack actually strikes, or None."""
    armed = ctx.damage_cache.get(_DRAWN_RECEIPT)
    return armed if isinstance(armed, dict) and armed.get("source") == ctx.source else None


def _release_drawn_cover(ctx: Any, armed: dict[str, Any]) -> None:
    """Half Cover is ignored for one attack only, so the exception leaves with it.

    This is the scope's own cleanup as well as the roll's, because an attacked reaction may negate the attack or move the
    defender out of reach before any roll exists. Only this attack's own instance is removed; a cover exception another
    caster applied, or one standing before the attack, is preserved.
    """
    cover = armed.get("cover") or {}
    who, source = cover.get("target"), cover.get("source")
    cover["target"] = None
    creature = ctx.engine.state.actors.get(str(who or ""))
    if creature is not None:
        remove_conditions(ctx.engine, creature, str(source), ctx.actor.entity_id, NO_HALF_COVER, reason="ONE_ATTACK")


@hook("effect_resolution_scope")
def drawn_attack_scope(ctx: Any, eff: dict[str, Any]) -> Any:
    """The chosen benefits belong to this attack block, including misses, cancellations and nested attacks.

    Only local scratch is used; no pending benefit is written into a saved fight. The Half Cover exception is released on
    the way out, so an attack cancelled before its roll cannot leave cover suppressed for later attacks.
    A later attack effect in the same action retains its ordinary ranges.
    """
    from contextlib import contextmanager
    if eff.get("type") != "attack" or not _drawn_line_attack(ctx):
        return None
    if not any(c.condition_id in DRAWN_STATES.values() for c in ctx.actor.conditions.values()) and not (
            (ctx.action.parameters or {}).get("stars_drawn_range") or ctx.damage_cache.get(_DRAWN_RECEIPT)):
        return None

    @contextmanager
    def scope():
        previous = ctx.damage_cache.pop(_DRAWN_RECEIPT, None)
        old_action, old_typed = ctx.action, ctx.typed
        ctx.typed = dict(ctx.typed)
        if (ctx.action.parameters or {}).get("stars_drawn_range") and not any(
                c.condition_id == DRAWN_RANGE for c in ctx.actor.conditions.values()):
            _ordinary_drawn_range(ctx)
        # Ignore receipts left by the older implementation; they were not attack-bound.
        ctx.actor.turn_flags.pop("stars_drawn_push_armed", None)
        ctx.actor.turn_flags.pop("stars_drawn_cover_fired", None)
        try:
            yield
        finally:
            armed = ctx.damage_cache.pop(_DRAWN_RECEIPT, None)
            if isinstance(armed, dict) and armed.get("cover"):
                _release_drawn_cover(ctx, armed)
            if previous is not None:
                ctx.damage_cache[_DRAWN_RECEIPT] = previous
            ctx.action, ctx.typed = old_action, old_typed
    return scope()


@hook("attack_sequence_start")
def drawn_benefit_spent(ctx: Any) -> None:
    """The chosen benefit belongs to the next line attack this turn: the 60 extra feet are the variant this state admits, and
    Half Cover and the marked-target push are recorded for the creature that attack actually strikes (see
    ``drawn_benefit_bound``), not for the one the action was aimed at before any redirection."""
    engine, actor = ctx.engine, ctx.actor
    if ctx.target is None or not _drawn_line_attack(ctx):
        return
    held = {condition.condition_id: condition for condition in actor.conditions.values() if condition.condition_id in DRAWN_STATES.values()}
    if not held:
        return
    for condition in held.values():
        engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)
    cover, push = held.get(DRAWN_COVER), held.get(DRAWN_PUSH)
    if cover is None and push is None:
        return
    ctx.damage_cache[_DRAWN_RECEIPT] = {
        "source": ctx.source,
        "cover": {"source": cover.source_definition_id, "target": None} if cover is not None else None,
        "push": {"source": push.source_definition_id, "target": None} if push is not None else None}


@hook("attack_mode")
def drawn_benefit_bound(ctx: Any, target: Any) -> None:
    """Bind the chosen benefits to the creature this attack really strikes.

    ``attack_mode`` is the earliest general seam that already carries the attack's actual recipient, after any
    redirection (an attacked reaction that becomes its target) and before the roll and the defence it is measured
    against. Returning None leaves the roll and every other subscriber exactly as they were.
    """
    armed = _pending(ctx)
    if armed is None or target is None or not target.active:
        return
    if armed.get("bound"):
        # A pre-roll cancellation skips attack_roll_finished/after_miss. A later
        # strike in this block must not inherit that cancelled strike's benefit.
        _release_drawn_cover(ctx, armed)
        ctx.damage_cache.pop(_DRAWN_RECEIPT, None)
        return
    armed["bound"] = True
    actor = ctx.actor
    cover = armed.get("cover") or {}
    if cover.get("source") and cover.get("target") is None and not any(
            c.condition_id == NO_HALF_COVER for c in target.conditions.values()):
        ctx.engine._apply_condition(target, NO_HALF_COVER, cover["source"], actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                    data={"label": "Cannot benefit from Half Cover (Star-Drawn Projectile)"})
        cover["target"] = target.entity_id
    push = armed.get("push") or {}
    if push.get("source") and push.get("target") is None:
        push["target"] = target.entity_id if bears_mark(target, actor.entity_id) else False


@hook("attack_roll_finished")
def drawn_cover_done(ctx: Any, target: Any, eff: Any, roll_id: str) -> None:
    armed = _pending(ctx)
    if armed is not None and armed.get("cover"):
        _release_drawn_cover(ctx, armed)  # only for that one attack


@hook("after_hit")
def drawn_push(ctx: Any, target: Any, kind: str) -> None:
    """The chosen push: "if the target bears your Stellar Mark and the attack hits, push it 10 feet"."""
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    armed = _pending(ctx)
    if armed is None:
        return
    ctx.damage_cache.pop(_DRAWN_RECEIPT, None)
    push = armed.get("push") or {}
    if push.get("target") != target.entity_id or not target.active or not bears_mark(target, actor.entity_id):
        return
    te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                   [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
                     "evidence": "Star-Drawn Projectile: the attack hit a creature bearing your Stellar Mark, so it is pushed 10 feet"}])


@hook("after_miss")
def drawn_push_missed(ctx: Any, target: Any) -> None:
    if _pending(ctx) is not None:
        ctx.damage_cache.pop(_DRAWN_RECEIPT, None)


@hook("attack_resolved")
def drawn_range_finished(ctx: Any, target: Any, hit: bool, eff: dict[str, Any]) -> None:
    _ordinary_drawn_range(ctx)


def _drawn_range_clone(action: Any, feet: int, *, suffix: str, label: str) -> Any:
    """``action`` with its own normal, long and action range ``feet`` further, admitted only while the chosen benefit stands.

    The ordinary ranges are remembered so the one boosted strike cannot leave this action's later strikes extended, and the
    weapon's own normal/long distinction is kept. Shared by Star-Drawn Projectile's own siblings and by the aligned Starbolt
    sibling it composes with.
    """
    import copy

    parameters = copy.deepcopy(action.parameters)
    reach = int(action.range_ft or 0)
    original = {"action": reach, "normal": int(parameters["typed"]["range_ft"]), "long": parameters["typed"].get("long_range_ft")}
    parameters["typed"]["range_ft"] = original["normal"] + feet
    if original["long"] is not None:
        parameters["typed"]["long_range_ft"] = int(original["long"]) + feet
    for attack in parameters["typed"].get("effects") or []:
        if isinstance(attack, dict) and attack.get("type") == "attack":
            attack["later_reach_ft"] = min(int(attack.get("later_reach_ft") or reach), reach)
    parameters["stars_drawn_original_range"] = original
    if parameters.get("requires_condition"):
        parameters["stars_drawn_requires_condition"] = parameters["requires_condition"]
    parameters["requires_condition"] = DRAWN_RANGE
    parameters["stars_drawn_range"] = 1
    return action.model_copy(update={"source_definition_id": action.source_definition_id + suffix,
                                     "display_name": label, "range_ft": reach + feet, "parameters": parameters})


@hook("compile_actions")
def drawn_range(info: dict[str, Any]) -> list[Any] | None:
    """The chosen "increase range by 60 feet": a 60-foot-longer variant of each of your own ranged attacks, admitted only while
    that benefit stands, so it is offered and spent exactly like the printed one."""
    if DRAWN not in (info.get("owned_ids") or ()):
        return None
    out = []
    for action in info.get("actions") or ():
        typed = (action.parameters or {}).get("typed") or {}
        reach = action.range_ft
        if (reach is None or typed.get("range_ft") is None or int(typed.get("range_ft") or 0) <= 0
                or (action.parameters or {}).get("stars_drawn_range") or action.source_definition_id.endswith("#drawn_range")):
            continue
        if not any(isinstance(row, dict) and row.get("type") == "attack" for row in typed.get("effects") or []):
            continue
        out.append(_drawn_range_clone(action, DRAWN_FEET, suffix="#drawn_range",
                                      label=f"{action.display_name} (Star-Drawn Projectile: next ranged or thrown attack "
                                            f"+60 ft; no extra cost)"))
    return out or None


@hook("candidate_allowed")
def drawn_range_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The extra 60 feet are this one chosen benefit, not a standing reach."""
    if (getattr(action, "parameters", None) or {}).get("stars_drawn_range"):
        required = action.parameters.get("stars_drawn_requires_condition")
        if required and not engine._has_condition(actor, required):
            return False
        return any(c.condition_id == DRAWN_RANGE for c in actor.conditions.values())
    return None


@effect('stars_spark_pick')
def spark_pick(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id
    if row(ctx.engine, ctx.actor, 'falling_spark') is None:
        return
    from ..typed_executor import save_subjects
    save = next((e for e in ctx.typed.get('effects') or () if e.get('type') == 'save'), {})
    subjects = [a for a in save_subjects(ctx, save) if a.active and bears_mark(a, ctx.actor.entity_id)]
    if not subjects:
        return
    labels = {a.entity_id: f'{a.display_name}: Disadvantage on the Falling Spark save' for a in subjects}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'FALLING_SPARK', ctx.actor.entity_id),
                 ctx.actor, CHOICE + 'falling_spark', list(labels), labels=labels, preferred=[subjects[0].entity_id],
                 prompt=f'Falling Spark: {ctx.actor.display_name} chooses one creature bearing their Stellar Mark in this area to save with Disadvantage. No extra cost.')
    ctx.damage_cache['_stars_spark_target'] = (picked or [subjects[0].entity_id])[0]
