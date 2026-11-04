"""Greater Invisibility's printed willing-creature target works through the table."""

from combat.gate5_service import CombatService

from tests.test_tabletop_hunt6 import ALLY, LEFT, table_fight


GREATER_INVISIBILITY = "tianxia.talent.illusion.greater_invisibility"


def test_greater_invisibility_can_target_an_ally_and_survives_table_reload(tmp_path):
    combat, table, match_id = table_fight(tmp_path, [GREATER_INVISIBILITY])
    state = table.state(match_id)
    group = next(
        group for group in state["menu"]["actions"]
        if GREATER_INVISIBILITY in group["source_definition_id"]
    )
    ally_option = next(
        option for option in group["options"] if ALLY in option["target_ids"]
    )

    committed = table.act(
        match_id,
        ally_option["candidate_id"],
        state["menu"]["decision_id"],
        state["menu"]["state_version"],
        state["last_sequence"],
    )
    assert committed["status"] == "COMMITTED"

    loaded = CombatService(combat.source_root, tmp_path)._load_session(match_id)
    ally = loaded.engine.state.actors[ALLY]
    assert any("invisible" in row.condition_id for row in ally.conditions.values())
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_greater_invisibility_can_target_its_willing_caster(tmp_path):
    _, table, match_id = table_fight(tmp_path, [GREATER_INVISIBILITY])
    state = table.state(match_id)
    group = next(
        group for group in state["menu"]["actions"]
        if GREATER_INVISIBILITY in group["source_definition_id"]
    )
    target_ids = {target for option in group["options"] for target in option["target_ids"]}
    assert LEFT in target_ids
