"""Area-of-effect abilities: reading an area from prose (owner 2026-09-26 bug), shape-aware
targeting in combat/typed_executor.py, and aiming a line/cone by its own length
(combat/factory_compiler.py._target_kind).

Found 2026-09-26: 242 usable abilities had a typed ``area`` (an "Area:" header the parser could
read); 305 more named their area only in the rules text, so combat/factory_compiler.py treated
them as single-target.  Separately, every area was targeted as a radius around the aim point, so
a 120-foot line caught every creature within 120 feet in any direction.
"""

import json
from functools import lru_cache
from pathlib import Path

from combat.factory_compiler import TYPED_AUTHORITY, _aimed_area, _target_kind
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from combat.typed_executor import _area_targets
from factory_authoring.typed_structure import infer_area_from_text

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def mechanics():
    """The pinned typed mechanics authority, as a mechanic id -> row map."""
    return json.loads(Path(TYPED_AUTHORITY).read_bytes())["mechanics"]

_SAVE = [{"type": "save", "ability": "dex", "on_fail": [{"type": "damage", "dice": {"count": 1, "sides": 6}}], "on_success": []}]
_ATTACK = [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
           "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}}], "on_miss": []}]


# ------------------------------------------------------------------ 1. area read from text
def test_area_from_text_reads_common_shapes():
    # A cylinder "Area:" header the original parser could not read (radius, then a separate height).
    cylinder = {"area": {"shape": "special", "size_ft": None, "text": "10-foot-radius, 30-foot-high cylinder"},
                "range": {"kind": "feet", "feet": 60}, "effects": _SAVE}
    area = infer_area_from_text(cylinder, "irrelevant body text")
    assert area["shape"] == "cylinder" and area["size_ft"] == 10 and area["source"] == "text"

    # A line whose length/width are only in the printed "Range:" field (e.g. Incinerating Lance).
    line = {"area": None, "range": {"kind": "special", "feet": None, "text": "120-foot line, 5 feet wide"}, "effects": _SAVE}
    area = infer_area_from_text(line, "irrelevant body text")
    assert area["shape"] == "line" and area["size_ft"] == 120 and area["width_ft"] == 5

    # A cube named only in the body text, no header at all (Gather Current, automatic delivery).
    cube_text = "You stir a small controlled Air Current in a 10-foot cube you can see within range."
    cube = {"area": None, "range": {"kind": "feet", "feet": 30}, "effects": []}
    area = infer_area_from_text(cube, cube_text)
    assert area == {"shape": "cube", "size_ft": 10, "evidence": "10-foot cube", "source": "text"}

    # A cone named only in body text (Cone of Death: an attack delivery, but "every creature ...
    # within a 30-foot cone" is the explicit each/all/every exception).
    cone_text = "Make one ranged weapon attack against every creature of your choice within a 30-foot cone."
    cone = {"area": None, "range": None, "effects": _ATTACK}
    area = infer_area_from_text(cone, cone_text)
    assert area["shape"] == "cone" and area["size_ft"] == 30

    # "Creatures within N feet of that point" (a reaction with no Area:/Range: header at all).
    point_text = "You descend onto a point below you. Creatures within 15 feet of that point make Dexterity saving throws."
    point = {"area": None, "range": None, "effects": _SAVE}
    area = infer_area_from_text(point, point_text)
    assert area["shape"] == "sphere" and area["size_ft"] == 15 and area["source"] == "text"


def test_area_from_text_is_conservative():
    # A splash line under an attack's hit is not the ability's own area.
    splash_text = "Make a ranged Cultivation Attack. On a hit, the target and each creature within 5 feet of the target take 1d6 Fire damage."
    splash = {"area": None, "range": {"kind": "feet", "feet": 60}, "effects": _ATTACK}
    assert infer_area_from_text(splash, splash_text) is None

    # An object's own size ("no larger than a 10-foot cube") is not an area of effect.
    container_text = "Create a lattice around a chest, ritual circle, or formation component no larger than a 10-foot cube."
    container = {"area": None, "range": {"kind": "feet", "feet": 30}, "effects": []}
    assert infer_area_from_text(container, container_text) is None

    # A later, conditional effect's own size (found 2026-09-26 on Hungry Flame) must not become
    # the ability's area.
    later_text = ("Deal extra Fire damage. If this damage reduces a creature to 0 HP or destroys an "
                  "object, create one 5-foot square of Fire Terrain in its space until the start of your next turn.")
    later = {"area": None, "range": None, "effects": []}
    assert infer_area_from_text(later, later_text) is None

    # Already typed: never overwritten.
    typed = {"area": {"shape": "sphere", "size_ft": 20}, "range": None, "effects": []}
    assert infer_area_from_text(typed, "irrelevant") == {"shape": "sphere", "size_ft": 20}


# ------------------------------------------------------------------ 2. shape-aware _area_targets geometry
class _Grid:
    square_size_ft = 5
    width = 20
    height = 20

    def distance_ft(self, a, b):
        return max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z)) * self.square_size_ft


class _Actor:
    def __init__(self, entity_id, team_id, x, y, active=True):
        self.entity_id, self.team_id, self.position, self.active = entity_id, team_id, Position(x=x, y=y), active


class _State:
    def __init__(self, actors):
        self.actors = {a.entity_id: a for a in actors}


class _Engine:
    def __init__(self, actors):
        self.grid, self.state = _Grid(), _State(actors)

    @staticmethod
    def _actor_cells(actor):
        return getattr(actor, "occupied_cells", ((actor.position.x, actor.position.y),))

    def _actor_volume(self, actor, at=None):
        return tuple((x, y, actor.position.z) for x, y in self._actor_cells(actor))


def _hit(area, aim, actor_pos=(2, 5), other_pos=(2, 5), other_team="hostile"):
    actor = _Actor("caster", "self", *actor_pos)
    other = _Actor("other", other_team, *other_pos)
    engine = _Engine([actor, other])
    hit = other in _area_targets(engine, actor, Position(x=aim[0], y=aim[1]), area)
    return hit


def test_sphere_cylinder_emanation_use_distance_from_center():
    area = {"shape": "sphere", "size_ft": 15}
    assert _hit(area, aim=(10, 5), other_pos=(13, 5))  # 15 ft away: just inside
    assert not _hit(area, aim=(10, 5), other_pos=(14, 5))  # 20 ft away: just outside
    for shape in ("cylinder", "emanation"):
        assert _hit({"shape": shape, "size_ft": 15}, aim=(10, 5), other_pos=(13, 5))


def test_area_recipients_default_to_every_creature_and_can_be_narrowed():
    caster = _Actor("caster", "self", 2, 5)
    ally = _Actor("ally", "self", 4, 5)
    enemy = _Actor("enemy", "hostile", 5, 5)
    engine = _Engine([caster, ally, enemy])
    aim = Position(x=4, y=5)
    shape = {"shape": "sphere", "size_ft": 15}

    assert set(_area_targets(engine, caster, aim, shape)) == {caster, ally, enemy}
    assert set(_area_targets(engine, caster, aim, {**shape, "recipients": "hostile"})) == {enemy}
    assert set(_area_targets(engine, caster, aim, {**shape, "recipients": "allies"})) == {ally}


def test_area_membership_uses_any_occupied_square_of_a_large_creature():
    caster = _Actor("caster", "self", 2, 5)
    large = _Actor("large", "hostile", 14, 5)
    large.occupied_cells = ((12, 5), (13, 5), (14, 5), (15, 5))
    engine = _Engine([caster, large])
    area = {"shape": "sphere", "size_ft": 10}

    assert large in _area_targets(engine, caster, Position(x=10, y=5), area)


def test_cube_and_square_use_the_square_centred_on_the_aim_point():
    # A 10-foot side is two cells, with the negative boundary breaking the even-size tie.
    for shape in ("cube", "square"):
        area = {"shape": shape, "size_ft": 10}
        assert _hit(area, aim=(10, 5), other_pos=(9, 4))
        assert _hit(area, aim=(10, 5), other_pos=(10, 5))
        assert not _hit(area, aim=(10, 5), other_pos=(11, 6))
        assert not _hit(area, aim=(10, 5), other_pos=(8, 5))


def test_line_uses_length_and_width_along_the_aim_direction():
    area = {"shape": "line", "size_ft": 30, "width_ft": 10}  # half-width 5 ft
    # Caster at (2,5) aiming east at (8,5): the line runs from x=10ft to x=40ft along y=25ft.
    assert _hit(area, aim=(8, 5), actor_pos=(2, 5), other_pos=(5, 5))  # on-axis, well inside
    assert _hit(area, aim=(8, 5), actor_pos=(2, 5), other_pos=(6, 6))  # perp = 5 ft: just inside
    assert not _hit(area, aim=(8, 5), actor_pos=(2, 5), other_pos=(12, 5))  # past the line's length
    # A line aimed east does not catch a creature to the north.
    assert not _hit(area, aim=(8, 5), actor_pos=(2, 5), other_pos=(5, 2))


def test_cone_widens_with_distance_from_the_caster():
    area = {"shape": "cone", "size_ft": 30}
    # Caster at (2,5) aiming east at (10,5); at 20 ft along, the cone is 20 ft wide (+-10 ft).
    assert _hit(area, aim=(10, 5), actor_pos=(2, 5), other_pos=(6, 6))  # along 20, perp 5: inside
    assert not _hit(area, aim=(10, 5), actor_pos=(2, 5), other_pos=(6, 8))  # along 20, perp 15: outside
    assert not _hit(area, aim=(10, 5), actor_pos=(2, 5), other_pos=(14, 5))  # past the cone's length


# ------------------------------------------------------------------ 3. aiming (factory_compiler._target_kind)
def test_earthbind_line_uses_its_printed_placement_range_and_keeps_its_area_length():
    mechanic = {"area": {"shape": "line", "size_ft": 20, "centered_on_self": False},
                "range": {"kind": "feet", "feet": 60}, "effects": _SAVE}
    assert _target_kind(mechanic) == ("CELL", 60)
    # The reach is the placement range; the shape keeps its own printed length, and says it is laid down at the aim
    # point so combat/typed_executor.py in_area puts it there (the table-level proof is tests/test_placed_areas.py).
    assert _aimed_area(mechanic) == {"shape": "line", "size_ft": 20, "centered_on_self": False, "placed": True}
    assert _aimed_area(mechanic)["size_ft"] == 20


def test_a_line_whose_own_length_is_its_range_is_aimed_by_that_length_and_not_placed():
    """Heaven-Splitting Gale: a 300-foot line with Range 300 feet. Its length IS its range, so the line still runs
    out from its user -- placing it at the aim point would give a 600-foot reach the text does not print."""
    mechanic = {"area": {"shape": "line", "size_ft": 300, "centered_on_self": False},
                "range": {"kind": "feet", "feet": 300}, "effects": _SAVE}
    assert _target_kind(mechanic) == ("CELL", 300)
    assert _aimed_area(mechanic) == mechanic["area"]


def test_self_origin_cone_is_still_aimed_by_its_own_length():
    mechanic = {"area": {"shape": "cone", "size_ft": 15, "centered_on_self": True},
                "range": {"kind": "feet", "feet": 60}, "effects": _SAVE}
    assert _target_kind(mechanic) == ("CELL", 15)
    assert _aimed_area(mechanic) == mechanic["area"]


def test_self_range_line_is_still_aimed_by_its_own_length():
    mechanic = {"area": {"shape": "line", "size_ft": 60}, "range": {"kind": "self", "feet": 0},
                "effects": _SAVE}
    assert _target_kind(mechanic) == ("CELL", 60)
    assert _aimed_area(mechanic) == mechanic["area"]


def test_line_with_no_separate_range_is_still_aimed_by_its_own_length():
    mechanic = {"area": {"shape": "line", "size_ft": 30}, "range": None, "effects": _SAVE}
    assert _target_kind(mechanic) == ("CELL", 30)
    assert _aimed_area(mechanic) == mechanic["area"]


def test_emanation_stays_self_centred():
    mechanic = {"area": {"shape": "emanation", "size_ft": 15}, "range": {"kind": "self", "feet": 0}, "effects": []}
    assert _target_kind(mechanic) == ("SELF", None)
    assert _aimed_area(mechanic) == mechanic["area"]


def test_only_the_seven_printed_placement_rows_are_marked_placed():
    """The placement rule is general, so it is worth pinning which typed rows it moves: the seven line rows whose
    printed Range is longer than the shape. Every other line/cone in the authority is untouched, which is what keeps
    replays of existing AI fights byte-identical."""
    placed = sorted(mid for mid, mechanic in mechanics().items() if (_aimed_area(mechanic) or {}).get("placed"))
    assert placed == ["TAL_EARTH_EARTHBIND_LINE", "TAL_MAGMA_BLACKGLASS_RIVER", "TAL_MAGMA_LAVA_FLOW",
                      "TAL_METAL_IRON_SAND_RIVER", "TAL_SOUND_RESONANT_SHATTER", "TAL_SOUND_WORLD_RINGING_NOTE",
                      "tianxia.talent.gravity.falling_line"]
    # A line/cone with no numeric Range, or one whose length is its own range, is never moved to the aim point.
    unplaced = {mid: mechanic for mid, mechanic in mechanics().items()
                if (mechanic.get("area") or {}).get("shape") in ("line", "cone")
                and not (_aimed_area(mechanic) or {}).get("placed")}
    assert "TAL_AIR_HEAVEN_SPLITTING_GALE" in unplaced      # 300-foot line, Range 300 feet
    assert "tianxia.talent.destruction.ruin_crossing_step" in unplaced  # 10-foot line, Range 10 feet
    assert "tianxia.subpath.qi.black_sea_leviathan_womb.feature.abyssal_maw" in unplaced  # a cone from its user


# ------------------------------------------------------------------ 4. one full engine run
def _intent(candidate):
    return ActionIntent(intent_id="test:area", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        destination=candidate.destination)


def test_full_engine_run_a_line_hits_two_and_misses_one_to_the_north():
    engine = Gate2Engine(ROOT, match_seed="AREA-LINE")
    actor = engine.state.actors[engine.state.current_actor_id]
    typed = {"effects": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"]}],
             "riders": [], "numbers": {"pb": 6, "save_dc": 10, "attack_bonus": 5, "key_mod": 3},
             "weapon": None, "duration": {"kind": "instant"}, "area": {"shape": "line", "size_ft": 30, "width_ft": 10}}
    action = ActionDefinition(source_definition_id="action:typed.line_test", display_name="Line test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL",
                              range_ft=30, radius_ft=30, parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    actor.position = Position(x=2, y=5)
    hostiles = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    assert len(hostiles) >= 3
    hostiles[0].position = Position(x=5, y=5)  # inside, on the line's axis
    hostiles[1].position = Position(x=6, y=6)  # inside, at the line's edge (perp = width/2)
    hostiles[2].position = Position(x=5, y=2)  # north of the line: outside
    before = {h.entity_id: h.current_hp + h.temporary_hp for h in hostiles}
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "action:typed.line_test" and c.destination == Position(x=8, y=5))
    engine.execute_intent(_intent(candidate))
    after = {h.entity_id: h.current_hp + h.temporary_hp for h in hostiles}
    assert after[hostiles[0].entity_id] < before[hostiles[0].entity_id]
    assert after[hostiles[1].entity_id] < before[hostiles[1].entity_id]
    assert after[hostiles[2].entity_id] == before[hostiles[2].entity_id]


def test_the_ai_counts_the_enemies_a_line_would_actually_catch_from_each_aim_square():
    """Step 13 (owner 2026-09-26): the aim squares offered for a line or cone, and the damage the AI expects,
    counted the enemies within a circle of the line's length around the square."""
    engine = Gate2Engine(ROOT, match_seed="AREA-LINE-AIM")
    actor = engine.state.actors[engine.state.current_actor_id]
    typed = {"effects": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"]}],
             "riders": [], "numbers": {"pb": 6, "save_dc": 10, "attack_bonus": 5, "key_mod": 3},
             "weapon": None, "duration": {"kind": "instant"}, "area": {"shape": "line", "size_ft": 30, "width_ft": 5}}
    action = ActionDefinition(source_definition_id="action:typed.line_aim", display_name="Line aim", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL",
                              range_ft=30, radius_ft=30, parameters={"typed": typed, "expected_damage": 3})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    actor.position = Position(x=2, y=5)
    hostiles = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    hostiles[0].position = Position(x=4, y=5)
    hostiles[1].position = Position(x=6, y=5)
    for other in hostiles[2:]:
        other.position = Position(x=2, y=9)  # due south of the caster, off the east-west row
    aims = {c.destination: c.metadata for c in engine.legal_candidates() if c.source_definition_id == "action:typed.line_aim"}
    assert aims[Position(x=7, y=5)]["hostiles_in_area"] == 2          # straight along the row: both
    assert aims[Position(x=7, y=5)]["expected_damage"] == 6
    # Players may aim at a visible empty square; the existing AI filter must
    # still omit the north-east line that catches no known enemy.
    assert aims[Position(x=5, y=2)]["hostiles_in_area"] == 0
    assert aims[Position(x=5, y=2)]["empty_area"]
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    ai = build_decision_context(engine, PolicyLibrary(ROOT).fallback(), for_ai=True)
    assert not any(c.destination == Position(x=5, y=2) and c.source_definition_id == action.source_definition_id
                   for c in ai.legal_candidates)
    assert all(meta["hostiles_in_area"] == sum(other.team_id != actor.team_id
                                               for other in _area_targets(engine, actor, aim, typed["area"]))
               for aim, meta in aims.items())
