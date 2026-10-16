"""Temporary queued traceback capture for clinical qualification; not acceptance."""
import traceback
from tests.test_mgr_t14_clinical_consumers import (
    test_successful_ingrain_save_spends_marks_and_cp_without_new_toxin as scenario,
)
from tests.test_mgr_t14_clinical_native import final_native_mechanical_replay


def test_successful_ingrain_trace(tmp_path, monkeypatch):
    try:
        scenario(tmp_path, monkeypatch)
    except Exception as exc:
        frames=traceback.extract_tb(exc.__traceback__)
        trace=' | '.join(f'{f.filename.rsplit("/",1)[-1]}:{f.lineno} {f.name}: {f.line}' for f in reversed(frames[-6:]))
        raise AssertionError(f'{type(exc).__name__}: {exc} | {trace}') from None
