"""Burden admission, save outcomes, choices and complete repeat-save expiry."""
import pytest
from tests.hunt31_support import OWNER, ALLY, FOE, fixture, prepare, pick, reload, send, owner_turn, act, finish_choices
from combat.ext.karma_imprints import held
from combat.typed_executor import mark_condition_id

BURDEN = 'tianxia.talent.karma.burden_of_deeds'
DEBT = {'type': 'condition', 'condition': mark_condition_id('Debt Imprint', OWNER).removeprefix('condition:typed.'),
        'applies_to': 'target', 'duration': 'until_removed'}


@pytest.mark.parametrize('auto', [False, True])
def test_burden_not_offered_without_own_debt(monkeypatch, tmp_path, auto):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN])
    assert not any('Burden of Deeds' in g['label'] for g in table.state(mid)['menu']['actions'])
    reload(combat, mid)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('dc', [1, 50])
def test_burden_save_and_per_imprint_choices(monkeypatch, tmp_path, auto, dc):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=dc, setup=[DEBT])
    prepare(table, mid, ALLY)
    prepare(table, mid, ALLY)
    assert len(held(reload(combat, mid).state.actors[ALLY], OWNER, 'debt')) == 2
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    sender = lambda answers: send(combat, table, mid, cid, auto, answers)
    result = sender([])
    if dc == 50 and not auto:
        assert result['status'] == 'REACTION_REQUIRED'
        assert 'Burden of Deeds' in str(result['reaction'])
    result = finish_choices(sender, result, option='Speed reduced by 5 feet')
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    target = engine.state.actors[ALLY]
    assert len(held(target, OWNER, 'debt')) == 2
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and any(r.reason.startswith('SAVE:') and r.reason.endswith(':CHA') for r in engine.rolls)
    if dc == 50:
        assert engine._effective_speed(target) == target.speed_ft - 10
        before = len(saves)
        owner_turn(table, mid, next_turn=True)
        engine = reload(combat, mid)
        assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED']) > before
    else:
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(target))
        owner_turn(table, mid, next_turn=True)
        assert not any(r.get('no_reactions') for r in condition_rules(reload(combat, mid).state.actors[ALLY]))


@pytest.mark.parametrize('auto', [False, True])
def test_successful_repeat_save_ends_all_burdens(monkeypatch, tmp_path, auto):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=10, setup=[DEBT])
    prepare(table, mid, ALLY)
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    sender = lambda answers: send(combat, table, mid, cid, auto, answers)
    assert finish_choices(sender, sender([]), option='Speed reduced by 5 feet')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[ALLY]) == 20  # seeded initial total 9 fails
    for _ in range(5):
        owner_turn(table, mid, next_turn=True)
        engine = reload(combat, mid)
        if not any(c.condition_id == 'condition:typed.karma_burden' for c in engine.state.actors[ALLY].conditions.values()):
            break
    assert engine._effective_speed(engine.state.actors[ALLY]) == 30
    assert not any('rider_repeat_group' in c.condition_id for c in engine.state.actors[ALLY].conditions.values())
    assert len(held(engine.state.actors[ALLY], OWNER, 'debt')) == 2


def test_check_burden_affects_only_next_check(monkeypatch, tmp_path):
    check = {'type': 'skill_check', 'ability': 'DEX', 'skill': 'Acrobatics'}
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=50, setup=[DEBT, check])
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    sender = lambda answers: send(combat, table, mid, cid, False, answers)
    result = sender([])
    prompt = result['reaction']
    choice = next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('Disadvantage'))
    assert sender([{**prompt['context'], 'selection': 'USE', 'option_ids': [choice]}])['status'] == 'COMMITTED'
    # Checks are target-scoped; another owner's legal preparation action rolls
    # two checks on the affected creature during one accepted table request.
    for _ in range(2):
        prepare(table, mid, ALLY)
    engine = reload(combat, mid)
    checks = [r for r in engine.rolls if r.reason.startswith('CHECK:') and r.actor_id == ALLY]
    assert [r.mode for r in checks[-2:]] == ['DISADVANTAGE', 'NORMAL']


@pytest.mark.parametrize('held_cast', [False, True])
def test_check_burden_ends_with_concentration_after_commit_reload(monkeypatch, tmp_path, held_cast):
    if held_cast:
        from tests import hunt28_support as h

        original = h.compile_character

        def compile_with_hold(doc, **kw):
            bundle = original(doc, **kw)
            if kw['actor_id'] == OWNER:
                aid = 'action:test.h31.hold'
                bundle['actor_template']['action_ids'].append(aid)
                bundle['action_catalog'].append({
                    'source_definition_id': aid, 'display_name': 'Hold another technique', 'owner_id': OWNER,
                    'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                    'parameters': {'typed': {'effects': [], 'numbers': {},
                                             'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True}}}})
            return bundle

        monkeypatch.setattr(h, 'compile_character', compile_with_hold)
    check = {'type': 'skill_check', 'ability': 'DEX', 'skill': 'Acrobatics'}
    # Generic preparation effects are sealed in the synthetic table before
    # genesis. End concentration through a committed action, never a patched
    # engine or a direct mutation of saved state.
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=50,
                                setup=[DEBT, check, {'type': 'lose_concentration', 'applies_to': 'self'}])
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    sender = lambda answers: send(combat, table, mid, cid, False, answers)
    assert finish_choices(sender, sender([]),
                          option='Disadvantage on the next ability check before its next turn ends')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].concentration is not None
    assert any(c.condition_id == 'condition:typed.karma_burden_check'
               for c in engine.state.actors[ALLY].conditions.values())

    if held_cast:
        assert act(table, mid, pick(table, mid, 'Hold another technique'))['status'] == 'COMMITTED'
        from combat.concentration import held as held_concentrations

        assert len(held_concentrations(reload(combat, mid).state.actors[OWNER])) == 1

    prepare(table, mid, OWNER)  # End/lose concentration before the ally checks.
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].concentration is None
    assert not any(c.condition_id in {'condition:typed.karma_burden', 'condition:typed.karma_burden_check'}
                   or c.condition_id.startswith('condition:typed.rider_repeat_group.')
                   for c in engine.state.actors[ALLY].conditions.values())
    prepare(table, mid, ALLY)
    engine = reload(combat, mid)
    checks = [r for r in engine.rolls if r.reason.startswith('CHECK:') and r.actor_id == ALLY]
    assert checks[-1].mode == 'NORMAL'


def test_check_burden_keeps_earlier_turn_deadline(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=50, setup=[DEBT])
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    sender = lambda answers: send(combat, table, mid, cid, False, answers)
    assert finish_choices(sender, sender([]),
                          option='Disadvantage on the next ability check before its next turn ends')['status'] == 'COMMITTED'
    owner_turn(table, mid, next_turn=True)
    engine = reload(combat, mid)
    conditions = engine.state.actors[ALLY].conditions.values()
    assert engine.state.actors[OWNER].concentration is not None
    assert any(c.condition_id == 'condition:typed.karma_burden' for c in conditions)
    assert not any(c.condition_id == 'condition:typed.karma_burden_check' for c in conditions)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('burden', ['-1 to attack rolls', '-1 to saving throws'])
def test_numeric_burdens_stack_on_actual_rolls(monkeypatch, tmp_path, auto, burden):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=50, setup=[DEBT], armed=True)
    prepare(table, mid, ALLY)
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    # Manual caster chooses both penalties; auto tests exercise the afflicted
    # actor's attack/end-turn resolution through the AI transport.
    sender = lambda answers: send(combat, table, mid, cid, False, answers)
    assert finish_choices(sender, sender([]), option=burden)['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != ALLY:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    if burden == '-1 to attack rolls':
        cid = pick(table, mid, 'attack', FOE)
        assert send(combat, table, mid, cid, auto, actor=ALLY)['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.actor_id == ALLY]
        assert rewrites[-1].payload['bonus'] == -2
    else:
        cid = table.state(mid)['menu']['end_turn']
        assert send(combat, table, mid, cid, auto, actor=ALLY)['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        saves = [r for r in engine.rolls if r.reason.startswith('SAVE:') and r.actor_id == ALLY]
        assert saves[-1].modifier == saves[0].modifier - 2


def test_burdens_omit_meaningless_speed_and_duplicate_reaction_denial(monkeypatch, tmp_path):
    speed = {'type': 'speed', 'applies_to': 'target', 'flat': -30, 'duration': 'until_removed'}
    combat, table, mid = fixture(monkeypatch, tmp_path, [BURDEN], dc=50, setup=[DEBT, speed])
    prepare(table, mid, ALLY)
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Burden of Deeds', ALLY)
    result = send(combat, table, mid, cid, False)
    prompt = result['reaction']
    assert 'Speed reduced by 5 feet' not in [o['id'] for o in prompt['choice']['options']]
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['Cannot take Reactions']}
    result = send(combat, table, mid, cid, False, [answer])
    second = result['reaction']
    assert 'Cannot take Reactions' not in [o['id'] for o in second['choice']['options']]
    answer2 = {**second['context'], 'selection': 'USE', 'option_ids': ['-1 to saving throws']}
    assert send(combat, table, mid, cid, False, [answer, answer2])['status'] == 'COMMITTED'
    reload(combat, mid)
