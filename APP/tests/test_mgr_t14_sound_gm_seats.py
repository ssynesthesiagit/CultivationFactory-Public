"""Automatic and model-selected Sound methods keep the GM-adjudicated route."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests.worker2_support import OWNER, fixture, candidate, reload
from tests.test_mgr_t14_sound_read import READ


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_seat_can_choose_gm_dc_with_perceived_opponents(tmp_path, monkeypatch, mode):
    combat, table, mid = fixture(tmp_path, [READ], named=True, ask=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    c = candidate(combat, mid, 'Read the Vibration')
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context))
    original = combat.controller.choose_reaction
    method_menus = []
    from combat.reaction_menu import ReactionMenuProbe
    original_answer = ReactionMenuProbe.answer
    discovered_gm_prompts = []

    def discover(probe, context, engine=None):
        if context.reaction_source_id == 'choice:needle.scene_gm_dc':
            # Main's menu discovery needs the preview engine for attack/packet
            # identity; Sound must keep supplying it when a GM fact pauses AI.
            assert engine is not None
            discovered_gm_prompts.append(context.checkpoint)
        return original_answer(probe, context, engine)

    monkeypatch.setattr(ReactionMenuProbe, 'answer', discover)

    def choose(context):
        if context.reaction_source_id == 'choice:needle.vibration_method':
            method_menus.append(set(context.extension_choice.option_ids))
            assert method_menus[-1] == {'gm_dc', 'stealth', 'sleight', 'perception', 'cultivation'}
            context = context.model_copy(update={'extension_choice': context.extension_choice.model_copy(
                update={'preferred_option_ids': ('gm_dc',)})})
        return original(context)

    monkeypatch.setattr(combat.controller, 'choose_reaction', choose)
    payload = {'actor_id': c.actor_id, 'decision_id': c.decision_id, 'state_version': c.state_version,
               'candidate_id': c.candidate_id, 'target_ids': list(c.target_ids), 'option_ids': [],
               'destination': None}
    # Exercise the native model-intent validator and executor with a fixed
    # selected intent. There is no provider, embedding client or network call.
    token = combat.ai_validate(mid, payload)['validation_token'] if mode == 'API_AUTO' else None

    def send(answers):
        return (combat.ai_execute(mid, payload, token, reactions=answers) if token
                else table.auto_step(mid, 0, answers))

    before = reload(tmp_path, mid)
    result = send([])
    answers = []
    for digit in ('0', 'done'):
        assert result['status'] == ('AWAITING_REACTION' if token else 'REACTION_REQUIRED'), result
        context = result['reaction_context'] if token else result['reaction']['context']
        assert context['reaction_source_id'] == 'choice:needle.scene_gm_dc'
        # The combined merge must discover the external-fact menu on both
        # native API and table auto paths, without treating it as an AI choice.
        assert context['checkpoint'] in discovered_gm_prompts
        assert len(reload(tmp_path, mid).rolls) == len(before.rolls)
        answers.append({**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                        'selection': 'USE', 'option_ids': [digit]})
        result = send(answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['check_metadata']['method'] == 'gm_dc'
    assert check.payload['dc'] == 0 and check.payload['success']
    assert method_menus and not check.payload.get('target')
    assert not e.state.actors[OWNER].action_available
