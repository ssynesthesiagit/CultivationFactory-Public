"""Review regressions through real session execution, table commits and cold replay."""
import json
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests.cw2_service_support import seal
from tests.test_a2_life import P, QI, OTHER, setup as base_setup, use, find, conditions
from tests.worker2_support import OWNER, ALLY, fixture, settle, reload


def setup(bundles):
    base_setup(bundles)
    for bundle, name in zip(bundles, ('Healer Mei', 'Patient Lin', 'Opponent Rui', 'Patient Jun')):
        bundle['actor_template']['display_name'] = name
        seal(bundle)


@pytest.mark.parametrize('base,price', [('Mend the Pulse', 1), ('Borrowed Breath', 0)])
@pytest.mark.parametrize('balance', [1, 100])
def test_restorative_empathic_signed_cost_and_affordability(tmp_path, base, price, balance):
    def prepare(bundles):
        setup(bundles)
        for resource in bundles[0]['actor_template']['resources']:
            if resource['resource_id'] == QI:
                resource['initial'] = balance
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [P+'restorative_mend', P+'empathic_transfer'], bundle_transform=prepare)
    use(combat, table, mid, 'Injury', ALLY)
    use(combat, table, mid, 'Poison', ALLY)
    e = reload(tmp_path, mid)
    before = e.state.actors[OWNER].resources[QI]
    rows = [c for c in e.legal_candidates() if c.target_ids == (ALLY,) and
            all(w in c.display_name for w in (base+' + Restorative Mend', '/ Purify', 'Remove Poisoned', 'Empathic Transfer'))]
    assert rows, 'Discounted treatment must remain affordable with only one CP'
    action = e.action_catalog[rows[0].source_definition_id]
    assert dict(action.costs).get(QI, 0) == price
    settle(table, mid, rows[0].candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[QI] == before-price
    assert 'condition:typed.poisoned' not in conditions(e, ALLY)
    assert 'condition:typed.poisoned' in conditions(e, OWNER)
    if base.startswith('Mend'):
        assert e.state.actors[ALLY].current_hp > 30
    else:
        assert e.state.actors[ALLY].current_hp == 30
        assert e.state.actors[ALLY].temporary_hp == 4


def assert_display(prompt, engine, action, recipient, *wording):
    assert prompt['action'] == action.display_name
    assert prompt['trigger_actor'] == engine.state.actors[OWNER].display_name
    assert prompt['affected'] == engine.state.actors[recipient].display_name
    assert prompt['by'] == engine.state.actors[recipient].display_name
    for text in wording:
        assert text in prompt['moment']
    for field in ('moment', 'action', 'affected', 'by', 'trigger_actor', 'reactor'):
        assert 'actor:' not in prompt[field]


@pytest.mark.parametrize('base,wording', [
    ('Read the Pulse', ('living pattern', 'Instantaneous', 'Pulse Seal')),
    ('Mend the Pulse', ('Hit Points', 'Instantaneous')),
    ('Borrowed Breath', ('Temporary HP', '1 hour', 'depleted')),
    ('Remove Poisoned', ('Purify the Pulse', 'Poisoned', 'Instantaneous')),
])
def test_group_prompt_names_actual_action_and_concrete_base_treatment(tmp_path, base, wording):
    combat, table, mid = fixture(tmp_path, [P+'shared_infirmary_hand'], extra_allies=1, bundle_transform=setup)
    for patient in (ALLY, OTHER):
        use(combat, table, mid, 'Injury', patient)
        use(combat, table, mid, 'Poison', patient)
    c = find(combat, mid, base, 'Shared Infirmary')
    e = reload(tmp_path, mid)
    action = e.action_catalog[c.source_definition_id]
    prompts = settle(table, mid, c.candidate_id, {'choice:needle.life_patients': OTHER, 'choice:needle.life_treatment': '3'})
    (tmp_path/'displayed-prompts.json').write_text(json.dumps(prompts, indent=2)+'\n')
    patients = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.life_patients')
    consent = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.life_patient_consent')
    assert_display(patients, e, action, ALLY, *wording, 'cultivation points')
    assert_display(consent, e, action, OTHER, *wording, 'no action or cultivation points')
    if base == 'Remove Poisoned':
        treatment = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.life_treatment')
        assert_display(treatment, e, action, OTHER, 'Purify the Pulse', 'Poisoned', 'Instantaneous', 'cultivation points')
    reload(tmp_path, mid)


@pytest.mark.parametrize('base,wording', [('Mend the Pulse', ('Hit Points', 'Instantaneous')),
                                        ('Borrowed Breath', ('Temporary HP', '1 hour'))])
def test_restorative_prompt_names_healing_trigger_and_purification(tmp_path, base, wording):
    combat, table, mid = fixture(tmp_path, [P+'restorative_mend'], bundle_transform=setup)
    use(combat, table, mid, 'Injury', ALLY)
    use(combat, table, mid, 'Poison', ALLY)
    c = find(combat, mid, base+' + Restorative Mend')
    e = reload(tmp_path, mid)
    prompts = settle(table, mid, c.candidate_id, {'choice:needle.life_treatment': '3'})
    (tmp_path/'displayed-prompts.json').write_text(json.dumps(prompts, indent=2)+'\n')
    treatment = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.life_treatment')
    assert_display(treatment, e, e.action_catalog[c.source_definition_id], ALLY,
                   *wording, 'Purify the Pulse', 'Poisoned', 'cultivation points')
    assert 'condition:typed.poisoned' not in conditions(reload(tmp_path, mid), ALLY)


@pytest.mark.parametrize('recipient_mode,accept', [('MANUAL', True), ('MANUAL', False), ('LOCAL_AUTO', True)])
def test_ai_healer_respects_patient_authority_and_commits_once(tmp_path, recipient_mode, accept):
    combat, table, mid = fixture(tmp_path, [P+'shared_infirmary_hand'], extra_allies=1, bundle_transform=setup)
    for patient in (ALLY, OTHER):
        use(combat, table, mid, 'Injury', patient)
    c = find(combat, mid, 'Mend the Pulse', 'Shared Infirmary')
    before = reload(tmp_path, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid, actor_id=OTHER, controller_mode=recipient_mode)
    # A supported controller adapter fixes the primary action under test;
    # automatic reactions retain the production controller's own policy.
    real_controller = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (c.candidate_id, ()),
        reaction_chooser=lambda context: real_controller.choose_reaction(context).decision)
    if recipient_mode == 'MANUAL':
        paused = table.auto_step(mid, 0)
        assert paused['status'] == 'REACTION_REQUIRED'
        p = paused['reaction']
        assert p['context']['reactor_id'] == OTHER
        assert p['context']['reaction_source_id'] == 'choice:needle.life_patient_consent'
        cold = reload(tmp_path, mid)
        assert cold.state.actors[ALLY].current_hp == 30
        assert cold.state.actors[OTHER].current_hp == 30
        assert cold.state.actors[OWNER].resources[QI] == before.state.actors[OWNER].resources[QI]
    prompts = settle(table, mid, c.candidate_id,
                     {'choice:needle.life_patient_consent': 'accept' if accept else None}, auto=True)
    e = reload(tmp_path, mid)
    consent = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.life_patient_consent']
    assert bool(consent) == (recipient_mode == 'MANUAL')
    assert all(p['context']['reactor_id'] == OTHER for p in consent)
    assert e.state.actors[ALLY].current_hp > 30
    assert (e.state.actors[OTHER].current_hp > 30) == accept
    assert e.state.actors[OWNER].resources[QI] == before.state.actors[OWNER].resources[QI]-2
    healed = [event for event in e.events[len(before.events):] if event.event_type == 'HEALING_APPLIED']
    assert sum(ALLY in event.target_ids for event in healed) == 1
    assert sum(OTHER in event.target_ids for event in healed) == int(accept)
