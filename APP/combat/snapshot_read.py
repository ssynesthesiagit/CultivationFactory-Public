"""Read-only table snapshots using the recorded checkpoint and journal suffix.

Used by CombatService's presentation loader only. Never returns a transaction
session or issues candidates. Actions, recovery and verification retain the full
history proof in Gate3Persistence.load_match. Missing/invalid checkpoints and
unfinished writes fall back to that loader; no saved bytes are changed here.
"""
from dataclasses import dataclass

from .gate3_models import Gate3CommitPayload
from .gate3_storage import Gate3MatchStore


@dataclass
class PresentationSession:
    match_id: str
    engine: object


def load(combat, match_id):
    """Return a checkpoint projection, or None when ordinary recovery is needed.

    Validate immutable inputs, every journal envelope/hash/transaction and the
    checkpoint's state/anchor with the existing persistence validators. Replay
    only commits after the checkpoint, checking their recorded post-state hashes.
    A changed input fingerprint discards this read rather than mixing versions.
    """
    persistence = combat.persistence
    before = combat._fingerprint(match_id)
    store = Gate3MatchStore(persistence.userdata_root, match_id)
    # Avoid the extra validation work for new fights without a checkpoint.
    if not any(store.snapshots_dir.glob('Snapshot_*.json')):
        return None
    _lock, genesis = persistence._load_lock_genesis(store)
    records, trailing = store.read_journal()
    persistence._validate_record_transactions(records)
    if trailing or (records and records[-1]['record_type'] == 'PREPARE'):
        return None
    snapshots, _diagnostics = store.valid_snapshots(records)
    if not snapshots:
        return None
    snapshot = snapshots[0]
    commits = persistence._commit_records(records)
    covered = [row for row in commits if row['record_sequence'] <= snapshot.journal_record_sequence]
    recorded_hash = covered[-1]['post_state_sha256'] if covered else genesis.canonical_state_sha256
    if snapshot.canonical_state_sha256 != recorded_hash:
        return None
    later = [row for row in commits if row['record_sequence'] > snapshot.journal_record_sequence]
    state = persistence._replay_from(snapshot.state, later)
    commanded = snapshot.commanded_cui_this_turn
    for row in later:
        events = row['events']
        control = events[-1].get('payload', {}).get('gate3_runtime_control_after') if events else None
        if control is not None:
            commanded = bool(control['commanded_cui_this_turn'])
    events, rolls = list(genesis.initial_events), list(genesis.initial_rolls)
    for row in commits:
        payload = Gate3CommitPayload.model_validate({key: row[key] for key in Gate3CommitPayload.model_fields})
        events.extend(payload.events)
        rolls.extend(payload.rolls)
    engine = persistence._engine_from_loaded(state, events, rolls, commanded_cui_this_turn=commanded)
    from .zones import sync_walls
    sync_walls(engine)
    metadata = (combat._read_metadata(match_id) if combat._metadata_path(match_id).exists()
                else combat._metadata_readonly(match_id, state.model_dump(mode='json')))
    engine.typed_control_modes = dict(metadata.get('participant_control_modes') or {})
    if combat._fingerprint(match_id) != before:
        return None
    return PresentationSession(match_id, engine)
