"""Terminal summaries reuse the replay performed by strict verification."""
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.diagnostics import CombatGate1Error
from tests.persistence_support import end_turn as _step

ROOT = Path(__file__).resolve().parents[1]


def completed(tmp_path):
    service = CombatService(ROOT, tmp_path)
    view = service.create_match(encounter_id=service.catalog()['encounters'][0]['stable_id'],
        display_name='Terminal summary control', match_seed='lock4-summary', control_modes={}, maximum_rounds=1)
    session = service._load_session(view['match_id'])
    while session.engine.state.terminal_result is None:
        _step(session)
    return service, session


def test_summary_runs_one_strict_replay_and_preserves_the_summary_bytes(tmp_path, monkeypatch):
    service, session = completed(tmp_path)
    replay = session.mechanical.replay()
    expected = service.final_summary(session.match_id)
    path = session.store.match_dir / 'FinalSummary.json'
    before = path.read_bytes()
    # Hunt10b merge bb8f59ad intentionally caches verified terminal summaries
    # by exact input bytes (96078469). Use a cold service to prove the first
    # summary still performs one strict replay, then check unchanged reuse.
    service = CombatService(ROOT, tmp_path)
    original = session.mechanical.persistence._replay_from
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(session.mechanical.persistence, '_replay_from', count)
    # The table already holds the current session. Reusing it must still verify
    # the on-disk journal, rather than load and replay the same fight again.
    monkeypatch.setattr(service, '_load_session', lambda _: session)
    result = service.final_summary(session.match_id)
    assert len(calls) == 1, 'the same terminal journal was replayed twice'
    assert result == expected and path.read_bytes() == before
    assert result['replay'] == {k: replay[k] for k in ('status', 'canonical_state_sha256', 'terminal_result')}
    assert service.final_summary(session.match_id) == result
    assert len(calls) == 1, 'unchanged verified inputs should reuse the summary'
    assert path.read_bytes() == before


def test_summary_still_rejects_a_loaded_state_that_disagrees_with_the_journal(tmp_path, monkeypatch):
    service, session = completed(tmp_path)
    actor = next(a for a in session.engine.state.actors.values() if a.current_hp > 1)
    actor.current_hp -= 1
    monkeypatch.setattr(service, '_load_session', lambda _: session)
    with pytest.raises(CombatGate1Error) as caught:
        service.final_summary(session.match_id)
    assert caught.value.diagnostic.code == 'MATCH_REPLAY_FINAL_STATE_MISMATCH'


def test_summary_still_checks_controller_journal_sequence(tmp_path):
    service, session = completed(tmp_path)
    import json
    path = session.controller_journal_path
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['record_sequence'] = 99
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError, match='CONTROLLER_JOURNAL_SEQUENCE_GAP'):
        service.final_summary(session.match_id)


def test_terminal_commit_reaction_audit_is_identical_after_service_reload(tmp_path, monkeypatch):
    """Lock4 reused live events, which lack the journal's replay enrichment."""
    import json
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.test_lock_choices import install

    # A small event fixture stands in for any reaction-producing plug-in. It
    # uses the real preview, table commit, journal enrichment and terminal read.
    def resolved(engine, actor):
        actor.reaction_available = False
        engine._append_event('REACTION_RESOLVED', 'test:summary.reaction',
                             actor_id=actor.entity_id, target_ids=(actor.entity_id,))

    service = CombatService(ROOT, tmp_path)
    view = service.create_match(encounter_id=service.catalog()['encounters'][0]['stable_id'],
        display_name='Reaction audit control', match_seed='r21-summary-reaction',
        control_modes={}, maximum_rounds=1)
    install(monkeypatch, 'turn_end', resolved)

    class EndTurnController:
        def choose_primary_action(self, context):
            cid = next(c.candidate_id for c in context.legal_candidates if c.kind.value == 'END_TURN')
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

    service.controller = EndTurnController()
    mid = view['match_id']
    for actor in view['state']['actors']:
        if actor['primary_combatant']:
            service.set_controller_mode(mid, actor_id=actor['entity_id'], controller_mode='LOCAL_AUTO')
    for _ in range(16):
        view = service.local_step(mid)['match']
        if view['state']['terminal_result'] is not None:
            break
    else:
        pytest.fail('bounded end-turn control never completed')
    summary = view['final_summary']
    session = service._load_session(mid)
    path = session.store.match_dir / 'FinalSummary.json'
    before = path.read_bytes()
    journal = [json.loads(line) for line in session.store.journal_path.read_text().splitlines()]
    committed = [e for row in journal if row['record_type'] == 'COMMIT'
                 for e in row['events'] if e['event_type'] == 'REACTION_RESOLVED']
    assert committed and all('gate3_reaction_available_after' in e['payload'] for e in committed)
    assert [e for e in summary['reactions_recorded'] if e['event_type'] == 'REACTION_RESOLVED'] == committed
    resumed = CombatService(ROOT, tmp_path)
    assert resumed.get_match(mid)['final_summary'] == summary
    assert resumed.final_summary(mid) == summary and path.read_bytes() == before
    assert resumed.verify(mid)['status'] == resumed.replay(mid)['status'] == 'PASS'

    # Matching on reload must not relax the stored-summary corruption check.
    corrupted = json.loads(before)
    corrupted['reactions_recorded'][0]['payload']['gate3_reaction_available_after'] = True
    path.write_text(json.dumps(corrupted))
    from combat.gate5_service import CombatServiceError
    with pytest.raises(CombatServiceError) as caught:
        resumed.get_match(mid)
    assert caught.value.diagnostic.code == 'COMBAT_FINAL_SUMMARY_MISMATCH'
