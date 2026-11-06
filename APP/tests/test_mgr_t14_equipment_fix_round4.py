"""Standing armor qualification must agree between the table and real damage."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_fitted_armor import ACTOR, ROOT, fight, sheet, support
from tests.test_mgr_t14_armor_defenses import DAMAGE, damage_action


@pytest.mark.parametrize("case", ["untrained", "use", "decline"])
def test_padded_table_defense_requires_training_but_not_packet_consent(tmp_path, case):
    doc = sheet(["padded_layers"], proficiency=() if case == "untrained" else ("medium",))
    combat, table, mid = fight(tmp_path, doc, prepare=damage_action)
    actor = combat._load_session(mid).engine.state.actors[ACTOR]
    expected = [] if case == "untrained" else [{
        "damage_type": f"Bludgeoning damage reduced by {actor.proficiency_bonus}",
        "source": "Padded Layers", "until": None, "note": "once per round"}]

    def card(service):
        row = next(row for row in service.state(mid)["presentation"]["actors"]
                   if row["entity_id"] == ACTOR)
        return row["damage_defenses"]["reductions"]

    assert card(table) == expected
    prompts = support._commit(combat, table, mid, DAMAGE,
                             answer=lambda prompt: None if case == "decline" else ["use"])
    cold = support._reload(tmp_path, mid)
    packet, = support._packets(cold, DAMAGE)
    assert packet.payload["hp_damage"] == 20 - actor.proficiency_bonus * int(case == "use")
    assert len(prompts) == int(case != "untrained")
    # The card describes a standing, once-per-round benefit even after this
    # packet was declined or this round's use was spent. Read from a new service.
    assert card(TabletopService(CombatService(ROOT, tmp_path), tmp_path)) == expected
