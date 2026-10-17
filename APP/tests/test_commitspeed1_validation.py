"""Human clicks validate fresh choices without rebuilding unrelated menus."""
import socket
import sys
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import FOE, fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))
    def denied(*a, **kw):
        raise AssertionError('Commit regressions must never contact a live server')
    monkeypatch.setattr(socket.socket, 'connect', denied)


@pytest.mark.parametrize('kind', ['mark', 'attack'])
def test_human_commit_uses_fresh_targeted_binding_and_matches_reload(tmp_path, kind):
    combat, table, mid = fixture(
        tmp_path, ['TAL_DAEMONIC_CULTIVATION_DEMON_MARK'], ask=False,
        owner_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}},
        foe_position={'x': 3, 'y': 5}, seed='COMMITSPEED1')
    state = table.state(mid)
    session = combat._load_session(mid)
    candidates = combat._legal_candidates(session)
    if kind == 'mark':
        chosen = next(c for c in candidates if 'DEMON_MARK' in c.source_definition_id
                      and c.target_ids == (FOE,))
    else:
        chosen = next(c for c in candidates if c.kind == 'ACTION' and c.target_ids == (FOE,)
                      and '.weapon.' in c.source_definition_id and '#' not in c.source_definition_id)
    generations = []
    def observed(frame, event, arg):
        if (event != 'call' or frame.f_code.co_name != '_generate_legal_candidates'
                or not frame.f_code.co_filename.endswith('/gate2_engine.py')):
            return
        caller = frame.f_back
        while caller is not None:
            if caller.f_code.co_name == 'candidates_for_intent':
                generations.append(frame.f_locals.get('intent'))
                break
            caller = caller.f_back
    previous = sys.getprofile()
    try:
        sys.setprofile(observed)
        result = table.act(mid, chosen.candidate_id, chosen.decision_id,
                           chosen.state_version, state['last_sequence'])
    finally:
        sys.setprofile(previous)
    assert result['status'] == 'COMMITTED'
    # Preview, PREPARE and resolution still validate independently. Each binds
    # only this intent; no full placement-menu scan precedes an ordinary click.
    assert len(generations) >= 3
    assert all(intent is not None and intent.candidate_id == chosen.candidate_id for intent in generations), \
        'full picker scan during ordinary binding'
    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert result['state'] == cold.state(mid)
    assert result['events'] == cold.events(mid, state['last_sequence'])
    loaded = cold.combat._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
