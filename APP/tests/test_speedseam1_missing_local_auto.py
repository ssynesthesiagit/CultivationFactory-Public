"""Missing Local Auto fights must not be created by taking a reservation."""
from contextlib import contextmanager

import pytest

from combat import tabletop_service
from combat.gate5_service import CombatService, CombatServiceError
from tests.worker2_support import ROOT


@pytest.mark.parametrize('method', ['local_step', 'local_run'])
@pytest.mark.parametrize('disappears_at_open', [False, True])
def test_missing_fight_does_not_create_storage(tmp_path, monkeypatch, method, disappears_at_open):
    combat = CombatService(ROOT, tmp_path)
    match_id = 'match:' + '0' * 24
    path = combat._match_dir(match_id)
    if disappears_at_open:
        path.mkdir(parents=True)
        lock = tabletop_service._table_action_lock

        @contextmanager
        def deleted_before_open(match_dir, *args, **kwargs):
            match_dir.rmdir()
            with lock(match_dir, *args, **kwargs):
                yield

        monkeypatch.setattr(tabletop_service, '_table_action_lock', deleted_before_open)

    with pytest.raises(CombatServiceError) as error:
        getattr(combat, method)(match_id)
    assert error.value.diagnostic.code == 'COMBAT_MATCH_NOT_FOUND'
    assert error.value.status_code == 404
    assert not path.exists()
