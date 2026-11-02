"""Per-strike Kindled Response arbitration through real table commits and cold replay."""
import pytest

from combat.typed_executor import bears_mark
from tests.test_auto35_yang import (fixture, candidate, settle, reload, _add_action, _seal,
                                    OWNER, ALLY, FOE, ROUND, FORCE)


IRON = 'tianxia.path.body_refining.feature.iron_fist'


def guaranteed_iron_hit(bundles):
    for action in bundles[0]['action_catalog']:
        if action['display_name'] == 'Iron Fist attack':
            action['parameters']['typed']['numbers']['attack_bonus'] = 100
    _seal(bundles[0])


@pytest.mark.parametrize('ask', [False, True])
def test_attack_decline_survives_flowing_combination_save_and_reload(tmp_path, ask):
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH',
        IRON, 'TAL_IRON_FIST_FLOWING_COMBINATION'], ask=ask, foe_position={'x': 3, 'y': 5},
        bundle_transform=guaranteed_iron_hit)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Iron Fist attack', target=FOE).candidate_id,
        {'choice:needle.yang_aim_attack': None, 'choice:needle.flowing_combination': 'Grapple',
         'choice:needle.yang_aim_save': None})
    ids = [p['context']['reaction_source_id'] for p in prompts]
    assert ids.count('choice:needle.yang_aim_attack') == 1
    assert ids.count('choice:needle.yang_aim_save') == 1
    assert 'reaction:typed.' + FORCE not in ids
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' for e in engine.events)
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FORCE for e in engine.events)
    assert bears_mark(engine.state.actors[OWNER], OWNER, 'Kindled Mark')
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) != engine.state.round_number


def strike():
    return {'type': 'attack', 'attack_kind': 'cultivation', 'on_hit': [
        {'type': 'damage', 'dice': {'count': 1, 'sides': 4}, 'damage_types': ['force']}], 'on_miss': []}


@pytest.mark.parametrize('ask', [False, True])
def test_nested_attack_restores_parent_force_selection(tmp_path, ask):
    def prepare(bundles):
        # Exercise a nested attack *before* the parent's own-hit checkpoint by
        # attaching it to the real Flowing Combination follow-up save.
        for action in bundles[0]['action_catalog']:
            if action['display_name'] == 'Grapple':
                def add_nested(rows):
                    for row in rows:
                        if row.get('type') == 'save':
                            row['on_fail'] = [strike()]
                            row['on_success'] = [strike()]
                        if isinstance(row.get('save'), dict):
                            add_nested([row['save']])
                add_nested(action['parameters']['typed']['effects'])
        guaranteed_iron_hit(bundles)
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH',
        IRON, 'TAL_IRON_FIST_FLOWING_COMBINATION'], ask=ask,
        foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    cid = candidate(combat, mid, 'Iron Fist attack', target=FOE).candidate_id
    from tests.worker2_support import act
    answers, prompts, attack_questions = [], [], 0
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        p = result['reaction']
        prompts.append(p)
        rid = p['context']['reaction_source_id']
        if rid == 'choice:needle.yang_aim_attack':
            pick = FORCE if attack_questions == 0 else None
            attack_questions += 1
        elif rid == 'choice:needle.flowing_combination':
            pick = 'Grapple'
        elif rid == 'choice:needle.yang_aim_save':
            pick = None
        else:
            pick = 'first' if rid.startswith('choice:') else None
        answer = {**p['context'], 'selection': 'USE' if pick is not None else 'DECLINE'}
        if pick is not None and p.get('choice'):
            answer['option_ids'] = [p['choice']['options'][0]['id'] if pick == 'first' else pick]
        answers.append(answer)
    else:
        raise AssertionError('Too many prompts')
    engine = reload(tmp_path, mid)
    assert attack_questions == 2
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED']) == 2
    assert len([e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == FORCE]) == 1
    assert not any(p['context']['reaction_source_id'] == 'reaction:typed.' + FORCE for p in prompts)
    assert not bears_mark(engine.state.actors[OWNER], OWNER, 'Kindled Mark')
    assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number


def test_strike_scope_restores_parent_on_exception():
    from types import SimpleNamespace
    from combat.ext.trigger_occurrence import strike_scope, current_strike
    engine, actor, target = SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    with strike_scope(engine, actor, target) as parent:
        with pytest.raises(RuntimeError):
            with strike_scope(engine, actor, target) as child:
                assert child is not parent
                raise RuntimeError('pause')
        assert current_strike(engine) is parent
    assert current_strike(engine) is None

@pytest.mark.parametrize('pick', [None, FORCE])
@pytest.mark.parametrize('ask', [False, True])
def test_two_recipient_area_attack_arbitrates_actual_strike(tmp_path, pick, ask):
    def prepare(bundles):
        action = _add_action(bundles[0], 'Two recipient wave', [strike()], target='CELL',
            area={'shape': 'sphere', 'size_ft': 5, 'recipients': 'all', 'include_self': True,
                  'exclude_self': False})
        action['parameters']['typed']['numbers']['attack_bonus'] = 100
        _seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], ask=ask,
        foe_position={'x': 5, 'y': 6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Two recipient wave', at=(5, 6)).candidate_id,
        {'choice:needle.yang_aim_attack': pick})
    menus = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack']
    # The first recipient is an ally: the inherited own-hit handler only fires
    # against hostiles, so the mark remains available for the second recipient.
    assert len(menus) == 2
    assert all(FORCE in [o['id'] for o in p['choice']['options']] for p in menus)
    assert not any(p['context']['reaction_source_id'] == 'reaction:typed.' + FORCE for p in prompts)
    engine = reload(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 2
    assert {a.target_ids[0] for a in attacks} == {ALLY, FOE}
    forced = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FORCE]
    assert len(forced) == (0 if pick is None else 1)
    assert bears_mark(engine.state.actors[OWNER], OWNER, 'Kindled Mark') is (pick is None)
    assert (engine.state.actors[OWNER].turn_flags.get(ROUND) == engine.state.round_number) is (pick is not None)
