"""Second review: preserve Forms, global-turn movement and mixed Death rosters.

All fights are local fixtures; no model or embedding service is contacted.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import brutal_momentum, qi_path
from tests.h1_support import sheet
from tests.worker2_support import (
    ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn,
)
from tests.test_a2r_borrowed_golden_form import setup as golden_setup, use
from tests.test_a2r_bone_general import setup as bone_setup, servants
from tests.test_a2r_brutal_momentum import _strong_owner


def qi_spend(bundles):
    """A sealed, harmless test action spends Qi through the normal transaction."""
    bundle = bundles[0]
    source = 'action:test.spend_qi'
    numbers = next(row['parameters']['typed']['numbers'] for row in bundle['action_catalog']
                   if row['display_name'] == 'Borrowed Golden Form')
    bundle['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Spend test Qi',
        'owner_id': OWNER, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
        'target_kind': 'SELF', 'costs': [[qi_path.QI, 95]],
        'parameters': {'golden_core_choices': True,
                       'typed': {'effects': [], 'numbers': numbers,
                                 'duration': {'kind': 'instant'}, 'riders': []}},
    })
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('cl,recovered', [(16, 1), (17, 2)])
def test_f1_default_stable_recovers_alongside_borrowed_circulating(tmp_path, cl, recovered):
    combat, table, mid = golden_setup(tmp_path, cl=cl, bundle_transform=qi_spend)
    # Finish initial-turn setup before measuring ordinary start-of-turn recovery.
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].turn_flags['golden_core_initiative_round_done']
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    # 100 starting Qi - 4 to borrow - 95 willingly spent = 1, below Stable's threshold.
    prompts = use(combat, table, mid, 'Spend test Qi',
                  choices={'choice:needle.golden_benefits': ['temp_hp']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.golden_benefits'
               for p in prompts)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[qi_path.QI] == 1
    assert owner.temporary_hp == owner.proficiency_bonus  # unperfected Circulating
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[qi_path.QI] == 1 + recovered
    assert set(qi_path.forms(owner)) == {'stable', 'circulating'}
    assert qi_path.form_state(engine, owner, 'stable') is (cl >= 17)
    assert qi_path.form_state(engine, owner, 'circulating') is False


def test_f1_borrow_does_not_consume_the_second_permanent_form_slot(tmp_path):
    from tests.test_a2r_borrowed_golden_form import Q
    combat, table, mid = golden_setup(
        tmp_path, cl=20, features=(Q + 'golden_core_form', Q + 'second_golden_core_form'))
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    permanent = [c.data['form'] for c in owner.conditions.values()
                 if c.condition_id == qi_path.FORM and not c.data.get('borrowed')]
    assert set(permanent) == {'stable', 'reservoir'}
    assert set(qi_path.forms(owner)) == {'stable', 'circulating', 'reservoir'}


def test_f2_own_turn_use_does_not_suppress_off_turn_kill_prompt(tmp_path):
    foe = sheet([], cl=15, score=3)
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1
    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=_strong_owner(), foe_sheet=foe,
        foe_position={'x': 2, 'y': 6}, named=True)
    # Own-turn use, deliberately staying beside the hostile to threaten its later move.
    prompts = settle(table, mid, candidate(combat, mid, 'Shove: Prone', target=FOE).candidate_id,
                     picks={'choice:needle.brutal_momentum': None})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.brutal_momentum'
               for p in prompts)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].turn_flags[brutal_momentum.TURN_FLAG]
    own_stamp = before.state.actors[OWNER].turn_flags[brutal_momentum.TURN_FLAG]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    move = next(c for c in engine.legal_candidates()
                if c.kind == 'MOVE' and c.destination.x == 0 and c.destination.y == 6)
    # Accept the real Opportunity Attack and then its manual Ask-me movement.
    answers, prompts = [], []
    for _ in range(8):
        from tests.test_r9i_karma_persistence import act
        result = act(table, mid, move.candidate_id, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    else:
        pytest.fail('Too many off-turn reaction prompts')
    steps = [p for p in prompts
             if p['context']['reaction_source_id'] == 'choice:needle.brutal_momentum']
    assert len(steps) == 1
    assert 'Brutal Momentum' in steps[0]['moment']
    assert 'reducing a hostile creature to 0 Hit Points' in steps[0]['moment']
    assert steps[0]['context']['reactor_id'] == OWNER
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp == 0
    assert after.state.actors[OWNER].position != engine.state.actors[OWNER].position
    assert after.state.actors[OWNER].turn_flags[brutal_momentum.TURN_FLAG] != own_stamp
    # Repeated qualifying receipts in this same global turn cannot offer another step.
    event_count = len(after.events)
    brutal_momentum.offer(after, after.state.actors[OWNER], 'another qualifying event')
    assert len(after.events) == event_count


@pytest.mark.parametrize('automatic', [False, True])
def test_f3_mixed_death_roster_uses_reserved_capacity_first(tmp_path, automatic):
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'} if automatic else None
    combat, table, mid = bone_setup(
        tmp_path, talents=('TAL_DEATH_CORPSE_SERVANT', 'TAL_DEATH_GRAVE_FORMATION'),
        plan={'counts': {'corpse_servant': 2, 'lesser_corpse_servant': 0, 'grave_formation': 1}},
        modes=modes)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].proficiency_bonus == 4
    assert len(servants(engine, 'corpse_servant')) == 2
    assert len(servants(engine, 'grave_formation')) == 1
    if automatic:
        from tests.test_a2r_bone_general import ai_send
        # Automatic seats have no manual menu; use the engine's full legal set.
        end_turn = next(c.candidate_id for c in engine.legal_candidates() if c.kind == 'END_TURN')
        ai_send(combat, table, mid, end_turn)
    else:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert len(servants(engine, 'corpse_servant')) == 2
    assert len(servants(engine, 'grave_formation')) == 1
