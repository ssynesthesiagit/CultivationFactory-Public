"""Senses in a fight (owner 2026-09-28 docket: "Darkvision, Blindsight, Tremorsense, Scent, AND the spheres' own unique
senses ... so plain Darkness (Darkvision sees through) differs from Pure Darkness (Darkvision 5 ft, other senses halved);
hiding/Search/attack modes should read them").

A fighter's senses come from its compiled bundle (``bundle["senses"]``, written by combat/factory_compiler.py from the
records it owns and combat/rules/senses.json) and from abilities it is using now (a Sense condition, combat/ext/
docket_senses.py). What each sense does here:

  Darkvision        sees through the Dark sphere's plain Darkness within its range ("A creature with Darkvision can
                    see through this Darkness"); inside Pure Darkness only within 5 feet.
  Blindsight        sees within its range through darkness, smoke and fog, and sees a hidden or invisible creature.
  Truesight         sees within its range through magical darkness and sees a hidden or invisible creature.
  Spiritual Sense   works as Blindsight against living creatures (Spirit Awakening).
  Tremorsense, Spiritual Truesight   pinpoint (not sight): a Search finds a hidden creature in range with no roll
                    (proposed ruling, combat/rules/senses.json).
  Bloodsense        observer-only authored blood facts (combat/ext/bloodsense.py); never grants targeting sight.
  Scent, Qi Sensing, Wicksight   kept and shown; no fight rule of their own.
Pure Darkness halves every sense but Darkvision for a creature inside it or looking at one inside it. No sense sees
through a wall that blocks sight (Total Cover): line of sight is still the grid's.

The Dark sphere's Melds (Darkvision, Dark Slaughter, Clearsight, Hide in Darkness, Step Through Darkness): several at once
(owner 2026-09-29 struck the printed "only one Meld talent granted by the same cultivator"). Melds are cast before a fight
(combat/prefight.py) or in it: "Meld: <talent>" (an Action; Concentration unless Persistent Meld's
2 CP are paid too; combat/ext/docket_senses.py). A fight made before pre-fight buffs starts with the first the character
knows (combat/rules/senses.json melds). ``meld_active`` answers for every Meld.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .concentration import concentrating_on
from .read_queries import pure

RULES_PATH = Path(__file__).resolve().parent / "rules" / "senses.json"
SENSE = "condition:typed.sense"      # a sense for a while (data: sense, range_ft, until_round, source, concentration)
MELD = "condition:typed.meld_set"    # the Meld it chose in the fight (data: talent, concentration, source)
MARTIAL_FOCUS = "resource:core.martial_focus"


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _range(row: dict[str, Any], cl: int) -> int:
    if row.get("range_by_cl"):
        return next((int(feet) for low, high, feet in row["range_by_cl"] if int(low) <= cl <= int(high)), 0)
    return int(row.get("range_ft") or 0)


def compile_grants(owned_ids: list[str], cl: int) -> dict[str, Any] | None:
    """The bundle's senses: every always-on (or Martial Focus, or Meld) sense its records give, the Melds it knows and
    the one it starts with. None when it has none."""
    table = rules()
    owned = list(dict.fromkeys(owned_ids))
    rows = []
    for record in owned:
        grant = (table.get("grants") or {}).get(record)
        if not grant or grant.get("when") == "active":
            continue
        for row in grant.get("senses") or []:
            rows.append({"feature_id": record, "sense": row["sense"], "range_ft": _range(row, cl), "when": grant.get("when") or "always",
                         **({"or_add_ft": int(row["or_add_ft"])} if row.get("or_add_ft") else {})})
    melds = [talent for talent in (table.get("melds") or {}).get("talents") or [] if talent in owned]
    gm = {record: note for record, note in (table.get("gm") or {}).items() if record in owned}
    if not rows and not melds and not gm:
        return None
    return {"rows": rows, "melds": melds, "meld_start": melds[0] if melds else None, **({"gm": gm} if gm else {})}


def _bundle(engine: Any, actor_id: str) -> dict[str, Any]:
    cache = engine.__dict__.setdefault("_sense_bundles", {})
    if actor_id not in cache:
        bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
        cache[actor_id] = (bundle or {}).get("senses") or {}
    return cache[actor_id]


# ------------------------------------------------------------------------------------------------ the Meld
def melds_of(engine: Any, actor: Any) -> list[str]:
    """The Melds it benefits from now, most recent last: the one it started with (a fight made without pre-fight buffs),
    then every one granted in (or before) the fight while its Concentration lasts unless Persistent. Several at once
    (owner 2026-09-29: the printed "only one Meld talent granted by the same cultivator" is removed)."""
    granted = sorted((condition for condition in actor.conditions.values() if condition.condition_id == MELD),
                     key=lambda condition: condition.applied_sequence)
    start = _bundle(engine, actor.entity_id).get("meld_start")
    out = [start] if start else []
    for condition in granted:
        data = condition.data or {}
        if data.get("concentration") and not concentrating_on(engine.state.actors.get(data.get("caster_id"), actor), data.get("source")):
            continue  # its Concentration ended, and the Meld with it (current or held: combat/concentration.py)
        if data.get("talent") and data["talent"] not in out:
            out.append(data["talent"])
    return out


def meld_of(engine: Any, actor: Any) -> str | None:
    """The most recent Meld it benefits from (melds_of has them all)."""
    melds = melds_of(engine, actor)
    return melds[-1] if melds else None


def meld_active(engine: Any, actor: Any, talent_id: str) -> bool:
    """Whether a Meld talent works for this fighter now. A fighter whose bundle lists no Melds (compiled before, or a
    character that is not a Dark cultivator) keeps what it had."""
    melds = _bundle(engine, actor.entity_id).get("melds") or []
    if talent_id not in melds:
        return True
    return talent_id in melds_of(engine, actor)


# ------------------------------------------------------------------------------------------------ its senses now
def of(engine: Any, actor: Any, *, unrestricted_only: bool = False, seen: Any = None) -> dict[str, dict[str, Any]]:
    """Best live range per sense; unrestricted_only excludes creature-qualified grants before merging.

    The default preserves the existing perception query. Effect-immunity readers
    can request general sight without a restricted grant masking an ordinary one.
    """
    info = _bundle(engine, actor.entity_id)
    plain: dict[str, int] = {}
    adds: dict[str, list[tuple[int, int]]] = {}
    against: dict[str, list[str]] = {}
    rows = list(info.get("rows") or [])
    for condition in actor.conditions.values():
        if condition.condition_id == SENSE:
            data = condition.data or {}
            required = data.get("requires_condition")
            if required:
                state = data.get("requires_condition_data") or {}
                live = any(c.condition_id == required and
                           all((c.data or {}).get(key) == value for key, value in state.items())
                           for c in actor.conditions.values())
                if not live:
                    continue
            if data.get("concentration") and not concentrating_on(actor, data.get("source")):
                continue
            source = str(data.get("source") or condition.source_definition_id)
            action = engine.action_catalog.get(source)
            typed_source = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
            rows.append({"feature_id": str(typed_source.get("option_of") or typed_source.get("source") or source),
                         "sense": data.get("sense"), "range_ft": int(data.get("range_ft") or 0), "when": "active",
                         **({"against_conditions": list(data["against_conditions"])} if data.get("against_conditions") else {})})
    from . import ext

    for provider in ext.subscribers("sense_rows"):
        replacement = provider(engine, actor, rows)
        if replacement is not None:
            rows = replacement
    for row in rows:
        answers = ext.run_strict('sense_grant_allowed', engine, actor, row, seen)
        if any(answer is not None and type(answer) is not bool for answer in answers):
            raise ValueError('sense_grant_allowed must return bool or None')
        if False in answers:
            continue
        if unrestricted_only and row.get("against_conditions"):
            continue
        when = row.get("when") or "always"
        if when == "martial_focus" and actor.resources.get(MARTIAL_FOCUS, 0) < 1:
            continue
        if when == "meld" and not meld_active(engine, actor, str(row.get("feature_id") or "")):
            continue
        sense, feet = str(row.get("sense") or ""), int(row.get("range_ft") or 0)
        if not sense or feet <= 0:
            continue
        if row.get("against_conditions"):
            against[sense] = list(row["against_conditions"])  # a limited sense (Fruiting Body of the Dream)
        if row.get("or_add_ft"):
            adds.setdefault(sense, []).append((feet, int(row["or_add_ft"])))
        else:
            plain[sense] = max(plain.get(sense, 0), feet)
    out = {}
    for sense in sorted({*plain, *adds}):
        feet = plain.get(sense, 0)
        for granted, extra in adds.get(sense, []):
            feet = feet + extra if feet else granted  # "If the target already possesses Darkvision, increase its range by 30 feet instead"
        out[sense] = {"range_ft": feet, **({"against_conditions": against[sense]} if sense in against else {})}
    from . import ext

    for sense, row in out.items():
        row["range_ft"] = max(0, int(row["range_ft"]) + sum(ext.run("sense_range", engine, actor, sense)))
        divisors = [int(n) for n in ext.run_strict("sense_range_divisor", engine, actor, sense) if n is not None]
        row["range_ft"] //= max([1, *divisors])
    return out


def _pure(zone: Any) -> bool:
    return (rules().get("pure") or {}).get("talent", "Pure Darkness") in (zone.trigger_profile.get("talents") or [])


def pure_zone(zone: Any) -> bool:
    """Whether this area is Pure Darkness, which plain Darkvision does not see through at all (public: the light model
    asks it to decide whether a Darkvision range has to be measured square by square, combat/lighting.py _pure_zones)."""
    return _pure(zone)


def _pure_around(engine: Any, *creatures: Any) -> list[Any]:
    from . import zones

    return [zone for zone in zones.typed_zones(engine) if _pure(zone) and any(zones._inside(engine, row, zone) for row in creatures)]


def reach(engine: Any, viewer: Any, sense: str, seen: Any, *, zone: Any = None,
          unrestricted_only: bool = False) -> int:
    """How far this sense of the viewer reaches toward ``seen``: Pure Darkness around either of them cuts Darkvision to
    5 feet and halves the others; Clearsight lets its owner's Darkvision through its own Pure Darkness."""
    if sense == "spiritual_sense" and getattr(seen, "perception_cell", False):
        return 0  # Spiritual Sense perceives creatures, not empty terrain.
    row = of(engine, viewer, unrestricted_only=unrestricted_only, seen=seen).get(sense)
    if not row:
        return 0
    if row.get("against_conditions") and not any(condition.condition_id in row["against_conditions"] for condition in seen.conditions.values()):
        return 0
    feet = int(row["range_ft"])
    # A creature-qualified range never enters the general sight projection.
    if not unrestricted_only:
        from . import ext
        for minimum in ext.run("sense_target_range", engine, viewer, sense, seen):
            if isinstance(minimum, int) and not isinstance(minimum, bool):
                feet = max(feet, minimum)
    pure = [zone] if zone is not None and _pure(zone) else ([] if zone is not None else _pure_around(engine, viewer, seen))
    if pure:
        from . import zones

        if sense == "darkvision":
            if not all(zones.clear_sighted(engine, row_, viewer) for row_ in pure):
                feet = min(feet, int((rules().get("pure") or {}).get("darkvision_ft") or 5))
        else:
            feet //= 2
    return feet


def _within(engine: Any, viewer: Any, seen: Any, feet: int) -> bool:
    return feet > 0 and engine._distance_actor_to_actor(viewer, seen) <= feet


def sees_through_unconditionally(engine: Any, viewer: Any, obstruction: str) -> bool:
    """Whether a live sense sees through an obstruction without a creature-only qualification.

    Effect-immunity readers (currently Dark's Blindfold) use this shared query for
    sight through an environmental obstruction, rather than sight of a particular
    afflicted creature. Require positive effective reach, including local Pure
    Darkness and sense-range modifiers. No events or fight state are changed.
    """
    return any(obstruction in (_kinds().get(sense, {}).get("through") or ())
               and reach(engine, viewer, sense, viewer, unrestricted_only=True) > 0
               for sense in of(engine, viewer, unrestricted_only=True))


def _kinds() -> dict[str, dict[str, Any]]:
    return rules().get("kinds") or {}


def perception_senses(engine: Any, viewer: Any, *, sight_only: bool = False) -> dict[str, dict[str, Any]]:
    """Filter live senses for visual presentation without changing combat sight.

    Blindsight and Spiritual Sense count as combat sight by the printed rules,
    but locate creatures without ordinary vision. Visual enhancements such as
    Darkvision and Truesight remain subject to their existing range/area policy.
    """
    available = of(engine, viewer)
    if not sight_only:
        return available
    return {sense: row for sense, row in available.items()
            if (_kinds().get(sense) or {}).get("sight")
            and sense not in ("blindsight", "spiritual_sense")}


def pierces(engine: Any, zone: Any, viewer: Any, seen: Any, *, sight_only: bool = False) -> bool:
    """Whether the viewer's senses see ``seen`` through this area of darkness or heavy obscurement (combat/zones.py
    _blocks): Darkvision through the Dark sphere's Darkness, Truesight through magical darkness, Blindsight through
    both and through smoke or fog -- each within its range."""
    senses = perception_senses(engine, viewer, sight_only=sight_only)
    if not senses:
        return False
    profile = zone.trigger_profile
    darkness = bool((profile.get("visual") or {}).get("darkness"))
    named = str(profile.get("name") or "") in ((rules().get("darkvision_sees_through") or {}).get("names") or [])
    for sense in senses:
        through = set((_kinds().get(sense) or {}).get("through") or [])
        fits = ("darkness" in through and darkness) or ("darkness_named" in through and darkness and named) or \
            ("obscured" in through and profile.get("obscured") == "heavy")
        if fits and _within(engine, viewer, seen, reach(engine, viewer, sense, seen, zone=zone)):
            return True
    return False


def pierces_wall(engine: Any, zone: Any, viewer: Any, seen: Any, *, sight_only: bool = False) -> bool:
    """A wall that hides without blocking (Wall of Smoke, Wall of Darkness, Monsoon Wall): Blindsight within range sees
    through any of them, Darkvision and Truesight through a wall of the Dark sphere's Darkness."""
    senses = perception_senses(engine, viewer, sight_only=sight_only)
    if not senses:
        return False
    material = str((zone.trigger_profile.get("wall") or {}).get("material") or (zone.trigger_profile.get("visual") or {}).get("material") or "")
    darkness = material == "darkness" or bool((zone.trigger_profile.get("visual") or {}).get("darkness"))
    for sense in senses:
        through = set((_kinds().get(sense) or {}).get("through") or [])
        fits = "obscured" in through or (darkness and ("darkness" in through or "darkness_named" in through))
        if fits and _within(engine, viewer, seen, reach(engine, viewer, sense, seen)):
            return True
    return False


def sees_hidden(engine: Any, viewer: Any, seen: Any) -> bool:
    """Whether a qualifying sense detects concealment, subject to range and intervening obscurement."""
    return perceives(engine, viewer, seen, locate_concealed=True)


def _condition_query_key(actor: Any) -> tuple[Any, ...]:
    """Capture the full condition inputs used by permission hooks, not just their ids."""
    return tuple(sorted(
        (str(condition_id), str(getattr(condition, "source_definition_id", "")),
         json.dumps(getattr(condition, "data", None) or {}, sort_keys=True, default=str))
        for condition_id, condition in actor.conditions.items()
    ))


def _footprint_query_key(engine: Any, actor: Any) -> tuple[Any, ...]:
    """Include the projected occupied cells because perception rays use actor footprints."""
    cells = engine._actor_cells(actor)
    return tuple(sorted((int(x), int(y)) for x, y in cells))


@pure
def perceives(engine: Any, viewer: Any, seen: Any, *, locate_concealed: bool = False,
              sight_only: bool = False) -> bool:
    """Shared table perception decision for sight and special senses.

    Sight needs line of sight, an unblinded viewer, and the engine's area and
    obscuring-wall visibility. Blindsight and Spiritual Sense work while
    Blinded; senses that find Hidden or Invisible creatures must also reach them
    and obey the engine's endpoint-area and intervening-wall policy. Deafened affects hearing,
    not these visual senses.

    ``sight_only`` excludes nonvisual senses throughout concealment, blindness,
    endpoint areas and intervening walls. It is an opt-in presentation query;
    the default keeps all existing combat perception permissions.

    Candidate enumeration asks this same question for every sampled square and
    every option root of one ability. One candidate pass shares the answer for
    one unchanged pair of projected creatures, keyed by their identities,
    squares, condition ids and the scoped sight action (a plug-in sight route
    can be action-specific). Outside a pass every call computes afresh.
    """
    from .read_queries import invariant_query

    frame = getattr(engine, '_shot_geometry', None)
    # A scoped plug-in sight route is a creature-to-creature projectile
    # exception. Synthetic cell probes ("can this square be seen?") have no
    # creature target, so their answer is independent of which ability asked.
    cell_probe = str(seen.entity_id) == 'perception:cell'
    sight_action = (None if cell_probe else
                    str(frame['action'].source_definition_id)
                    if frame and frame.get('actor_id') == viewer.entity_id else None)
    viewer_key = (id(viewer), viewer.entity_id, viewer.position.x, viewer.position.y,
                  viewer.position.z, bool(viewer.active),
                  _condition_query_key(viewer), _footprint_query_key(engine, viewer))
    # A square probe is rebuilt per call but carries exactly its position,
    # active/conditions/summon/perception_cell (senses.PROBE_FIELDS), so its
    # content is the key: the same square asked by another ability shares it.
    seen_key = ((seen.position.x, seen.position.y, seen.position.z) if cell_probe else
                (id(seen), seen.entity_id, seen.position.x, seen.position.y, seen.position.z,
                 bool(seen.active),
                 _condition_query_key(seen), _footprint_query_key(engine, seen),
                 str(getattr(seen, 'summon', None))))
    key = ('perceives', viewer_key, seen_key, locate_concealed, sight_only, sight_action)
    return invariant_query(engine, key,
                           lambda: _perceives(engine, viewer, seen,
                                              locate_concealed=locate_concealed,
                                              sight_only=sight_only),
                           refs=(viewer, seen))


def _perceives(engine: Any, viewer: Any, seen: Any, *, locate_concealed: bool = False,
               sight_only: bool = False) -> bool:
    # Position/footprint queries (reaction teleport destinations) copy the actor
    # and retain its id. Only the actual actor object is a self-target here.
    if not engine._on_battlefield(viewer) or not engine._on_battlefield(seen):
        return False
    if not viewer.active or viewer is seen:
        return False
    if not physical_sight(engine, viewer, seen):
        return False
    from . import zones

    hidden_ids = set(rules().get("hidden_conditions") or [])
    blinded_ids = set(rules().get("blinded_conditions") or [])
    # A viewer-specific suppression removes only those condition instances.
    # Keep the same ownership rules as attack modes; walls, area visibility and
    # the viewer's own blindness still apply independently below.
    # Innate senses are checked below. Their derived masks call perception,
    # so query only plug-in suppression here to avoid recursion on Hidden.
    masked = plugin_condition_masks(engine, viewer, seen, sight_only=sight_only).get(seen.entity_id, set())
    target_hidden = any(iid not in masked and c.condition_id in hidden_ids
                        for iid, c in seen.conditions.items())
    viewer_blinded = any(c.condition_id in blinded_ids for c in viewer.conditions.values())
    available = perception_senses(engine, viewer, sight_only=sight_only)

    if viewer_blinded:
        if sight_only:
            return False
        return any(sense in (("blindsight",) if getattr(seen, "perception_cell", False)
                             else ("blindsight", "spiritual_sense"))
                   and _within(engine, viewer, seen, reach(engine, viewer, sense, seen))
                   for sense in available)

    from . import lighting

    # A square the viewer cannot see into is no sight target at all: the light model says Heavily Obscured, and only a
    # sense that sees through darkness lets the creature act anyway (docs/specs/LIGHTING_SPEC.md §2.5, §4.1 step 7).
    # Darkness, smoke and fog areas keep their own route below, so this adds unlit squares rather than re-deciding them.
    if lighting.creature_heavily_obscured(engine, viewer, seen) and not _sees_into_dark(engine, viewer, seen, available):
        return False

    if locate_concealed and target_hidden:
        kinds = [sense for sense in available if (_kinds().get(sense) or {}).get("sees_hidden")]
        return (not zones.hidden_from(engine, viewer, seen, sight_only=sight_only)
                and any(_within(engine, viewer, seen, reach(engine, viewer, sense, seen)) for sense in kinds))

    if zones.hidden_from(engine, viewer, seen, sight_only=sight_only):
        return False
    invisible = any(iid not in masked and c.condition_id == "condition:typed.invisible"
                    for iid, c in seen.conditions.items())
    if invisible:
        kinds = [sense for sense in available if (_kinds().get(sense) or {}).get("sees_hidden")]
        return any(_within(engine, viewer, seen, reach(engine, viewer, sense, seen)) for sense in kinds)
    return True


def _sees_into_dark(engine: Any, viewer: Any, seen: Any, available: dict[str, dict[str, Any]]) -> bool:
    """Whether a sense that sees through darkness or obscurement -- Blindsight, Truesight, Spiritual Sense -- reaches
    this square. Such a sense does not change the light level; it lets the creature act anyway (spec §2.8)."""
    for sense in available:
        if not (set((_kinds().get(sense) or {}).get("through") or ()) & {"darkness", "obscured"}):
            continue
        if _within(engine, viewer, seen, reach(engine, viewer, sense, seen)):
            return True
    return False


def sees_into_dark(engine: Any, viewer: Any, seen: Any) -> bool:
    """Public form of _sees_into_dark for callers asking one viewer about one creature (combat/zones.py attack modes)."""
    return _sees_into_dark(engine, viewer, seen, perception_senses(engine, viewer))


def physical_sight(engine: Any, viewer: Any, seen: Any) -> bool:
    """Perception ray from the creature's real position, including altitude.

    Shared by terrain probes, creature perception and sight-independent senses.
    Effect origins never move the viewer's eyes. Explicit source-backed
    projectile sight routes retain their scoped attack exception; ordinary fog
    and AI knowledge queries have no attack route. Empty-cell probes retain
    their requested z; finite terrain and
    object spans are resolved by the grid's common line-of-sight geometry.
    """
    from .shot_geometry import sight
    alternate = sight(engine, viewer, seen)
    if alternate is not None:
        return alternate
    if (getattr(seen, 'perception_cell', False) and viewer.position.z
            and not getattr(seen, 'near_side', False)):
        # An airborne floor/surface probe sees the actual surface, rather than
        # the near face of an obstacle occupying its target square. Creature
        # rays retain their endpoint/volume policy. Use physical base-altitude
        # origins, not a rounded voxel or a scoped projectile origin.
        from .terrain_occlusion import segment_clear
        from .gate2_runtime_models import Position
        origins = engine._actor_cells(viewer)
        endpoint = getattr(seen, 'surface_position', seen.position)
        return any(segment_clear(engine.grid, Position(x=x, y=y, z=viewer.position.z),
                                 endpoint, obscured_cells=engine._obscured_cells())
                   for x, y in origins)
    elevated = viewer.position.z or seen.position.z or engine.grid.finite_heights
    cells = engine._actor_volume if elevated else engine._actor_cells
    target = (seen.position,) if getattr(seen, "perception_cell", False) else cells(seen)
    return engine.grid.line_of_sight_between_cell_sets(
        cells(viewer), target, obscured_cells=engine._obscured_cells())


def pinpoints(engine: Any, viewer: Any, seen: Any) -> bool:
    """Whether a sense that pinpoints (Tremorsense, Spiritual Truesight) reaches ``seen``; a creature a Sensing Eye array's owner
    has located with its Pulse is pinpointed by that owner (Formations: "you know its location, even if it is Invisible or Hidden")."""
    if not engine._on_battlefield(viewer) or not engine._on_battlefield(seen):
        return False
    if any(condition.condition_id == "condition:typed.formation_located" for condition in seen.conditions.values()):
        from .ext import formations

        if formations.located(engine, viewer, seen):
            return True
    from . import ext
    replies = ext.run_strict('pinpoint_target', engine, viewer, seen)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('pinpoint_target requires a boolean or None')
    if True in replies:
        return True
    kinds = [sense for sense in of(engine, viewer) if (_kinds().get(sense) or {}).get("pinpoints")]
    return any(_within(engine, viewer, seen, reach(engine, viewer, sense, seen)) for sense in kinds)


#: The exact fields the square probe below carries. A per-probe plug-in hook may rely on these and nothing else.
PROBE_FIELDS = ("entity_id", "position", "active", "conditions", "summon", "perception_cell")


def cell_probe(position: Any) -> Any:
    """The lightweight stand-in ``perceives_cell`` uses to ask about one empty square.

    A square is not a creature, but the perception policy is shared with creatures, so this probe is passed
    through ``perceives`` and on to every ``masked_conditions`` subscriber as if it were a target. It carries
    only ``PROBE_FIELDS``: no team, no turn flags, no name, no modifiers, no resources. Plug-in hooks that run
    per probe must ask ``is_creature`` first (a square never owns a printed rule) rather than reading creature
    attributes off it.
    """
    from types import SimpleNamespace
    return SimpleNamespace(entity_id="perception:cell", position=position,
                            active=True, conditions={}, summon=None,
                            perception_cell=True)


def is_creature(actor: Any) -> bool:
    """Whether ``actor`` is a real fighter (or summon) rather than the square probe or nothing at all.

    The shared per-probe entry points (``masked_conditions``, ``darkness_lifted``) are called once per visible
    square during a fog projection, with a probe in place of one or both creatures. A plug-in hook that reads a
    creature attribute (team, turn flags, name) must return early here: the probe has none of them, and a
    square can never own a printed rule, so skipping it is always the right answer and never a behaviour change
    for a real actor.
    """
    return actor is not None and not getattr(actor, "perception_cell", False)


def perceives_cell(engine: Any, viewer: Any, position: Any) -> bool:
    """Public square-level sight query, using ``perceives``' endpoint policy.

    A square is empty terrain, not a living creature: Spiritual Sense and
    pinpointing senses do not reveal it. Blindsight can reveal terrain while
    Blinded. Heavy areas use the same inside/outward and directional decisions
    as creatures; only obscuring walls block intervening ray cells. No separate
    far-side rule is inferred from painted area opacity.
    """
    from .read_queries import memo
    key = ('perceives_cell', id(viewer), (position.x, position.y, position.z))
    return memo(engine, key, lambda: (viewer, perceives(engine, viewer, cell_probe(position))))[1]


def surface_probe(x, y, feet):
    """Exact terrain/object surface for table sight; never persisted.

    Sense/area rules use the native voxel containing the surface, while the
    physical ray uses its authored height without rounding.
    """
    from fractions import Fraction
    from .space import SurfacePoint
    from .gate2_runtime_models import Position
    probe = cell_probe(Position(x=x,y=y,z=feet//5))
    probe.surface_position = SurfacePoint(x,y,Fraction(feet,5))
    return probe


def perceives_object(engine, viewer, obj):
    """Table object visibility independent of the floor beneath its body.

    Above a known top, query that surface. Other views retain the grid's near
    face endpoint rule; roofs and senses still apply. Uses public footprint
    geometry, not object-kind guesses or another plug-in's private helpers.
    """
    from .object_geometry import target_cells
    top = None if obj.height_ft is None else obj.position.z*5+obj.height_ft
    for cell in target_cells(engine,obj):
        if top is not None and viewer.position.z*5 >= top:
            probe = surface_probe(cell.x,cell.y,top)
        else:
            probe = cell_probe(cell)
            probe.near_side = True
        if perceives(engine,viewer,probe):
            return True
    return False


@pure
def perception(engine: Any, viewer: Any) -> dict[str, Any]:
    """Public tabletop projection for one viewer, built on ``perceives``.

    Cells use ``perceives_cell``; creatures use concealed-target perception or
    pinpointing. Teammates remain known, as in target knowledge. Positioned
    downed/defeated creatures remain targets; only active creatures are viewers.
    sensed_creatures maps already-known ids to the senses locating them when
    their creature is not seen by the sight-only perception query.
    Blindsight's combat sight permission is unchanged. It explains knowledge; it
    never grants perception. The result is derived coordinates/string ids and
    reason names, never saved state.
    """
    from .gate2_runtime_models import Position

    if not viewer.active or viewer.position is None:
        return {"cells": [], "creatures": [], "sensed_creatures": {}}
    creatures = []
    sensed = {}
    for target in engine.state.actors.values():
        if target.position is None:
            continue
        perceived = perceives(engine, viewer, target, locate_concealed=True)
        pinpointed = pinpoints(engine, viewer, target)
        if not (target.entity_id == viewer.entity_id or target.team_id == viewer.team_id
                or perceived or pinpointed):
            continue
        creatures.append(target.entity_id)
        if target.entity_id == viewer.entity_id or ordinary_sight_perceives(engine, viewer, target):
            continue
        reasons = []
        if perceived and perceives_without_sight(engine, viewer, target):
            reasons.extend(sense for sense in ("spiritual_sense", "blindsight")
                           if _within(engine, viewer, target, reach(engine, viewer, sense, target)))
        if pinpointed:
            reasons.extend(sense for sense in of(engine, viewer)
                           if (_kinds().get(sense) or {}).get("pinpoints")
                           and _within(engine, viewer, target, reach(engine, viewer, sense, target)))
            if not reasons:
                reasons.append("pinpointed")
        sensed[target.entity_id] = reasons or ["allied_location" if target.team_id == viewer.team_id
                                              else "known_location"]
    result = {
        "cells": [[x, y] for y in range(engine.grid.height) for x in range(engine.grid.width)
                  if perceives_cell(engine, viewer, Position(x=x, y=y))],
        "creatures": creatures,
        "sensed_creatures": sensed,
    }
    if viewer.position.z:
        # Separate sense/area restrictions from geometric shadows. The browser
        # projects the latter continuously; only rule-limited surfaces need a
        # cell mask. Roof tops are queried at exact authored feet, never rounded
        # to a five-foot voxel and never substituted for the floor beneath them.
        from .terrain_occlusion import segment_clear, sight_geometry
        origins = [Position(x=x, y=y, z=viewer.position.z) for x,y in engine._actor_cells(viewer)]
        seen = {tuple(c) for c in result['cells']}
        limits = []
        for y in range(engine.grid.height):
            for x in range(engine.grid.width):
                if (x,y) not in seen and any(segment_clear(engine.grid, origin, Position(x=x,y=y)) for origin in origins):
                    limits.append([x,y,0])
        geometry = sight_geometry(engine.grid)
        tops = {(r['x'],r['y'],r['top_ft']) for r in geometry['roofs']}
        tops.update((r['x'],r['y'],r['top_ft']) for r in geometry['volumes']
                    if r.get('solid') and r['top_ft'] is not None)
        for x,y,top in sorted(tops):
            if top > viewer.position.z*5:
                continue
            probe = surface_probe(x,y,top)
            endpoint = probe.surface_position
            if (not perceives(engine,viewer,probe)
                    and any(segment_clear(engine.grid, origin, endpoint) for origin in origins)):
                limits.append([x,y,top])
        if limits:
            result['surface_limits'] = limits
    # All viewers receive object-body visibility, including ground-level viewers.
    # A visible floor is not proof that a temporary image/object is visible.
    result['objects'] = [obj.object_id for obj in (*engine.state.objects.values(), *engine.state.map_images.values())
                         if not obj.destroyed and not obj.suppressed and perceives_object(engine,viewer,obj)]
    from .information_results import for_observer, describe
    information = for_observer(engine, viewer)
    if information:
        result['information'] = information
        result['information_text'] = describe(engine, viewer, information)
    return result


def ordinary_sight_perceives(engine: Any, viewer: Any, seen: Any) -> bool:
    """Creature vision, using the combat perception path with alternate senses off."""
    return perceives(engine, viewer, seen, locate_concealed=True, sight_only=True)


def perceives_without_sight(engine: Any, viewer: Any, seen: Any) -> bool:
    """Alternate-sense capability, whether or not the viewer is Blinded.

    Blindsight and Spiritual Sense must reach the queried creature or footprint;
    ordinary sight alone cannot satisfy sight-independent attack/teleport rules.
    """
    return (viewer.active and viewer is not seen
            and physical_sight(engine, viewer, seen)
            and any(_within(engine, viewer, seen, reach(engine, viewer, sense, seen))
                    for sense in ("blindsight", "spiritual_sense")))


def plugin_condition_masks(engine: Any, attacker: Any, target: Any, *, sight_only: bool = False) -> dict[str, set[str]]:
    """Shared plug-in masks for perception and attack-mode condition queries.

    Innate sense masks are derived separately, because they query perception.
    Legacy hook answers are visual by default. A hook may return
    ``{"conditions": {entity_id: {condition_ids}}, "visual": False}`` when a
    nonvisual sense lets its owner ignore concealment. Sight-only presentation
    skips those masks; combat queries retain them. Empty answers are inert and
    never change stored conditions.
    """
    from . import ext

    out: dict[str, set[str]] = {}
    for extra in ext.run("masked_conditions", engine, attacker, target):
        if not isinstance(extra, dict):
            continue
        visual = extra.get("visual", True)
        conditions = extra.get("conditions", extra)
        if sight_only and visual is False:
            continue
        if not isinstance(conditions, dict):
            continue
        for entity_id, ids in conditions.items():
            out.setdefault(entity_id, set()).update(ids)
    return out


def masked_conditions(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]]:
    """The conditions whose Advantage or Disadvantage do not count for this attack (2024 Invisible: "If a creature can
    somehow see you, you don't gain this benefit against that creature"): the target's Hidden/Invisible when the attacker
    sees it with Blindsight or Truesight, the attacker's when the target sees it; a Blinded creature's own Blinded toward
    a creature its Blindsight reaches. Read by Gate4ControllerEngine._attack_mode."""
    hidden = set(rules().get("hidden_conditions") or [])
    blinded = set(rules().get("blinded_conditions") or [])
    out: dict[str, set[str]] = {}
    for who, other in ((target, attacker), (attacker, target)):
        rows = {iid for iid, condition in who.conditions.items() if condition.condition_id in hidden}
        if rows and sees_hidden(engine, other, who):
            out.setdefault(who.entity_id, set()).update(rows)
        rows = {iid for iid, condition in who.conditions.items() if condition.condition_id in blinded}
        if rows and perceives_without_sight(engine, who, other):
            out.setdefault(who.entity_id, set()).update(rows)
    for entity_id, ids in plugin_condition_masks(engine, attacker, target).items():
        out.setdefault(entity_id, set()).update(ids)
    return out


def finds(engine: Any, searcher: Any, hidden_one: Any) -> bool:
    """A Search finds a hidden creature with no roll when the searcher's senses reach it (proposed ruling)."""
    return perceives(engine, searcher, hidden_one, locate_concealed=True) or pinpoints(engine, searcher, hidden_one)


def summary(engine: Any, actor: Any) -> list[str]:
    """"Darkvision 60 ft", ... -- for the sheet and the fight log."""
    return [f"{sense.replace('_', ' ').title()} {row['range_ft']} ft" for sense, row in of(engine, actor).items()]
