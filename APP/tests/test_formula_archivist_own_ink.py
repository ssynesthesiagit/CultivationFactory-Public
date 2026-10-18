"""Own spiritual ink must preserve the Common-check decision across table reloads."""
from copy import deepcopy
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from combat.table_procedure_seats import suggest
from combat.tabletop import TabletopError
from tests.test_formula_archivist_choices import with_paths
from tests.test_formula_archivist_table import install, cold, call, PID, COMMON, UNCOMMON, DISCOVERED

INK = 'tianxia.talent.talismans.talisman_master_s_ink'
LEGENDARY = 'tianxia.talent.talismans.legendary_talisman_crafting'
QI = 'tianxia.path.qi_cultivation'
INK_FACT = 'GM confirms the crafter used their own spiritual ink for this check.'


def test_reviewed_archivist_admission_and_half_time_survive_authority_integration(tmp_path):
    table = install(tmp_path)
    menu = table.procedures(PID)[0]
    assert {g['rank'] for g in menu['grants']} == {'Common', 'Uncommon'}
    assert menu['study_minutes'] == 240
    call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': 'admitted',
                           'provenance': 'GM discovery'}, 'admitted-discovery', gm=True)
    saved = cold(tmp_path).procedures(PID)[0]['projects'][0]
    assert saved['time_source'] == 'insight.formula-archivist'
    assert saved['required_minutes'] == 240


def ink_table(tmp_path, *, owned=True, qi=False, legendary=False):
    table = install(tmp_path, owner=False, cl=15 if legendary else 8)
    package = table.combat.combatant_library.install_root / PID / 'current.zip'
    with ZipFile(package) as archive:
        sheet = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    sheet['spheres_and_talents']['learned_talent_record_ids'] += (
        ([INK] if owned else []) + ([LEGENDARY] if legendary else []))
    with ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    if qi:
        with_paths(table, QI)
    return table


def checked(table, *, key='study-1', formula=DISCOVERED, own_ink=True, die=1):
    call(table, 'discover', {'formula_id': formula, 'discovery_id': key,
                           'provenance': 'GM-only discovery location'}, key, gm=True)
    call(table, 'study', {'discovery_id': key, 'minutes': table.procedures(PID)[0]['study_minutes']},
         key + '-elapsed', gm=True)
    payload = {'discovery_id': key, 'd20': die, 'roll_provenance': 'GM-only physical die receipt'}
    if own_ink:
        payload['own_ink_provenance'] = INK_FACT
    return call(table, 'check', payload, key + '-check', gm=True)['procedure']['projects'][-1]


def decision_form(table, key='study-1'):
    menu = table.procedures(PID)[0]
    form = next(f for f in menu['forms'] if f['action'] == 'resolve_failure' and
                f['defaults']['discovery_id'] == key)
    return menu, form


@pytest.mark.parametrize('first,decision,die,status', [
    (1, 'ink_reroll', 20, 'learned'), (9, 'ink_reroll', 1, 'destroyed'),
    (1, 'decline', None, 'destroyed'), (10, 'decline', None, 'failed'),
    (20, 'ink_reroll', 1, 'destroyed'), (20, 'decline', None, 'learned')])
def test_common_own_ink_choice_precedes_finalization_cold(tmp_path, first, decision, die, status):
    table = ink_table(tmp_path)
    project = checked(table, die=first)
    assert project['check']['total'] == first + 3
    assert project['check']['own_ink_provenance'] == INK_FACT
    assert project['status'] == 'awaiting_reroll'
    original = deepcopy(project['check'])
    table = cold(tmp_path)
    menu, form = decision_form(table)
    assert {o['value'] for o in form['fields'][0]['options']} == {'ink_reroll', 'decline'}
    label = next(o['label'] for o in form['fields'][0]['options'] if o['value'] == 'ink_reroll')
    assert 'Talisman Master' in label and 'long rest' in label and 'new result' in label
    assert menu['ink_reroll_available'] and not menu['qi_reroll_available']
    payload = {'discovery_id': 'study-1', 'decision': decision}
    if die is not None:
        payload.update(d20=die, roll_provenance='GM new physical die')
    before = table.buttons.get(PID)
    preview = call(table, 'resolve_failure', payload, 'decision', gm=True, preview=True)
    assert preview['procedure']['projects'][0]['status'] == status
    assert table.buttons.get(PID) == before
    result = call(table, 'resolve_failure', payload, 'decision', gm=True)
    assert call(table, 'resolve_failure', payload, 'decision', gm=True, revision=0) == result
    saved = result['procedure']['projects'][0]
    assert saved['status'] == status
    assert result['procedure'].get('ink_reroll_used', 0) == int(die is not None)
    assert result['procedure'].get('qi_reroll_used', 0) == 0
    if die is not None:
        assert saved['check']['first_roll'] == original
        assert saved['check']['total'] == original['total'] - original['d20'] + die
        assert saved['check']['reroll_source'] == INK
    else:
        assert saved['check'] == original
    table = cold(tmp_path)
    assert table.procedures(PID)[0]['projects'][0] == saved
    learned = table.combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']
    assert (DISCOVERED in learned) == (status == 'learned')
    with pytest.raises(TabletopError):
        call(table, 'resolve_failure', payload, 'second-decision', gm=True)
    if status == 'destroyed':
        with pytest.raises(TabletopError):
            call(table, 'retry', {'discovery_id': 'study-1'}, 'retry-destroyed', gm=True)


@pytest.mark.parametrize('case', ['unowned', 'uncommon', 'unconfirmed', 'exhausted'])
def test_ineligible_ink_never_offered_or_accepted_using_another_pending_reroll(tmp_path, case):
    table = ink_table(tmp_path, owned=case != 'unowned', qi=True)
    if case == 'exhausted':
        checked(table, key='first-common', formula=COMMON)
        call(table, 'resolve_failure', {'discovery_id': 'first-common', 'decision': 'ink_reroll',
             'd20': 1, 'roll_provenance': 'GM first reroll'}, 'spend-ink', gm=True)
        table = cold(tmp_path)
    project = checked(table, formula=UNCOMMON if case == 'uncommon' else DISCOVERED,
                      own_ink=case not in ('unconfirmed', 'unowned'))
    assert project['status'] == 'awaiting_reroll'  # Qi still protects this check.
    table = cold(tmp_path)
    _, form = decision_form(table)
    assert {o['value'] for o in form['fields'][0]['options']} == {'reroll', 'decline'}
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'ink_reroll',
             'd20': 20, 'roll_provenance': 'GM forged eligibility'}, 'invalid-ink', gm=True)
    assert cold(tmp_path).buttons.get(PID) == before


@pytest.mark.parametrize('owned,formula,own_ink', [(False, DISCOVERED, False),
    (True, UNCOMMON, True), (True, DISCOVERED, False)])
def test_ineligible_without_other_reroll_finalizes_normally(tmp_path, owned, formula, own_ink):
    table = ink_table(tmp_path, owned=owned)
    assert checked(table, formula=formula, own_ink=own_ink)['status'] == 'destroyed'
    assert not any(f['action'] == 'resolve_failure' for f in cold(tmp_path).procedures(PID)[0]['forms'])


def test_own_ink_use_is_separate_persistent_and_restored_only_by_a_new_completed_rest(tmp_path):
    table = ink_table(tmp_path, qi=True)
    checked(table, key='first-common', formula=COMMON)
    call(table, 'resolve_failure', {'discovery_id': 'first-common', 'decision': 'ink_reroll',
         'd20': 1, 'roll_provenance': 'GM new die'}, 'use-ink', gm=True)
    table = cold(tmp_path)
    assert table.procedures(PID)[0]['ink_reroll_used'] == 1
    assert table.procedures(PID)[0]['qi_reroll_available']
    checked(table)
    with pytest.raises(TabletopError):
        call(table, 'long_rest', {'rest_id': 'night-1', 'provenance': 'GM completed rest'}, 'early-rest', gm=True)
    call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'reroll',
         'd20': 1, 'roll_provenance': 'GM Qi new die'}, 'use-qi', gm=True)
    table = cold(tmp_path)
    menu = table.procedures(PID)[0]
    assert menu['ink_reroll_used'] == menu['qi_reroll_used'] == 1
    assert checked(table, key='exhausted', formula=COMMON)['status'] == 'destroyed'
    rest = {'rest_id': 'night-1', 'provenance': 'GM completed rest'}
    call(table, 'long_rest', rest, 'rest', gm=True)
    table = cold(tmp_path)
    assert table.procedures(PID)[0]['ink_reroll_available']
    assert table.procedures(PID)[0]['qi_reroll_available']
    checked(table, key='restored', formula=COMMON)
    call(table, 'resolve_failure', {'discovery_id': 'restored', 'decision': 'ink_reroll',
         'd20': 1, 'roll_provenance': 'GM new die after rest'}, 'use-again', gm=True)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'long_rest', rest, 'same-night', gm=True)
    assert cold(tmp_path).buttons.get(PID) == before


def test_non_qi_owner_can_restore_ink_without_restoring_an_unowned_path(tmp_path):
    table = ink_table(tmp_path)
    checked(table)
    call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'ink_reroll',
         'd20': 1, 'roll_provenance': 'GM new die'}, 'use', gm=True)
    table = cold(tmp_path)
    assert any(f['action'] == 'long_rest' for f in table.procedures(PID)[0]['forms'])
    call(table, 'long_rest', {'rest_id': 'night-1', 'provenance': 'GM completed rest'}, 'rest', gm=True)
    menu = cold(tmp_path).procedures(PID)[0]
    assert menu['ink_reroll_available'] and not menu['qi_reroll_available']


@pytest.mark.parametrize('decision', ['ink_reroll', 'reroll', 'paid_reroll'])
def test_each_reroll_spends_only_its_own_allowance_and_preserves_modifiers(tmp_path, decision):
    table = ink_table(tmp_path, qi=True, legendary=True)
    call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': 'study-1',
                           'provenance': 'GM discovery'}, 'discover', gm=True)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 480}, 'study', gm=True)
    first = call(table, 'check', {'discovery_id': 'study-1', 'd20': 4, 'roll_provenance': 'GM die',
                 'own_ink_provenance': INK_FACT, 'paid_cp': 2, 'payment_provenance': 'GM original 2 CP',
                 'tool_name': 'Calligraphy tools', 'tool_provenance': 'GM proficient tool'}, 'check', gm=True)
    original = first['procedure']['projects'][0]['check']
    assert original['total'] == 12
    payload = {'discovery_id': 'study-1', 'decision': decision, 'd20': 1, 'roll_provenance': 'GM new die'}
    if decision == 'paid_reroll':
        payload.update(paid_cp=5, payment_provenance='GM separate reroll payment')
    result = call(table, 'resolve_failure', payload, 'decision', gm=True)['procedure']
    assert result.get('ink_reroll_used', 0) == int(decision == 'ink_reroll')
    assert result.get('qi_reroll_used', 0) == int(decision == 'reroll')
    project = cold(tmp_path).procedures(PID)[0]['projects'][0]
    assert project['status'] == 'destroyed' and project['check']['total'] == 9
    assert project['check']['first_roll'] == original
    assert project['check']['paid_cp'] == 2 and project['check']['tool_bonus'] == 3
    assert ('reroll_payment' in project['check']) == (decision == 'paid_reroll')


def test_successful_ink_check_cannot_unlock_failed_check_only_rerolls(tmp_path):
    table = ink_table(tmp_path, qi=True, legendary=True)
    assert checked(table, die=20)['status'] == 'awaiting_reroll'
    _, form = decision_form(table)
    assert {o['value'] for o in form['fields'][0]['options']} == {'ink_reroll', 'decline'}
    before = table.buttons.get(PID)
    for decision in ('reroll', 'paid_reroll'):
        payload = {'discovery_id': 'study-1', 'decision': decision, 'd20': 1, 'roll_provenance': 'GM new die'}
        if decision == 'paid_reroll':
            payload.update(paid_cp=5, payment_provenance='GM payment')
        with pytest.raises(TabletopError):
            call(table, 'resolve_failure', payload, decision, gm=True)
    assert cold(tmp_path).buttons.get(PID) == before


@pytest.mark.parametrize('kind', ['local', 'd1'])
def test_all_rerolls_reach_human_and_model_without_sending_physical_facts(tmp_path, kind):
    table = ink_table(tmp_path, qi=True, legendary=True)
    checked(table)
    menu, form = decision_form(table)
    options = form['fields'][0]['options']
    assert {o['value'] for o in options} == {'ink_reroll', 'reroll', 'paid_reroll', 'decline'}
    prompts = []
    for option in options:
        def transport(settings, prompt):
            prompts.append(prompt)
            if kind == 'd1':
                return next(line[0] for line in prompt.splitlines() if ') ' in line and option['label'] in line), {}
            return json.dumps({'decision': option['value']}), {}
        seats = SimpleNamespace(registry=SimpleNamespace(load=lambda: {'fake': {'kind': kind}}),
                                suggest_preparation=transport)
        before = table.buttons.get(PID)
        result = suggest(table, seats, PID, menu['id'], form['id'], menu['revision'], 'fake')
        assert result['values'] == {'decision': option['value']}
        assert table.buttons.get(PID) == before
    for prompt in prompts:
        assert all(o['label'] in prompt for o in options)
        assert INK_FACT not in prompt and 'GM-only' not in prompt and 'own_ink_provenance' not in prompt


@pytest.mark.parametrize('fact,gm', [('', True), (True, True), (1, True), ('GM ink', False)])
def test_own_ink_confirmation_is_a_validated_gm_fact(tmp_path, fact, gm):
    table = ink_table(tmp_path)
    call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': 'study-1',
                           'provenance': 'GM discovery'}, 'discover', gm=True)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 480}, 'study', gm=True)
    form = next(f for f in table.procedures(PID)[0]['forms'] if f['action'] == 'check')
    field = next(f for f in form['fields'] if f['name'] == 'own_ink_provenance')
    assert field['optional'] and not field.get('seat_choice') and form['gm']
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die',
                             'own_ink_provenance': fact}, 'invalid', gm=gm)
    assert cold(tmp_path).buttons.get(PID) == before
