"""Coagulate ends the chosen ordinary wound through real consent and table use."""
from tests.test_mgr_t14_clinical_native import (
    A, B, game, anatomy, exposure, start, engine, use, clinical,
    final_native_mechanical_replay,
)


def test_clinical_source_treatment_keeps_the_helpful_effect_contract():
    from combat.effect_harm import classify_effect
    for operation, category in [('coagulate','ordinary_bleeding'),('purify','disease')]:
        assert classify_effect({'type':'clinical_treatment','operation':operation,'category':category}) is False


def test_coagulate_ends_the_selected_wound_and_preserves_another_source(tmp_path, monkeypatch):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('blood',))
    anatomy(world)
    first = exposure(world, label='First cut')
    second = exposure(world, label='Second cut')
    mid = start(cold, jid)
    use(cold, table, mid, 'Blood Thread: willing creature (any creature)')
    loaded = engine(cold, mid)
    selected = next(c.instance_id for c in clinical(loaded.state.actors[B], 'ordinary_bleeding')
                    if c.data['clinical']['source_instance'] == second)
    before = loaded.state.actors[A].resources['resource:core.qi']
    offered = []
    def choose(prompt, ids):
        if selected in ids:
            offered.extend(ids)
            return [selected]
        return ids[:1]
    use(cold, table, mid, 'Coagulate: End Bleeding (any creature)', choose=choose)
    loaded = engine(cold, mid)
    remaining = clinical(loaded.state.actors[B], 'ordinary_bleeding')
    assert selected in offered
    assert [c.data['clinical']['source_instance'] for c in remaining] == [first]
    assert loaded.state.actors[A].resources['resource:core.qi'] == before - 1


def test_automatic_practitioner_uses_only_known_wounds_and_patient_keeps_consent(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('blood',))
    anatomy(world)
    hidden = exposure(world, label='A wound known only to the patient', readers=[B])
    known = exposure(world, label='A wound identified by the practitioner')
    mid = start(cold, jid)
    use(cold, table, mid, 'Blood Thread: willing creature (any creature)')
    service = cold()
    service.set_controller_mode(mid, actor_id=A, controller_mode='LOCAL_AUTO')
    real = service.controller
    class TreatmentController:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates
                if c.display_name.startswith('Coagulate: End Bleeding') and B in c.target_ids)
            return ManualControllerAdapter(lambda _:(candidate.candidate_id,())).choose_primary_action(context)
        def __getattr__(self, name):return getattr(real, name)
    service.controller = TreatmentController()
    before = engine(cold, mid).state.model_dump(mode='json')
    paused = service.local_step(mid)
    assert paused['status'] == 'AWAITING_REACTION'
    prompt = paused['reaction_context']
    assert prompt['reactor_id'] == B and prompt['reaction_source_id'] == 'choice:willing.consent'
    assert engine(cold, mid).state.model_dump(mode='json') == before
    answer = {k:prompt[k] for k in ('checkpoint','reactor_id','reaction_source_id')}
    resumed = service.local_step(mid, reactions=[{**answer,'selection':'USE','option_ids':['accept']}])
    assert resumed['status'] == 'COMMITTED'
    loaded = engine(cold, mid)
    remaining = clinical(loaded.state.actors[B], 'ordinary_bleeding')
    assert [c.data['clinical']['source_instance'] for c in remaining] == [hidden]
    assert known not in [c.data['clinical']['source_instance'] for c in remaining]
    assert loaded.state.actors[A].resources['resource:core.qi'] == before['actors'][A]['resources']['resource:core.qi'] - 1
