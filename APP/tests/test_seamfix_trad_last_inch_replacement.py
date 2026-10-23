"""Public table regression for replacing a creature with a spiritual object."""
from combat.ext import last_inch_palm as palm, object_subjects
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


def test_spirit_touch_object_replaces_creature_before_expiry_after_reload(tmp_path, monkeypatch):
    arena = to_battlefield(normalize_map({
        'display_name': 'Handspan replacement', 'width_squares': 20, 'height_squares': 14,
        'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]},
        'objects': [{
            'id': 1, 'kind': 'custom', 'x': 4, 'y': 5, 'name': 'External spirit asset',
            'hp': 100, 'ac': 1, 'blocks': False,
            'spiritual_profile': {'source_rule': 'test:external_spirit', 'source_cl': 3,
                                  'identity': 1, 'known_to': [OWNER]},
        }],
    }))
    foe = sheet([], cl=3, name='Mara')
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 100
    combat, table, mid = fixture(
        tmp_path, [], cl=3, primary='Resonance', owner_path='Spirit Awakening',
        owner_features=[palm.LAST_INCH], foe_sheet=foe, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 7}, FOE: {'x': 4, 'y': 6}},
        battlefield=arena, seed='SEAMFIX-LAST-1',
    )
    settle(table, mid, candidate(combat, mid, 'Spirit-Touch Unarmed Strike (Strength)', target=FOE).candidate_id,
           choices={'choice:needle.last_inch.designate': 'designate'})
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    owner, old_subject = engine.state.actors[OWNER], engine.state.actors[FOE]
    # The previous designation is still live until this turn ENDS.
    assert palm.is_subject(engine, owner, old_subject)
    assert palm.strike_reach(engine, owner, old_subject) == 10
    assert all(action.reach_ft == 10 for action in palm.spirit_touch_opportunity(engine, owner, old_subject))

    prompts = settle(table, mid,
        candidate(combat, mid, 'Spirit-Touch Unarmed Strike (Strength)', target='object:map.1').candidate_id,
        choices={'choice:needle.last_inch.object_designate': 'designate'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.last_inch.object_designate' for p in prompts)
    engine = reload(tmp_path, mid)
    owner, old_subject = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert engine.state.current_actor_id == OWNER
    assert not any(c.condition_id == palm.SUBJECT and c.source_actor_id == OWNER
                   for c in old_subject.conditions.values())
    assert not palm.is_subject(engine, owner, old_subject)
    assert palm.strike_reach(engine, owner, old_subject) == palm.actual_unarmed_reach(engine, owner) == 5
    assert all(action.reach_ft == 5 for action in palm.spirit_touch_opportunity(engine, owner, old_subject))

    # Neither a reach crossing nor attempted passage may offer the old subject's Step.
    steps = []
    monkeypatch.setattr(palm, '_last_inch_step', lambda *args: steps.append(args))
    palm.subject_reach_crossing(engine, old_subject, old_subject.position,
                               old_subject.position.model_copy(update={'x': 6}), None)
    palm.subject_passage_attempt(engine, old_subject, old_subject.position, owner.position, None)
    assert not steps

    obj = engine.state.objects['object:map.1']
    [record] = object_subjects.records(obj, 'handspan_subject', OWNER)
    assert record['boundary'] == 'end' and record['due_turn'] == owner.turns_started + 1
    assert object_subjects.relationship_status(engine, obj, record) == 'ACTIVE'
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Spirit-Touch Unarmed Strike (Strength)')
    assert palm.spirit_touch_object_allowed(engine, owner, action, obj)
