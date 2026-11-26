"""Sound review: authoritative scene constraints and dormant unrelated menus."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests.worker2_support import OWNER, ALLY, fixture, candidate, reload, turn
from tests.test_mgr_t14_sound_base import DAMPEN, cast

NAME = 'Check movement: move quietly'


def quiet_candidates(combat, mid):
    engine = combat._load_session(mid).engine
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == NAME]


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
def test_unrelated_scene_has_no_quiet_check_on_any_seat(tmp_path, mode):
    combat, table, mid = fixture(tmp_path, [], ask=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    assert not quiet_candidates(combat, mid)
    reload(tmp_path, mid)
    assert not quiet_candidates(combat, mid)


def test_nonowner_check_appears_when_dampening_scene_becomes_live(tmp_path):
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': 2, 'y': 6})
    turn(table, mid, ALLY)
    assert not quiet_candidates(combat, mid)
    turn(table, mid, OWNER)
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    assert quiet_candidates(combat, mid)
    assert reload(tmp_path, mid).state.zones
    assert quiet_candidates(combat, mid)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('issues,expected', [('mixed', 'NORMAL'), ('sound', 'ADVANTAGE')])
def test_auto_quiet_check_waits_for_gm_constraints_before_dice(tmp_path, monkeypatch, mode, issues, expected):
    combat, table, mid = fixture(tmp_path, [DAMPEN], ask=False, ally_position={'x': 2, 'y': 6})
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=mode)
    c = candidate(combat, mid, NAME)
    # Deterministic chosen legal action; native AI execution and external fact
    # transport still run, without a model or embedding transport.
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context))
    payload = {'actor_id': c.actor_id, 'decision_id': c.decision_id, 'state_version': c.state_version,
               'candidate_id': c.candidate_id, 'target_ids': list(c.target_ids), 'option_ids': [],
               'destination': None}
    token = combat.ai_validate(mid, payload)['validation_token'] if mode == 'API_AUTO' else None

    def send(answers):
        return (combat.ai_execute(mid, payload, token, reactions=answers) if token
                else table.auto_step(mid, 0, answers))

    before = reload(tmp_path, mid)
    result, answers = send([]), []
    for source, option in [('choice:needle.movement_issues', issues),
                           ('choice:needle.scene_gm_dc', '0'), ('choice:needle.scene_gm_dc', 'done')]:
        assert result['status'] == ('AWAITING_REACTION' if token else 'REACTION_REQUIRED'), result
        context = result['reaction_context'] if token else result['reaction']['context']
        assert context['reaction_source_id'] == source
        assert len(reload(tmp_path, mid).rolls) == len(before.rolls)
        answers.append({**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                        'selection': 'USE', 'option_ids': [option]})
        result = send(answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == expected
    assert check.payload['check_metadata']['issues'] == (['sound'] if issues == 'sound' else ['sound', 'sight'])
    assert check.payload['check_metadata']['source_actor_id'] == ALLY
    assert check.payload['dc'] == 0
    assert not any(((e.action_catalog.get(source).parameters or {}).get('typed') or {}).get('source') == DAMPEN
                   for source in e.state.actors[ALLY].action_ids if e.action_catalog.get(source))
