"""act() accepts an exact native cell id that the guarded player menu omits.

Regression for the TABLETOP_STALE break: the exact-id fallback must search the
engine's full native list, so every id the engine reports as legal commits.
"""
from tests.worker2_support import candidate, fixture, reload, settle

STILL = 'TAL_WATER_STILL_SURFACE_METHOD'


def test_exact_native_cell_id_missing_from_the_guarded_menu_commits(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [STILL])
    native = candidate(combat, mid, 'Shape Current: Mist Basin', at=(4, 6))
    cid = native.candidate_id
    assert native.destination is not None

    guarded = combat._legal_candidates

    def without_native_cell(session, *args, **kwargs):
        # The guarded player query drops this legal native id, as it did before the fix.
        return tuple(c for c in guarded(session, *args, **kwargs) if c.candidate_id != cid)

    monkeypatch.setattr(combat, '_legal_candidates', without_native_cell)
    # Precondition: the menu does not offer the id, so act() must take the exact-id fallback.
    offered = {row['candidate_id'] for row in combat.decision(mid)['context']['legal_candidates']}
    assert cid not in offered

    before = reload(tmp_path, mid).state.event_sequence
    settle(table, mid, cid)  # act() must commit it, not refuse it as TABLETOP_STALE
    assert reload(tmp_path, mid).state.event_sequence > before
