"""Nested opportunity attacks must carry their own source to the table prompt."""
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, HOLD
from tests.test_carry import KIT
from tests.r10_fixup_support import cast_sender
from tests.test_hunt18_teamwork import TEAMWORK, commit


def test_teamwork_names_opportunity_attack_during_movement(tmp_path):
    combat, table, mid = table_fight(tmp_path, [TEAMWORK], kit={"starting_kit": KIT},
                                     ask=True, ally_talents=[])
    # A completed action cannot become the source of an attack nested in Move.
    commit(cast_sender(combat, table, mid, "Hold position"))
    prompts = commit(cast_sender(combat, table, mid, "Move", at=(0, 4)))
    teamwork = next(p for p in prompts if p["reaction"] == "Defensive Teamwork")
    assert "opportunity" in teamwork["trigger"].lower()
    assert "Hold position" not in teamwork["trigger"]
    assert "Left" in teamwork["trigger"] and "Right" in teamwork["trigger"]
    assert CombatService(combat.source_root, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
