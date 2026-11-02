"""Native control-boundary coverage, sharing the source-backed Pulse fixture.

Only the primary AI action is selected by a fake controller. The ordinary
recipient consent/cleanup transport, payments, source facts and replay run.
"""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests import test_mgr_t15_gentle_source_pulse as pulse


@pytest.mark.parametrize('accept_cleanup', [False, True])
def test_manual_patient_chooses_cleanup_during_ai_pulse_turn(tmp_path, monkeypatch, accept_cleanup):
    combat, table, mid = pulse.setup(tmp_path, initial=1)
    penalty = pulse.native_penalty(combat, table, mid, tmp_path)
    pulse.classify(combat, mid, pulse.declaration(combat, mid, penalty))
    pulse.turn(table, mid, pulse.OWNER)
    combat.set_controller_mode(mid, actor_id=pulse.OWNER, controller_mode='LOCAL_AUTO')

    def choose(context):
        selected = next(c for c in context.legal_candidates
                        if c.display_name == 'Gentle Source Pulse' and c.target_ids == (pulse.ALLY,))
        return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

    monkeypatch.setattr(combat.controller, 'choose_primary_action', choose)
    prompts = pulse.use(combat, table, mid, 'Gentle Source Pulse', pulse.ALLY, auto=True, picks={
        'choice:willing.consent': 'accept', pulse.CLEANUP: penalty.modifier_id if accept_cleanup else None})
    for choice in ('choice:willing.consent', pulse.CLEANUP):
        owned = [p for p in prompts if p['context']['reaction_source_id'] == choice]
        assert len(owned) == 1 and owned[0]['context']['reactor_id'] == pulse.ALLY
        assert 'Gentle Source Pulse' in str(owned[0])
    engine = pulse.reload(tmp_path, mid)
    assert (penalty.modifier_id in engine.state.actors[pulse.ALLY].modifiers) is not accept_cleanup
    assert engine.state.actors[pulse.ALLY].temporary_hp == 3  # automatic giver's independent Vessel bonus
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == pulse.DEW]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1


def test_automatic_nonally_refuses_without_a_player_prompt(tmp_path):
    combat, table, mid = pulse.setup(tmp_path, initial=1)
    combat.set_controller_mode(mid, actor_id=pulse.FOE, controller_mode='LOCAL_AUTO')
    prompts = pulse.use(combat, table, mid, 'Gentle Source Pulse (willing creature)', pulse.FOE)
    assert not prompts
    engine = pulse.reload(tmp_path, mid)
    assert engine.state.actors[pulse.FOE].temporary_hp == 0
    assert engine.state.actors[pulse.OWNER].resources[pulse.DEW] == 0


def test_automatic_patient_selects_only_its_authorized_minor_penalty(tmp_path):
    combat, table, mid = pulse.setup(tmp_path, initial=1)
    penalty = pulse.native_penalty(combat, table, mid, tmp_path)
    pulse.classify(combat, mid, pulse.declaration(combat, mid, penalty))
    pulse.turn(table, mid, pulse.OWNER)
    combat.set_controller_mode(mid, actor_id=pulse.ALLY, controller_mode='LOCAL_AUTO')
    prompts = pulse.use(combat, table, mid, 'Gentle Source Pulse', pulse.ALLY, picks={pulse.SUPPORT: None})
    assert not any(p['context']['reactor_id'] == pulse.ALLY for p in prompts)
    engine = pulse.reload(tmp_path, mid)
    assert penalty.modifier_id not in engine.state.actors[pulse.ALLY].modifiers
    assert engine.state.actors[pulse.ALLY].temporary_hp == 1
