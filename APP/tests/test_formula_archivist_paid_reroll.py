"""Reviewed failure boundary: owned paid rerolls survive real table commits."""
from copy import deepcopy
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from combat.table_procedure_seats import suggest
from combat.tabletop import TabletopError
from tests.test_formula_archivist_choices import ready, with_paths
from tests.test_formula_archivist_table import install, cold, call, PID, DISCOVERED

LEGENDARY = 'tianxia.talent.talismans.legendary_talisman_crafting'
QI = 'tianxia.path.qi_cultivation'


def legendary_table(tmp_path, qi='none', *, first_die=1):
    table = install(tmp_path, cl=15)
    if qi != 'none':
        with_paths(table, QI)
    package = table.combat.combatant_library.install_root / PID / 'current.zip'
    with ZipFile(package) as archive:
        sheet = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    sheet['spheres_and_talents']['learned_talent_record_ids'].append(LEGENDARY)
    with ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    if qi == 'exhausted':
        ready(table, 'spent-free-use')
        call(table, 'check', {'discovery_id': 'spent-free-use', 'd20': 1,
                             'roll_provenance': 'GM first die'}, 'free-failure', gm=True)
        call(table, 'resolve_failure', {'discovery_id': 'spent-free-use', 'decision': 'reroll',
                                       'd20': 1, 'roll_provenance': 'GM mandatory new die'}, 'free-use', gm=True)
    ready(table)
    # Original bonus payment and proficient tool are independent of reroll cost.
    result = call(table, 'check', {'discovery_id': 'study-1', 'd20': first_die, 'ability': 'INT',
                                  'roll_provenance': 'GM original die', 'paid_cp': 2,
                                  'payment_provenance': 'GM original 2 CP payment',
                                  'tool_name': 'Calligraphy tools', 'tool_provenance': 'GM confirms proficient tools'},
                  'paid-failure', gm=True)
    return table, result['procedure']['projects'][-1]


@pytest.mark.parametrize('qi', ['none', 'exhausted'])
@pytest.mark.parametrize('decision,die,status', [('paid_reroll', 20, 'learned'),
                                               ('paid_reroll', 1, 'destroyed'),
                                               ('decline', None, 'destroyed')])
def test_paid_failure_choice_before_destruction_cold(tmp_path, qi, decision, die, status):
    first_die = 4 if decision == 'paid_reroll' and die == 1 else 1
    table, project = legendary_table(tmp_path, qi, first_die=first_die)
    assert project['check']['total'] == first_die + 8
    assert project['status'] == 'awaiting_reroll'
    original = deepcopy(project['check'])
    table = cold(tmp_path)
    menu = table.procedures(PID)[0]
    assert not menu['qi_reroll_available'] and menu['paid_reroll_available']
    form = next(f for f in menu['forms'] if f['action'] == 'resolve_failure' and f['defaults']['discovery_id'] == 'study-1')
    assert {o['value'] for o in form['fields'][0]['options']} == {'paid_reroll', 'decline'}
    assert '5 CP' in next(o['label'] for o in form['fields'][0]['options'] if o['value'] == 'paid_reroll')
    payload = {'discovery_id': 'study-1', 'decision': decision}
    if die is not None:
        payload.update(d20=die, roll_provenance='GM mandatory new die', paid_cp=5,
                       payment_provenance='GM confirms 5 CP already paid for Legendary reroll')
    before = table.buttons.get(PID)
    preview = call(table, 'resolve_failure', payload, 'paid-decision', gm=True, preview=True)
    assert preview['procedure']['projects'][-1]['status'] == status
    assert table.buttons.get(PID) == before
    result = call(table, 'resolve_failure', payload, 'paid-decision', gm=True)
    saved = result['procedure']['projects'][-1]
    assert saved['status'] == status
    assert call(table, 'resolve_failure', payload, 'paid-decision', gm=True, revision=0) == result
    assert result['procedure'].get('qi_reroll_used', 0) == int(qi == 'exhausted')
    if die is not None:
        check = saved['check']
        assert check['first_roll'] == original
        assert check['total'] == original['total'] - original['d20'] + die
        assert check['paid_cp'] == 2 and check['tool_bonus'] == 3
        assert check['reroll_source'] == LEGENDARY
        assert check['reroll_payment'] == {'paid_cp': 5, 'payment_provenance': payload['payment_provenance']}
    else:
        assert saved['check'] == original
    table = cold(tmp_path)
    assert table.procedures(PID)[0]['projects'][-1] == saved
    learned = table.combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']
    assert (DISCOVERED in learned) == (status == 'learned')
    with pytest.raises(TabletopError):
        call(table, 'resolve_failure', payload, 'second-decision', gm=True)


@pytest.mark.parametrize('change', [{'paid_cp': 4}, {'paid_cp': True}, {'payment_provenance': ''},
                                    {'payment_provenance': None}, {'gm': False}])
def test_paid_reroll_requires_exact_external_payment_without_writing(tmp_path, change):
    table, project = legendary_table(tmp_path)
    assert project['status'] == 'awaiting_reroll'
    payload = {'discovery_id': 'study-1', 'decision': 'paid_reroll', 'd20': 20,
               'roll_provenance': 'GM new die', 'paid_cp': 5, 'payment_provenance': 'GM confirms 5 CP paid'}
    payload.update({k: v for k, v in change.items() if k != 'gm'})
    if payload.get('payment_provenance') is None:
        payload.pop('payment_provenance')
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'resolve_failure', payload, 'invalid-payment', gm=change.get('gm', True))
    assert cold(tmp_path).buttons.get(PID) == before


def test_both_rerolls_reach_human_and_ai_without_spending_free_use(tmp_path):
    table, project = legendary_table(tmp_path, 'available')
    assert project['status'] == 'awaiting_reroll'
    menu = table.procedures(PID)[0]
    form = next(f for f in menu['forms'] if f['action'] == 'resolve_failure')
    assert {o['value'] for o in form['fields'][0]['options']} == {'reroll', 'paid_reroll', 'decline'}
    for kind in ('local', 'd1'):
        prompts = []
        def transport(settings, prompt):
            prompts.append(prompt)
            if kind == 'd1':
                return next(line[0] for line in prompt.splitlines() if ') ' in line and 'Legendary Talisman Crafting' in line), {}
            return json.dumps({'decision': 'paid_reroll'}), {}
        seats = SimpleNamespace(registry=SimpleNamespace(load=lambda: {'fake': {'kind': kind}}), suggest_preparation=transport)
        result = suggest(table, seats, PID, menu['id'], form['id'], menu['revision'], 'fake')
        assert result['values'] == {'decision': 'paid_reroll'}
        assert '5 CP' in prompts[0] and 'payment_provenance' not in prompts[0]
    result = call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'paid_reroll', 'd20': 20,
                  'roll_provenance': 'GM new die', 'paid_cp': 5, 'payment_provenance': 'GM confirms 5 CP paid'}, 'paid', gm=True)
    assert result['procedure'].get('qi_reroll_used', 0) == 0
    assert cold(tmp_path).procedures(PID)[0]['qi_reroll_available']


def test_unowned_paid_reroll_cannot_use_pending_free_choice(tmp_path):
    table = install(tmp_path)
    with_paths(table, QI)
    ready(table)
    call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die'}, 'failed', gm=True)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'paid_reroll', 'd20': 20,
             'roll_provenance': 'GM new die', 'paid_cp': 5, 'payment_provenance': 'GM confirms 5 CP paid'}, 'unowned', gm=True)
    assert table.buttons.get(PID) == before
