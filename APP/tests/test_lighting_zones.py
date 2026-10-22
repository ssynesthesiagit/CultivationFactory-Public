"""Magical darkness over ordinary light: docs/specs/LIGHTING_SPEC.md §2.7, §4.1 step 4, §4.2 E10.

Light is painted onto the field; the area then resolves it per viewer. These tests pin the order: the field keeps the
torch, the area takes the square down to Dark for a viewer without a sense into it, and only a printed suppression
lifts the cap -- for the viewer that print names, never for everyone.
"""
from combat import attack_modes, ext, lighting, senses, zones
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import candidate, reload, settle

NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]


def darkness(tmp_path, **kwargs):
    document = map_document(20, 14, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION,
                               talents=["DARK_BASE_DARKNESS"],
                               positions={OWNER: {"x": 6, "y": 6}, ALLY: {"x": 17, "y": 6}, FOE: {"x": 2, "y": 2}},
                               **kwargs)
    settle(table, mid, candidate(combat, mid, "Darkness", at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    return engine, engine.state.actors[OWNER], engine.state.actors[ALLY]


def test_worked_example_e10_the_field_keeps_the_torch_and_the_area_resolves_it(tmp_path):
    engine, owner, ally = darkness(tmp_path)
    torch = lighting._position_of((8, 6))
    assert lighting.base(engine, 8, 6) == lighting.BRIGHT          # the model paints the light
    assert lighting.seen_level(engine, owner, torch) == lighting.DARK   # the area resolves it for a viewer without Darkvision
    assert lighting.seen_level(engine, ally, torch) == lighting.DIM     # Darkvision raises the capped level one step
    assert len(zones.heavy_zones(engine)) == 1


def test_the_capped_square_is_dark_for_every_creature_that_stands_in_it(tmp_path):
    engine, owner, ally = darkness(tmp_path)
    assert lighting.seen_level(engine, owner, lighting._position_of((6, 6))) == lighting.DARK
    assert lighting.seen_level(engine, ally, lighting._position_of((17, 6))) == lighting.DIM
    assert zones.dark_cell(engine, owner, senses.cell_probe(lighting._position_of((8, 6)))) is True
    assert zones.dark_cell(engine, owner, senses.cell_probe(lighting._position_of((2, 12)))) is False


def test_both_creatures_blind_cancels_the_way_it_always_did(tmp_path):
    engine, owner, ally = darkness(tmp_path)
    modes = zones.attack_modes(engine, owner, ally)
    assert "DISADVANTAGE" in modes
    assert set(attack_modes.presentation_modes(engine, owner, ally)) <= {"ADVANTAGE", "DISADVANTAGE"}


def test_a_printed_suppression_lifts_the_cap_for_the_viewer_it_names(tmp_path, monkeypatch):
    engine, owner, ally = darkness(tmp_path)
    torch = lighting._position_of((8, 6))
    assert lighting.seen_level(engine, owner, torch) == lighting.DARK
    assert lighting.seen_level(engine, ally, torch) == lighting.DIM

    def suppressed(engine_, zone, viewer, seen):
        """A printed darkness_lifted: this viewer, and no one else, sees through the area."""
        return True if getattr(viewer, "entity_id", None) == OWNER else None

    monkeypatch.setitem(ext._HOOKS, "darkness_lifted",
                        (*ext._HOOKS.get("darkness_lifted", ()), suppressed))
    assert lighting.seen_level(engine, owner, torch) == lighting.BRIGHT
    assert lighting.seen_level(engine, ally, torch) == lighting.DIM
