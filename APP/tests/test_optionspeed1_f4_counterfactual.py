"""Disposable review evidence: every new bug regression rejects pre-fix code."""
from pathlib import Path
import pytest
from tests import test_optionspeed1_f4_review as review


@pytest.fixture(autouse=True)
def old_clients(monkeypatch):
    base = Path(__file__).parent / 'optionspeed1_f4_baseline'
    monkeypatch.setenv('OPTIONSPEED_DESKTOP_SOURCE', str(base / 'tabletop.js'))
    monkeypatch.setenv('OPTIONSPEED_PHONE_SOURCE', str(base / 'play-client.js'))


def test_assisted_rejects_old_desktop(tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match='Assisted must preview the draft before committing'):
        review.test_desktop_assisted_confirmation_uses_draft_and_reconfirms_square(tmp_path, monkeypatch)


@pytest.mark.parametrize('client', ['desktop', 'phone'])
@pytest.mark.parametrize('source', [review.posture.SOURCE, review.hold_position.SOURCE])
def test_native_rejects_old_clients(tmp_path, monkeypatch, client, source):
    marker = ('Native action must use its issued candidate' if client == 'desktop'
              else 'Choosing a native action must not preview a composition')
    with pytest.raises(AssertionError, match=marker):
        review.test_native_actions_remain_usable_with_a_local_draft(tmp_path, monkeypatch, client, source)


def test_named_talent_rejects_old_desktop(tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match='Explicitly named saved-active talent must replace the conflicting draft'):
        review.test_named_saved_active_sheet_talent_replaces_a_conflicting_draft(tmp_path, monkeypatch)
