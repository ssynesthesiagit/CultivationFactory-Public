"""Heavy armor requires ten minutes of fitting after waking, not before sleep."""
import pytest

from combat import posture
from tests.test_a2_equipment import PREPARE
from tests.test_mgr_t14_armor_consumers import heavy_sheet, HEAVY, finish
from tests.test_mgr_t14_fitted_armor import command, fit, fight, support, ACTOR, prone_action


def test_heavy_refit_discards_pre_rest_work_and_survives_cold_fights(tmp_path):
    doc = heavy_sheet(["sleep_in_armor", "breath_aligned_armor"])
    fit(tmp_path, doc, HEAVY)
    command(tmp_path, doc, "armor.fit.start", item_key=HEAVY)
    command(tmp_path, doc, "time.advance", seconds=599, observation="fitting")
    command(tmp_path, doc, "rest.start", kind="long_rest")
    command(tmp_path, doc, "time.advance", seconds=28800, observation="sleep")
    after = command(tmp_path, doc, "time.advance", seconds=1, observation="fitting")
    assert after["armor"]["ready"] == 0, "Pre-rest work cannot satisfy post-waking refitting"
    combat, table, mid = fight(tmp_path, doc, prepare=prone_action)
    support._commit(combat, table, mid, PREPARE, actor=ACTOR)
    before = support._reload(tmp_path, mid).state.actors[ACTOR].movement_remaining_ft
    support._commit(combat, table, mid, posture.SOURCE, actor=ACTOR)
    assert support._reload(tmp_path, mid).state.actors[ACTOR].movement_remaining_ft == before - 10
    finish(combat, table, mid)
    assert command(tmp_path, doc, "time.advance", seconds=598, observation="fitting")["armor"]["ready"] == 0
    assert command(tmp_path, doc, "time.advance", seconds=1, observation="fitting")["armor"]["ready"] == 1
    combat, table, mid = fight(tmp_path, doc, prepare=prone_action)
    support._commit(combat, table, mid, PREPARE, actor=ACTOR)
    before = support._reload(tmp_path, mid).state.actors[ACTOR].movement_remaining_ft
    support._commit(combat, table, mid, posture.SOURCE, actor=ACTOR)
    assert support._reload(tmp_path, mid).state.actors[ACTOR].movement_remaining_ft == before - 5


def test_sleep_in_armor_rest_uses_committed_hp_without_helmet_discipline(tmp_path):
    from tests.test_mgr_t14_armor_defenses import damage_action, DAMAGE
    from services.factory_dm_v0.gameplay.models import EngineError
    doc = heavy_sheet(["sleep_in_armor"])
    def fatal(bundle):
        damage_action(bundle)
        if bundle["actor_id"] == support.ATTACKER:
            next(a for a in bundle["action_catalog"] if a["source_definition_id"] == DAMAGE)["parameters"]["typed"]["effects"][0]["flat"] = 1000
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=fatal)
    support._commit(combat, table, mid, DAMAGE)
    finish(combat, table, mid)
    assert support._reload(tmp_path, mid).state.actors[ACTOR].current_hp == 0
    with pytest.raises(EngineError, match="ACTOR_CANNOT_ACT"):
        command(tmp_path, doc, "rest.start", kind="long_rest")
