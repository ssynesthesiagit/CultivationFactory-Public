"""A2R23F16: fix ambiguous height labels without losing elevated landings."""
from combat import falling
from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, answer_for, engine_of, find, play, table_fight,
)
from tests.test_a2_elevated_teleport_destinations import elevated_map

KEEP = elevated_map(10)


def _cell(option_id):
    parts = option_id.split(":", 1)[1].split(",")
    return int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0


def test_height_suffix_distinguishes_landings_and_all_heights_reach_the_table(tmp_path):
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP], map_doc=KEEP,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 9, "y": 7}},
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


def test_map_pick_labels_name_the_height_of_each_landing(tmp_path):
    """The landing question the player clicks on the map labels each legal
    height on a shared square, so "ground" and "20 ft up" are readable and
    distinct choices rather than two identical squares."""
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP], map_doc=KEEP,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 9, "y": 7}},
    )
    seen = []

    def choose(prompt):
        rows = [row for row in (prompt.get("choice") or {}).get("options") or []
                if str(row.get("id", "")).startswith("cell:")]
        if rows:
            seen.extend(rows)
        return answer_for(prompt)

    play(table, mid, find(table, mid, "flash_step"), answer=choose)
    assert seen, "the manual owner is asked where to land"
    by_square = {}
    for row in seen:
        x, y, z = _cell(row["id"])
        by_square.setdefault((x, y), {})[z] = row["label"]
    ambiguous = {square: levels for square, levels in by_square.items() if len(levels) > 1}
    assert ambiguous, "the roof map offers more than one legal height on one square"
    fighter = engine_of(combat, mid).state.actors[FIGHTER]
    for square, levels in by_square.items():
        for z in levels:
            if z:
                assert falling.supported(engine_of(combat, mid), fighter, Position(x=square[0], y=square[1], z=z)), \
                    f"aerial landing without support: {square} z={z}"
    for (x, y), levels in ambiguous.items():
        assert len(set(levels.values())) == len(levels)
        for z, label in levels.items():
            height = "ground" if z == 0 else f"{z * 5} ft up"
            assert label == f"Teleport to {x},{y} — {height}"
