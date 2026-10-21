"""Hidden Eye awareness the table can answer without the GM (lane A2R13, observer information and masking).

The Hidden Eye sphere's printed talents hand the player *information* rather than a new attack or defence: what a
Search can detect, where a tracked creature went, and which way a creature an Inheritance has opened lies. Those are
the printed sentences this plug-in resolves at the table, through the engine's existing knowledge records and plain
fight-log lines. Nothing here invents a fact: every line is read from live state (a condition the engine already
holds, a position, a distance) or from a check the engine already rolled.

Printed text (owner text, APP/authority/typed_mechanics/rules_text.json):

  Magical Cognizance (TAL_THE_HIDDEN_EYE_MAGICAL_COGNIZANCE, the group's one MANUAL row)
    "Range: 10 feet. You may use the Search action to detect the presence and general location of an ongoing
     magical effect within range. If the effect does not provide a DC, use the creator's Cultivation Save DC or spell
     save DC. If no such DC exists, use DC 15. A successful check reveals that a magical effect is active and its
     general location. It does not automatically identify the effect, its creator, its school, its sphere, its
     duration, or a method of ending it. While you hold Martial Focus, calculate your Passive Cognizance as 10 + your
     highest bonus among Intelligence (Investigation), Wisdom (Perception), and Wisdom (Survival)."
    -> the documented ``after_search`` seam (typed_executor.block_search runs it after the ordinary hidden-creature
    Perception check) asks one Intelligence (Investigation) check per ongoing *magical* effect within 10 feet,
    against that effect's own save DC or its creator's, else DC 15. A success reports only "an ongoing magical
    effect is active, over there" -- the printed "presence and general location" -- as a coarse bearing and distance
    band, never naming the effect, its carrier or its creator.

    Three things this deliberately does NOT do, because the printed sentence does not license them:

      * It does not sense every sourced condition. "An ongoing *magical* effect" is resolved by ``effect_is_magical``:
        the effect's own source must resolve to a printed sphere mechanic. A mundane condition -- a prone from a
        stumble, a mark a player wrote, an exhaustion clock -- is not a magical effect, so it is not detected.
      * It does not sense past what this creature can perceive. The printed 10 feet is the talent's sensing
        range; on top of that the effect's anchor has to be something the creature could actually tell is
        there (``_perceived`` / ``anchor_perceivable``), which is the owner ruling of 2026-10-12 made
        mechanical: a player learns only what the creature they control can perceive. Walls, solid pillars and
        closed doors end the search; the engine's own terrain decision decides, and a stale row on a creature
        that has left the field or an expired area is never reported as something present.
      * It does not stop at magical Darkness. The ray is tested geometrically rather than through ordinary
        sight, precisely so that noticing magic *through* magical Darkness -- the reason the talent exists -- is
        not thrown away. Blinded is respected, and Blindsight, Spiritual Sense or a sense that pinpoints still
        reach an anchor with no light at all.
      * It does not name a carrier. ``where_effect`` reports a bearing and a coarse distance band ("about 10 feet to
        the north-east") and stops; the creature holding the effect is not printed, because "it does not
        automatically identify the effect, its creator, its school..." names identity as exactly what is withheld.

    Passive Cognizance uses the printed skill bonuses (Investigation, Perception, Survival -- the sheet totals, so
    proficiency counts) and is reported only while Martial Focus is held, which is the printed condition. It is a
    passive number, so it can never turn a failed active check into a detection.

  No Footstep Escapes the World (TAL_THE_HIDDEN_EYE_NO_FOOTSTEP_ESCAPES_THE_WORLD)
    "You always know the direction of your rival while you and your rival are on the same plane of existence. If your
     rival is within 1 mile, you also know its approximate distance from you."
    -> NOT automated here: "your rival" is the designation Worthy Opponent
    (TAL_THE_HIDDEN_EYE_WORTHY_OPPONENT) creates, and no other module creates one. This lane owns neither that
    talent nor a rival record, so there is no rival for the printed knowledge to be about. Reported as remaining
    rather than guessed at a substitute target.

  Spirit-Trace Pursuit (TAL_THE_HIDDEN_EYE_SPIRIT_TRACE_PURSUIT)
    "When you successfully Analyze a creature through Spirit-Trace Pursuit, you also learn the direction in which the
     trace continued when it left the scene."
    -> the documented ``analyze_checked`` seam adds one learned characteristic to the same Analyze that made the
    existing ones. The printed clause is about the direction the trace continued *when it left the scene*, so a real
    departure is established first: the engine's account of leaving the scene is battlefield presence, and the saved
    journal says when a creature stopped being held on the field (``trace_departure``). The bearing is then the last
    ground the creature covered *before* that moment -- the way its trail was running when it went. Ordinary movement
    across the arena is not a departure, and a teleport (a return to a banishment's origin square, say) is not a trail,
    so neither can stand in for one. A creature that has never left the scene leaves nothing to read, and nothing is
    claimed. The learned direction is stored on the record as a value as well as a name, so it survives a cold reload
    and later mechanics can read what was learned; it records no position and no mark, so "does not reveal the
    creature's exact location and does not create a permanent tracking mark" holds by construction.

Not automated here, and why:

  Court of the Hidden Eye "you know when a creature you can perceive enters or leaves the Domain" is the obvious
  next seam (``zone_arrival`` receives both the arrival's start and end squares, so the crossing is measurable), but
  this lane could not reach it through a real table intent: in the fixture fights used here the only movement the
  engine offers a creature that is not its owner is Dash, which carries no destination, so no committed move crosses
  the 60-foot boundary. Rather than ship a hook with no table/service-level regression, it is left as a GM line.

  Heaven Keeps No Secret from the Patient Eye's "you know the target's direction and approximate distance" restsates
  what the fight map already shows for a creature in the same encounter, so it adds nothing the table does not have.

  No Footstep Escapes the World needs "your rival", the designation Worthy Opponent
  (TAL_THE_HIDDEN_EYE_WORTHY_OPPONENT) creates. No module in the tree creates a rival record and that talent is not
  in this lane's scope, so there is no subject for the printed knowledge.

Hooks used: ``after_search`` (after the ordinary Search check; documented in combat/ext/__init__.py) and
``analyze_checked`` (an Analyze's counted facts; riders14_eye). Both are existing documented seams; this module adds
no new hook point and no per-ability branch in a core file. Ownership is read the established way, from the
creature's own compiled ``hidden_eye`` passive rows in combat/rules/feature_blocks.d/eye.json (``eye_common.has``).
"""

from __future__ import annotations

from typing import Any

from . import hook, note
from .eye_common import has
from .mind_hidden_eye import FOCUS, record_characteristic

COGNIZANCE = "TAL_THE_HIDDEN_EYE_MAGICAL_COGNIZANCE"
TRACE_PURSUIT = "TAL_THE_HIDDEN_EYE_SPIRIT_TRACE_PURSUIT"

COGNIZANCE_RANGE_FT = 10          # "Range: 10 feet"
DEFAULT_EFFECT_DC = 15            # "If no such DC exists, use DC 15"
TRACE_CHARACTERISTIC = "Spirit-Trace Direction"
#: "an ongoing *magical* effect": a source whose printed mechanic belongs to a Cultivation Sphere. Ordinary
#: bookkeeping (a fall, a mark, an exhaustion clock) has no sphere and is not a magical effect.
SPHERE_PREFIX = "tianxia.sphere."


def compass(dx: int, dy: int) -> str:
    """A plain-language bearing for a fight-log line: squares' x grows east and their y grows south."""
    ns = "north" if dy < 0 else "south" if dy > 0 else ""
    ew = "east" if dx > 0 else "west" if dx < 0 else ""
    if ns and ew and min(abs(dx), abs(dy)) * 2 >= max(abs(dx), abs(dy)):
        return f"{ns}-{ew}"
    return (ns if abs(dy) >= abs(dx) else ew) or "here"


def bearing(engine: Any, viewer: Any, subject: Any) -> str:
    """How far, and which way, ``subject`` lies from ``viewer`` -- the printed "direction and approximate distance"."""
    distance = engine._distance_actor_to_actor(viewer, subject)
    where = compass(subject.position.x - viewer.position.x, subject.position.y - viewer.position.y)
    if where == "here":
        return "right here with you"
    return f"about {distance} feet to the {where}"


# ----------------------------------------------------------------------------------------- Magical Cognizance
def passive_cognizance(engine: Any, actor: Any) -> int:
    """"10 + your highest bonus among Intelligence (Investigation), Wisdom (Perception), and Wisdom (Survival)".

    Those are the three printed *skill* bonuses, so each is read as a skill total (combat/ability_checks.skill_bonus
    prefers the compiled sheet's own total, which already carries proficiency) and only falls back to the related
    ability modifier when the creature has no compiled skill. The earlier version added the bare Intelligence or
    Wisdom modifier, which silently dropped proficiency from every one of the three.
    """
    from .eye_common import skill

    from ..ability_checks import ability_modifier

    return 10 + max(skill(engine, actor, "Investigation", ability_modifier(actor, "INT")),
                    skill(engine, actor, "Perception", ability_modifier(actor, "WIS")),
                    skill(engine, actor, "Survival", ability_modifier(actor, "WIS")))


def investigation_bonus(engine: Any, actor: Any) -> int:
    """The actor's own Investigation skill bonus, the same way the compiler prices its Search row."""
    from .eye_common import skill

    from ..ability_checks import ability_modifier

    return skill(engine, actor, "Investigation", ability_modifier(actor, "INT"))


def _effect_dc(engine: Any, effect: Any) -> int:
    """"use the creator's Cultivation Save DC or spell save DC. If no such DC exists, use DC 15."

    Read in that order, so a creature's own printed DC wins over its creator's and DC 15 is the last resort.
    """
    data = getattr(effect, "data", None) or {}
    for key in ("save_dc", "dc"):
        try:
            printed = int(data.get(key) or 0)
        except (TypeError, ValueError):
            printed = 0
        if printed:
            return printed
    creator_id = getattr(effect, "source_actor_id", None) or data.get("creator_id")
    creator = engine.state.actors.get(creator_id) if creator_id else None
    if creator is not None and creator.entity_id != getattr(effect, "actor_id", None):
        from ..save_dcs import save_dc

        return int(save_dc(engine, creator))
    return DEFAULT_EFFECT_DC


def source_sphere(engine: Any, source_id: str) -> str:
    """The printed Sphere a source belongs to, or "" for one that is not a Cultivation effect.

    Resolves a condition or area's own ``source_definition_id`` through the action catalog to the mechanic that
    created it, then reads that mechanic's ``sphere_id`` from the typed authority -- the same lookup
    combat/ext/alchemy_riders.py uses to recognise its own printed talents. Nothing here names an ability: any
    sphere's effect qualifies, which is what "an ongoing magical effect" asks for.
    """
    import json

    from ..factory_compiler import TYPED_AUTHORITY
    from .ability_source import mechanic_at

    mechanic = str(mechanic_at(engine, source_id) or "").split("#")[0]
    if not mechanic:
        return ""
    row = (json.loads(TYPED_AUTHORITY.read_bytes()).get("mechanics") or {}).get(mechanic) or {}
    sphere = str(row.get("sphere_id") or "")
    return sphere if sphere.startswith(SPHERE_PREFIX) else ""


def _area_sphere(zone: Any) -> str:
    from .. import zone_sources

    return str((zone_sources.of(zone) or {}).get("sphere_id") or "")


def effect_is_magical(engine: Any, effect: Any) -> bool:
    """Whether this live effect is one a Search could sensibly call "magical".

    An area answers from its own sealed provenance (``zone_sources``); a condition from the sphere of whatever put
    it there. A sourced condition with no sphere behind it -- a stumble, a GM's mark, an exhaustion tick -- is
    ordinary state, and printing "an ongoing magical effect" for it would both overstate the talent and leak
    bookkeeping the printed ability never promised.
    """
    if hasattr(effect, "affected_cells") or hasattr(effect, "trigger_profile"):
        return _area_sphere(effect).startswith(SPHERE_PREFIX)
    source = str(getattr(effect, "source_definition_id", "") or "")
    return source_sphere(engine, source).startswith(SPHERE_PREFIX)


def anchor_perceivable(engine: Any, searcher: Any, anchor: Any) -> bool:
    """Whether ``searcher``'s own senses can tell it that something is at ``anchor``'s place on the field.

    This is the owner ruling of 2026-10-12 made mechanical: a player learns only what the creature they control can
    perceive, so an ongoing effect is knowledge only when that creature could tell it is there. The previous version
    asked merely whether the searcher and the anchor were both standing on the field, which reported a magical effect
    sealed behind a closed door or a stone pillar -- information the creature had no way to acquire.

    Magical Cognizance senses *magic*, not light, so the ray is tested geometrically:
    ``senses.physical_sight`` is the engine's own terrain decision -- walls, solid pillars and obscuring cells all
    end the search -- while a field of magical Darkness deliberately does not, because noticing magic through magical
    Darkness is exactly what the printed talent is for. Ordinary sight (``senses.perceives``) is therefore *not*
    consulted: it refuses that very case, and gating on it would silently delete the talent's reason to exist.

    The creature's own senses decide the rest of the question, and the engine's existing answers are reused rather
    than re-derived: Blindsight and Spiritual Sense reach an anchor with no sight at all, a sense that pinpoints
    (Tremorsense, Spiritual Truesight) finds it outright, and a Blinded creature holding neither has no perception of
    any anchor. ``anchor`` is a creature, or the ``senses.cell_probe`` for an area's square.
    """
    from .. import senses

    if not searcher.active or not engine._on_battlefield(searcher):
        return False
    if senses.is_creature(anchor) and not (anchor.active and engine._on_battlefield(anchor)):
        return False
    # An alternate sense reaches the anchor on its own terms, with or without ordinary sight.
    if senses.perceives_without_sight(engine, searcher, anchor) or senses.pinpoints(engine, searcher, anchor):
        return True
    blinded = set(senses.rules().get("blinded_conditions") or [])
    if any(condition.condition_id in blinded for condition in searcher.conditions.values()):
        return False
    return senses.physical_sight(engine, searcher, anchor)


def _perceived(engine: Any, searcher: Any, effect: Any) -> bool:
    """Whether this effect's anchor is live on the field and within this creature's actual perception."""
    carried = getattr(effect, "actor_id", None) or getattr(effect, "target_id", None)
    creature = engine.state.actors.get(carried) if carried else None
    if creature is not None:
        return anchor_perceivable(engine, searcher, creature)
    centre = getattr(effect, "center", None)
    if centre is None:
        return False
    from ..senses import cell_probe

    return anchor_perceivable(engine, searcher, cell_probe(centre))


def ongoing_effects(engine: Any, searcher: Any) -> list[Any]:
    """The ongoing magical effects within ``COGNIZANCE_RANGE_FT`` of the searcher that the searcher can perceive.

    An "ongoing magical effect" is a live engine effect someone else put on the field whose printed source belongs to
    a Cultivation Sphere (``effect_is_magical``): a condition carrying a source, or an area whose owner is a
    creature. The searcher never detects their own working, and plain bookkeeping with no sphere behind it is not a
    magical effect. Being in range is not enough either: the effect's anchor must be something this creature can
    actually perceive (``_perceived``), because a player learns only what their creature can perceive (owner ruling
    of 2026-10-12).

    Every qualifying effect is returned. Each one is a separate thing the printed Search can detect, and the text
    puts no ceiling on the list; an earlier version stopped after the first condition on a creature and after three
    effects overall, which meant a Search could never notice a fourth aura. The caller's own output stays readable
    because every line says the same short thing.
    """
    found: list[tuple[int, Any]] = []
    for other in engine.state.actors.values():
        if not other.active or other.entity_id == searcher.entity_id:
            continue
        if engine._distance_actor_to_actor(searcher, other) > COGNIZANCE_RANGE_FT:
            continue
        for condition in other.conditions.values():
            if not condition.source_actor_id or condition.source_actor_id == searcher.entity_id:
                continue
            if not effect_is_magical(engine, condition):
                continue
            found.append((engine._distance_actor_to_actor(searcher, other), condition))
    for zone in (getattr(engine.state, "zones", None) or {}).values():
        if not getattr(zone, "active", True):
            continue
        owner = engine.state.actors.get(getattr(zone, "owner_id", None))
        if owner is None or not owner.active or owner.entity_id == searcher.entity_id:
            continue
        if not effect_is_magical(engine, zone):
            continue
        centre = getattr(zone, "center", None)
        if centre is None or engine.grid.distance_ft(searcher.position, centre) > COGNIZANCE_RANGE_FT:
            continue
        found.append((engine.grid.distance_ft(searcher.position, centre), zone))
    perceivable = [(distance, effect) for distance, effect in found if _perceived(engine, searcher, effect)]
    perceivable.sort(key=lambda row: row[0])
    return [effect for _, effect in perceivable]


def where_effect(engine: Any, searcher: Any, effect: Any) -> str:
    """Where an effect is, in the player's own words: a bearing and a coarse distance band, and nothing else.

    The printed sentence reveals "its general location" and withholds identity, so this must not name the creature
    carrying the effect, the effect, or its creator -- an earlier version printed ``on <creature>``, which answered
    a question the talent explicitly does not. Distance is rounded to the 5-foot band the creature is standing in.
    """
    centre = getattr(effect, "center", None)
    carried = getattr(effect, "actor_id", None) or getattr(effect, "target_id", None)
    creature = engine.state.actors.get(carried) if carried else None
    point = centre if centre is not None else getattr(creature, "position", None)
    if point is None:
        return "close by"
    dx, dy = point.x - searcher.position.x, point.y - searcher.position.y
    where = compass(dx, dy)
    if where == "here":
        return "right here with you"
    feet = int(round(engine.grid.distance_ft(searcher.position, point) / 5.0)) * 5
    return f"about {feet} feet to the {where}"


@hook("after_search")
def cognizance_search(ctx: Any, effect: dict[str, Any]) -> None:
    """A Search also detects an ongoing magical effect within 10 feet (Magical Cognizance).

    The printed talent rides the ordinary Search action, so it costs and rolls where the Search does; this only adds
    the magical half of what the Search could notice. A failure reveals nothing, which is what "A successful check
    reveals" means -- and neither a failure nor a strong Passive Cognizance turns into a detection, because the
    passive number is the Game Master's to weigh ("The GM may use that score..."), not an automatic second look.
    """
    engine, actor = ctx.engine, ctx.actor
    if not has(engine, actor.entity_id, "magical_cognizance"):
        return
    from .roll_context import described_check

    targets = ongoing_effects(engine, actor)
    holding_focus = actor.resources.get(FOCUS, 0) > 0
    passive = passive_cognizance(engine, actor)
    for other in targets:
        dc = _effect_dc(engine, other)
        roll = described_check(engine, description=f"Intelligence (Investigation) to sense the ongoing magical effect ({'DC ' + str(dc)})",
                             modifier=investigation_bonus(engine, actor), actor_id=actor.entity_id,
                             reason="CHECK:MAGICAL_COGNIZANCE:investigation", ability="INT", skill="Investigation")
        engine._record_roll(roll)
        found = roll.total >= dc
        engine._append_event("CHECK_ROLLED", COGNIZANCE, actor_id=actor.entity_id,
                             target_ids=tuple(filter(None, [getattr(other, "actor_id", None)])),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": found,
                                      "check": "Investigation"})
        if found:
            note(engine, COGNIZANCE, actor,
                 f"Magical Cognizance: {actor.display_name} senses an ongoing magical effect {where_effect(engine, actor, other)}. "
                 f"You learn that it is active and roughly where; its nature, source and ending are still unknown "
                 f"({roll.total} against DC {dc}).")
    if holding_focus and targets:
        note(engine, COGNIZANCE, actor,
             f"Magical Cognizance: while you hold Martial Focus your Passive Cognizance is {passive} "
             "(10 plus your best Investigation, Perception or Survival bonus). The Game Master may use it to decide "
             "whether you notice an ongoing magical effect as you pass within 10 feet.")


# -------------------------------------------------------------------------------------- Spirit-Trace Pursuit
def _walked_bearing(event: Any) -> str:
    """The bearing of one committed movement, or "" when the creature did not walk anywhere.

    A teleport is not a trail: the printed sentence is about the direction a creature's trace *continued*, which is
    the ground it actually covered. Spatial absence's own return, for instance, commits a zero-cost teleport back to
    its origin square, and reading that as a departure direction would answer with the place it came from.
    """
    payload = event.payload or {}
    if payload.get("teleport"):
        return ""
    path = list(payload.get("path") or [])
    if len(path) < 2:
        return ""
    start, end = path[0], path[-1]
    where = compass(int(end["x"]) - int(start["x"]), int(end["y"]) - int(start["y"]))
    return "" if where == "here" else where


def trace_departure(engine: Any, target: Any) -> str:
    """The bearing the creature's own trail ran on when it actually left this scene, or "".

    The printed clause is "the direction in which the trace continued *when it left the scene*", so a departure is
    the thing that has to be established before any bearing can be read. The engine's own account of leaving the scene
    is battlefield presence: a creature the engine no longer holds on the field (combat/ext/spatial_absence.py, whose
    ``battlefield_presence`` veto is what ``engine._on_battlefield`` asks) has left it, and that transition is in the
    saved journal, so it survives a cold reload. The bearing is then the last ground the creature covered *before* that
    moment -- the way its trace was running when it went.

    Ordinary movement is not a departure. The earlier version took the creature's last committed step of any kind, so a
    fight in which the target simply walked across the arena was reported as though it had fled, and once it had been
    banished and returned the newest committed step was the return teleport, not a trail. Both are now excluded: a
    departure is required, it is read before it rather than after it, and a teleport is not a trail.

    The departure stays readable after the creature comes back, because that is the only time the printed sentence can
    be asked: a creature that is off the field cannot be Analyzed, so the trace it left is necessarily one it has
    already returned from. The journal is the saved record of that, which is why the learned direction survives a
    cold reload.
    """
    from .spatial_absence import ABSENT

    walking, direction = "", ""
    for event in sorted(engine.events, key=lambda record: record.sequence):
        if event.actor_id == target.entity_id and event.event_type == "MOVEMENT_COMMITTED":
            where = _walked_bearing(event)
            if where:
                walking = where
            continue
        if event.event_type == "CONDITION_APPLIED" and target.entity_id in (event.target_ids or ()) \
                and str((event.payload or {}).get("condition_id") or "") == ABSENT:
            direction = walking          # the trace's heading at the moment it left the scene
    return direction


@hook("analyze_checked")
def trace_direction(engine: Any, actor: Any, target: Any, payload: dict[str, Any]) -> None:
    """A successful Spirit-Trace Analyze also learns the direction the trace ran on when it left the scene.

    Reads the same Analyze result the counted characteristics come from (``analyze_checked``) and adds one recorded
    fact, so it cannot fire without an Analyze that actually succeeded. The direction is the creature's own recorded
    departure bearing (``trace_departure``); with no recorded departure the printed sentence has nothing to report,
    so nothing is claimed and nothing is recorded.
    """
    if actor is None or target is None or not has(engine, actor.entity_id, "spirit_trace_pursuit"):
        return
    if not payload.get("success"):
        return
    where = trace_departure(engine, target)
    if not where:
        note(engine, TRACE_PURSUIT, actor,
             f"Spirit-Trace Pursuit: {actor.display_name}'s Analyze succeeded, but {target.display_name} has not left "
             "this scene on the record, so there is no trace direction to learn from it.")
        return
    record_characteristic(engine, actor, target, TRACE_CHARACTERISTIC, TRACE_PURSUIT, value=where)
    note(engine, TRACE_PURSUIT, actor,
         f"Spirit-Trace Pursuit: the trace {actor.display_name} followed left this scene to the {where}, which is the "
         f"direction it continued. This is a direction only -- no position, and nothing left behind to follow later.")
