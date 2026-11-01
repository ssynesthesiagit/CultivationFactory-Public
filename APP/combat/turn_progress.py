"""Read-only failed-action history for table menus and Local Auto.

The existing PREPARE bindings and COMMIT receipts own this history. Never
persist a cache, patch the engine, or confuse fresh candidate IDs with progress.
Manual moves omit failed first edges too; other manual actions remain available.
This general controller guard is independent of abilities and creature type.
"""
from .canonical import canonical_sha256
from .gate3_reducer import capture_runtime_control

# At most 64 ordinary PREPARE/COMMIT pairs, including the preceding control
# snapshot. Older attempts are conservatively eligible again if this window
# is exhausted; persisted movement-safety flags still own blocked first edges.
HISTORY_RECORD_LIMIT = 128


def control_without_vetoes(control):
    """Movement safety's public failure markers record attempts, not progress."""
    from .ext.movement_safety import FLAG
    return {**control, 'actors': {aid: {**row, 'turn_flags': {
        key: value for key, value in row['turn_flags'].items()
        if not key.startswith(FLAG + ':')}} for aid, row in control['actors'].items()}}


def identity(candidate):
    """A choice without version/candidate IDs or changing tactical estimates."""
    if hasattr(candidate, 'model_dump'):
        candidate = candidate.model_dump(mode='json')
    return canonical_sha256({key: candidate.get(key) for key in (
        'actor_id', 'kind', 'source_definition_id', 'target_ids', 'destination',
        'option_ids', 'canonical_path')})


def first_edge(candidate):
    path = candidate.get('canonical_path') or ()
    if len(path) < 2:
        return None
    return tuple(tuple(int(p.get(axis, 0)) for axis in ('x', 'y', 'z')) for p in path[:2])


def _failed_attempts(session, actor_id, *, verified_records):
    """Find identical no-ops only in the same actor's unchanged turn state.

    Confirm unchanged runtime control AND absence of mechanical event types.
    A payment, hit, roll, condition, observation, turn boundary, summon or other
    recorded effect prevents classifying an action as a no-op. Scanning stops
    at a changed state, so an opened route or changed economy can be retried.
    Blocked first edges suppress all destinations behind that same failed step.
    Gate5 supplies its mechanical session's already verified records. Inspect
    only their last HISTORY_RECORD_LIMIT entries: no disk read or integrity
    revalidation, and no whole-history iteration/copy. If the window has no
    preceding snapshot, leave that oldest attempt eligible rather than guessing
    its before-state. Existing bindings/replay are untouched. Keep End Turn.
    """
    if session.engine.state.pending_resolution is not None:
        return set(), set()
    last = session.engine.events[-1] if session.engine.events else None
    if last is None or last.event_type not in {
            'INTENT_ACCEPTED', 'PASSIVE_TRIGGERED', 'MOVEMENT_COMMITTED', 'HOLD_POSITION_COMMITTED'}:
        return set(), set()
    if last.event_type == 'MOVEMENT_COMMITTED' and (
            last.payload.get('cost_ft', 0) or last.payload.get('granted_cost_ft', 0)
            or len(last.payload.get('path') or ()) > 1):
        return set(), set()
    records = verified_records[-HISTORY_RECORD_LIMIT:]
    if not records:
        return set(), set()
    current = control_without_vetoes(capture_runtime_control(session.engine).model_dump(mode='json'))
    prepares = {r['transaction_id']: r for r in records if r['record_type'] == 'PREPARE'}
    commits = [r for r in records if r['record_type'] == 'COMMIT']
    failed, edges = set(), set()
    harmless = {'INTENT_ACCEPTED', 'PASSIVE_TRIGGERED', 'MOVEMENT_COMMITTED', 'HOLD_POSITION_COMMITTED'}
    for index in range(len(commits)-1, -1, -1):
        commit = commits[index]
        events = commit.get('events') or ()
        binding = (prepares.get(commit['transaction_id']) or {}).get('candidate_binding') or {}
        if binding.get('actor_id') != actor_id or binding.get('kind') == 'END_TURN':
            break
        before_events = (commits[index-1].get('events') or ()) if index else ()
        after = events[-1]['payload'].get('gate3_runtime_control_after') if events else None
        before = before_events[-1]['payload'].get('gate3_runtime_control_after') if before_events else None
        if index == 0 and len(verified_records) <= HISTORY_RECORD_LIMIT:
            import json
            from types import SimpleNamespace
            from .gate2_runtime_models import MatchState
            genesis = MatchState.model_validate(json.loads(session.store.genesis_path.read_text())['state'])
            before = capture_runtime_control(SimpleNamespace(state=genesis)).model_dump(mode='json')
        if after is not None:
            after = control_without_vetoes(after)
        if before is not None:
            before = control_without_vetoes(before)
        if before != current or after != current:
            break
        if any(e['event_type'] not in harmless for e in events):
            break
        if commit.get('roll_counter_end') != commit.get('roll_counter_start'):
            break
        moves = [e for e in events if e['event_type'] == 'MOVEMENT_COMMITTED']
        if any(e['payload'].get('cost_ft', 0) or e['payload'].get('granted_cost_ft', 0)
               or len(e['payload'].get('path') or ()) > 1 for e in moves):
            break
        failed.add(identity(binding))
        if binding.get('kind') == 'MOVE' and moves:
            edge = first_edge(binding)
            if edge is not None:
                edges.add(edge)
    return failed, edges


def requires_native_routes(session, *, verified_records):
    """Whether the table must retain full paths for unchanged no-op guards.

    Reuse the same bounded verified-history analysis as narrow, so an ordinary
    PASSIVE_TRIGGERED event alone never disables compact movement queries.
    Only failed movement edges require paths. Non-movement no-ops do not narrow
    manual movement; an empty/one-square path cannot match an offered route.
    """
    _, edges = _failed_attempts(session, session.engine.state.current_actor_id,
                                verified_records=verified_records)
    return bool(edges)


def narrow(session, candidates, *, verified_records, for_ai=False):
    """Suppress unchanged no-ops using the shared verified-history analysis."""
    if not candidates:
        return candidates
    failed, edges = _failed_attempts(session, candidates[0].actor_id,
                                     verified_records=verified_records)
    if not failed:
        return candidates
    out = []
    for candidate in candidates:
        if candidate.kind.value == 'END_TURN':
            out.append(candidate)
            continue
        if candidate.kind.value == 'MOVE':
            if first_edge(candidate.model_dump(mode='json')) in edges or identity(candidate) in failed:
                continue
        elif for_ai and identity(candidate) in failed:
            continue
        out.append(candidate)
    return tuple(out)
