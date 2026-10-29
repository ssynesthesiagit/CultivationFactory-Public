"""Offline small-seat frames and retained v2 decision schema; no inference."""
import json
import re

import pytest

from agent_seats.choices import build_prompt, parse_letter, turn_options
from tests.test_seat_tactics import situation
from tests.h1_support import ROOT
from tools.summarize_dao import summarize


@pytest.mark.parametrize('reply', ['A', 'Option A', '**A**', 'Option **A**', 'A)',
    'A) I attack a visible enemy.', 'A\nI attack a visible enemy.',
    '**A**: conserve a resource.'])
def test_unambiguous_small_model_formats(reply):
    assert parse_letter(reply, {'A': {'plan': ['hit', 'end']}, 'B': {'plan': ['end']}}) == {'plan': ['hit', 'end']}


@pytest.mark.parametrize('reply', ['**C**', 'Option Z', '**A', 'A**', 'A) or B',
    '**A**\nOption B', 'A) choose b', 'A\nB', 'A) actually C',
    '**A** or **B**', 'A because option Z is better', 'B\na', 'A) I',
    'B) a) attack', 'B) **a** is better'])
def test_unoffered_and_ambiguous_letters_still_fail(reply):
    with pytest.raises(ValueError, match='one offered letter'):
        parse_letter(reply, {'A': 1, 'B': 2})


@pytest.mark.parametrize('reply', [
    'B) I prefer a instead', 'B) I prefer a', 'B) a is better',
    'B) a would work better', 'B) a rather than this', 'B) a over this',
    'B) a dominates here', 'B) a sounds better', 'B) a to avoid damage',
    'A) attack; actually option b', 'A) I prefer b instead',
    'A) i instead', 'A) i is better', 'A) I prefer i instead',
    'A) i dominates here',
])
def test_lowercase_option_references_in_reasoning_fail(reply):
    with pytest.raises(ValueError, match='one offered letter'):
        parse_letter(reply, {'A': 1, 'B': 2, 'I': 9})


@pytest.mark.parametrize('reply', [
    'B) I prefer a move instead', 'B) I choose a visible enemy.',
    'A) a move puts me out of reach.', 'A) I conserve a resource.',
    'A) I think a defensive move is better.', 'A) I will attack.',
    'A) i attack a visible enemy.',
])
def test_articles_and_pronouns_remain_reasoning(reply):
    offered = {'A': 1, 'B': 2, 'I': 9}
    assert parse_letter(reply, offered) == offered[reply[0]]


@pytest.mark.parametrize('kind', ['TURN', 'REACTION'])
@pytest.mark.parametrize('bad_reply', ['B) I prefer a instead',
                                     'A) attack; actually option b'])
@pytest.mark.parametrize('repair_succeeds', [False, True])
def test_real_seat_contradiction_repairs_before_commit_or_uses_builtin(
        tmp_path, kind, bad_reply, repair_succeeds):
    from combat.gate5_service import CombatService
    from tests.test_agent_seats import runner_for, raw_state
    from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
    from tests.test_seat_choices import configure

    mechanic = 'AIR_BASE_GATHER_CURRENT' if kind == 'TURN' else 'TAL_FENCING_FOOTWORK'
    _, table, mid, cid, _ = fixture(tmp_path, mechanic)
    prompts, sequences = [], []
    replies = iter([bad_reply, 'A' if repair_succeeds else bad_reply])
    def model(config, prompt, png):
        prompts.append(prompt)
        sequences.append(table.state(mid)['last_sequence'])
        assert config['choices_bytes'] == 1600 and config['max_options'] == 5
        assert len(prompt.encode()) <= 1600
        assert 'A)' in prompt and 'B)' in prompt
        return next(replies), None

    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    config = json.loads(runner.registry.path.read_text())
    config['providers'][0].update(choices_bytes=1600, max_options=5)
    runner.registry.path.write_text(json.dumps(config))
    actor = FOE if kind == 'TURN' else PLAYER
    runner.set_seat(mid, actor, 'MODEL', 'fake')
    if kind == 'REACTION':
        menu = table.state(mid)['menu']
        assert table.act(mid, cid, menu['decision_id'], menu['state_version'], 0)['status'] == 'MODEL_DECIDING'
    before = raw_state(runner, mid)['last_sequence']
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[0]
    assert row['kind'] == kind and row['attempts'] == 2
    assert row['invalid_replies'] == (1 if repair_succeeds else 2)
    assert bool(row['fallback']) == (not repair_succeeds)
    assert len(prompts) == 2 and 'Invalid reply' in prompts[1]
    assert sequences == [before, before]  # Neither contradictory reply commits.
    if kind == 'TURN':
        assert row['chosen'][0] == row['built_in_pick']
        if not repair_succeeds:
            assert row['chosen'] == [row['built_in_pick']]
    else:
        assert row['chosen'] == row['built_in_pick']
    assert raw_state(runner, mid)['last_sequence'] > before
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.verify()['status'] == saved.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('budget,maximum', [(800, 6), (1200, 5), (2400, 12)])
@pytest.mark.parametrize('repair', [None, 'invalid'])
def test_instructions_name_only_the_letters_actually_packed(budget, maximum, repair):
    view, legal = situation()
    options = turn_options(view, legal, 'hit', limit=3, choices_bytes=budget, max_options=maximum)
    prompt, offered = build_prompt(view, options, 'TURN', legal, repair,
                                   choices_bytes=budget, max_options=maximum)
    last = next(reversed(offered))
    advertised = re.search(r'(?:Reply |letter only \()(A(?:-[A-Z])?)', prompt)[1]
    assert advertised == ('A' if last == 'A' else 'A-' + last)
    assert len(prompt.encode()) <= budget
    assert len(offered) <= (4 if budget == 800 else maximum)
    assert any('Move' == legal[k]['action'] for a in offered.values() for k in a['plan'])
    assert {'plan': ['end']} in offered.values()
    assert 'Dao:' in prompt and 'HP:' in prompt and 'Threat: Bone Guard' in prompt
    for answer in offered.values():
        for key in answer['plan']:
            row = legal[key]
            if row.get('cost_label'):
                assert row['cost_label'] in prompt
            if row.get('description'):
                assert row['description'] in prompt


def test_compact_tactical_retreat_retains_risk_cost_and_destination():
    from agent_seats.choices import Option, TurnOptions
    view, legal = situation()
    purpose = 'put distance between you and Bone Guard; leaving reach may provoke an attack'
    legal['move0-6']['cost_label'] = '5 feet of movement'
    move = 'move0-6'
    options = TurnOptions([
        Option({'plan': [move, 'end']}, 'Move to (0,6) — '+purpose+' (5 feet of movement)', ''),
        Option({'plan': ['end']}, 'End turn here', '', 'take no further action')], {move: purpose})
    prompt, offered = build_prompt(view, options, 'TURN', legal, choices_bytes=800)
    assert 'retreat from Bone Guard; leaving reach may provoke an attack' in prompt
    assert '(0,6)' in prompt and '5 feet of movement' in prompt
    assert offered['A'] == {'plan': [move, 'end']}


@pytest.mark.parametrize('repair', [None, 'invalid'])
def test_recorded_lightning_body_overflow_keeps_its_complete_rules(repair):
    # Recorded v2 failure: 9/55 HP at (11,6), no movement remaining,
    # Lightning/Sabers Dao and Lightning-God Body plus End. Use public rules
    # and an anonymous fighter, without committing owner capture contents.
    rules = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    own = dict(entity_id='me', display_name='Fighter', team_id='ours',
               position={'x': 11, 'y': 6}, hit_points={'current': 9, 'maximum': 55})
    view = {'fighter': 'me', 'actors': [own], 'dao': {'name': 'Lightning / Sabers',
        'temperament': {'fighting': 'strikes, connects, interrupts, advances, chops, points'}}}
    legal = {'body': {'action': 'Lightning-God Body', 'targets': ['me'], 'economy': 'BONUS_ACTION',
                     'cost_label': 'Bonus Action, 1 CP', 'description': rules['TAL_LIGHTNING_LIGHTNING_GOD_BODY']},
             'end': {'action': 'End turn', 'targets': []}}
    options = turn_options(view, legal, 'body', choices_bytes=1600, max_options=5)
    prompt, offered = build_prompt(view, options, 'TURN', legal, repair, choices_bytes=1600, max_options=5)
    assert len(prompt.encode()) <= 1600
    assert 'Reply A-B' in prompt and {'plan': ['body', 'end']} in offered.values()
    from agent_seats.choices import option_description
    assert option_description(legal['body'], legal) in prompt
    assert 'Bonus Action, 1 CP' in prompt and 'HP: 9/55 at (11,6)' in prompt
    assert 'Dao: Lightning / Sabers' in prompt


@pytest.mark.parametrize('reply', ['**A**', 'Option A\nI attack a visible enemy.'])
def test_recovered_letter_commits_through_seat_and_reload(tmp_path, reply):
    from combat.gate5_service import CombatService
    from tests.test_agent_seats import runner_for
    from tests.test_hunt5_player_choices import fixture, FOE
    from tests.test_seat_choices import configure
    _, table, mid, *_ = fixture(tmp_path, 'AIR_BASE_GATHER_CURRENT')
    prompts = []
    def model(config, prompt, png):
        prompts.append(prompt)
        return reply, None
    runner, _ = runner_for(tmp_path, table, model)
    configure(runner)
    runner.set_seat(mid, FOE, 'MODEL', 'fake')
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[0]
    assert not row['fallback'] and row['attempts'] == 1 and row['invalid_replies'] == 0
    assert len(prompts) == 1 and len(prompts[0].encode()) <= 800
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.verify()['status'] == saved.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('capture_kind', ['empty', 'step-only', 'model'])
def test_v2_metrics_survive_empty_capture_and_use_complete_logs(tmp_path, capture_kind):
    decision = dict(actor_id='fighter', kind='TURN', chosen=['guard', 'end'],
                    built_in_pick='guard', dao_policy_top2=['guard', 'strike'], fallback=None, latency_ms=1)
    root = tmp_path / 'iteration1-0'
    root.mkdir()
    content = '' if capture_kind == 'empty' else json.dumps({'kind': 'STEP'})+'\n'
    if capture_kind == 'model':
        content += json.dumps(decision)+'\n'
    (root / 'Agent_Decisions.jsonl').write_text(content)
    rows = [dict(arm='iteration1', seed='LONG-0', pair=['one', 'two'], calls=1, decisions=[decision])]
    result = summarize(rows, tmp_path)
    # v2 is iteration1 only: don't lead with fabricated zero/null mirror arms.
    assert [arm['arm'] for arm in result['aggregate']] == ['iteration1']
    overall = result['dao_fidelity']['overall']
    assert overall['model_decisions'] == overall['top1'] == overall['top2'] == 1
    assert overall['top1_rate'] == overall['top2_rate'] == 1
    assert result['decision_sources'][0]['source'] == ('capture' if capture_kind == 'model' else 'metrics')
