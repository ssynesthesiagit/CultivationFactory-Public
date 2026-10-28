"""TEMPORARY diagnostics for SOLSYS-SPACE1F2 (not for commit)."""
import pytest

from tests.test_hunt32_edge import OWNER, FOE, match
from tests.test_solsys_space import candidates

REACH = "tianxia.talent.space.folded_reach"
LINE = "tianxia.talent.space.folded_weapon_line"

LINES = []


def open_centre(arena):
    arena["terrain_regions"] = [r for r in arena.get("terrain_regions", [])
                                if r.get("region_id") != "pillar.centre"]


@pytest.mark.parametrize("foe,label,edit", [({"x": 9, "y": 6}, "pillar", None),
                                           ({"x": 9, "y": 6}, "nopillar", open_centre),
                                           ({"x": 8, "y": 6}, "near", None),
                                           ({"x": 12, "y": 6}, "far", None)])
def test_diag_reason(tmp_path, foe, label, edit):
    combat, table, mid = match(tmp_path, [REACH, LINE], positions={
        OWNER: {"x": 3, "y": 6}, FOE: foe}, arena_edit=edit, setup_actions=[{
            "name": "AC", "target": "ANY_CREATURE",
            "effects": [{"type": "ac_bonus", "flat": -100, "applies_to": "target",
                         "expires_on": "UNTIL_REMOVED"}]}])
    engine = combat._load_session(mid).engine
    LINES.append("=== %s foe=%s" % (label, foe))
    for region in (engine.arena.get("terrain_regions") or []):
        LINES.append("REGION %s %s %s" % (region.get("region_id"), region.get("terrain_type"),
                                          [c for c in region.get("cells", [])]))
    choices = list(candidates(combat, mid, "test:h32.setup"))
    LINES.append("SETUPCANDS %s" % [(c.source_definition_id, c.target_ids) for c in choices])
    from combat import action_legality
    from combat import target_knowledge
    LINES.append("QUERY %s" % (action_legality.query_target(
        engine, OWNER, "action:test.h32.setup.0", FOE),))
    LINES.append("CANSEE %s" % (target_knowledge.can_see(
        engine, engine.state.actors[OWNER], engine.state.actors[FOE]),))
    LINES.append("KNOWN %s" % (target_knowledge.knowledge(
        engine, engine.state.actors[OWNER], engine.state.actors[FOE],
        engine.action_catalog["action:test.h32.setup.0"]),))


def test_zz_report():
    assert False, "\n".join(LINES)
