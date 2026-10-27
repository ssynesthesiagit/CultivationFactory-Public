"""Relevant opposition and audible Note paths through table commits and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_read import READ
from tests.test_mgr_t14_sound_review import scene
from tests.test_mgr_t14_sound_note import NOTE, BLOCK, scene_setup

MANTRA = 'tianxia.subpath.qi.mantra_cultivator.feature.mantra_of_silence'
SCENE_VOICE = 'test.sound_relevance.audible_voice'


def audible_influence(bundles):
    scene(bundles)
    for bundle in bundles:
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Speak in scene':
                action['parameters']['sensory_facts'] = {'supernatural_influence': 1}
                action['parameters']['typed']['source'] = SCENE_VOICE
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('topic', ['hidden_sound', 'influence', 'movement'])
@pytest.mark.parametrize('opposition', ['ally', 'source', 'gm'])
def test_inquiry_cannot_use_ally_to_disclose_separate_hidden_source(tmp_path, monkeypatch, topic, opposition):
    from combat import speech
    # Declare this synthetic fixture action's voice requirement explicitly.
    # It must not depend on an optional production speech catalogue being
    # installed in the public test export. Native hearing/receipt code runs.
    monkeypatch.setitem(speech.rules(), 'needs_voice', {
        **speech.rules().get('needs_voice', {}), SCENE_VOICE: {'reason': 'Spoken scene fixture'}})
    combat, table, mid = fixture(tmp_path, [READ], named=True,
        bundle_transform=audible_influence, ally_score=1,
        foe_sheet=sheet([], score=1, name='Mara') if opposition == 'source' else None)
    turn(table, mid, FOE)
    move = next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.kind == 'MOVE' and c.destination and (c.destination.x, c.destination.y) == (6, 7))
    settle(table, mid, move.candidate_id)
    movement = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'MOVEMENT_COMMITTED')
    settle(table, mid, candidate(combat, mid, 'Become hidden').candidate_id)
    # Keep the hidden source unseen even in this otherwise exposed cell.
    settle(table, mid, candidate(combat, mid, 'Become invisible').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    turn(table, mid, OWNER)
    heard = next(e for e in reversed(reload(tmp_path, mid).events) if e.payload.get('sound_scene_receipt'))
    assert heard.payload['source_actor_id'] == FOE and heard.payload['supernatural_influence'] == 1
    prompts = settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_clue': topic,
               'choice:needle.vibration_method': 'gm_dc' if opposition == 'gm' else 'stealth',
               'choice:needle.vibration_opponent': ALLY if opposition == 'ally' else 'sound:' + str(heard.sequence),
               'choice:needle.scene_gm_dc': ('0', 'done')})
    e = reload(tmp_path, mid)
    check = next(e for e in reversed(e.events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['success'], check.payload
    clue = next(e for e in reversed(e.events) if e.payload.get('clue'))
    expected = movement.sequence if topic == 'movement' else heard.sequence
    assert (expected in clue.payload['evidence_sequences']) == (opposition != 'ally')
    if opposition == 'ally':
        assert not clue.payload['evidence_sequences'] and 'unknown' in clue.payload['text']
    assert not clue.target_ids and clue.payload['exact_location'] == 0
    assert 'Mara' not in clue.payload['text'] and FOE not in clue.payload['text']
    assert prompts[0]['context']['reaction_source_id'] == 'choice:needle.vibration_clue'
    opponent = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.vibration_opponent'), None)
    if opponent:
        assert any(o['id'] == 'sound:' + str(heard.sequence) for o in opponent['choice']['options'])
        assert all('Mara' not in str(o) and FOE not in str(o) for o in opponent['choice']['options'])


@pytest.mark.parametrize('topic', ['structure', 'object'])
def test_scene_inquiry_uses_gm_difficulty_before_dice(tmp_path, topic):
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    c = candidate(combat, mid, 'Read the Vibration')
    before = reload(tmp_path, mid)
    pending = act(table, mid, c.candidate_id)
    assert pending['status'] == 'REACTION_REQUIRED'
    assert pending['reaction']['context']['reaction_source_id'] == 'choice:needle.vibration_clue'
    assert {o['id'] for o in pending['reaction']['choice']['options']} == {
        'movement', 'structure', 'hidden_sound', 'object', 'influence'}
    assert len(reload(tmp_path, mid).rolls) == len(before.rolls)
    prompts = settle(table, mid, c.candidate_id, picks={'choice:needle.vibration_clue': topic,
        'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('0', 'done')})
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.vibration_opponent' for p in prompts)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.scene_gm_dc' for p in prompts)
    check = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['dc'] == 0 and check.payload['success'] and not check.payload.get('target')
    assert check.payload['check_metadata']['inquiry'] == topic


@pytest.mark.parametrize('boundary', [True, False])
def test_note_cannot_forbid_concealment_across_silence_boundary(tmp_path, boundary):
    from combat import speech, typed_executor
    metadata = {'purpose': 'conceal_sound', 'senses': ['hearing'], 'ordinary': 1,
                'source_actor_id': FOE, 'observer_id': ALLY}
    def ordered_scene(bundles):
        scene_setup(metadata)(bundles)
        # Keep Note, the observer's silence cast, and the concealment check
        # before the caster's next turn, when the rider correctly expires.
        for bundle in bundles:
            bundle['actor_template']['initiative_bonus'] = {OWNER: 20, ALLY: 0, FOE: -20}[bundle['actor_id']]
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    foe = sheet([])
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 0
    combat, table, mid = fixture(tmp_path, [NOTE], ally_talents=[MANTRA],
        foe_sheet=foe, foe_position={'x': 7, 'y': 6}, bundle_transform=ordered_scene,
        seed='T14-Note', ask=True)
    settle(table, mid, candidate(combat, mid, 'Scene: pre-existing Resonance', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Resonant Note: Prevent ordinary sound-based hiding', target=FOE).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Mantra of Silence', at=(0 if boundary else 3, 6)).candidate_id,
        picks={'choice:needle.mantra_silence_exempt': [ALLY, FOE]})
    turn(table, mid, FOE)
    e = reload(tmp_path, mid)
    source, observer = e.state.actors[FOE], e.state.actors[ALLY]
    assert any(c.condition_id == BLOCK for c in source.conditions.values())
    assert not typed_executor.cant_hear(observer) and not typed_executor.cant_hear(source)
    assert e.grid.line_of_sight_between_cell_sets(e._actor_volume(source), e._actor_volume(observer))
    assert speech.can_hear_from(e, source, observer) == (not boundary)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    check = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['total'] >= 0
    assert check.payload['success'] == boundary
    assert check.payload['check_metadata'] == metadata
