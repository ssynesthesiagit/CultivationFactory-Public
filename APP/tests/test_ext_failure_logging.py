"""A failing plug-in hook never changes the fight while choices are listed, and is reported once (2026-09-30: one failing
hook wrote 436 events during legal_candidates(), so every button was refused as stale)."""

from combat import ext
from tests.test_effect_durations import _fight


def test_a_failing_hook_while_listing_writes_no_event_and_keeps_candidate_ids(monkeypatch):
    engine, me, foe = _fight("EXTFAIL")
    ext._load()

    def broken(*args, **kwargs):
        raise KeyError("")

    monkeypatch.setitem(ext._HOOKS, "candidate_allowed", [*ext._HOOKS.get("candidate_allowed", []), broken])
    before = len(engine.events)
    first = [c.candidate_id for c in engine.legal_candidates()]
    second = [c.candidate_id for c in engine.legal_candidates()]
    assert first == second and len(engine.events) == before


def test_outside_listing_a_failing_hook_is_one_gm_note_per_fight():
    engine, me, foe = _fight("EXTFAIL")

    def broken(*args, **kwargs):
        raise ValueError("boom")

    for _ in range(3):
        ext._log("technique_used", broken, ValueError("boom"), (engine,))
    notes = [e for e in engine.events if e.event_type == "GM_RIDER" and "boom" in str((e.payload or {}).get("rider"))]
    assert len(notes) == 1
