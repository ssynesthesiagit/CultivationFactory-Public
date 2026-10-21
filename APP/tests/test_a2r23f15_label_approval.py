"""A2R23F16: fix ambiguous height labels without losing elevated landings."""
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, engine_of, table_fight,
)
from tests.test_a2r23f_review import KEEP


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
    for row in options:
        pos = row.destination
        suffix = ""
        if len(heights[(pos.x, pos.y)]) > 1:
            height = "ground" if pos.z == 0 else f"{pos.z * 5} ft up"
            suffix = f" ({height})"
        assert row.display_name == f"Flash Step to {pos.x},{pos.y}{suffix}"
    labels = {
        option["candidate_id"]: option["label"]
        for group in table.state(mid)["menu"]["actions"]
        for option in group["options"]
    }
    assert all(labels[row.candidate_id] == row.display_name for row in options)
    assert len({row.candidate_id for row in options}) == len(options)
