"""Exported hover-card guards report absent board assets before DOM checks."""
import subprocess

import pytest

from tests import test_hovercard_interactive as hover


def test_board_snapshot_validates_shared_art_asset_before_node(monkeypatch, tmp_path):
    monkeypatch.setattr(hover, 'APP', tmp_path)
    def unexpected_node(*args, **kwargs):
        pytest.fail('Node must not start with an incomplete board snapshot')
    monkeypatch.setattr(subprocess, 'run', unexpected_node)
    with pytest.raises(AssertionError, match=r'Missing board runtime asset: static/tabletop/art-kit\.js'):
        hover.test_map_card_dismissal_and_two_cards_in_one_document()


def test_compact_hover_failure_retains_missing_module_cause(monkeypatch):
    message = "# Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/snapshot/art-kit.js'"
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, stdout=message + '\n', stderr=''))
    with pytest.raises(AssertionError) as failure:
        hover._node_test('tests/hovercard_board_dom.test.mjs')
    assert "Cannot find module '/snapshot/art-kit.js'" in str(failure.value).splitlines()[0]
