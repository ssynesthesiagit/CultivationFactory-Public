"""MAINREDSYSRES1 F6R: the Gate 2 candidate_allowed pass must not veto lazy action headers.

Gate 2 seats (human and AI alike) get their options from _generate_legal_candidates. A lazy
header (combat/lazy_menu.py) is only a source-level group: its candidate_allowed checks run on
the exact expansion and again at commit, so the Gate 2 pass must keep headers untouched. A
dormant option (candidate_allowed False) must still leave the Gate 2 menu.
"""
from pathlib import Path

from combat import ext, lazy_menu
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import CandidateKind

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "system:combat.dash"
SEED = "MAINREDSYSRES1-GATE2-VETO"


def _veto_source(monkeypatch, seen=None):
    def veto(engine, actor, candidate, action):
        if seen is not None:
            seen.append(candidate)
        if candidate.source_definition_id == SOURCE:
            return False
    ext._load()
    monkeypatch.setitem(ext._HOOKS, "candidate_allowed", [*ext._HOOKS.get("candidate_allowed", []), veto])


def test_gate2_seat_loses_a_dormant_option(monkeypatch):
    engine = Gate2Engine(ROOT, match_seed=SEED)
    before = engine.legal_candidates()
    offered = [c for c in before if c.source_definition_id == SOURCE]
    assert offered, "the fixture must offer Dash before the veto"
    _veto_source(monkeypatch)
    after = engine.legal_candidates()
    assert not any(c.source_definition_id == SOURCE for c in after)
    assert len(after) == len(before) - len(offered)


def test_gate2_veto_leaves_a_lazy_header_alone(monkeypatch):
    engine = Gate2Engine(ROOT, match_seed=SEED)
    original = Gate2Engine._action_candidates

    def header_for_dash(self, actor, definition, **kwargs):
        if definition.source_definition_id == SOURCE:
            return [lazy_menu.header(self, actor, definition, CandidateKind.ACTION)]
        return original(self, actor, definition, **kwargs)

    monkeypatch.setattr(Gate2Engine, "_action_candidates", header_for_dash)
    seen = []
    _veto_source(monkeypatch, seen)
    headers = [c for c in engine.legal_candidates() if c.source_definition_id == SOURCE]
    assert len(headers) == 1 and headers[0].metadata.get("lazy_action") is True
    assert not any(c.metadata.get("lazy_action") for c in seen), "a candidate veto ran on a lazy header"
