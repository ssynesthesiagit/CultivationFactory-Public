"""Public synthetic menu regressions for explicit primary-intent permissions."""
from tests.test_a2_hunger_second_pass import table_fixture, BASE, DRAGON
from tests.hunt31_support import OWNER


def test_hunger_paid_options_reach_owner_menu(monkeypatch, tmp_path):
    combat, table, mid = table_fixture(monkeypatch, tmp_path, [BASE, DRAGON])
    engine = combat._load_session(mid).engine
    rows = [a for a in engine.action_catalog.values() if a.owner_id == OWNER
            and "Digestive Mantle" in a.display_name]
    menu = table.state(mid)["menu"]
    assert "Digestive Mantle: Thick Hide" in {g["label"] for g in menu["actions"]}, (
        [(a.display_name, str(a.economy), a.costs, a.parameters) for a in rows],
        engine.state.actors[OWNER], menu)
