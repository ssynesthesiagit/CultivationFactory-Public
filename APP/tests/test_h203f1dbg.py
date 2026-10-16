"""Temporary H203FIX1F1 diagnostics (deleted before commit)."""
import json
import pytest
from tests.worker2_support import fixture, OWNER, FOE, ALLY
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_r9i_karma_persistence import act

ERODE = "TAL_VOID_ERODE_TECHNIQUE"


def _rows_dump(e, actor):
    return [(r.get("feature_id"), r.get("kind"), str(r.get("effects"))[:130],
             str(r.get("costs"))[:60], r.get("consent_source_id")) for r in e.typed_reaction_rows.get(actor, [])]


def test_dbg_temp_hp_dispatch(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [ERODE], ask=False)
    def grant(e):
        e._grant_temp_hp(e.state.actors[FOE], 20, "test:regeneration", FOE)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    result = act(table, mid, cid)
    e = combat._load_session(mid).engine
    evs = [(x.event_type, x.source_definition_id, str(x.payload)[:150]) for x in e.events[-22:]]
    assert False, f"DBGTP status={result.get('status')} rows={_rows_dump(e, OWNER)} events={evs}"


def test_dbg_scopes_dispatch(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [ERODE], ask=False)
    def grant(e):
        e._add_modifier(e.state.actors[FOE], "test:buff", "armor_class", "ADD", 3, "SELF",
                        expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    result = act(table, mid, cid)
    e = combat._load_session(mid).engine
    evs = [(x.event_type, x.source_definition_id, str(x.payload)[:150]) for x in e.events[-22:]]
    assert False, f"DBGSC status={result.get('status')} rows={_rows_dump(e, OWNER)} events={evs}"


def test_dbg_ask_prompt(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [ERODE], ask=True, named=True)
    def grant(e):
        e._grant_temp_hp(e.state.actors[FOE], 20, "test:regeneration", FOE)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    paused = act(table, mid, cid)
    if paused.get("status") == "REACTION_REQUIRED":
        p = paused["reaction"]
        assert False, f"DBGASK rid={p['context'].get('reaction_source_id')} trigger={str(p.get('trigger'))[:160]} summary={str(p.get('summary'))[:160]} moment={str(p.get('moment'))[:120]}"
    e = combat._load_session(mid).engine
    evs = [(x.event_type, x.source_definition_id, str(x.payload)[:120]) for x in e.events[-14:]]
    assert False, f"DBGASK status={paused.get('status')} events={evs}"
