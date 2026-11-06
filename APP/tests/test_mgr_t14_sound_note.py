"""The owned Note option, existing-mark gate, sensory consumer and source expiry."""
import pytest

from combat.canonical import canonical_sha256
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_base import checks

NOTE = 'TAL_SOUND_RESONANT_NOTE'
BLOCK = 'condition:typed.sound_hiding_block'


def scene_setup(metadata):
    """Establish the pre-existing mark via a visible, journaled fixture action.

    Actual Note remains its compiled action with its printed economy/range/dice.
    No engine state mutation or mock resolver prepares or tests the rider.
    """
    def setup(bundles):
        checks(metadata, ability='DEX', skill='Stealth')(bundles)
        for bundle in bundles:
            actor = bundle['actor_id']
            source = 'action:test.scene_resonance.' + actor.rsplit('-', 1)[-1]
            bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Scene: pre-existing Resonance',
                'owner_id': actor, 'economy': 'BONUS_ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
                'range_ft': 60, 'costs': [], 'parameters': {'typed': {'source': source, 'numbers': {'pb': 4, 'key_mod': 2},
                'effects': [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target',
                             'duration': {'kind': 'until_start_of_your_next_turn'}}]}}})
            bundle['actor_template']['action_ids'].append(source)
            # This real scene check tests permission to conceal ordinary sound;
            # a low DC makes a restriction distinguishable from a failed die.
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Scene check':
                    action['parameters']['typed']['effects'][0]['dc'] = 0
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    return setup


def note_fixture(tmp_path, metadata, marked=True):
    foe_sheet = sheet([])
    foe_sheet['ability_scores_and_statistics']['armor_class']['base_value'] = 0
    combat, table, mid = fixture(tmp_path, [NOTE], named=True, foe_sheet=foe_sheet,
                                 bundle_transform=scene_setup(metadata), seed='T14-Note', ask=False)
    if marked:
        settle(table, mid, candidate(combat, mid, 'Scene: pre-existing Resonance', target=FOE).candidate_id)
        from combat.typed_executor import bears_mark
        assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Resonance')
    settle(table, mid, candidate(combat, mid, 'Resonant Note: Prevent ordinary sound-based hiding', target=FOE).candidate_id)
    return combat, table, mid


@pytest.mark.parametrize('marked', [True, False])
def test_note_only_existing_resonance_grants_restriction_on_hit(tmp_path, marked):
    combat, table, mid = note_fixture(tmp_path, {}, marked)
    e = reload(tmp_path, mid)
    hits = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and NOTE in v.source_definition_id]
    assert hits and hits[-1].payload['provisional_hit']
    blocks = [c for c in e.state.actors[FOE].conditions.values() if c.condition_id == BLOCK]
    assert bool(blocks) == marked
    if marked:
        assert blocks[0].source_actor_id == OWNER
        assert blocks[0].expires_on == 'START_OF_MARKER_NEXT_TURN'
        turn(table, mid, ALLY)
        assert any(c.condition_id == BLOCK for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
        turn(table, mid, OWNER)
        assert not any(c.condition_id == BLOCK for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


@pytest.mark.parametrize('senses,ordinary,blocked', [(['hearing'], 1, True), (['vision'], 1, False),
    (['hearing', 'vision'], 1, False), (['hearing'], 0, False)])
def test_note_completed_concealment_check_only_blocks_ordinary_hearing(tmp_path, senses, ordinary, blocked):
    metadata = {'purpose': 'conceal_sound', 'senses': senses, 'ordinary': ordinary,
                'source_actor_id': FOE, 'observer_id': ALLY}
    combat, table, mid = note_fixture(tmp_path, metadata)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id)
    assert check.payload['actor']['total'] >= 0
    assert check.payload['success'] == (not blocked)
    assert check.payload['check_metadata'] == metadata
    assert not any(v.event_type == 'CONDITION_REMOVED' and v.payload.get('reason') == 'found' for v in e.events)
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    later = next(v for v in reversed(reload(tmp_path, mid).events) if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id)
    assert later.payload['success'], 'the caster-start expiry must retire the hearing consumer'
