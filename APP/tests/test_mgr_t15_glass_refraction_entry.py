"""The entry declaration covers later turns in the same scene."""
import pytest

from combat.tabletop_service import TabletopError
from combat.ext.glass_heart_refraction import SOURCE
from tests.test_a2_foundations_two import table_fixture, use
from tests.glass_refraction_support import declare, available
from tests.worker2_support import OWNER, FOE, reload, turn


def test_other_turn_entry_remains_available_in_the_same_scene(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    turn(table, mid, FOE)
    declare(combat, table, mid)
    turn(table, mid, OWNER)
    assert available(reload(tmp_path, mid))
    turn(table, mid, FOE); turn(table, mid, OWNER)
    assert available(reload(tmp_path, mid))


def test_other_turn_entry_can_activate_after_cold_reload(tmp_path):
    from combat.ext.foundation_combat import held
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    turn(table, mid, FOE)
    declare(combat, table, mid)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert held(owner, 'glass_refraction')
    assert owner.resources['resource:core.qi'] == before - 2


def test_malformed_private_input_fails_without_a_commit(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    version = table.source_inputs(mid)['state_version']
    before = reload(tmp_path, mid).state.state_version
    with pytest.raises(TabletopError):
        table.record_source_input(mid, SOURCE, OWNER,
            {'scene': [], 'reason': 'The actual scene.'}, version)
    assert reload(tmp_path, mid).state.state_version == before


def test_state_says_whether_declarations_exist_without_reading_the_endpoint(tmp_path, monkeypatch):
    """The table's declaration entry follows the poll, so the state (not the entry) knows the answer.

    A GM view shows the entry exactly when this fight has owner declarations; the fight state carries that
    yes/no from the same plug-in forms the /source-inputs dialog lists, and reading the state never asks the
    endpoint itself (one extra request per poll is what made an unchanged poll do work).
    """
    from combat.tabletop_service import TabletopService
    reads = []
    monkeypatch.setattr(TabletopService, 'source_inputs',
                        lambda *args, **kwargs: reads.append(args) or {'forms': []})
    _, glass, glass_mid = table_fixture(tmp_path / 'glass', 'glass', current=0)
    assert glass.state(glass_mid)['source_inputs_available'] is True
    _, plain, plain_mid = table_fixture(tmp_path / 'plain', 'tyrant', current=0)
    assert plain.state(plain_mid)['source_inputs_available'] is False
    assert reads == []
