"""Radiance's revealing light, Domain judgment and saves; shared form receipts for radiance_states.
Rules text: the owner's Sphere Compendium, "Radiance" (authority/typed_mechanics/rules_text.json). Dawnmark itself and Dawnmark
Scripture are combat/ext/radiance_dawnmark.py.

Unclean classification and timed-halo combat effects use creature_kinds and radiance_states.

What sees through what (the ``masked_conditions`` hook: a creature's Invisible / Hidden benefit that does not count in one attack;
the ``darkness_lifted`` hook, combat/zones.py _blocks: an area of darkness that does not hide one creature from another):
  Revealing Light      "Inside the aura: ordinary darkness is suppressed; ordinary Invisible provides no benefit ...; a creature bearing
                        your Dawnmark cannot benefit from ordinary visual concealment."
  Court of Unshadowed Dawn  you and allies inside: "ordinary Darkness and Dim Light do not impose penalties on sight"; enemies inside:
                        "ordinary Invisible provides no benefit; ordinary visual concealment cannot be used to Hide from creatures inside".
  World of Revealed Morning  allies inside: "the ability to ignore ordinary Darkness and ordinary visual concealment"; hostile creatures
                        inside: "ordinary Invisible fails ... ordinary Darkness disappears".
  First Dawn Before Falsehood  inside the Emanation "ordinary Invisible ... ordinary Darkness and non-Legendary magical Darkness" are
                        suppressed; "shadow travel that relies on ordinary or non-Legendary shadows" too (the ``teleport_gate`` hook:
                        a Shadow-sphere teleport into or out of it fails).
  Heavenly Radiance    "suppress non-Legendary magical Darkness ... ordinary invisibility ... inside your Bright Light" (120 feet).
  Expose False Form    "When you apply Dawnmark to a creature, you may pay 1 CP. Until the Dawnmark ends: the target cannot benefit from
                        ordinary Invisible; ... attacks against the target ignore ordinary visual concealment" -- paid (when 1 CP is
                        there) only when the creature is Invisible or Hidden as the mark lands, when paying changes something.
  Sun-White Judgment Spear  "The attack ignores Half Cover, Three-Quarters Cover, ordinary Darkness, ordinary visual concealment": its
                        typed rows put the engine's own no-cover condition and a marker on the target around its one attack roll
                        (``radiance_piercing``).
No Darkness on this table is Legendary, and none of these areas is dim: Dim Light and illusions are not modelled.

Saves (the ``after_save`` hook; typed saving throws, whose failure rows name the conditions they are against):
  Court                "once per round when an ally succeeds on a saving throw against Charmed, Frightened, possession, or corruption,
                        that ally gains Temporary HP equal to your Proficiency Bonus" (inside the Domain).
  Halo of the Merciful Sovereign  "when the target succeeds on a save against Charmed, Frightened, possession, or corruption, one hostile
                        creature within 10 feet of the target becomes Dawnmarked until the start of your next turn" (the nearest).
  Mirror of Clean Dawn "If the saving throw succeeds, the creature that created the triggering effect becomes Dawnmarked until the start
                        of your next turn if it is within 60 feet and not behind Total Cover."
Also: Court's "ordinary Blinded effects caused by light or darkness are suppressed at the start of the ally's turn" (a Blinded from a
Radiance, Dark or Shadow ability ends then); Crown of the Unblinking Sun's "once per turn, when you apply Dawnmark, you may extend it to
one additional hostile creature within 10 feet of the original target" (the nearest unmarked one); Halo's "you may maintain only one
Halo"; Heavenly Radiance's Radiance Strike, Solar Aura and Dawn Wave; Heaven-Opening Judgment's "one ordinary Radiant Resistance";
Gentle Dawn's and Purifying Radiance's cleansing rows (``radiance_repeat_save``, ``radiance_suppress``, ``radiance_cure_disease``).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

P = "tianxia.talent.radiance."
STRIKE = "RADIANCE_BASE_STRIKE"
SPEAR = "RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR"
JUDGMENT = "RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT"
REVEALING, COURT, WORLD, FIRST_DAWN = P + "revealing_light", P + "court_of_unshadowed_dawn", P + "world_of_revealed_morning", \
    P + "first_dawn_before_falsehood"
SEARING, SOLAR = P + "searing_halo", P + "solar_radiance_form"
HEAVENLY, CROWN, EXPOSE, HALO, MIRROR, GENTLE = P + "heavenly_radiance", P + "crown_of_the_unblinking_sun", P + "expose_false_form", \
    P + "halo_of_the_merciful_sovereign", P + "mirror_of_clean_dawn", P + "gentle_dawn"
MARK = "Dawnmark"
PIERCING = "condition:typed.radiance_piercing"
NO_HALF_COVER = "condition:an_eui.break_guard.no_half_cover"  # the engine's own "no cover" condition (gate2_engine)
SUPPRESSED = "condition:typed.radiance_suppressed"
EXPOSED_CHECK = "condition:typed.check_against"  # the engine's scoped check-penalty condition (combat/ext/scoped_checks.py)
LEGACY_EXPOSED_CHECK = "condition:typed.radiance_exposed_check"
CREATURE_CHECKS = {"tianxia.talent.radiance.radiant_exorcism_palm",
                   "tianxia.talent.radiance.heaven_reading_dawnbeam"}
LIGHT_OR_DARK = ("tianxia.sphere.radiance", "tianxia.sphere.dark", "tianxia.sphere.shadow", "tianxia.sphere.light")
SAVES_AGAINST = {"charmed", "frightened"}  # possession and corruption are not conditions on this table


@hook("compile_action")
def creature_check_targets(action: Any, info: dict[str, Any]) -> Any:
    """Palm touches one creature; Dawnbeam can read one creature, including an ally.

    A failure's mark must not make the diagnosis hostile-only; manual Palm must
    not become ally-only merely because its unresolved effect is a GM rider.
    Object/effect targets still require GM adjudication.
    """
    source = str(((action.parameters or {}).get("typed") or {}).get("source") or "").split("#")[0]
    if source in CREATURE_CHECKS and source in info["owned_ids"]:
        return action.model_copy(update={"target_kind": "ANY_CREATURE"})
    return None


# ------------------------------------------------------------------------------------------------ helpers
def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def _holds(actor: Any, feature: str) -> bool:
    """The creature is under its own ``feature`` now (a condition, a modifier or the Concentration it started)."""
    return any(feature in str(c.source_definition_id) and c.source_actor_id == actor.entity_id for c in actor.conditions.values()) or \
        any(feature in str(m.source_definition_id) and m.source_actor_id == actor.entity_id for m in actor.modifiers.values()) or \
        (actor.concentration is not None and feature in str(actor.concentration.source_definition_id))


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(feature in str(action_id) for action_id in (*actor.action_ids, *actor.passive_ids, *actor.reaction_ids)) or \
        any(str(row.get("feature_id") or "") == feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _action(engine: Any, actor: Any, feature: str) -> Any | None:
    return engine.action_catalog.get(next((a for a in actor.action_ids if feature in a), ""))


def _areas(engine: Any, feature: str) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.active and feature in str(zone.source_definition_id)]


def _inside(engine: Any, creature: Any, zone: Any) -> bool:
    from .. import zones

    return creature is not None and creature.active and zones._inside(engine, creature, zone)


def _hostile_to(engine: Any, zone: Any, creature: Any) -> bool:
    owner = engine.state.actors.get(zone.owner_id)
    return owner is not None and owner.team_id != creature.team_id


def _in(engine: Any, creature: Any, feature: str, *, side: str | None = None) -> bool:
    """Inside one of ``feature``'s areas (side: "hostile" / "ally" to its owner, or either)."""
    for zone in _areas(engine, feature):
        if _inside(engine, creature, zone) and (side is None or _hostile_to(engine, zone, creature) == (side == "hostile")):
            return True
    return False


def _bright(engine: Any, creature: Any) -> bool:
    """Whether an active Heavenly Radiance owner covers the creature with its own bright radius."""
    from .. import lighting

    target_cells = engine._actor_cells(creature)
    if not target_cells:
        return False
    width, height = int(engine.grid.width), int(engine.grid.height)
    square = lighting._square(engine)
    for owner in engine.state.actors.values():
        if not owner.active or not _holds(owner, HEAVENLY):
            continue
        origins = frozenset(engine._actor_cells(owner))
        if not origins:
            continue
        # Resolve this owner's actual emitter independently: total field brightness may come
        # from an unrelated torch, and radius alone incorrectly shines through opaque walls.
        # The emitter is the printed light of Heavenly Radiance itself (combat/rules/light_sources.json, emitted
        # from the lasting state by combat/ext/printed_light.py), never the field's un-attributed brightness.
        source = next((row for row in lighting.sources(engine)
                       if row.entity_id == f"printed:{HEAVENLY}:{owner.entity_id}"), None)
        if source is None:
            continue
        cells = bytearray(width * height)
        lighting._emit(engine, source, lighting.DARK, square, cells, lighting._Rays(engine))
        if any(0 <= x < width and 0 <= y < height and cells[y * width + x] == lighting.BRIGHT
               for x, y in target_cells):
            return True
    return False


def _invisible(creature: Any) -> set[str]:
    return {iid for iid, c in creature.conditions.items() if c.condition_id.endswith(".invisible")}


def _hidden(creature: Any) -> set[str]:
    return {iid for iid, c in creature.conditions.items() if c.condition_id.endswith(".hidden")}


def _dawnmarked_by(creature: Any, owner_id: str) -> bool:
    return any(c.condition_id == _mark_id(owner_id) for c in creature.conditions.values())


def _pierced(engine: Any, attacker: Any, target: Any) -> bool:
    return any(c.condition_id == PIERCING and c.source_actor_id == attacker.entity_id for c in target.conditions.values())


def _exposed(engine: Any, creature: Any) -> bool:
    for condition in creature.conditions.values():
        owner = engine.state.actors.get(condition.source_actor_id or "")
        if owner is not None and condition.condition_id == _mark_id(owner.entity_id) and \
                owner.turn_flags.get(f"_round_radiance_expose:{creature.entity_id}") == condition.instance_id:
            return True
    return False


def _context(engine: Any, owner: Any, action: Any, subject: Any, typed: dict[str, Any] | None = None) -> Any:
    from ..typed_executor import Context

    typed = typed if typed is not None else dict(((action.parameters or {}).get("typed") or {}) if action is not None else {})
    from .rider_choices import intent_for
    return Context(engine, owner, action, intent_for(engine), typed, [subject], subject, {})


def _dawnmark(engine: Any, owner: Any, subject: Any, feature: str, kind: str) -> None:
    """Put the owner's Dawnmark on ``subject`` (typed_executor.block_mark, with the owner's own ability as its source)."""
    from ..typed_executor import run_effects

    action = _action(engine, owner, feature) or next((engine.action_catalog[a] for a in owner.action_ids if a in engine.action_catalog), None)
    if action is None or not subject.active:
        return
    run_effects(_context(engine, owner, action, subject), [{"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": kind}}])


def _source_sphere(engine: Any, source: str) -> str:
    action = engine.action_catalog.get(str(source or ""))
    return str((((action.parameters or {}).get("typed") or {}).get("sphere")) if action is not None else "")


@hook("compile_block")
def radiance_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "radiance", "kind": spec.get("kind"),
             **({"expose_checks": True} if spec.get("expose_checks") else {})}] if block == "radiance" else None


# ------------------------------------------------------------------------------------------------ what can be seen
@hook("masked_conditions")
def revealed(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for who, other in ((attacker, target), (target, attacker)):
        if who is None or other is None:
            continue
        invisible, hidden = _invisible(who), _hidden(who)
        if not invisible and not hidden:
            continue
        masked: set[str] = set()
        for zone in _areas(engine, REVEALING):
            if _inside(engine, who, zone):
                masked |= invisible
                if _dawnmarked_by(who, zone.owner_id):
                    masked |= hidden
        for zone in _areas(engine, COURT):
            if _inside(engine, who, zone) and _hostile_to(engine, zone, who):
                masked |= invisible
                if _inside(engine, other, zone):
                    masked |= hidden
        for zone in _areas(engine, WORLD):
            if _inside(engine, who, zone) and _hostile_to(engine, zone, who):
                masked |= invisible
            if _inside(engine, other, zone) and not _hostile_to(engine, zone, other):
                masked |= hidden
        if _in(engine, who, FIRST_DAWN) or _bright(engine, who):
            masked |= invisible
        if _exposed(engine, who):
            masked |= invisible | hidden
        if who is target and _pierced(engine, attacker, target):
            masked |= hidden
        if masked:
            out.setdefault(who.entity_id, set()).update(masked)
    return out or None


@hook("darkness_lifted")
def dawnlight(engine: Any, zone: Any, viewer: Any, seen: Any) -> bool | None:
    """An area of darkness that does not hide ``seen`` from ``viewer``: the Spear's target from its attacker; a viewer that is the
    Court's or the World's owner or ally inside it; or every one of the two that stands in the darkness also stands where Radiance
    suppresses it (Revealing Light, First Dawn, the World, Heavenly Radiance's Bright Light)."""
    from .darkness_scope import scope
    kind = scope(engine, zone)
    if kind == "superior":
        return None  # a contest is a GM/lock-round ruling, never automatic suppression
    if kind == "ordinary" and _pierced(engine, viewer, seen):
        return True
    if kind == "ordinary" and (_in(engine, viewer, COURT, side="ally") or _in(engine, viewer, WORLD, side="ally")):
        return True
    from .. import zones

    dark = [creature for creature in (viewer, seen) if zones._inside(engine, creature, zone)]
    lit = lambda creature: (_in(engine, creature, FIRST_DAWN) or _bright(engine, creature)
                            or kind == "ordinary" and (_in(engine, creature, REVEALING) or _in(engine, creature, WORLD)))
    return True if dark and all(lit(creature) for creature in dark) else None


@hook("teleport_gate")
def no_shadow_road(ctx: Any, start: Any, destination: Any) -> bool | None:
    """First Dawn Before Falsehood suppresses "shadow travel that relies on ordinary or non-Legendary shadows" inside it: a Shadow-sphere
    teleport that starts or ends there fails."""
    engine = ctx.engine
    if str((ctx.typed or {}).get("sphere") or "") != "tianxia.sphere.shadow":
        return None
    for zone in _areas(engine, FIRST_DAWN):
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        if (start.x, start.y) in cells or (destination.x, destination.y) in cells:
            note(engine, f"passive:{FIRST_DAWN}", engine.state.actors.get(zone.owner_id) or ctx.actor,
                 f"First Dawn Before Falsehood: the shadow road fails ({ctx.actor.display_name} stays where it is).", (ctx.actor.entity_id,))
            return False
    return None


@effect("radiance_piercing")
def piercing(ctx: Any, eff: dict[str, Any]) -> None:
    """Sun-White Judgment Spear, around its one attack roll: ``end`` false puts the engine's no-cover condition (unless the target
    already has one) and a marker on the target; ``end`` true takes off what it put there."""
    target, engine = ctx.target, ctx.engine
    if target is None:
        return
    if eff.get("end"):
        from .rider_support import remove_instance
        for condition in list(target.conditions.values()):
            if condition.condition_id == PIERCING and condition.source_actor_id == ctx.actor.entity_id:
                remove_instance(engine, target, condition.instance_id, ctx.source)
                if (condition.data or {}).get("cover"):
                    for cover in list(target.conditions.values()):
                        if cover.condition_id == NO_HALF_COVER and cover.source_actor_id == ctx.actor.entity_id and cover.source_definition_id == ctx.source:
                            remove_instance(engine, target, cover.instance_id, ctx.source)
        return
    if not target.active:
        return
    cover = not any(c.condition_id == NO_HALF_COVER for c in target.conditions.values())
    if cover:
        engine._apply_condition(target, NO_HALF_COVER, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Sun-White Judgment Spear: no cover"})
    engine._apply_condition(target, PIERCING, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Sun-White Judgment Spear: seen through darkness and concealment", "cover": cover})


# ------------------------------------------------------------------------------------------------ Dawnmark placed
@hook("event")
def dawnmark_placed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "REACTION_RESOLVED":
        _mirror_seen(engine, kwargs)
        return
    if event_type != "CONDITION_APPLIED":
        return
    owner = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    subject = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    payload = kwargs.get("payload") or {}
    if owner is None or subject is None or str(payload.get("condition_id") or "") != _mark_id(owner.entity_id):
        return
    condition = next((c for c in subject.conditions.values() if c.condition_id == _mark_id(owner.entity_id)), None)
    if condition is None:
        return
    _expose(engine, owner, subject, condition)
    _crown(engine, owner, subject, condition)


def _expose(engine: Any, owner: Any, subject: Any, condition: Any) -> None:
    from ..ability_checks import VISUAL_CONCEALMENT
    from .rider_support import cp_pool as _cp_pool
    from .rider_choices import pick

    if not _owns(engine, owner, EXPOSE) or subject.team_id == owner.team_id:
        return
    pool = _cp_pool(owner)
    if pool is None or owner.resources.get(pool, 0) < 1:
        return
    if not pick(engine, owner, "radiance_expose", "Expose False Form", ["pay"], subject=subject,
                labels={"pay": f"Pay 1 CP to expose {subject.display_name} while Dawnmark lasts"},
                automatic=bool(_invisible(subject) or _hidden(subject))):
        return
    engine._spend_resource(owner, pool, 1, f"passive:{EXPOSE}")
    owner.turn_flags[f"_round_radiance_expose:{subject.entity_id}"] = condition.instance_id
    if any(row.get("expose_checks") for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, ())):
        engine._apply_condition(subject, EXPOSED_CHECK, f"passive:{EXPOSE}", owner.entity_id,
                                expires_on=condition.expires_on,
                                data={"marker_turn": int(condition.data.get("marker_turn") or owner.turns_started),
                                      "mark_instance": condition.instance_id,
                                      "rule": {"check_against": {"abilities": ["DEX"], "skills": ["Stealth"],
                                                                 "against": [VISUAL_CONCEALMENT],
                                                                 "mode": "DISADVANTAGE"}},
                                      "label": "Expose False Form: Dexterity (Stealth) checks that rely on being unseen have "
                                               "Disadvantage while this Dawnmark lasts"})
    note(engine, f"passive:{EXPOSE}", owner, f"Expose False Form (1 CP): {subject.display_name} cannot benefit from ordinary Invisible or "
         f"visual concealment while the Dawnmark lasts.", (subject.entity_id,))


@hook("event", nested=True)
def exposed_mark_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A removed or replaced Dawnmark also removes its scoped check penalty."""
    if event_type != "CONDITION_REMOVED":
        return
    removed = (kwargs.get("payload") or {}).get("instance_id")
    if not removed:
        return
    from .condition_ownership import remove_instance
    for aid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(aid)
        if actor is None:
            continue
        for held in list(actor.conditions.values()):
            if held.condition_id in (EXPOSED_CHECK, LEGACY_EXPOSED_CHECK) and held.data.get("mark_instance") == removed:
                remove_instance(engine, actor, held.instance_id, f"passive:{EXPOSE}")


def _crown(engine: Any, owner: Any, subject: Any, condition: Any) -> None:
    from .effect_durations import apply_condition_preserving_clock
    if not _holds(owner, CROWN) or subject.team_id == owner.team_id:
        return
    key, now = "_round_radiance_crown", f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if owner.turn_flags.get(key) == now:
        return
    marked = _mark_id(owner.entity_id)
    near = sorted((other for other in engine.state.actors.values() if other.active and other.team_id != owner.team_id and other is not subject
                   and not _dawnmarked_by(other, owner.entity_id) and engine._distance_actor_to_actor(subject, other) <= 10),
                  key=lambda other: (engine._distance_actor_to_actor(subject, other), other.entity_id))
    if not near:
        return
    from .rider_choices import pick
    chosen = pick(engine, owner, "radiance_crown", "Crown of the Unblinking Sun", [o.entity_id for o in near],
                  labels={o.entity_id: f"Extend Dawnmark to {o.display_name}" for o in near}, subject=subject,
                  preferred=[near[0].entity_id])
    if not chosen:
        return
    recipient = engine.state.actors[chosen[0]]
    owner.turn_flags[key] = now
    apply_condition_preserving_clock(engine, recipient, condition, marked, condition.source_definition_id, owner.entity_id, expires_on=condition.expires_on,
                            data=copy.deepcopy(condition.data or {}), previous_holder=subject)
    note(engine, f"passive:{CROWN}", owner, f"Crown of the Unblinking Sun: the Dawnmark spreads to {recipient.display_name}.", (recipient.entity_id,))


# ------------------------------------------------------------------------------------------------ saves
def _mirror_seen(engine: Any, kwargs: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_radiance_mirror")
    last = engine.events[-1] if engine.events else None
    payload = kwargs.get("payload") or {}
    if last is None or MIRROR not in str(last.source_definition_id) or payload.get("checkpoint") != "D20_PENDING" or payload.get("roll") != "save":
        return
    for subject_id in kwargs.get("target_ids") or ():
        engine.__dict__.setdefault("_radiance_mirror", {})[subject_id] = str(kwargs.get("actor_id") or "")


@hook("after_save")
def radiance_saves(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_radiance_mirror")
    engine = ctx.engine
    watcher = engine.state.actors.get((engine.__dict__.get("_radiance_mirror") or {}).pop(subject.entity_id, ""))
    if failed:
        return
    creator = ctx.actor
    if watcher is not None and watcher.active and creator.team_id != watcher.team_id and creator.active and \
            engine._distance_actor_to_actor(watcher, creator) <= 60 and engine._line_of_sight_actor_to_actor(watcher, creator):
        _dawnmark(engine, watcher, creator, MIRROR, "until_start_of_your_next_turn")
        note(engine, f"passive:{MIRROR}", watcher, f"Mirror of Clean Dawn: {creator.display_name}, whose effect was resisted, is Dawnmarked.",
             (creator.entity_id,))
    if not SAVES_AGAINST & {str(name).lower() for name in named or ()}:
        return
    for zone in _areas(engine, COURT):
        owner = engine.state.actors.get(zone.owner_id)
        key = f"_round_radiance_court_thp:{subject.entity_id}"
        if owner is None or _hostile_to(engine, zone, subject) or not _inside(engine, subject, zone) or \
                owner.turn_flags.get(key) == engine.state.round_number:
            continue
        owner.turn_flags[key] = engine.state.round_number
        from ..typed_executor import run_effects

        run_effects(_context(engine, owner, engine.action_catalog.get(zone.source_definition_id), subject),
                    [{"type": "temp_hp", "applies_to": "target", "formula": "pb"}])
        note(engine, f"passive:{COURT}", owner, f"Court of Unshadowed Dawn: {subject.display_name} resists and gains Temporary HP.", (subject.entity_id,))
        break
    halo = next((m for m in subject.modifiers.values() if HALO in str(m.source_definition_id)), None)
    owner = engine.state.actors.get(halo.source_actor_id) if halo is not None else None
    if owner is not None and owner.active:
        near = sorted((other for other in engine.state.actors.values() if other.active and other.team_id != subject.team_id
                       and engine._distance_actor_to_actor(subject, other) <= 10),
                      key=lambda other: (engine._distance_actor_to_actor(subject, other), other.entity_id))
        if near:
            from .rider_choices import pick
            chosen = pick(engine, owner, "radiance_halo", "Halo of the Merciful Sovereign", [o.entity_id for o in near],
                          labels={o.entity_id: f"Dawnmark {o.display_name}" for o in near}, subject=subject,
                          trigger=f"{subject.display_name} resists a charm or fear saving throw", preferred=[near[0].entity_id], intent=getattr(ctx, "intent", None))
            if chosen:
                recipient = engine.state.actors[chosen[0]]
                _dawnmark(engine, owner, recipient, HALO, "until_start_of_your_next_turn")
                note(engine, f"passive:{HALO}", owner, f"Halo of the Merciful Sovereign: {recipient.display_name} is Dawnmarked.", (recipient.entity_id,))


# ------------------------------------------------------------------------------------------------ turns
@hook("turn_start")
def court_clears_sight(engine: Any, actor: Any) -> None:
    """Court: "ordinary Blinded effects caused by light or darkness are suppressed at the start of the ally's turn"."""
    if not actor.active or not _in(engine, actor, COURT, side="ally"):
        return
    for condition in list(actor.conditions.values()):
        if condition.condition_id.endswith(".blinded") and _source_sphere(engine, condition.source_definition_id) in LIGHT_OR_DARK:
            from .rider_support import remove_instance
            remove_instance(engine, actor, condition.instance_id, f"passive:{COURT}")
            note(engine, f"passive:{COURT}", actor, f"Court of Unshadowed Dawn: the light-or-darkness blindness on {actor.display_name} lifts.")


@hook("turn_start")
def solar_aura(engine: Any, actor: Any) -> None:
    """Heavenly Radiance, Solar Aura: "When a hostile creature starts its turn within 20 feet of you, it makes a Constitution saving throw.
    Failed Save: Take 4d10 Radiant damage and become Blinded until the start of its next turn. Successful Save: Take half damage and cannot
    take Reactions until the start of its next turn." """
    from ..typed_executor import run_effects

    for owner in list(engine.state.actors.values()):
        if not actor.active or not owner.active or owner.team_id == actor.team_id or not _holds(owner, HEAVENLY):
            continue
        if engine._distance_actor_to_actor(owner, actor) > 20:
            continue
        action = _action(engine, owner, HEAVENLY)
        if action is None:
            continue
        note(engine, f"passive:{HEAVENLY}", owner, f"Solar Aura: {actor.display_name} starts its turn within 20 feet of {owner.display_name}.",
             (actor.entity_id,))
        run_effects(_context(engine, owner, action, actor), [{
            "type": "save", "ability": "con",
            "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "damage_types": ["radiant"]},
                        {"type": "condition", "applies_to": "target", "condition": "blinded", "expires_on": "START_OF_SELF_NEXT_TURN",
                         "evidence": "become Blinded until the start of its next turn"}],
            "on_success": [{"type": "half_damage"},
                           {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SELF_NEXT_TURN",
                            "evidence": "cannot take Reactions until the start of its next turn"}]}])


@hook("turn_start")
def restore_suppressed(engine: Any, actor: Any) -> None:
    """Gentle Dawn's suppression ends at the start of its user's next turn: the effect comes back as it was, if its own time is not up."""
    for holder in list(engine.state.actors.values()):
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != SUPPRESSED or condition.source_actor_id != actor.entity_id:
                continue
            from .rider_support import remove_instance
            from .suppressed_effects import alive, restore
            remove_instance(engine, holder, iid, condition.source_definition_id)
            kept = (condition.data or {}).get("kept") or {}
            clock = (condition.data or {}).get("lifetime") or {"expiry": kept.get("expires_on")}
            if (condition.data or {}).get("original"):
                restore(engine, holder, condition.data["original"], clock)
            elif kept and holder.active and alive(engine, clock):
                engine._apply_condition(holder, kept["condition_id"], kept["source"], kept.get("source_actor_id"),
                                        expires_on=clock.get("expiry") or kept.get("expires_on") or "UNTIL_REMOVED", data=kept.get("data") or {})


# ------------------------------------------------------------------------------------------------ cleansing rows
@effect("radiance_repeat_save")
def repeat_save(ctx: Any, eff: dict[str, Any]) -> None:
    """"May immediately repeat a saving throw against Charmed or Frightened" (Gentle Dawn, Dawn-Cleansing Wave's allies): one condition it
    has from those named, that remembers the save it came from (origin_save / repeat_save), is rolled against again; a success ends it.
    ``who``: "target" (default) or "allies_in_area" (the allies in the ability's own area)."""
    engine = ctx.engine
    names = {str(name).lower() for name in eff.get("against") or ()}
    subjects = [ctx.target] if eff.get("who", "target") == "target" else _allies_in_area(ctx)
    for subject in subjects:
        if subject is None or not subject.active:
            continue
        for condition in list(subject.conditions.values()):
            if condition.condition_id.rsplit(".", 1)[-1] not in names:
                continue
            save = (condition.data or {}).get("origin_save") or (condition.data or {}).get("repeat_save") or {}
            if not save.get("ability") or not save.get("dc"):
                continue
            from .rider_choices import pick
            if not pick(engine, subject, "radiance_repeat_save", ctx.action.display_name, ["repeat"],
                        labels={"repeat": f"Repeat the save against {condition.condition_id.rsplit('.', 1)[-1].title()}"},
                        subject=subject, trigger=ctx.action.display_name, intent=ctx.intent):
                break
            roll = engine._roll_save(subject, str(save["ability"]).upper(), int(save["dc"]), ctx.source)
            if roll is not None and roll.total >= int(save["dc"]):
                from .rider_support import remove_instance
                remove_instance(engine, subject, condition.instance_id, ctx.source)
                ctx.rider(f"{subject.display_name} repeats the save and ends {condition.condition_id.rsplit('.', 1)[-1].title()}.")
            break


def _allies_in_area(ctx: Any) -> list[Any]:
    from ..typed_executor import _area_targets

    area = ctx.typed.get("area") or {}
    aim = ctx.damage_cache.get("_checkpoint_aim") or getattr(getattr(ctx, "intent", None), "destination", None)
    try:
        found = _area_targets(ctx.engine, ctx.actor, aim, area) if area.get("size_ft") else []
    except Exception:  # an area the table cannot aim leaves the allies out rather than guessing
        found = []
    return [creature for creature in found if creature.team_id == ctx.actor.team_id and creature is not ctx.actor]


@effect("radiance_suppress")
def suppress(ctx: Any, eff: dict[str, Any]) -> None:
    """Gentle Dawn: "suppress one ordinary fear ... effect on the target until the start of your next turn" -- its Frightened is taken off
    and comes back then (``restore_suppressed``)."""
    subject = ctx.target
    names = {str(name).lower() for name in eff.get("conditions") or ()}
    condition = next((c for c in subject.conditions.values() if c.condition_id.rsplit(".", 1)[-1] in names), None) if subject is not None else None
    if condition is None:
        ctx.rider("Nothing on the target to suppress.")
        return
    kept = {"condition_id": condition.condition_id, "source": condition.source_definition_id, "source_actor_id": condition.source_actor_id,
            "expires_on": condition.expires_on, "data": copy.deepcopy(condition.data or {})}
    from .rider_support import remove_instance
    from .suppressed_effects import lifetime
    clock = lifetime(ctx.engine, subject, condition)
    remove_instance(ctx.engine, subject, condition.instance_id, ctx.source)
    ctx.engine._apply_condition(subject, SUPPRESSED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"{condition.condition_id.rsplit('.', 1)[-1].title()} suppressed", "kept": kept,
                                      "original": condition.model_dump(mode="json"), "lifetime": clock})


@effect("radiance_cure_disease")
def cure_disease(ctx: Any, eff: dict[str, Any]) -> None:
    """Purifying Radiance: "remove one ordinary disease" -- one effect on the target that came from a Disease-sphere ability (not a mark)."""
    subject = ctx.target
    if subject is None:
        return
    for condition in list(subject.conditions.values()):
        if ".mark." in condition.condition_id or _source_sphere(ctx.engine, condition.source_definition_id) != "tianxia.sphere.disease":
            continue
        from .rider_support import remove_instance
        remove_instance(ctx.engine, subject, condition.instance_id, ctx.source)
        ctx.rider(f"{subject.display_name}'s disease ({condition.condition_id.rsplit('.', 1)[-1].replace('_', ' ')}) is removed.")
        return
    ctx.rider("No disease on the target.")


@hook("candidate_allowed")
def once_per_rest(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Gentle Dawn: "A creature may gain Temporary HP from your Gentle Dawn only once per short rest" (the fight is within one rest)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if GENTLE not in str(typed.get("source") or "") or not any(row.get("type") == "temp_hp" for row in typed.get("effects") or []):
        return None
    target = next(iter(getattr(candidate, "target_ids", None) or ()), actor.entity_id)
    return False if actor.turn_flags.get(f"_round_radiance_gentle_thp:{target}") else None


@hook("technique_used")
def radiance_used(ctx: Any) -> None:
    source = str((ctx.typed or {}).get("source") or ctx.source)
    target = ctx.target or ctx.actor  # an ability aimed at its own user runs with no target
    if GENTLE in source and any(row.get("type") == "temp_hp" for row in (ctx.typed or {}).get("effects") or []):
        ctx.actor.turn_flags[f"_round_radiance_gentle_thp:{target.entity_id}"] = True
    if HALO in source:
        # "you may maintain only one Halo of the Merciful Sovereign at a time": the one before ends.
        for other in ctx.engine.state.actors.values():
            if other is target:
                continue
            for mid, modifier in list(other.modifiers.items()):
                if HALO in str(modifier.source_definition_id) and modifier.source_actor_id == ctx.actor.entity_id:
                    del other.modifiers[mid]
                    ctx.engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=ctx.actor.entity_id,
                                             target_ids=(other.entity_id,), payload={"modifier_id": mid, "reason": "REPLACED"})
            for condition in list(other.conditions.values()):
                if HALO in str(condition.source_definition_id) and condition.source_actor_id == ctx.actor.entity_id:
                    from .rider_support import remove_instance
                    remove_instance(ctx.engine, other, condition.instance_id, ctx.source)


def legacy_strike_states(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """Adapt saved pre-state form markers to radiance_states' single strike implementation."""
    records = []
    for feature, kind in ((SEARING, 'searing_halo'), (SOLAR, 'solar_form')):
        if not _holds(actor, feature):
            continue
        if any(c.condition_id == 'condition:typed.radiance_state' and c.data.get('kind') == kind
               for c in actor.conditions.values()):
            continue
        action = _action(engine, actor, feature) or _action(engine, actor, STRIKE)
        if action is not None:
            numbers = dict((action.parameters.get('typed') or {}).get('numbers') or {})
            records.append({'kind': kind, 'source': feature, 'numbers': numbers})
    return records


# ------------------------------------------------------------------------------------------------ Heavenly Radiance
@hook("attack_damage")
def heavenly_strike(ctx: Any, dice: Any) -> Any | None:
    """"Radiance Strike deals 8d10 Radiant damage instead of its normal damage" (and so does its Dawn Wave beam)."""
    from ..gate2_runtime_models import DiceSpec

    if isinstance(dice, DiceSpec) and STRIKE in str(ctx.source) and _holds(ctx.actor, HEAVENLY):
        return DiceSpec(count=8, sides=10, modifier=dice.modifier)
    return None


@hook("maneuvers")
def dawn_wave(info: dict[str, Any]) -> dict[str, Any] | None:
    """Dawn Wave: "While Heavenly Radiance is active, when you use Radiance Strike, you may instead release one of the following: a
    single-target beam with a range of 120 feet; a 60-foot line, 10 feet wide; a 30-foot cone. The line and cone require Dexterity
    saving throws for half damage instead of attack rolls. Creatures that fail are Dawnmarked until the end of your next turn." --
    three variants of the character's own Radiance Strike, offered only while it is transformed."""
    if HEAVENLY not in set(info.get("owned") or ()):
        return None
    strike = next((a for a in info.get("actions") or () if str(a.source_definition_id).endswith(STRIKE)), None)
    if strike is None:
        return None
    made = []
    for key, label, area in (("beam", "Dawn Wave (120-foot beam)", None), ("line", "Dawn Wave (60-foot line)", {"shape": "line", "size_ft": 60, "width_ft": 10}),
                             ("cone", "Dawn Wave (30-foot cone)", {"shape": "cone", "size_ft": 30})):
        parameters = copy.deepcopy(strike.parameters)
        typed = parameters["typed"]
        if area is not None:
            typed["effects"] = [{"type": "save", "ability": "dex", "applies_to": "creatures_in_area",
                                 "on_fail": [{"type": "damage", "applies_to": "creatures_in_area", "dice": {"count": 8, "sides": 10}, "damage_types": ["radiant"]},
                                             {"type": "mark", "mark": MARK, "applies_to": "creatures_in_area", "duration": {"kind": "until_end_of_your_next_turn"}}],
                                 "on_success": [{"type": "half_damage", "applies_to": "creatures_in_area"}]}]
            typed["area"] = area
        typed.update({"option_of": strike.source_definition_id, "option_label": label})
        parameters["radiance_dawn_wave"] = key
        made.append(type(strike)(source_definition_id=f"{strike.source_definition_id}#dawn_{key}", display_name=f"Radiance Strike: {label}",
                                 owner_id=strike.owner_id, economy=strike.economy, resolution_kind=strike.resolution_kind,
                                 target_kind="CELL" if area else strike.target_kind, range_ft=int(area["size_ft"]) if area else 120,
                                 costs=strike.costs, parameters=parameters))
    return {"actions": made}


@hook("candidate_allowed")
def dawn_wave_while_radiant(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("radiance_dawn_wave"):
        return None
    return None if _holds(actor, HEAVENLY) else False


@hook("resistance_ignored")
def judgment_pierces(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    """Heaven-Opening Judgment "ignores ... one ordinary Radiant Resistance"."""
    if str(kind).upper() != "RADIANT" or not isinstance(typed, dict) or JUDGMENT not in str(typed.get("source") or ""):
        return None
    return True
