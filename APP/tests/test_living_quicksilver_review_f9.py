"""Review F9 regression diagnostics and native acceptance."""
import traceback
import pytest
from tests import test_living_quicksilver_native as native


def test_no_space_start_turn_native(tmp_path, monkeypatch):
    try:
        native.test_native_start_turn_without_any_legal_body_space_continues_to_configuration(tmp_path, monkeypatch)
    except StopIteration:
        frames = traceback.extract_tb(__import__('sys').exc_info()[2])
        pytest.fail(str([(f.name, f.lineno, f.line) for f in frames[-3:]]))
