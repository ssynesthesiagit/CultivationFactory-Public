"""Hollow Field (CL10) — tianxia.subpath.qi.void_touched_cultivator.feature.hollow_field.

The record is one lasting Qi field empowered by Secret authority (not a Spirit
Awakening Domain). It is placed through the table's ordinary zone machinery
(combat/zones.py): a 20-foot sphere at a square up to 60 feet away, 1 minute,
Concentration. Ending the Concentration removes the field and everything it
still holds (gate2_engine._end_concentration -> zones.remove).

What lives here (the whole record, one plug-in):

* ``compile_action``  seals the field's zone_spec (shape, sound, light and the
  enter/start Charisma save) onto the acquired action.
* ``hollow_field_choose`` (effect) runs inside the field's own enter/start
  trigger after the native Charisma save. It asks the owning player (or decides
  for an AI owner) which printed Hollowing effect a failed save takes, which
  lesser effect a successful one takes, and whether to Deepen the Hollow.
* Continuous inside-field rules use the engine's existing facts, never a tag:
  ``technique_cost_floor`` (+1 CP), ``resource_gain_allowed`` (no CP regain),
  ``healing_pending`` (hostile-granted Temporary HP halved), ``technique_used``
  (no Reactions after a powered technique), ``candidate_allowed`` (a suppressed
  Sphere talent / Domain Armament / system is not offered) and
  ``teleport_check`` (a lower-Source-CL crossing fails unless the owner permits
  it).

Hostility is the engine's own ``team_id`` difference; nothing here reads a
damage name, a tag or test metadata. Every hook is default-inert: it returns
early unless a recorded Hollow Field (or a marker that field put on a creature)
is present, so no other character's light, sound, costs, regeneration,
Reactions or teleports change.

Marker conditions used by the printed Hollowing/lesser effects all carry an
expiry the engine removes (the start of the affected creature's next turn),
keep only integers and strings, and get plain labels from ``status_description``.
The Deepen suppression is stored on the marker condition and on the field, so
it ends when the creature leaves the field or the field ends; it never changes
the saved-fight schema. Shared benefit_suppression.suppress_sources suspends
already-active contributions, including areas and effects on other recipients.
Their original durations continue to pass; only still-live effects return.

Hooks used (all documented in combat/ext/__init__.py):
  compile_action             the field's zone (sound, light, enter/start save)
  zones                      current, spatially clipped dim-to-darkness areas
  technique_cost_floor       hostile CP costs +1 (and the lesser next-cost +1)
  resource_gain_allowed      hostile creatures cannot regain CP
  healing_pending            hostile-granted Temporary HP is halved
  technique_used             no Reactions after a powered technique
  candidate_allowed          suppressed systems/armament/concentration are not offered
  row_allowed                the same for Reaction rows
  teleport_check             the field's Source-CL crossing rule and the Hollowing bar
  turn_start / after_move / teleport_settled / event  Deepen release
  status_description         plain words for the marker conditions
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

FEATURE = "tianxia.subpath.qi.void_touched_cultivator.feature.hollow_field"
FAMILY = "tianxia.subpath.qi.void_touched_cultivator"
MARK_NAME = "Void Mark"
ZONE_TAG = "hollow_field"
DEEPEN = "hollow_deepen"
NEXT_COST = "condition:typed.next_cultivation_cost_increased"
NO_CONCENTRATION = "condition:typed.cannot_begin_concentration"
ARMAMENT = "condition:typed.domain_armament_suppressed"
REACTION_AFTER = "condition:typed.reactions_after_powered_technique"
SYSTEM = "condition:typed.suppressed_system"
TELEPORT_BAR = "condition:typed.teleport_barred_by_hollow_field"
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
NO_REACTIONS = "condition:typed.reaction_denied"

# The printed Hollowing and lesser lists, in printed order. ``key`` is stored in
# the trigger payload and never shown to a player.
HOLLOWING = (
    ("speed15", "Speed is reduced by 15 feet"),
    ("suppress_talent", "One active Sphere talent is suppressed"),
    ("suppress_armament", "Domain Armament movement and attacks are suppressed"),
    ("no_concentration", "It cannot begin Concentration"),
    ("no_audible", "It cannot activate audible techniques"),
    ("no_healing", "It cannot restore Hit Points"),
    ("no_teleport", "It cannot use teleportation or planar movement"),
)
LESSER = (
    ("speed5", "Speed is reduced by 5 feet"),
    ("reaction_after", "It cannot take Reactions after activating a powered technique"),
    ("next_cost", "Its next Cultivation Point cost increases by 1"),
)
SYSTEM_KINDS = {
    "sphere": "Sphere",
    "subpath": "Subpath",
    "method": "Method",
    "golden_core_form": "Golden Core Form",
    "nascent_soul": "Nascent Soul feature",
    "domain_armament": "Domain Armament system",
    "foundation": "Foundation active system",
    "path_recovery": "Path resource recovery feature",
}


# ------------------------------------------------------------------------------------------------ ownership and fields
def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def source_of(action: Any) -> str:
    return str(_typed(action).get("source") or "")


def owns(engine: Any, actor: Any) -> bool:
    """The actor owns the acquired record (its sealed action carries the Void Scar)."""
    from . import void_touched_cultivator as void

    for action_id in getattr(actor, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        if void.family_source(action) == FEATURE and str(_typed(action).get("void_scar") or ""):
            return True
    return False


def _zones_module() -> Any:
    from .. import zones

    return zones


def fields(engine: Any) -> list[Any]:
    """Active stored Hollow Fields, oldest first (map/painted areas never carry the tag)."""
    zones = _zones_module()
    return [zone for zone in zones.typed_zones(engine)
            if (((zone.trigger_profile or {}).get("profile") or {}).get(ZONE_TAG)
                or (zone.trigger_profile or {}).get(ZONE_TAG)) and zone.active]


def _holds(engine: Any, zone: Any, cell: Any) -> bool:
    """Native volume membership: the field's sphere holds ``cell`` at its own altitude too."""
    if cell is None:
        return False
    from ..spatial_areas import positions_inside_zone

    return positions_inside_zone(engine, [(cell.x, cell.y, cell.z)], zone)


def fields_covering(engine: Any, actor: Any, cell: Any) -> list[Any]:
    """Every active field that holds the traveller where it stands or ``cell`` at either end."""
    zones = _zones_module()
    return [zone for zone in fields(engine)
            if zones.actor_inside_zone(engine, actor, zone) or _holds(engine, zone, cell)]


def _field_at(engine: Any, cell: Any) -> Any | None:
    """The oldest active field whose volume holds ``cell`` (space and altitude, not just x/y)."""
    return next((zone for zone in fields(engine) if _holds(engine, zone, cell)), None)


def _hostile(engine: Any, zone: Any, actor: Any) -> bool:
    """Native hostility: the field owner and the creature are on different teams."""
    owner = engine.state.actors.get(zone.owner_id)
    return owner is not None and actor is not None and owner.team_id != actor.team_id


def _field_cl(zone: Any) -> int:
    profile = (zone.trigger_profile or {}).get("profile") or {}
    numbers = (zone.trigger_profile or {}).get("numbers") or {}
    return int(profile.get("source_cl") or numbers.get("source_cl") or numbers.get("cl") or 1)


def _field_dc(zone: Any) -> int:
    return int(((zone.trigger_profile or {}).get("numbers") or {}).get("save_dc") or 10)


def _note(engine: Any, zone: Any, text: str, targets: Any = ()) -> None:
    owner = engine.state.actors.get(zone.owner_id)
    note(engine, zone.source_definition_id, owner or zone.owner_id, text, tuple(targets or ()))


def _hostile_fields(engine: Any, actor: Any) -> list[Any]:
    zones = _zones_module()
    return [zone for zone in fields(engine)
            if _hostile(engine, zone, actor) and zones.actor_inside_zone(engine, actor, zone)]


# ------------------------------------------------------------------------------------------------ the zone the action leaves
@hook("compile_action")
def seal_zone(action: Any, info: dict[str, Any]) -> Any:
    """Give the acquired action its complete Hollow Field zone (or leave it sealed and inert)."""
    from . import void_touched_cultivator as void

    if void.family_source(action) != FEATURE:
        return None
    typed = dict(_typed(action))
    # The inherited family hook seals the Scar, but this transform must be right
    # whatever order the two subscribers run in: read the recorded choice itself.
    from character_creation.acquisition_choices import recorded

    scar = str(typed.get("void_scar") or recorded(info.get("owner_sheet") or {}, void.PARENT).get("void_scar") or "")
    if not scar:
        # No recorded acquisition: no field at all (the inherited admission hook
        # already refuses the action; this keeps a plain sphere of Darkness from
        # being inferred and made inert).
        # Drop the key rather than store None: the core typed-candidate check reads
        # `typed["zone_spec"].get(...)` and would crash on an explicit None.
        typed.pop("zone_spec", None)
        params = {**action.parameters, "typed": typed, "inert": True}
        return action.model_copy(update={"parameters": params})
    typed["void_scar"] = scar
    numbers = dict(typed.get("numbers") or {})
    cl = int(numbers.get("source_cl") or numbers.get("cl") or 1)
    spec = {
        "name": "Hollow Field",
        "shape": "sphere",
        "size_ft": 20,
        "centered_on_self": False,
        "duration": {"kind": "minutes", "amount": 1, "concentration": True},
        "terrain": [],
        "difficult": None,
        # Bright light becomes dim throughout the sphere. ambient_darkness
        # projects only its currently dim-lit squares as Darkness; no cast-time
        # sample or light source is created by the field.
        "obscured": "light",
        "visual": {"material": "void", "obscured": "light", "darkness": False,
                   "light": None},
        "follows_owner": False,
        "triggers": [{
            "id": FEATURE + ":save",
            "name": "Hollow Field",
            "on": ["enter", "start"],
            "who": "hostile",
            "effects": [{
                "type": "save",
                "ability": "CHA",
                "on_fail": [{"type": "hollow_field_choose", "outcome": "failed"}],
                "on_success": [{"type": "hollow_field_choose", "outcome": "succeeded"}],
            }],
        }],
        # Ordinary sound is reduced to a whisper for everyone inside: the engine's
        # own sound reader (combat/zones.muffled, used by combat/stealth.py).
        "inside": [{
            "id": FEATURE + ":whisper",
            "name": "Hollow Field: ordinary sound is a whisper",
            "who": "any",
            "muffles": True,
            "rule": {},
            "reading": "Ordinary sound inside the field is reduced to a whisper.",
        }],
        "profile": {ZONE_TAG: 1, "source_cl": cl},
    }
    params = {**action.parameters, "typed": {**typed, "zone_spec": spec}, "inert": False}
    return action.model_copy(update={"parameters": params})


def _is_field(zone: Any) -> bool:
    profile = zone.trigger_profile or {}
    return bool((profile.get("profile") or {}).get(ZONE_TAG) or profile.get(ZONE_TAG))


@hook("zones")
def ambient_darkness(engine: Any) -> list[Any]:
    """Project the dim-lit part of each live field as Darkness, on every read.

    Stored light emitters (and painted areas) supply the current surroundings.
    Bright takes precedence over dim where they overlap. Hollow Fields are
    reducers, never emitters for another field. The unlit table defaults to
    bright, as before; an existing darkness area remains dark independently.
    Derived zones carry sight only, never saves, sounds or another field tag.
    Exact native volume membership is projected into separate horizontal
    slices, so a small lamp never darkens an entire vertical column.
    """
    zones = _zones_module()
    stored = [zone for zone in engine.state.zones.values() if zone.active]
    held = [zone for zone in stored if _is_field(zone)]
    if not held:
        return []
    emitters = []
    from ..spatial_areas import zone_contains_cells, zone_volume_cells
    from ..gate2_runtime_models import Position

    for other in [*stored, *zones.map_zones(engine)]:
        if _is_field(other):
            continue
        light = (other.trigger_profile.get("visual") or {}).get("light")
        level = light.get("level") if isinstance(light, dict) else None
        if level in ("bright", "dim"):
            emitters.append((other, level))
    out = []
    if not any(level == "dim" for _zone, level in emitters):
        return []
    for zone in held:
        planes: dict[int, list[Any]] = {}
        for point in zone_volume_cells(engine, zone):
            levels = {level for other, level in emitters if zone_contains_cells(engine, [point], other)}
            if "dim" in levels and "bright" not in levels:
                x, y, z = point
                planes.setdefault(z, []).append(Position(x=x, y=y, z=z))
        for z, cells in sorted(planes.items()):
            out.append(zone.model_copy(update={
                "zone_id": zone.zone_id + f":darkness:{z}", "affected_cells": tuple(cells),
                "center": zone.center.model_copy(update={"z": z}), "radius_cells": 0,
                "concentration_link": False,
                "trigger_profile": {
                    "kind": zones.KIND, "name": "Hollow Field: dim light becomes darkness",
                    "shape": "painted", "footprint_is_authoritative": True,
                    "obscured": "heavy", "visual": {"darkness": True, "material": "darkness"},
                    "triggers": [], "inside": [], "follows_owner": False,
                }}))
    return out


def _zone_for_source(engine: Any, source: str) -> Any | None:
    """The stored field whose declared trigger id is ``source`` (a zone trigger's typed source)."""
    for zone in fields(engine):
        if any(str(trigger.get("id") or "") == str(source) for trigger in (zone.trigger_profile or {}).get("triggers") or []):
            return zone
    return None


def _zone_for_action(engine: Any, action_source: str) -> Any | None:
    """The stored field placed by this catalog action (one field per action; a recast replaces it)."""
    for zone in fields(engine):
        if zone.source_definition_id == str(action_source):
            return zone
    return None


# ------------------------------------------------------------------------------------------------ the save and its choices
def _answerable(engine: Any, actor: Any) -> bool:
    from .needle import answerable

    return answerable(engine, actor)


def _ai_choice(options: list[str], preferred: list[str]) -> str | None:
    return next((key for key in preferred if key in options), options[0] if options else None)


def _ask(engine: Any, owner: Any, zone: Any, target: Any, key: str, options: list[str], labels: dict[str, str],
         prompt: str, preferred: list[str], *, allow_decline: bool = False) -> list[str]:
    from .needle import ask

    intent = getattr(engine, "_active_intent", None)
    checkpoint = f"NEEDLE:{key}:{zone.zone_id}:{target.entity_id}:{getattr(intent, 'intent_id', '')}"
    return ask(engine, intent, checkpoint, owner, "choice:needle.hollow_field", options, labels=labels,
               prompt=prompt, preferred=preferred, name="Hollow Field", target_id=target.entity_id,
               allow_decline=allow_decline)


def _choose(engine: Any, owner: Any, zone: Any, target: Any, outcome: str) -> str | None:
    failed = outcome == "failed"
    table = HOLLOWING if failed else LESSER
    options = [key for key, _label in table]
    preferred = ["speed15"] if failed else ["speed5"]
    if _answerable(engine, owner):
        prompt = (f"Hollow Field: {target.display_name} {'failed' if failed else 'succeeded on'} its Charisma save "
                  f"inside {owner.display_name}'s Hollow Field. Choose one {'Hollowing' if failed else 'lesser'} "
                  f"effect on {target.display_name}; it lasts until the start of {target.display_name}'s next turn.")
        answer = _ask(engine, owner, zone, target, "hollow_choice", options, dict(table), prompt, preferred)
        return answer[0] if answer else None
    return _ai_choice(options, preferred)


def _until_target_next_turn(target: Any) -> str:
    from .effect_durations import token

    return token("start", target.entity_id, int(target.turns_started) + 1)


@effect("hollow_field_choose", harmful=True)
def hollow_field_choose(ctx: Any, row: dict[str, Any]) -> None:
    """The user's choice after the field's Charisma save (printed Hollowing/lesser effect)."""
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    zone = _zone_for_action(engine, ctx.action.source_definition_id) or _zone_for_source(engine, str(ctx.source))
    if zone is None or target is None or not target.active or not owns(engine, owner):
        return
    if not _hostile(engine, zone, target):
        return
    outcome = str(row.get("outcome") or "failed")
    chosen = _choose(engine, owner, zone, target, outcome)
    if chosen is None:
        return
    apply_effect(engine, owner, zone, target, chosen)
    if outcome == "failed":
        _deepen(engine, owner, zone, target)


def _effect_context(engine: Any, owner: Any, zone: Any, target: Any) -> Any:
    from .. import typed_executor

    action = engine.action_catalog.get(zone.source_definition_id)
    numbers = dict((zone.trigger_profile or {}).get("numbers") or {})
    typed = {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []}
    return typed_executor.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed,
                                  [target], target, {})


def apply_effect(engine: Any, owner: Any, zone: Any, target: Any, key: str) -> None:
    from .. import typed_executor

    expires = _until_target_next_turn(target)
    ctx = _effect_context(engine, owner, zone, target)
    if key in ("speed15", "speed5"):
        typed_executor.run_effects(ctx, [{
            "type": "speed", "applies_to": "target", "flat": -15 if key == "speed15" else -5,
            "formula": "none", "duration": "until_start_of_next_turn", "expires_on": expires,
            "evidence": "Speed is reduced by 15 feet" if key == "speed15" else "Speed is reduced by 5 feet",
        }])
    elif key == "suppress_talent":
        _suppress_active_talent(engine, owner, zone, target)
    elif key == "suppress_armament":
        engine._apply_condition(target, ARMAMENT, zone.source_definition_id, owner.entity_id, expires_on=expires,
                                data={"label": f"Hollow Field: {target.display_name}'s Domain Armament cannot move or "
                                               f"attack until the start of its next turn."})
        _note(engine, zone, f"Hollow Field: {target.display_name}'s Domain Armament movement and attacks are "
                            f"suppressed until the start of its next turn.", (target,))
    elif key == "no_concentration":
        engine._apply_condition(target, NO_CONCENTRATION, zone.source_definition_id, owner.entity_id, expires_on=expires,
                                data={"label": f"Hollow Field: {target.display_name} cannot begin Concentration until "
                                               f"the start of its next turn."})
        _note(engine, zone, f"Hollow Field: {target.display_name} cannot begin Concentration until the start of its "
                            f"next turn.", (target,))
    elif key == "no_audible":
        typed_executor.run_effects(ctx, [{
            "type": "condition", "applies_to": "target", "condition": "silenced", "expires_on": expires,
            "evidence": "It cannot activate audible techniques",
        }])
    elif key == "no_healing":
        typed_executor.run_effects(ctx, [{
            "type": "healing_reduction", "applies_to": "target", "expires_on": expires,
            "evidence": "It cannot regain Hit Points",
        }])
    elif key == "no_teleport":
        # A custom rule key, so the engine's native no_teleport reader does not
        # apply the bar without the printed "equal or higher Secret authority"
        # exception (see hollow_teleport).
        engine._apply_condition(target, TELEPORT_BAR, zone.source_definition_id, owner.entity_id, expires_on=expires,
                                data={"rule": {"hollow_teleport_bar": True}, "cl": _field_cl(zone),
                                      "label": f"Hollow Field: {target.display_name} cannot teleport or move between "
                                               f"planes until the start of its next turn."})
        _note(engine, zone, f"Hollow Field: {target.display_name} cannot use teleportation or planar movement until "
                            f"the start of its next turn.", (target,))
    elif key == "reaction_after":
        engine._apply_condition(target, REACTION_AFTER, zone.source_definition_id, owner.entity_id, expires_on=expires,
                                data={"rule": {"no_reactions_after_powered": True},
                                      "label": f"Hollow Field: after {target.display_name} activates a powered "
                                               f"technique it cannot take Reactions until the start of its next turn."})
        _note(engine, zone, f"Hollow Field: after {target.display_name} activates a powered technique it cannot take "
                            f"Reactions until the start of its next turn.", (target,))
    elif key == "next_cost":
        engine._apply_condition(target, NEXT_COST, zone.source_definition_id, owner.entity_id, expires_on=expires,
                                data={"label": f"Hollow Field: {target.display_name}'s next Cultivation Point cost is 1 "
                                               f"higher, until the start of its next turn."})
        _note(engine, zone, f"Hollow Field: {target.display_name}'s next Cultivation Point cost is 1 higher, until the "
                            f"start of its next turn.", (target,))


def _suppress_active_talent(engine: Any, owner: Any, zone: Any, target: Any) -> None:
    """Suppress one active Sphere talent through the engine's ability-lockout model."""
    from . import ability_lockout, needle

    options: list[tuple[str, str]] = []
    for key, action_id in ability_lockout.used(engine, target):
        action = engine.action_catalog.get(action_id)
        if _typed(action).get("sphere") or str(key).startswith("TAL_"):
            options.append((key, action_id))
    if not options:
        _note(engine, zone, f"Hollow Field: {target.display_name} has no active Sphere talent to suppress.", (target,))
        return
    labels = {key: str(engine.action_catalog[action_id].display_name) for key, action_id in options}
    preferred = [options[0][0]]
    if _answerable(engine, owner):
        intent = getattr(engine, "_active_intent", None)
        answer = needle.ask(engine, intent,
                            f"NEEDLE:hollow_talent:{zone.zone_id}:{target.entity_id}:{getattr(intent, 'intent_id', '')}",
                            owner, "choice:needle.hollow_field_talent", list(labels), labels=labels,
                            preferred=preferred, name="Hollow Field", target_id=target.entity_id,
                            prompt=(f"Hollow Field: {target.display_name} failed its Charisma save. Choose one active "
                                    f"Sphere talent of {target.display_name} to suppress until the start of its next "
                                    f"turn."))
        key = answer[0] if answer else preferred[0]
    else:
        key = preferred[0]
    action = engine.action_catalog[next(aid for k, aid in options if k == key)]
    ability_lockout.lock(_effect_context(engine, owner, zone, target), target, ability_lockout.key_of(action),
                         action.source_definition_id,
                         {"mode": "barred", "expires_on": "START_OF_TARGET_NEXT_TURN",
                          "source": zone.source_definition_id})
    from .benefit_suppression import suppress_sources
    from .ability_source import mechanic_at

    binding = next(c for c in reversed(list(target.conditions.values()))
                   if c.condition_id == ability_lockout.LOCKOUT
                   and (c.data or {}).get("ability") == ability_lockout.key_of(action))
    suppress_sources(engine, owner, target, binding,
                     lambda source: mechanic_at(engine, source) == ability_lockout.key_of(action),
                     zone.source_definition_id,
                     f"Hollow Field: {target.display_name}'s {action.display_name} is suppressed until its next turn.")
    _note(engine, zone, f"Hollow Field: {target.display_name}'s {action.display_name} is suppressed until the start "
                        f"of its next turn.", (target,))


# ------------------------------------------------------------------------------------------------ Deepen the Hollow
def _title(text: str) -> str:
    return " ".join(word.capitalize() for word in str(text).replace("_", " ").split())


def _sphere_name(sphere: str) -> str:
    return _title(sphere.rsplit(".", 1)[-1])


def sphere_of_mechanic(mechanic_id: str) -> str:
    """The Sphere a compiled talent belongs to, from the shipped typed authority.

    A passive talent has no catalog action, so its compiled passive row carries
    no sphere; the record's own typed entry is the only honest source. Read once
    and cached; no fight state and no runtime patching.
    """
    mapping = globals().get("_SPHERE_BY_MECHANIC")
    if mapping is None:
        import json

        from ..factory_compiler import TYPED_AUTHORITY

        try:
            mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8")).get("mechanics") or {}
        except (OSError, ValueError):
            mechanics = {}
        mapping = {str(key): str(row.get("sphere_id") or "") for key, row in mechanics.items()}
        globals()["_SPHERE_BY_MECHANIC"] = mapping
    return mapping.get(str(mechanic_id) or "", "")


def _is_recovery(source: str, name: str) -> bool:
    text = f"{source} {name}".lower()
    return bool(source) and ("recover" in text or "regain" in text)


def _systems(engine: Any, creature: Any) -> list[dict[str, str]]:
    """Every major system this creature actually carries, in printed order.

    Read from the creature's own compiled actions and passive rows; a system it
    does not have is never offered (so a Method, which this table does not
    compile as a fight row, offers nothing).
    """
    found: dict[tuple[str, str], str] = {}

    def add(kind: str, value: str, label: str) -> None:
        if value and (kind, value) not in found:
            found[(kind, value)] = label

    rows: list[tuple[str, str, str]] = []
    for action_id in getattr(creature, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        typed = _typed(action)
        rows.append((str(typed.get("source") or ""), str(typed.get("sphere") or ""),
                     str(getattr(action, "display_name", "") or "")))
    for store in ("typed_passive_rows", "typed_reaction_rows"):
        for row in (getattr(engine, store, {}) or {}).get(creature.entity_id, []) or []:
            rows.append((str(row.get("feature_id") or ""), "", str(row.get("name") or "")))
    for source, sphere, name in rows:
        sphere = sphere or sphere_of_mechanic(source)
        if sphere:
            add("sphere", sphere, _sphere_name(sphere))
        if source.startswith("tianxia.subpath."):
            add("subpath", source.split(".feature.")[0], _title(source.split(".feature.")[0].rsplit(".", 1)[-1]))
        if ".method." in source or source.startswith("tianxia.method."):
            add("method", source.split(".feature.")[0], _title(source.rsplit(".", 1)[-1]))
        from .qi_path import NASCENT_FEATURES, NASCENT_SOUL, nascent_feature_source
        nascent_source = nascent_feature_source(source)
        if nascent_source.startswith(NASCENT_SOUL + "."):
            key = nascent_source.removeprefix(NASCENT_SOUL + ".")
            if key in NASCENT_FEATURES:
                add("nascent_soul", nascent_source, NASCENT_FEATURES[key])
        if source.startswith("armament.") or "feature.domain_armament" in source:
            add("domain_armament", "armament.", "Domain Armament")
        if source.startswith("foundation."):
            add("foundation", source.rsplit(".", 1)[0], _title(source.rsplit(".", 1)[0].rsplit(".", 1)[-1]))
        if _is_recovery(source, name):
            add("path_recovery", source, name or "Path resource recovery")
    # One option per Form the creature actually holds: the Hollow suspends one Form, never its sibling.
    from .qi_path import FORMS as form_names, forms as held_forms
    for held in held_forms(creature):
        add("golden_core_form", held, f"Golden Core Form: {form_names.get(held, held)}")
    order = {kind: index for index, kind in enumerate(SYSTEM_KINDS)}
    return [{"kind": kind, "value": value, "label": f"{SYSTEM_KINDS[kind]}: {found[(kind, value)]}"}
            for kind, value in sorted(found, key=lambda key: (order.get(key[0], 99), key[1]))]


def _covers(record: dict[str, Any], source: str, sphere: str = "") -> bool:
    kind, value = str(record.get("kind") or ""), str(record.get("value") or "")
    if not value:
        return False
    if kind == "sphere":
        return sphere == value or source.startswith(value)
    if kind == "domain_armament":
        return source.startswith("armament.") or "feature.domain_armament" in source
    if kind == "golden_core_form":
        return source in (f"form.{value}", value)
    if kind == "nascent_soul":
        from .qi_path import nascent_feature_source
        return nascent_feature_source(source) == value
    return source == value or source.startswith(value + ".")


def _spend_marks(engine: Any, owner: Any, target: Any, number: int, source: str) -> bool:
    """Spend ``number`` of the owner's Void Marks from ``target`` (never doubles up)."""
    from . import void_touched_cultivator as void
    from ..typed_executor import mark_condition_id

    if void.mark_count(target, owner.entity_id) < number:
        return False
    condition_id = mark_condition_id(MARK_NAME, owner.entity_id)
    for instance_id, condition in list(target.conditions.items()):
        if condition.condition_id != condition_id:
            continue
        remaining = int((condition.data or {}).get("count") or 1) - number
        target.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(target.entity_id,),
                             payload={"condition_id": condition_id, "instance_id": instance_id, "reason": "SPENT"})
        if remaining > 0:
            engine._apply_condition(target, condition_id, condition.source_definition_id, condition.source_actor_id,
                                    expires_on=condition.expires_on,
                                    data={**(condition.data or {}), "count": remaining,
                                          "label": f"{remaining} Void Mark{'s' if remaining != 1 else ''} from "
                                                   f"{owner.display_name} — a fixed Void sign perceptible through Qi "
                                                   f"Sensing until the scene ends"})
        engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                             payload={"log": f"Deepen the Hollow: {owner.display_name} spends {number} Void Marks from "
                                             f"{target.display_name}."})
        return True
    return False


def _deepen_records(zone: Any) -> list[dict[str, Any]]:
    return list((zone.trigger_profile or {}).get(DEEPEN) or [])


def _save_zone(engine: Any, zone: Any) -> None:
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                         payload={"zone": zone.model_dump(mode="json")})


def _deepen(engine: Any, owner: Any, zone: Any, target: Any) -> None:
    """Once per turn, when a marked creature fails its save: spend 2 Void Marks to suppress one system."""
    from . import void_touched_cultivator as void

    if not owns(engine, owner) or void.mark_count(target, owner.entity_id) < 2:
        return
    # Once per turn per OWNER: the owner's Deepen is one use per turn, whichever creature it targets.
    turn = f"{engine.state.round_number * 1000 + engine.state.current_slot_index}"
    records = _deepen_records(zone)
    if any(row.get("turn") == turn and row.get("owner") == owner.entity_id for row in records):
        return
    options = _systems(engine, target)
    if not options:
        return
    keys = [row["kind"] + "|" + row["value"] for row in options]
    labels = {row["kind"] + "|" + row["value"]: row["label"] for row in options}
    if _answerable(engine, owner):
        answer = _ask(engine, owner, zone, target, "hollow_deepen", keys, labels,
                      (f"Deepen the Hollow: {target.display_name} failed its Charisma save inside "
                       f"{owner.display_name}'s Hollow Field and bears 2 of {owner.display_name}'s Void Marks. Spend 2 "
                       f"Void Marks to suppress one system of {target.display_name} until it leaves the field or the "
                       f"field ends? Choose one system, or decline."),
                      keys[:1], allow_decline=True)
        if not answer:
            return
        chosen = answer[0]
    else:
        chosen = keys[0]
    row = next(item for item in options if item["kind"] + "|" + item["value"] == chosen)
    if not _spend_marks(engine, owner, target, 2, zone.source_definition_id):
        return
    data = {"zone": zone.zone_id, "kind": row["kind"], "value": row["value"], "label": row["label"],
            "cl": _field_cl(zone), "rows": _take_system_rows(engine, target, row["kind"], row["value"]),
            "label_text": f"Hollow Field: {target.display_name}'s {row['label']} is suppressed until it leaves the "
                          f"field or the field ends."}
    engine._apply_condition(target, SYSTEM, zone.source_definition_id, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data=data)
    _reconcile_systems(engine)
    zone.trigger_profile = {**(zone.trigger_profile or {}), DEEPEN: [*records, {
        "target": target.entity_id, "turn": turn, "kind": row["kind"], "value": row["value"],
        "label": row["label"], "cl": _field_cl(zone), "owner": owner.entity_id}]}
    _save_zone(engine, zone)
    _note(engine, zone, f"Deepen the Hollow: {target.display_name}'s {row['label']} is suppressed until it leaves "
                        f"the field or the Hollow Field ends.", (target,))


def _take_system_rows(engine: Any, target: Any, kind: str, value: str) -> dict[str, Any]:
    """Take the suppressed system's live passive/reaction rows off the fight, keeping them on the record."""
    taken: dict[str, Any] = {"passive": [], "reaction": []}
    for store, key in (("typed_passive_rows", "passive"), ("typed_reaction_rows", "reaction")):
        rows = (getattr(engine, store, {}) or {}).get(target.entity_id) or []
        keep = []
        for row in rows:
            source = str(row.get("feature_id") or "")
            sphere = str(row.get("sphere") or "") or sphere_of_mechanic(source)
            if _covers({"kind": kind, "value": value}, source, sphere):
                taken[key].append(copy.deepcopy(row))
            else:
                keep.append(row)
        getattr(engine, store)[target.entity_id] = keep
    return taken


def _give_back_system_rows(engine: Any, target: Any, data: dict[str, Any]) -> None:
    rows = data.get("rows") or {}
    for store, key in (("typed_passive_rows", "passive"), ("typed_reaction_rows", "reaction")):
        current = list((getattr(engine, store, {}) or {}).get(target.entity_id) or [])
        known = {str(row.get("feature_id")) for row in current}
        for row in rows.get(key) or []:
            if str(row.get("feature_id")) not in known:
                current.append(copy.deepcopy(row))
        getattr(engine, store)[target.entity_id] = current


def _release_system(engine: Any, target: Any, condition: Any, reason: str) -> None:
    for instance_id, held in list(target.conditions.items()):
        if held is not condition:
            continue
        _give_back_system_rows(engine, target, condition.data or {})
        target.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(target.entity_id,),
                             payload={"condition_id": SYSTEM, "instance_id": instance_id, "reason": reason,
                                      "label": str((condition.data or {}).get("label_text") or "")})
        _reconcile_systems(engine)


def _suspend_system_effects(engine: Any, actor: Any, condition: Any) -> None:
    from .benefit_suppression import suppress_sources

    data = condition.data or {}
    owner = engine.state.actors.get(condition.source_actor_id)
    if owner is None:
        return
    if data.get("kind") == "golden_core_form":
        # Exactly one chosen Form: suspend only that Form's own condition. Its sibling Form, and the
        # shared Golden Core feature rows, stay live. The binding restores it when this system ends.
        from .benefit_suppression import suppress
        from .qi_path import FORM as FORM_CONDITION
        ref = {"actor": actor.entity_id, "instance": condition.instance_id}
        for held in list(actor.conditions.values()):
            if held.condition_id == FORM_CONDITION and str((held.data or {}).get("form") or "") == str(data.get("value") or ""):
                suppress(engine, owner, actor, f"condition:{held.instance_id}", "binding", condition.source_definition_id,
                         label=str(data.get("label_text") or ""), bindings=[ref])
        return

    def matches(source_id: str) -> bool:
        from .ability_source import mechanic_at

        action = engine.action_catalog.get(source_id)
        source = mechanic_at(engine, source_id) or source_id.removeprefix("passive:").removeprefix("reaction:")
        sphere = str(_typed(action).get("sphere") or "") or sphere_of_mechanic(source)
        return _covers(data, source, sphere)

    suppress_sources(engine, owner, actor, condition, matches, condition.source_definition_id,
                     str(data.get("label_text") or "One cultivation system is suppressed."))


def _reconcile_systems(engine: Any) -> None:
    """Reconcile active contributions as well as admission rows, including cold reload."""
    if getattr(engine, "_reconciling_hollow_systems", False):
        return
    engine._reconciling_hollow_systems = True
    try:
        _reconcile_systems_pass(engine)
    finally:
        engine._reconciling_hollow_systems = False


def _reconcile_systems_pass(engine: Any) -> None:
    zones = _zones_module()
    for actor in list(engine.state.actors.values()):
        for condition in [c for c in list(actor.conditions.values()) if c.condition_id == SYSTEM]:
            data = condition.data or {}
            zone = engine.state.zones.get(str(data.get("zone") or ""))
            if zone is None or not zone.active:
                _release_system(engine, actor, condition, "FIELD_ENDED")
            elif not zones.actor_inside_zone(engine, actor, zone):
                _release_system(engine, actor, condition, "LEFT_FIELD")
            else:
                # A cold reload rebuilds typed rows from the sealed bundle: take
                # the suppressed system's rows off again (idempotent).
                taken = _take_system_rows(engine, actor, str(data.get("kind") or ""), str(data.get("value") or ""))
                held = copy.deepcopy(data.get("rows") or {"passive": [], "reaction": []})
                changed = False
                for kind, rows in taken.items():
                    for row in rows:
                        if row not in held.setdefault(kind, []):
                            held[kind].append(row)
                            changed = True
                if changed:
                    # An overlapping binding may inherit rows just released by
                    # another suppression; retain them for its eventual release.
                    engine._update_condition_data(actor, condition, {**data, "rows": held},
                                                  condition.source_definition_id)
                _suspend_system_effects(engine, actor, condition)


def creature_cl(engine: Any, actor: Any) -> int:
    """The creature's Source CL, from its sealed typed numbers or its bundle."""
    from .ability_source import numbers_of

    numbers = numbers_of(engine, actor)
    cl = numbers.get("source_cl") or numbers.get("cl")
    if cl:
        return int(cl)
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == getattr(actor, "entity_id", None) and bundle.get("cl") is not None:
            return int(bundle["cl"])
    return 0


@hook("turn_end")
def deepen_repeat_save(engine: Any, actor: Any) -> None:
    """A target at least 3 CL higher repeats the Charisma save at the end of each of its turns.

    A lower-CL target gets no automatic repeat (the record says so), so only the
    qualifying creature's own turn end rolls here.
    """
    for condition in [c for c in list(actor.conditions.values()) if c.condition_id == SYSTEM]:
        data = condition.data or {}
        if creature_cl(engine, actor) < int(data.get("cl") or 0) + 3:
            continue
        zone = engine.state.zones.get(str(data.get("zone") or ""))
        if zone is None or not zone.active:
            continue
        dc = _field_dc(zone)
        roll = engine._roll_save(actor, "CHA", dc, zone.source_definition_id)
        if roll is None:
            continue
        if int(roll.total) >= dc:
            _release_system(engine, actor, condition, "SAVE_SUCCEEDED")
            _note(engine, zone, f"Hollow Field: {actor.display_name} is at least 3 Cultivation Levels higher and "
                                f"repeated its Charisma save (result {int(roll.total)} against DC {dc}); its "
                                f"{data.get('label') or 'suppressed system'} is no longer suppressed.", (actor,))


def _active_system(engine: Any, actor: Any, source: str, sphere: str = "") -> dict[str, Any] | None:
    zones = _zones_module()
    for condition in actor.conditions.values():
        if condition.condition_id != SYSTEM:
            continue
        data = condition.data or {}
        zone = engine.state.zones.get(str(data.get("zone") or ""))
        if zone is None or not zone.active or not zones.actor_inside_zone(engine, actor, zone):
            continue
        if _covers(data, source, sphere):
            return data
    return None


# ------------------------------------------------------------------------------------------------ continuous inside-field rules
def _powered(action: Any) -> bool:
    """A powered (Qi/CP) technique: it says so, spends a CP pool, or is a Qi Path technique."""
    typed = _typed(action)
    if typed.get("qi_powered"):
        return True
    for pool, _amount in (getattr(action, "costs", ()) or ()):
        if str(pool) in CP_POOLS:
            return True
    return source_of(action).startswith(("tianxia.subpath.qi.", "tianxia.path.qi_cultivation."))


@hook("candidate_allowed")
def gate_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Suppressed systems, a suppressed Domain Armament and "cannot begin Concentration" are not offered."""
    if action is None:
        return None
    source = source_of(action)
    typed = _typed(action)
    sphere = str(typed.get("sphere") or "") or sphere_of_mechanic(source)
    if not source and not sphere:
        return None
    for condition in actor.conditions.values():
        if condition.condition_id == NO_CONCENTRATION and bool((typed.get("duration") or {}).get("concentration")):
            return False
        if condition.condition_id == ARMAMENT and _covers({"kind": "domain_armament", "value": "armament."}, source, sphere):
            return False
    return False if _active_system(engine, actor, source, sphere) is not None else None


@hook("row_allowed")
def gate_rows(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    source = str(row.get("feature_id") or "")
    sphere = str(row.get("sphere") or "") or sphere_of_mechanic(source)
    if not source and not sphere:
        return None
    return False if _active_system(engine, actor, source, sphere) is not None else None


@hook("technique_cost_floor")
def hostile_cost(engine: Any, actor: Any, source_id: str, listed: Any, current: Any) -> dict[str, int] | None:
    """Hostile CP costs +1 inside a Hollow Field; the lesser effect adds 1 to the next CP cost."""
    if actor is None:
        return None
    from ..typed_executor import is_active_typed_condition

    extra = 1 if _hostile_fields(engine, actor) else 0
    if any(c.condition_id == NEXT_COST and is_active_typed_condition(c) for c in actor.conditions.values()):
        extra += 1
    if not extra:
        return None
    printed, proposed = dict(listed), dict(current)
    answer = {pool: int(proposed.get(pool) or 0) + extra for pool in CP_POOLS if int(printed.get(pool) or 0) > 0}
    return answer or None


@hook("event")
def spend_next_cost(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The lesser "next CP cost +1" is used up by the next Cultivation Point spend."""
    if event_type != "RESOURCE_SPENT":
        return
    payload = kwargs.get("payload") or {}
    if str(payload.get("resource_id") or "") not in CP_POOLS or int(payload.get("amount") or 0) <= 0:
        return
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if actor is None:
        return
    for instance_id, condition in list(actor.conditions.items()):
        if condition.condition_id != NEXT_COST:
            continue
        actor.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(actor.entity_id,),
                             payload={"condition_id": NEXT_COST, "instance_id": instance_id, "reason": "USED"})


@hook("resource_gain_allowed")
def no_hostile_regain(engine: Any, actor: Any, resource_id: str, amount: int, source_id: str) -> bool | None:
    """A hostile creature inside a Hollow Field cannot regain Cultivation Points."""
    if str(resource_id) not in CP_POOLS or int(amount or 0) <= 0:
        return None
    return False if _hostile_fields(engine, actor) else None


@hook("healing_pending")
def halve_hostile_temp_hp(engine: Any, subject: Any, amount: int, healer: Any, source: str, kind: str) -> int | None:
    """Temporary HP granted to a hostile creature by a hostile cultivation effect is halved."""
    if kind != "temp_hp" or int(amount or 0) <= 0:
        return None
    zones_at = _hostile_fields(engine, subject)
    if not zones_at:
        return None
    owner = engine.state.actors.get(zones_at[0].owner_id)
    # "hostile cultivation effects": the grant comes from the field owner's
    # enemies, not from the field's own side.
    if healer is None or owner is None or healer.team_id == owner.team_id:
        return None
    if not _cultivation_source(engine, source):
        return None
    return int(amount) - int(amount) // 2


def _cultivation_source(engine: Any, source: str) -> bool:
    """A compiled cultivation ability or passive row, never an ordinary item or terrain grant."""
    action = engine.action_catalog.get(str(source or ""))
    if action is not None:
        typed = _typed(action)
        return bool(typed.get("coverage") or typed.get("typing_status") or typed.get("source"))
    mark = str(source or "").removeprefix("passive:")
    return mark.startswith(("tianxia.", "TAL_", "FOUNDATION", "foundation."))


@hook("technique_used")
def reaction_lock_after_powered(ctx: Any) -> None:
    """A hostile creature that activates a powered technique cannot take Reactions until its next turn.

    This is the field's own inside clause, and it also carries the lesser
    save effect's printed version (which outlives the field for its own turn).
    """
    engine, actor = ctx.engine, ctx.actor
    if actor is None or ctx.action is None or not _powered(ctx.action):
        return
    zones_at = _hostile_fields(engine, actor)
    marker = next((c for c in actor.conditions.values() if c.condition_id == REACTION_AFTER), None)
    if not zones_at and marker is None:
        return
    if zones_at:
        source, owner_id, zone = zones_at[0].source_definition_id, zones_at[0].owner_id, zones_at[0]
    else:  # the lesser effect outlives the field for its own turn
        source, owner_id, zone = marker.source_definition_id, marker.source_actor_id, None
    if any(c.condition_id == NO_REACTIONS and c.source_definition_id == source for c in actor.conditions.values()):
        return
    engine._apply_condition(actor, NO_REACTIONS, source, owner_id,
                            expires_on=_until_target_next_turn(actor),
                            data={"label": f"Hollow Field: {actor.display_name} activated a powered technique and cannot "
                                           f"take Reactions until the start of its next turn."})
    if marker is not None and zone is not None:
        _note(engine, zone, f"Hollow Field: after {actor.display_name} activated a powered technique it cannot take "
                            f"Reactions until the start of its next turn.", (actor,))


# ------------------------------------------------------------------------------------------------ teleport and planar movement
def _action_numbers(action: Any) -> dict[str, Any]:
    return dict(_typed(action).get("numbers") or {})


def _secret_authority(action: Any) -> bool:
    """This table's one Secret-authority source: the Void-Touched Cultivator Secret Law."""
    return source_of(action).startswith(FAMILY)


def _permit(engine: Any, zone: Any, actor: Any) -> bool:
    """The field owner's permission for a lower-Source-CL crossing (human asked, AI decides)."""
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return True
    if _answerable(engine, owner):
        answer = _ask(engine, owner, zone, actor, "hollow_permit",
                      ["permit", "refuse"], {"permit": "Permit the teleport", "refuse": "Refuse the teleport"},
                      (f"Hollow Field: {actor.display_name} is teleporting inside {owner.display_name}'s Hollow Field "
                       f"with a Source CL lower than {owner.display_name}'s. Permit this teleport?"),
                      ["refuse" if actor.team_id != owner.team_id else "permit"])
        return bool(answer) and answer[0] == "permit"
    return actor.team_id == owner.team_id


def _say_bar(engine: Any, zone: Any, bar: Any, actor: Any, text: str) -> None:
    if zone is not None:
        _note(engine, zone, text, (actor,))
    else:
        note(engine, bar.source_definition_id, actor, text, (actor,))


@hook("teleport_check")
def hollow_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    """The field's Source-CL crossing rule per field, and each Hollowing "no teleportation" bar.

    Each field that covers either end enforces its own crossing rule, so owning
    one field never exempts another caster's rule. Each Hollowing bar is judged by
    the Source CL recorded when that bar was applied: the bar outlives its field,
    and a lower-CL field carried into it must not weaken it.
    """
    if actor is None:
        return None
    applicable = fields_covering(engine, actor, destination)
    bars = [c for c in actor.conditions.values() if c.condition_id == TELEPORT_BAR]
    if not applicable and not bars:
        return None
    action = engine.action_catalog.get(str(getattr(engine, "_active_action_source_id", "") or ""))
    numbers = _action_numbers(action)
    source_cl = int(numbers.get("source_cl") or numbers.get("cl") or 0)
    secret = _secret_authority(action)

    def _from_source(source: str) -> Any | None:
        return next((zone for zone in applicable if zone.source_definition_id == source), None)

    passed = None
    for bar in bars:
        if secret and source_cl >= int((bar.data or {}).get("cl") or 0):
            passed = bar
            continue
        _say_bar(engine, _from_source(bar.source_definition_id), bar, actor,
                 f"Hollow Field: {actor.display_name}'s teleportation fails; it cannot teleport or move between planes "
                 f"until the start of its next turn.")
        return False

    for zone in applicable:
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or actor.entity_id == owner.entity_id:
            continue
        if source_cl < _field_cl(zone) and not _permit(engine, zone, actor):
            _note(engine, zone, f"Hollow Field: {actor.display_name}'s teleportation fails; its Source CL {source_cl} is "
                                f"lower than the field's {_field_cl(zone)} and {owner.display_name} did not permit it.",
                  (actor,))
            return False
    if passed is not None:
        _say_bar(engine, _from_source(passed.source_definition_id), passed, actor,
                 f"Hollow Field: {actor.display_name} passes through the Hollowing bar with equal or higher Secret "
                 f"authority.")
    return None


# ------------------------------------------------------------------------------------------------ release and plain words
@hook("turn_start")
def turn_start_release(engine: Any, actor: Any) -> None:
    _reconcile_systems(engine)


@hook("after_move")
def after_move_release(engine: Any, mover: Any, moved_ft: int) -> None:
    _reconcile_systems(engine)


@hook("teleport_settled")
def teleport_release(ctx: Any, subject: Any, previous: Any, destination: Any, unwilling: Any) -> None:
    _reconcile_systems(ctx.engine)


@hook("event")
def movement_release(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type in ("ZONE_REMOVED", "CONCENTRATION_ENDED", "MOVEMENT_COMMITTED"):
        _reconcile_systems(engine)


_PLAIN = {
    NEXT_COST: "Its next Cultivation Point cost is 1 higher (Hollow Field).",
    NO_CONCENTRATION: "It cannot begin Concentration (Hollow Field).",
    ARMAMENT: "Domain Armament movement and attacks are suppressed (Hollow Field).",
    REACTION_AFTER: "After it activates a powered technique it cannot take Reactions until the start of its next turn "
                    "(Hollow Field).",
    SYSTEM: "One of its major cultivation systems is suppressed (Hollow Field).",
    TELEPORT_BAR: "It cannot use teleportation or planar movement (Hollow Field).",
}


@hook("status_description")
def plain_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    condition_id = str((row or {}).get("condition_id") or "")
    if condition_id not in _PLAIN:
        return None
    data = data or {}
    return {"text": str(data.get("label") or _PLAIN[condition_id]),
            "display_name": str(data.get("label_text") or data.get("label") or _PLAIN[condition_id]),
            "source_ability": "Hollow Field" if condition_id != SYSTEM else "Deepen the Hollow"}
