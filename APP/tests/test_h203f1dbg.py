"""Temporary H203FIX1F1 diagnostics round 2 (deleted before commit)."""
import pytest
from tests.worker2_support import fixture, OWNER, FOE, ALLY
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_r9i_karma_persistence import act

ERODE = "TAL_VOID_ERODE_TECHNIQUE"


def test_dbg_temp_hp_probe(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [ERODE], ask=False)
    def grant(e):
        e._grant_temp_hp(e.state.actors[FOE], 20, "test:regeneration", FOE)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    result = act(table, mid, cid)
    e = combat._load_session(mid).engine
    counts = {}
    for x in e.events:
        counts[x.event_type] = counts.get(x.event_type, 0) + 1
    riders = [f"{x.event_type}:{x.source_definition_id}:{str(x.payload)[:90]}" for x in e.events
              if x.event_type in ("GM_RIDER", "PASSIVE_TRIGGERED", "REACTION_DECLINED", "REACTION_RESOLVED", "RESOURCE_SPENT")]
    tp = e.state.actors[FOE].temporary_hp
    from combat import typed_reactions as tr
    e._pending_healing = {"subject": FOE, "amount": 20, "kind": "temp_hp", "source": "test:regeneration"}
    try:
        rows = tr._generic_rows(e, OWNER, "temp_hp_gained")
        kinds = [(r.get("kind"), r.get("name"), [eff.get("type") for eff in r.get("effects") or []]) for r in rows]
        before = len(e.events)
        tr.on_creature_event(e, e.state.actors[FOE], "temp_hp_gained", source_id="test:regeneration")
        added = [f"{x.event_type}:{x.source_definition_id}:{str(x.payload)[:80]}" for x in e.events[before:]]
        after = e.state.actors[FOE].temporary_hp
    finally:
        e.__dict__.pop("_pending_healing", None)
    assert False, f"DBG2 tp={tp} counts={ {k: counts.get(k, 0) for k in ('REACTION_RESOLVED','REACTION_DECLINED','GM_RIDER','PASSIVE_TRIGGERED','RESOURCE_SPENT','TEMP_HP_GRANTED','HEALING_APPLIED')} } riders={riders[:5]} rows2={kinds} added={added[:8]} after2={after} react_avail={e.state.actors[OWNER].reaction_available}"
