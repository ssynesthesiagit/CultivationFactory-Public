"""Review gaps through compiled menus, journaled actions and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_base import DAMPEN, cast
from tests.test_mgr_t14_sound_read import READ

SCENE_VOICE = 'test.sound_review.spoken_scene'


@pytest.fixture
def voiced_scene(monkeypatch):
    """Classify our synthetic speech without relying on a production catalogue."""
    from combat import speech
    monkeypatch.setitem(speech.rules(), 'needs_voice', {
        **speech.rules().get('needs_voice', {}),
        SCENE_VOICE: {'reason': 'Spoken scene fixture'}})
    return scene


@pytest.mark.parametrize('issues,inside,expected', [
    ('sound', True, 'ADVANTAGE'), ('mixed', True, 'NORMAL'), ('sound', False, 'NORMAL')])
def test_production_quiet_check_menu(tmp_path, issues, inside, expected):
    combat, table, mid = fixture(tmp_path, [DAMPEN],
        ally_position={'x': 2 if inside else 7, 'y': 6})
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Check movement: move quietly').candidate_id,
        picks={'choice:needle.movement_issues': issues,
               'choice:needle.scene_gm_dc': ('0', 'done')})
    check = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == expected
    assert check.payload['check_metadata']['purpose'] == 'quiet_movement'
    assert check.payload['check_metadata']['issues'] == (['sound'] if issues == 'sound' else ['sound', 'sight'])


def scene(bundles):
    """Native scene actions establish unseen speech and later silence, never patch state."""
    for bundle in bundles:
        for name, condition in [('Become hidden', 'hidden'), ('Become invisible', 'invisible'),
                                ('Become blinded', 'blinded'), ('Become silent', 'silenced')]:
            source = 'action:test.review.' + condition + '.' + bundle['actor_id']
            bundle['action_catalog'].append({'source_definition_id': source, 'display_name': name,
                'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
                'target_kind': 'SELF', 'costs': [], 'parameters': {'free_primary': True, 'typed': {'effects': [
                    {'type': 'condition', 'condition': condition, 'applies_to': 'self',
                     'duration': {'kind': 'rounds', 'amount': 5}}]}}})
            bundle['actor_template']['action_ids'].append(source)
        source = 'action:test.review.voice.' + bundle['actor_id']
        bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Speak in scene',
            'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'SELF', 'costs': [], 'parameters': {'free_primary': True, 'typed': {
                'source': SCENE_VOICE, 'effects': []}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('blind,invisible', [(False, True), (True, False)])
def test_audible_unseen_source_offers_anonymous_opposed_checks(tmp_path, voiced_scene, blind, invisible):
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=voiced_scene)
    if blind:
        settle(table, mid, candidate(combat, mid, 'Become blinded').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Become invisible' if invisible else 'Become hidden').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    turn(table, mid, OWNER)
    from combat.senses import perceives
    e = reload(tmp_path, mid)
    assert not perceives(e, e.state.actors[OWNER], e.state.actors[FOE])
    receipt = next(e for e in reversed(e.events) if e.payload.get('sound_scene_receipt'))
    assert receipt.payload['source_actor_id'] == FOE and receipt.target_ids == (OWNER,)
    prompts = settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'stealth',
               'choice:needle.vibration_opponent': 'sound:' + str(receipt.sequence),
               'choice:needle.vibration_clue': 'hidden_sound'})
    opponent = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.vibration_opponent')
    options = opponent['choice']['options']
    assert any(o['id'] == 'sound:' + str(receipt.sequence) for o in options)
    assert all('Mara' not in str(o) and FOE not in str(o) for o in options)
    check = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['target']['actor_id'] == FOE
    assert check.payload['target_skill'] == 'Stealth'


@pytest.mark.parametrize('stale', ['silenced', 'elapsed', 'range', 'fresh'])
def test_stale_hidden_voice_receipt_does_not_answer_current_sound(tmp_path, voiced_scene, stale):
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=voiced_scene, owner_speed=90)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Become hidden').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    assert any(e.payload.get('sound_scene_receipt') and e.payload['source_actor_id'] == FOE
               and e.target_ids == (OWNER,) for e in reload(tmp_path, mid).events)
    if stale == 'silenced':
        settle(table, mid, candidate(combat, mid, 'Become silent').candidate_id)
    turn(table, mid, OWNER)
    if stale == 'elapsed':
        turn(table, mid, ALLY)
        turn(table, mid, OWNER)
    if stale == 'range':
        e = combat._load_session(mid).engine
        move = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                    and c.metadata.get('movement_mode', 'walk') == 'walk'
                    and not ({(p.x, p.y) for p in c.canonical_path}
                             & set(e._actor_cells(e.state.actors[FOE])))
                    and e.grid.distance_between_cell_sets_ft([(c.destination.x, c.destination.y, c.destination.z)],
                        e._actor_volume(e.state.actors[FOE])) > 60)
        settle(table, mid, move.candidate_id)
        moved = reload(tmp_path, mid)
        assert moved._distance_actor_to_actor(moved.state.actors[OWNER], moved.state.actors[FOE]) > 60
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('0', 'done'),
               'choice:needle.vibration_clue': 'hidden_sound'})
    clue = next(e for e in reversed(reload(tmp_path, mid).events) if e.payload.get('clue'))
    assert bool(clue.payload['evidence_sequences']) == (stale == 'fresh')
    assert 'unknown' in clue.payload['text']
    if stale == 'fresh':
        assert 'since your previous turn' in clue.payload['text']
        assert not clue.target_ids and clue.payload['exact_location'] == 0


def test_blinded_ai_contests_only_its_heard_anonymous_source(tmp_path, voiced_scene):
    from combat.gate2_runtime_models import ActionIntent
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=voiced_scene, ask=False)
    settle(table, mid, candidate(combat, mid, 'Become blinded').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    assert any(e.payload.get('sound_scene_receipt') and e.payload['source_actor_id'] == FOE
               and e.target_ids == (OWNER,) for e in reload(tmp_path, mid).events)
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    c = candidate(combat, mid, 'Read the Vibration')
    session = combat._load_session(mid)
    session.mechanical.execute_intent(ActionIntent(intent_id='t14-review-ai', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=OWNER,
        target_ids=c.target_ids, destination=c.destination))
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['target']['actor_id'] == FOE
    assert not any(v.payload.get('clue') and (v.target_ids or v.payload.get('exact_location')) for v in e.events)
