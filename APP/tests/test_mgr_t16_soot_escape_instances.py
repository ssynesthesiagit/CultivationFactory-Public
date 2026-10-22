"""Independent source-owned Soot-Scent choices through table commit and reload."""
from combat.canonical import canonical_sha256
from combat.ext.smoke_tracking import TRACK
from tests.test_mgr_t16_talents_misc_3 import BASE, SOOT, setup_actions
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle


CHOICE = 'choice:needle.soot_scent_escape'


def _two_casters(bundles):
    setup_actions(bundles)
    # Each trace must retain its own DC. The second escape is deterministic.
    ally = next(bundle for bundle in bundles if bundle['actor_id'] == ALLY)
    follow = next(action for action in ally['action_catalog']
                  if action['display_name'] == 'Follow the Soot')
    follow['parameters']['typed']['numbers']['save_dc'] = -50
    ally.pop('bundle_sha256', None)
    ally['bundle_sha256'] = canonical_sha256(ally)


def _turn_declining(table, mid, actor_id):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor_id:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks={CHOICE: None})
    raise AssertionError('No turn')


def test_declining_one_casters_escape_does_not_answer_another_trace(tmp_path):
    combat, table, mid = fixture(tmp_path, BASE + [SOOT], ally_talents=BASE + [SOOT],
                                owner_dc=50, bundle_transform=_two_casters, named=True)
    for caster in (OWNER, ALLY):
        _turn_declining(table, mid, caster)
        settle(table, mid, candidate(combat, mid, 'Test mark', target=FOE).candidate_id)
        settle(table, mid, candidate(combat, mid, 'Follow the Soot', target=FOE).candidate_id)
    _turn_declining(table, mid, FOE)
    before = reload(tmp_path, mid)
    traces = [held for held in before.state.actors[FOE].conditions.values()
              if held.condition_id == TRACK]
    assert [(held.source_actor_id, held.data['save_dc']) for held in traces] == [(OWNER, 50), (ALLY, -50)]
    first, second = traces

    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     picks={CHOICE: (None, 'stealth')})
    escapes = [prompt for prompt in prompts if prompt['context']['reaction_source_id'] == CHOICE]
    assert len(escapes) == 2, 'Each caster-owned trace must ask independently after a decline'
    assert escapes[0]['context']['checkpoint'] != escapes[1]['context']['checkpoint']
    assert all(prompt['context']['reactor_id'] == FOE for prompt in escapes)
    assert 'Wren' in str(escapes[0]) and 'Tobin' in str(escapes[1])
    assert all('Mara' in str(prompt) and 'Follow the Soot' in str(prompt) for prompt in escapes)

    after = reload(tmp_path, mid)  # Cold load also verifies the committed replay.
    remaining = [held for held in after.state.actors[FOE].conditions.values()
                 if held.condition_id == TRACK]
    assert [held.instance_id for held in remaining] == [first.instance_id]
    assert remaining[0].model_dump(mode='json') == first.model_dump(mode='json')
    checks = [event for event in after.events[len(before.events):]
              if event.event_type == 'CHECK_ROLLED' and 'follow_soot' in event.source_definition_id]
    assert len(checks) == 1 and checks[0].actor_id == FOE
    assert second.instance_id not in after.state.actors[FOE].conditions
