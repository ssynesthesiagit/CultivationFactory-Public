"""Native attached-effect/funding regression chunk for whole-file public CI.

Reuse the preservation scenario rather than copying its casts and assertions;
only these three cases changed when main added the player funding question.
"""
import pytest

from tests.test_hunt27_water import test_returning_streams_move_preserves_attached_effects_reload as attached_case


@pytest.mark.parametrize(('manual', 'mixed'), [(True, False), (False, False), (True, True)])
def test_native_attached_effects_survive_free_return_funding(tmp_path, manual, mixed):
    attached_case(tmp_path, manual, mixed)
