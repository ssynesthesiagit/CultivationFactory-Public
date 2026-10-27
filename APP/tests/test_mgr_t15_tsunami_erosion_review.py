"""Review regressions: GM permission on automatic turns and mundane erosion.

Portable synthetic fixtures only; no network or private character/history data.
"""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests.test_mgr_t15_close_heaven_falling_tsunami import (
    A, B, C, actions, cast, cold, setup,
)


EROSION = 'choice:needle.scouring_erosion'


@pytest.mark.parametrize('shape', ['line', 'cone'])
@pytest.mark.parametrize('benefit', [None, 'double'], ids=['declined', 'approved'])
def test_all_automatic_tsunami_waits_for_gm_and_replays(tmp_path, monkeypatch, shape, benefit):
    combat, table, mid = setup(tmp_path, patch={
        81: {'name': 'Mundane Crate'},
        82: {'name': 'Artifact Control Wall', 'artifact': True},
        **{oid: {'unattended': False} for oid in (84, 86, 87)},
    })
    for actor_id in (A, B, C):
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    _, _, before = cold(tmp_path, mid)
    assert not before.typed_ask_reactors, 'No manual reactor may accidentally enable GM preview'
    ids = {a.source_definition_id for a in actions(before)
           if a.parameters['typed']['area']['shape'] == shape}
    candidate = next(c for c in before.legal_candidates()
                     if c.source_definition_id in ids and c.destination
                     and (c.destination.x, c.destination.y) == (14, 6))
    def choose(context):
        # Auto receives the native lazy placement root, not an exhaustive
        # player candidate ID. Bind the legal directional aim on its intent.
        root = next(c for c in context.legal_candidates if c.source_definition_id in ids)
        choice = ManualControllerAdapter(lambda _: (root.candidate_id, ())).choose_primary_action(context)
        return choice.model_copy(update={'intent': choice.intent.model_copy(
            update={'placement_destination': candidate.destination})})

    monkeypatch.setattr(combat.controller, 'choose_primary_action', choose)
    result = table.auto_step(mid, 0, [])
    answers, prompts = [], []
    for _ in range(20):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == EROSION, prompt
        assert 'Heaven-Falling Tsunami' in prompt['moment']
        assert 'Artifact Control Wall' not in prompt['moment']
        prompts.append(prompt)
        # The preview is transactional: no dice, CP or damage is committed yet.
        _, _, waiting = cold(tmp_path, mid)
        assert len(waiting.rolls) == len(before.rolls)
        assert waiting.state.actors[A].resources == before.state.actors[A].resources
        assert waiting.state.objects['object:map.81'].current_hp == 200
        answers.append({**prompt['context'], 'selection': 'USE' if benefit else 'DECLINE',
                        'option_ids': [benefit] if benefit else []})
        result = table.auto_step(mid, 0, answers)
    assert result['status'] == 'COMMITTED', result
    assert any('Mundane Crate' in p['moment'] for p in prompts), 'GM choice missing on automatic turn'
    _, _, after = cold(tmp_path, mid)
    ordinary = 200 - after.state.objects['object:map.82'].current_hp
    assert 8 <= ordinary <= 64
    assert 200 - after.state.objects['object:map.81'].current_hp == ordinary * (2 if benefit else 1)
    assert before.state.actors[A].resources['resource:core.qi'] - after.state.actors[A].resources['resource:core.qi'] == 5


@pytest.mark.parametrize('benefit', ['bypass', 'double'])
def test_packed_earth_wall_is_eligible_but_stone_artifact_is_not(tmp_path, benefit):
    combat, table, mid = setup(tmp_path, patch={
        81: {'material': 'stone', 'artifact': True, 'name': 'Stone Artifact',
             'resist': ['BLUDGEONING']},
        82: {'material': 'packed earth', 'name': 'Packed Earth Wall',
             'resist': ['BLUDGEONING']},
        **{oid: {'unattended': False} for oid in (84, 86, 87)},
    })
    _, _, before = cold(tmp_path, mid)
    assert before.state.objects['object:map.81'].component['artifact']
    assert before.state.objects['object:map.82'].component['material'] == 'packed earth'
    prompts = cast(combat, table, mid, recipients=[], erosion=benefit)
    offered = [p for p in prompts if p['context']['reaction_source_id'] == EROSION]
    assert any('Packed Earth Wall' in p['moment'] for p in offered)
    assert not any('Stone Artifact' in p['moment'] for p in offered)
    _, _, after = cold(tmp_path, mid)
    # The attended wooden control receives the same roll, without erosion
    # or Resistance. Only the packed-earth wall can receive the GM benefit.
    base = 200 - after.state.objects['object:map.86'].current_hp
    assert 8 <= base <= 64
    assert 200 - after.state.objects['object:map.81'].current_hp == base // 2
    assert 200 - after.state.objects['object:map.82'].current_hp == (
        base if benefit == 'bypass' else 2 * (base // 2))
