"""The table's Sever Aspect label selects the stable, Aspect-only choice."""
import pytest

from combat.ext.effect_durations import parse_round
from tests.hunt12_support import hit_dice
from tests.test_a2_group_traditions_2 import advance, cold, end
from tests.test_mgr_blood_moon_native import FOE, ME, STATE, accumulate, scene, strike

TEARS = 'tianxia.talent.beauty.tears_like_pearls'


def record_fact(combat, table, mid, fact):
    state = combat._load_session(mid).engine.state
    assert table.record_fact(
        mid, fact, expected_state_version=state.state_version,
    )['status'] == 'COMMITTED'


@pytest.mark.parametrize('foe_cl', [12, 13], ids=['six-level-gap', 'five-level-gap'])
def test_sever_aspect_offers_only_aspects_and_uses_printed_expiry(tmp_path, monkeypatch, foe_cl):
    combat, table, mid = scene(tmp_path, foe_cl=foe_cl, foe_features=(TEARS,))
    hit_dice(monkeypatch, save_roll=1)
    accumulate(combat, table, mid)

    engine = combat._load_session(mid).engine
    aspect_action = next(
        action.source_definition_id for action in engine.action_catalog.values()
        if action.owner_id == FOE and (action.parameters.get('typed') or {}).get('source') == TEARS
    )
    position = engine.state.actors[FOE].position.model_dump(mode='json')
    common = {'category': 'system', 'source_cl': foe_cl, 'visible_sign': 'Demonstrated in this scene'}
    record_fact(combat, table, mid, {
        'record_id': 'fact:identified-systems', 'subject_id': FOE, 'subject_name': 'Subject',
        'subject_kind': 'creature', 'position': position, 'source_reference': 'campaign:observed-systems',
        'witness_ids': [ME], 'valid_through_round': 20,
        'answers': {
            'beauty': {**common, 'fact': 'Subject used a Way of Beauty talent.', 'relationship': {
                'kind': 'system', 'category': 'sphere', 'key': 'beauty', 'name': 'Way of Beauty',
                'source_ids': [aspect_action], 'source_reference': TEARS,
            }},
            'method': {**common, 'fact': 'Subject used a Cultivation Method.', 'relationship': {
                'kind': 'system', 'category': 'method', 'key': 'method', 'name': 'Cultivation Method',
                'source_reference': 'campaign:observed-method',
            }},
        },
    })

    before = combat._load_session(mid).engine
    round_and_slot = (before.state.round_number + 10, before.state.current_slot_index)
    prompts = strike(
        combat, table, mid, ('Sever Sphere', 'fact:identified-systems:beauty'), special='Moon-Edged Sentence',
    )
    by_source = {p['context']['reaction_source_id']: p for p in prompts}
    choices = by_source['choice:needle.blood_moon_execution']['choice']['options']
    assert next(o['id'] for o in choices if o['label'] == 'Sever Aspect') == 'Sever Sphere'
    systems = by_source['choice:needle.blood_moon_system']['choice']['options']
    assert [(o['id'], o['label']) for o in systems] == [('fact:identified-systems:beauty', 'Way of Beauty')]

    engine = cold(tmp_path, mid)
    instance, = [
        c for c in engine.state.actors[FOE].conditions.values()
        if c.condition_id == STATE and c.data['kind'] == 'system'
    ]
    assert instance.data['label'] == 'Sever Aspect: Way of Beauty'
    assert instance.data['category'] == 'sphere'
    assert instance.data['source_ids'] == [aspect_action]

    repeat = instance.data.get('repeat_save')
    if foe_cl == 12:
        assert instance.expires_on == 'UNTIL_REMOVED'
        assert instance.data['until_scene_end'] == 1 and repeat is None
    else:
        assert parse_round(instance.expires_on) == round_and_slot
        assert instance.data['until_scene_end'] == 0 and repeat['ability'] == 'CHA'

    advance(combat, table, mid, FOE)
    before_end = combat._load_session(mid).engine
    last_sequence = before_end.events[-1].sequence
    end(combat, table, mid)
    engine = cold(tmp_path, mid)
    repeats = [
        e for e in engine.events if e.sequence > last_sequence and e.event_type == 'SAVE_ROLLED'
        and e.actor_id == FOE and e.source_definition_id == instance.source_definition_id
    ]
    assert instance.instance_id in engine.state.actors[FOE].conditions
    if foe_cl == 12:
        assert not repeats
        record_fact(combat, table, mid, {
            'record_id': 'fact:scene-ended', 'subject_id': 'scene:encounter', 'subject_name': 'End of scene',
            'subject_kind': 'event', 'position': position, 'source_reference': 'campaign:scene ended',
            'witness_ids': [ME, FOE], 'valid_through_round': 20, 'answers': {}, 'scene_ended': True,
        })
        assert instance.instance_id not in cold(tmp_path, mid).state.actors[FOE].conditions
    else:
        save, = repeats
        assert save.payload['reason'].endswith(':CHA')
        assert save.payload['dc'] == repeat['dc'] and not save.payload['success']
