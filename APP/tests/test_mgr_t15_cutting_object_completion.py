"""A resolved Cutting Current object action reaches strict completion subscribers."""
from combat import ext
from tests.test_mgr_t15_cutting_object_activation import fixture, finish
from tests.test_mgr_t15_close_cutting_current import cold


def test_object_lash_publishes_completion_only_after_successful_resolution(tmp_path, monkeypatch):
    _, table, mid, candidate = fixture(tmp_path, 'cutting', monkeypatch)
    _, _, before = cold(tmp_path, mid)
    first = len(before.events)
    enabled, delivered = [], []

    def completion_enabled(ctx):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            enabled.append(ctx.action.source_definition_id)
            return True

    def completion_subscriber(ctx, receipt):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            ctx.engine._append_event('PASSIVE_TRIGGERED', 'test:completion_subscriber',
                actor_id=ctx.actor.entity_id,
                payload={'completed_action': ctx.action.source_definition_id})
            delivered.append(True)

    monkeypatch.setitem(ext._HOOKS, 'technique_resolution_enabled',
                       [*ext._HOOKS['technique_resolution_enabled'], completion_enabled])
    monkeypatch.setitem(ext._HOOKS, 'technique_resolved',
                       [*ext._HOOKS['technique_resolved'], completion_subscriber])
    finish(table, mid, candidate)
    _, _, engine = cold(tmp_path, mid)
    events = engine.events[first:]

    assert candidate.source_definition_id in enabled
    assert delivered
    assert any(e.source_definition_id == 'test:completion_subscriber'
               and e.payload.get('completed_action') == candidate.source_definition_id for e in events)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in events)


def test_vetoed_object_lash_does_not_publish_completion(tmp_path, monkeypatch):
    _, table, mid, candidate = fixture(tmp_path, 'cutting', monkeypatch)
    _, _, before = cold(tmp_path, mid)
    first = len(before.events)
    enabled, delivered = [], []

    def veto(engine, actor, action):
        if action.source_definition_id == candidate.source_definition_id:
            return True

    def completion_enabled(ctx):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            enabled.append(ctx.action.source_definition_id)
            return True

    def completion_subscriber(ctx, receipt):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            delivered.append(ctx.action.source_definition_id)

    monkeypatch.setitem(ext._HOOKS, 'technique_start', [*ext._HOOKS['technique_start'], veto])
    monkeypatch.setitem(ext._HOOKS, 'technique_resolution_enabled',
                       [*ext._HOOKS['technique_resolution_enabled'], completion_enabled])
    monkeypatch.setitem(ext._HOOKS, 'technique_resolved',
                       [*ext._HOOKS['technique_resolved'], completion_subscriber])
    finish(table, mid, candidate)
    _, _, engine = cold(tmp_path, mid)

    assert not enabled and not delivered
    assert not any(e.event_type == 'ATTACK_ROLLED' for e in engine.events[first:])
