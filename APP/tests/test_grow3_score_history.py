"""Level growth and campaign resets use the same chronology; public fixtures."""
from combat import table_advance as ta
from tests.test_grow3_levelup import PID, choices, service


def test_reset_at_new_level_recomputes_hp_pools_ac_and_saves_then_removes(tmp_path):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    before = s.combat._factory_owner_sheet(PID)
    spread = ta.default_spread("INT")
    s.add_ability(PID, {"reason": "gm_respec", "cl": 2, "changes": spread})
    cold = service(tmp_path)
    after = cold.combat._factory_owner_sheet(PID)
    old, new = before["ability_scores_and_statistics"], after["ability_scores_and_statistics"]
    assert ta.current_scores(after) == spread
    assert new["hit_points"]["maximum"] == old["hit_points"]["maximum"] - 2
    assert new["saving_throws"]["CON"] == 4
    assert new["saving_throws"]["INT"] == 4
    assert new["armor_class"]["base_value"] == 11  # DEX 13, modifier +1
    assert new["primary_resource"]["maximum"] == 4  # INT 15, max(2*CL, INT mod*CL)
    cold.remove_advancement(PID, "ability", "0")
    assert service(tmp_path).combat._factory_owner_sheet(PID) == before
    service(tmp_path).undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID)["identity"]["cultivation_level"] == 1
