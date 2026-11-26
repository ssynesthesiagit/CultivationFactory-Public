"""What the ground under a square is made of, and what it does -- in plain words.

The table already paints a map's materials onto squares (floor patches from the map editor, named
terrain areas, arena terrain cells, walls and trees) but only ever *drew* them: hovering a floor,
a patch of difficult ground or a wall showed nothing. The owner asked (2026-09-30) that resting
the pointer on a ground square for a couple of seconds bring up the material's name and what it
does. This module is the one place that turns a material kind into that name-and-effect reading,
so the server, the map editor and the tabletop all say the same thing and no rule is guessed in
the browser.

Every entry is ``{"name": <what the player calls it>, "lines": [<what it does>, ...]}``. The text is
written for someone who knows only basic D&D: it says what the ground does (movement, cover,
damage, saves), never an internal id, never an owner citation, and never a bare "see its source".
The rule source for a named terrain is ``combat/rules/terrain.json`` -- only its *player-facing*
fields are read (difficult/obscured/enter_start/move_through); the ``evidence`` citation beside
them is deliberately not surfaced.

This module is the ONLY place a ground mechanic is described in words. The browser's hover card
(``static/tabletop/ground-text.js``) is a pure assembler that looks a square's kinds up here, so
the table, the map editor and the tests cannot drift from the engine and a mechanic is never
restated in a browser string. ``CELL_READINGS`` covers the ground kinds a map paints directly
rather than through a named terrain -- cover, hazard, sight-blockers, walls and trees -- and each
line states the rule the engine actually runs (``gate2_grid.cover_bonus``,
``gate2_engine._resolve_qi_hazard``, ``gate2_grid``'s BLOCKED / SIGHT_BLOCKED columns); the
regression in ``tests/test_ground_text_matches_engine.py`` pins those numbers to the engine.

Consumers: ``combat/tabletop_service.py`` puts the catalog on the state payload as ``ground`` and
``app/api.py``'s ``GET /api/tabletop/terrains`` serves it to the map editor;
``static/tabletop/board.js`` looks a square up in it to draw the hover card. No combat rule reads
this module, so nothing about a fight changes.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .tabletop import BACKGROUND_STYLES
from .zones import terrain_rules

# What a creature caught in terrain does when it enters or starts its turn there.
_ON_ENTER = "entering it, or starting its turn inside, "
_ABILITIES = {"DEX": "Dexterity", "CON": "Constitution", "STR": "Strength", "WIS": "Wisdom",
              "INT": "Intelligence", "CHA": "Charisma"}
_WHO = {"hostile": "A hostile creature", "any": "A creature", "ally": "An ally", "self": "Its creator"}

# One wording for "difficult terrain", shared by a named terrain (terrain_reading) and a square a map
# painted difficult (CELL_READINGS), so the two can never disagree.
_DIFFICULT_ALL = "Difficult terrain: entering these squares costs twice as much movement."


def _ability(code: Any) -> str:
    return _ABILITIES.get(str(code or "CON").upper(), str(code or "CON").upper().title())


def _who(who: Any) -> str:
    return _WHO.get(str(who or "hostile"), "An affected creature")


def _amount(effect: dict[str, Any]) -> str:
    """The size of a damage effect, as a phrase that reads in front of the word 'damage'."""
    formula = str(effect.get("formula") or "")
    if formula == "pb":
        return "equal to its Proficiency Bonus"
    if formula:
        return formula
    flat = effect.get("flat")
    return str(flat) if flat not in (None, 0) else ""


def _effect(effect: Any) -> str | None:
    """One typed effect as a short clause. Only the kinds the terrain rules actually use are
    spelled out; anything else reads as a plain effect rather than a guessed rule."""
    if not isinstance(effect, dict):
        return None
    kind = str(effect.get("type") or "")
    if kind == "damage":
        types = [str(t) for t in (effect.get("damage_types") or []) if t]
        label = " / ".join(t.title() for t in types)
        amount = _amount(effect)
        if amount.startswith("equal to"):
            head = f"{label} damage {amount}" if label else f"damage {amount}"
        elif amount and label:
            head = f"{amount} {label} damage"
        else:
            head = f"{label} damage" if label else (f"{amount} damage" if amount else "damage")
        return f"takes {head}"
    if kind == "condition":
        condition = str(effect.get("condition") or "a condition").replace("_", " ")
        return f"gains {condition.title()}"
    return "is affected"


def _effects(effects: Any) -> str:
    parts = [clause for clause in (_effect(effect) for effect in (effects or [])) if clause]
    if not parts:
        return "no effect"
    if len(parts) == 1:
        return parts[0]
    return ", then ".join([", ".join(parts[:-1]), parts[-1]])


def floor_reading(style: str) -> dict[str, Any]:
    """A painted floor patch. The style is the *look* of those squares: the engine gives a floor
    no movement cost, cover or effect of its own, and the card says so plainly so a player never
    mistakes a nice texture for a rule. The claim is about the paint alone -- a named terrain or a
    wall on the same square is a rule of its own and is listed above this line, so the card never
    says a square "changes nothing" while naming what it does."""
    name = str(style or "").replace("_", " ").strip().title() or "Ground"
    return {"name": f"{name} floor",
            "lines": ["Painted ground: this square is drawn as that material, and the paint is only "
                      "the look. On its own it costs no movement, gives no cover and deals no "
                      "damage; whatever this square really does comes from the terrain or the wall "
                      "on it."]}


def terrain_reading(name: str, rule: dict[str, Any]) -> dict[str, Any]:
    """A named terrain area. The lines are assembled from the rule's own player-facing fields, so
    what the card says is exactly what the engine does to the squares."""
    lines: list[str] = []
    difficult = rule.get("difficult")
    if difficult == "all":
        lines.append(_DIFFICULT_ALL)
    elif difficult == "hostile":
        lines.append("Difficult terrain for the creatures this is hostile to: their movement into it costs twice as much.")
    obscured = rule.get("obscured")
    if obscured == "light":
        lines.append("Lightly obscured: you can see through it, but fine detail is hard to make out. It does not make creatures Hidden.")
    elif obscured == "heavy":
        lines.append("Heavily obscured: you can see very little through it. It does not make creatures Hidden.")
    enter = rule.get("enter_start")
    if isinstance(enter, dict):
        outcome = ("the damage of the ability that created it" if enter.get("from_ability")
                   else (_effects(enter.get("on_fail")) if enter.get("on_fail") else "no effect"))
        tail = "; half that damage on a success" if enter.get("half") else ""
        # What a creature that makes the save gets is part of what the ground does, so it is named
        # too (OC13: Fire Terrain's card said only what a failure did, and nothing at all about a
        # success). A half-damage rule already states what a success gets.
        success = ("" if enter.get("half") or not enter.get("on_success")
                   else f"; on a success, {_effects(enter.get('on_success'))}")
        lines.append(f"{_who(enter.get('who'))} {_ON_ENTER}makes a {_ability(enter.get('ability'))} save and, on a failure, "
                     f"{outcome}{tail}{success}.")
    through = rule.get("move_through")
    if isinstance(through, dict):
        least = int(through.get("min_ft") or 0)
        span = f"moves more than {least} ft through it in a turn" if least else "moves through it"
        ability = through.get("ability")
        if ability:
            on_fail = _effects(through.get("on_fail")) if through.get("on_fail") else "no effect"
            clause = f"makes a {_ability(ability)} save and, on a failure, {on_fail}"
        else:
            clause = _effects(through.get("effects"))
        lines.append(f"{_who(through.get('who'))} that {span} {clause}.")
    if not lines:
        lines.append("An area laid down by an ability. Its special effects are shown while it is active.")
    return {"name": str(name or "").replace("_", " ").title(), "lines": lines}


# The ground a map paints directly, rather than through a named terrain. Each line states the rule
# the engine runs for that square, so the card cannot advise a player wrongly:
#
# * "cell:cover"  -- gate2_grid.SquareGrid.cover_bonus gives +2 to the TARGET's Armor Class when a
#   SIMPLE_COVER cell lies strictly BETWEEN the two (the ray's own endpoints are excluded), and
#   gate2_engine/directional_cover only consults terrain cover for a ranged attack. So standing in
#   the cover square is worth nothing, and a sword fight at arm's length is unaffected.
# * "cell:hazard" -- gate2_engine.Gate2Engine._resolve_qi_hazard: a creature whose footprint touches
#   a Qi-hazard square makes a DC 12 Dexterity save, takes 1d4 damage on a failure, and is stamped
#   for the turn so it happens at most once per creature per turn.
# * "cell:sight"  -- a SIGHT_BLOCKED region (a screen / a sight-only wall): it stops line of sight,
#   and its movement cost is 1, so a creature walks straight through it.
# * "structure:wall" / "structure:tree" -- a BLOCKED square: no creature can stand in it and it
#   stops sight. A tree's canopy is only the look.
CELL_READINGS: dict[str, dict[str, Any]] = {
    "cell:difficult": {"name": "Difficult ground", "lines": [_DIFFICULT_ALL]},
    "cell:cover": {"name": "Cover", "lines": [
        "Cover: a creature standing on the far side of it is harder to hit. The attacker has to "
        "send the attack through the cover, and that creature's Armor Class is 2 higher.",
        "The cover square itself is worth nothing -- the cover has to be BETWEEN the creature and "
        "the attacker. It only helps against attacks that travel, such as arrows, thrown weapons "
        "and spells, not against a fight at arm's length."]},
    "cell:hazard": {"name": "Hazard", "lines": [
        "Hazard: any creature that moves through these squares makes a Dexterity saving throw "
        "of 12.",
        "On a failure it takes 1d4 damage; on a success nothing happens. Each creature is only "
        "affected once per turn, however far it moves through the hazard."]},
    "cell:sight": {"name": "Blocks sight", "lines": [
        "This square blocks line of sight: a creature on one side cannot be seen from the other, "
        "so nobody can attack or target it from over there.",
        "It is not a wall. A creature can walk straight through it, and a fight at arm's length "
        "is unaffected."]},
    "structure:wall": {"name": "Wall", "lines": [
        "A wall: it blocks movement and sight, and no creature can be standing in it or be seen "
        "through it."]},
    "structure:tree": {"name": "Tree", "lines": [
        "A tree: its trunk blocks movement and sight exactly as a wall does. The canopy is only "
        "the look."]},
}


# Geometry variants are presentation data for the bound arena, not map defaults.
# Both the table and editor use this catalog through the shared ground card.
_CENTERLINE_SIGHT = (
    "Sight is blocked along two crossing centre lines through this square. "
    "The near side stays visible, and gaps near the corners allow sight and targeting "
    "when no other obstacle blocks the view."
)
CELL_READINGS.update({
    "cell:sight:centerline": {"name": "Blocks sight", "lines": [
        _CENTERLINE_SIGHT, CELL_READINGS["cell:sight"]["lines"][1]]},
    "structure:wall:centerline": {"name": "Wall", "lines": [
        "A wall: it blocks movement, so a creature cannot stand in this square.", _CENTERLINE_SIGHT]},
    "structure:tree:centerline": {"name": "Tree", "lines": [
        "A tree: its trunk blocks movement, so a creature cannot stand in this square. "
        "The canopy is only the look.", _CENTERLINE_SIGHT]},
})


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Any]]:
    """Every ground kind the table can show, keyed ``"floor:<style>"`` / ``"terrain:<name>"`` /
    ``"cell:<kind>"`` / ``"structure:<kind>"``. Built once and shared read-only; the state payload
    and the map editor's terrain endpoint both reference it."""
    out: dict[str, dict[str, Any]] = dict(CELL_READINGS)
    for style in BACKGROUND_STYLES:
        out[f"floor:{style}"] = floor_reading(style)
    for name, rule in (terrain_rules().get("terrains") or {}).items():
        out[f"terrain:{name}"] = terrain_reading(name, rule if isinstance(rule, dict) else {})
    return out


def reading(material: str) -> dict[str, Any] | None:
    """The name-and-effect reading for one material kind, or None when the kind is unknown (the
    table then stays quiet rather than inventing a rule)."""
    return catalog().get(str(material or ""))
