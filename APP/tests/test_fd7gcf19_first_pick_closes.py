"""FD7GCF19 round: no Golden Core Form record at all once the CL15 Nascent Soul feature is used.

The printed window "Choose one Golden Core Form. You may replace the chosen Form after a
successful CL15 breakthrough before using your CL15 Nascent Soul feature." closed only on a
REPLACEMENT (a recorded first Form): a character that had recorded no Form could still pick a
permanent first Form after the use, so the table-level regression in
tests/test_h52_nascent_continuity.py (a real fight spends Nascent Continuity, commits, then a Grow
pick) could never see its refusal. The printed permission the CL10 first Form rides ends with the
same use, so ``validate`` now refuses any slot-1 record, first pick included, with a plain reason.
"""
import pytest

from combat.ext.qi_path import NASCENT_SOUL
from combat.tabletop_service import TabletopError
from tests.test_fd7gcf11_golden_core_closure import _reloaded, _service


def test_the_first_permanent_form_cannot_be_recorded_after_the_nascent_soul_use():
    """GOLDEN feature owner with no recorded Form at CL20: after the Nascent Soul use, Grow refuses."""
    table, sheet, store = _service(20)
    store['advancement']['feature_uses'] = [{'feature_id': NASCENT_SOUL, 'at': 'test'}]
    with pytest.raises(TabletopError) as refused:
        table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert refused.value.code == 'TABLETOP_GOLDEN_CLOSED'
    # and nothing was recorded beside the character
    reloaded = _reloaded(sheet, store)
    assert reloaded['path_and_subpath']['golden_core_forms'] == []


def test_the_first_permanent_form_is_still_choosable_before_the_nascent_soul_use():
    """Owner 2026-10-19 08:50Z: a no-record Golden Core character must still be able to choose."""
    table, sheet, store = _service(20)
    table.set_build_choice('char', 'golden_core', choice='stable', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['stable']
