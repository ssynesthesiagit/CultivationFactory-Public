"""Temporary queued traceback capture for clinical qualification; not acceptance."""
import traceback
from tests.test_mgr_t14_clinical_consumers import (
    test_successful_ingrain_save_spends_marks_and_cp_without_new_toxin as scenario,
)
from tests.test_mgr_t14_clinical_native import final_native_mechanical_replay


def test_successful_ingrain_trace(tmp_path, monkeypatch):
    try:
        scenario(tmp_path, monkeypatch)
    except Exception:
        raise AssertionError(traceback.format_exc()) from None
