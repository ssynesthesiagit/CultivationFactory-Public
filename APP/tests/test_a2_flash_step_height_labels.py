"""A2R23F16: fix ambiguous height labels without losing elevated landings."""
from combat import falling
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, engine_of, table_fight,
)
from tests.test_a2_elevated_teleport_destinations import elevated_map

KEEP = elevated_map(10)


def test_height_suffix_distinguishes_landings_and_all_heights_reach_the_table(tmp_path):
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP], map_doc=KEEP,
        where={FIGHTER: {"x": 7, "y": 3}, FOE: {"x": 10, "y": 7}},
    )
    options = [
        row for row in engine_of(combat, mid).legal_candidates()
        if "flash_step" in row.source_definition_id and row.destination is not None
    ]
    heights = {}
    for row in options:
        pos = row.destination
        heights.setdefault((pos.x, pos.y), set()).add(pos.z)
    assert any(len(levels) > 1 for levels in heights.values())
    fighter = engine_of(combat, mid).state.actors[FIGHTER]
    for row in options:
        pos = row.destination
        if pos.z:
            assert falling.supported(engine_of(combat, mid), fighter, pos), f"aerial landing without support: {pos}"
    for row in options:
        pos = row.destination
        suffix = ""
        if len(heights[(pos.x, pos.y)]) > 1:
            height = "ground" if pos.z == 0 else f"{pos.z * 5} ft up"
            suffix = f" — {height}"
        assert row.display_name == f"Flash Step to {pos.x},{pos.y}{suffix}"
    labels = {
        option["candidate_id"]: option["label"]
        for group in table.state(mid)["menu"]["actions"]
        for option in group["options"]
    }
    assert all(labels[row.candidate_id] == row.display_name for row in options)
    assert len({row.candidate_id for row in options}) == len(options)


def test_destination_menu_labels_name_the_height_of_each_landing(tmp_path):
    """Menu choices at a shared square name their distinct landing heights."""
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP], map_doc=KEEP,
        where={FIGHTER: {"x": 7, "y": 3}, FOE: {"x": 10, "y": 7}},
    )
    labels = {option["candidate_id"]: option["label"]
              for group in table.state(mid)["menu"]["actions"]
              for option in group["options"]}
    by_square = {}
    for row in engine_of(combat, mid).legal_candidates():
        if "flash_step" in row.source_definition_id and row.destination is not None:
            pos = row.destination
            by_square.setdefault((pos.x, pos.y), {})[pos.z] = labels[row.candidate_id]
    ambiguous = {square: levels for square, levels in by_square.items() if len(levels) > 1}
    assert ambiguous, "the roof map offers more than one legal height on one square"
    for (x, y), levels in ambiguous.items():
        assert len(set(levels.values())) == len(levels)
        for z, label in levels.items():
            height = "ground" if z == 0 else f"{z * 5} ft up"
            assert label == f"Flash Step to {x},{y} — {height}"
