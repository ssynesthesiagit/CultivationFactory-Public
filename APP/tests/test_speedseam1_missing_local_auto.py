"""Missing Local Auto fights must not be created by taking a reservation."""
import pytest

from combat.gate5_service import CombatService, CombatServiceError
from tests.worker2_support import ROOT


@pytest.mark.parametrize('method', ['local_step', 'local_run'])
def test_missing_fight_does_not_create_storage(tmp_path, method):
    combat = CombatService(ROOT, tmp_path)
    match_id = 'missing-fight'
    path = combat._match_dir(match_id)
    with pytest.raises(CombatServiceError) as error:
        getattr(combat, method)(match_id)
    assert error.value.status_code == 404
    assert not path.exists()
