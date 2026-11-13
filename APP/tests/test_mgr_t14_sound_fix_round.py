"""Sound review regressions at the committed table boundary, with cold replay."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_read import READ
from tests.test_mgr_t14_sound_review import scene, voiced_scene


def test_anonymous_contest_stays_anonymous_in_committed_history_and_dice(tmp_path, voiced_scene):
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=voiced_scene)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Become invisible').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    turn(table, mid, OWNER)
    receipt = next(e for e in reversed(reload(tmp_path, mid).events) if e.payload.get('sound_scene_receipt'))
    assert receipt.payload['source_actor_id'] == FOE and receipt.target_ids == (OWNER,)
    after = reload(tmp_path, mid).state.event_sequence
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'stealth',
               'choice:needle.vibration_opponent': 'sound:' + str(receipt.sequence),
               'choice:needle.vibration_clue': 'hidden_sound'})
    e = reload(tmp_path, mid)
    check = next(e for e in reversed(e.events) if e.event_type == 'CHECK_ROLLED')
    assert check.target_ids == (FOE,) and check.payload['target']['actor_id'] == FOE
    # Both incremental table polling and a full cold history use the label
    # captured at the contest, regardless of subsequent visibility changes.
    for cursor in (after, 0):
        feed = table.events(mid, cursor, engine=e)
        row = next(r for r in feed['events'] if r['event_sequence'] == check.sequence)
        assert 'Unseen audible source 1' in row['summary']
        assert 'Mara' not in row['summary'] and FOE not in row['summary']
        die = next(r for r in feed['dice'] if r['roll_id'] == check.payload['target']['roll_id'])
        assert 'Unseen audible source 1' in die['label'] and 'Mara' not in die['label']


@pytest.mark.parametrize('all_auto', [False, True])
def test_automatic_sound_read_waits_for_journaled_gm_dc_without_opponents(tmp_path, monkeypatch, all_auto):
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=scene, ask=False)
    settle(table, mid, candidate(combat, mid, 'Become blinded').candidate_id)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    if all_auto:
        for actor_id in (ALLY, FOE):
            combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Read the Vibration').candidate_id
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context))
    before = reload(tmp_path, mid)
    if all_auto:
        assert not before.typed_ask_reactors, 'GM adjudication must not depend on a manual participant'
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompts, answers = [], []
    for digit in ('1', '3', '5', 'done'):
        prompt = result['reaction']
        prompts.append(prompt)
        assert prompt['context']['reaction_source_id'] == 'choice:needle.scene_gm_dc'
        assert 'Read the Vibration' in str(prompt)
        assert len(reload(tmp_path, mid).rolls) == len(before.rolls)
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [digit]})
        # Cold service load between replies exercises the journaled transport.
        result = table.auto_step(mid, 0, answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['check_metadata']['method'] == 'gm_dc'
    assert check.payload['dc'] == 135 and not check.payload['success']
    assert not check.payload.get('target') and not e.state.actors[OWNER].action_available


def test_visible_contest_keeps_ordinary_names_and_both_recorded_dice(tmp_path):
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    after = reload(tmp_path, mid).state.event_sequence
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'stealth', 'choice:needle.vibration_opponent': ALLY,
               'choice:needle.vibration_clue': 'movement'})
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert 'opponent_display_name' not in check.payload['check_metadata']
    feed = table.events(mid, after, engine=e)
    row = next(v for v in feed['events'] if v['event_sequence'] == check.sequence)
    assert 'against Tobin' in row['summary'] and 'Unseen audible' not in row['summary']
    dice = {v['roll_id']: v for v in feed['dice']}
    assert 'Wren' in dice[check.payload['actor']['roll_id']]['label']
    assert 'Tobin' in dice[check.payload['target']['roll_id']]['label']


@pytest.mark.parametrize('aged', [False, True])
def test_movement_clue_expires_after_previous_round_across_commit_reload(tmp_path, aged):
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    turn(table, mid, ALLY)
    move = next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.kind == 'MOVE' and c.destination and c.destination.x == 4 and c.destination.y == 7)
    settle(table, mid, move.candidate_id)
    movement = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'MOVEMENT_COMMITTED')
    turn(table, mid, OWNER)
    if aged:
        for _ in range(2):
            turn(table, mid, ALLY)
            turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('0', 'done'),
               'choice:needle.vibration_clue': 'movement'})
    e = reload(tmp_path, mid)
    clue = next(v for v in reversed(e.events) if v.payload.get('clue'))
    assert (movement.sequence in clue.payload['evidence_sequences']) == (not aged)
    assert ('No recent movement' in clue.payload['text']) == aged
    assert not clue.target_ids and clue.payload['exact_location'] == 0
