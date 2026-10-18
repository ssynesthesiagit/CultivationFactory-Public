"""Real table caller/cold-sheet regressions, with explicit physical-table facts.

The small installed package is a compiler harness, not an end-to-end Factory
acquisition certificate. Source selection/ASI contracts are checked separately.
No server, browser, model client or private character data is used.
"""
from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.test_factory_combat_compiler import SHEET

ROOT = Path(__file__).resolve().parents[1]
PID = 'aaaaaaaa'
ARCHIVIST = 'insight.formula-archivist'
SPHERE = 'tianxia.sphere.talismans'
ADVANCED = 'tianxia.talent.talismans.advanced_talisman_crafting'
NAMESPACE = 'talisman_formulae'
COMMON = 'tianxia.talent.talismans.message_talisman'
UNCOMMON = 'tianxia.talent.talismans.binding_talisman'
DISCOVERED = 'tianxia.talent.talismans.healing_talisman'


def install(tmp_path, *, owner=True, sphere=True, advanced=True, cl=8, god_body=False):
    sheet = deepcopy(SHEET)
    sheet['identity'].update(cultivation_level=cl, proficiency_bonus=3)
    sheet['spheres_and_talents'] = {
        'sphere_record_ids': [SPHERE] if sphere else [],
        'learned_talent_record_ids': ([ADVANCED] if advanced else []) +
                                    (['tianxia.talent.talismans.talisman_god_body'] if god_body else []),
        'cultivation_insight_record_ids': [ARCHIVIST] if owner else [],
    }
    combat = CombatService(ROOT, tmp_path)
    package = combat.combatant_library.install_root / PID / 'current.zip'
    package.parent.mkdir(parents=True)
    with ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    return TabletopService(combat, tmp_path)


def cold(tmp_path):
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path)


def call(table, action, payload, key, *, gm=False, preview=False, revision=None):
    if revision is None:
        state = (table.buttons.get(PID).get('advancement') or {}).get('procedures', {}).get(NAMESPACE, {})
        revision = state.get('revision', 0)
    return table.procedure(PID, NAMESPACE, action, payload, revision, key, gm=gm, preview=preview)


def discover(table, name='study-1'):
    return call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': name,
                                  'provenance': 'GM confirms a Healing Talisman found during the table scene.'}, name, gm=True)


def test_additional_formula_choices_persist_and_compile_without_crafting(tmp_path):
    table = install(tmp_path)
    [menu] = table.procedures(PID)
    assert [row['rank'] for row in menu['grants']] == ['Common', 'Uncommon']
    # All eleven printed Common/Uncommon formula rows, independent of the
    # provider's catalog implementation; higher/Secret ranks are excluded.
    assert {row['id'] for grant in menu['grants'] for row in grant['options']} == {
        'tianxia.talent.talismans.' + suffix for suffix in (
            'ember_talisman', 'featherfall_talisman', 'healing_talisman', 'message_talisman',
            'purifying_talisman', 'revealing_talisman', 'shield_talisman', 'warding_talisman',
            'binding_talisman', 'ghost_warding_talisman', 'qi_storage_talisman')}
    before = table.buttons.get(PID)
    preview = call(table, 'choose', {'formula_id': COMMON}, 'common', preview=True)
    assert preview['status'] == 'PREVIEW' and table.buttons.get(PID) == before
    committed = call(table, 'choose', {'formula_id': COMMON}, 'common')
    assert call(table, 'choose', {'formula_id': COMMON}, 'common', revision=0) == committed
    table = cold(tmp_path)
    call(table, 'choose', {'formula_id': UNCOMMON}, 'uncommon')
    sheet = cold(tmp_path).combat._factory_owner_sheet(PID)
    assert {COMMON, UNCOMMON} <= set(sheet['spheres_and_talents']['learned_talent_record_ids'])
    assert cold(tmp_path).procedures(PID)[0]['grants'] == []
    with pytest.raises(TabletopError):
        call(table, 'choose', {'formula_id': DISCOVERED}, 'extra-common')
    bundle = compile_character(sheet, actor_id='actor:factory.' + PID)
    assert any(UNCOMMON in row['source_definition_id'] for row in bundle['action_catalog'])


@pytest.mark.parametrize('owner,sphere,advanced,cl', [(False, True, False, 8), (True, False, True, 8), (True, True, True, 5)])
def test_wrong_owner_prerequisites_are_inert(tmp_path, owner, sphere, advanced, cl):
    table = install(tmp_path, owner=owner, sphere=sphere, advanced=advanced, cl=cl)
    assert not any(row['grants'] for row in table.procedures(PID))
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'choose', {'formula_id': COMMON}, 'wrong-owner')
    assert table.buttons.get(PID) == before


@pytest.mark.parametrize('owner,minutes', [(True, 240), (False, 480)])
def test_actual_discovery_study_boundary_commit_cold_reload(tmp_path, owner, minutes):
    table = install(tmp_path, owner=owner)
    assert discover(table)['procedure']['projects'][0]['required_minutes'] == minutes
    before = table.buttons.get(PID)
    for invalid in (-1, 0, True, 1.5, minutes + 1):
        with pytest.raises(TabletopError):
            call(table, 'study', {'discovery_id': 'study-1', 'minutes': invalid}, 'invalid-' + str(invalid), gm=True)
    assert table.buttons.get(PID) == before
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': minutes - 1}, 'elapsed-1', gm=True)
    table = cold(tmp_path)
    assert table.procedures(PID)[0]['projects'][0]['status'] == 'studying'
    result = call(table, 'study', {'discovery_id': 'study-1', 'minutes': 1}, 'elapsed-2', gm=True)
    assert result['procedure']['projects'][0]['status'] == 'awaiting_crafting_check'
    receipts = result['procedure']['events']
    assert [event['revision'] for event in receipts] == [1, 2, 3]
    assert sum(event['payload']['minutes'] for event in receipts if event['action'] == 'study') == minutes
    assert all(len(event['source_sheet_sha256']) == 64 for event in receipts)
    assert DISCOVERED not in cold(tmp_path).combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']


@pytest.mark.parametrize('die,status', [(20, 'learned'), (10, 'failed'), (6, 'destroyed')])
def test_real_reported_check_derives_outcome_and_cold_knowledge(tmp_path, die, status):
    table = install(tmp_path)
    discover(table)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'elapsed', gm=True)
    result = call(table, 'check', {'discovery_id': 'study-1', 'd20': die,
                                  'roll_provenance': 'Physical d20 confirmed by GM.'}, 'check', gm=True)
    project = result['procedure']['projects'][0]
    # Harness Intelligence is 10; PB 3; Common formula DC 12 + 2.
    assert project['check']['total'] == die + 3
    assert project['status'] == status
    table = cold(tmp_path)
    known = table.combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']
    assert (DISCOVERED in known) == (status == 'learned')
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 20, 'roll_provenance': 'New die'}, 'reroll', gm=True)
    if status == 'failed':
        call(table, 'retry', {'discovery_id': 'study-1'}, 'retry', gm=True)
        assert cold(tmp_path).procedures(PID)[0]['projects'][0]['studied_minutes'] == 0


def test_talisman_god_body_advantage_uses_highest_physical_die_and_persists(tmp_path):
    table = install(tmp_path, cl=15, god_body=True)
    menu = table.procedures(PID)[0]
    assert 'Talisman God Body gives you Advantage' in menu['check_requirement']
    discover(table)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'elapsed', gm=True)
    check_form = next(form for form in cold(tmp_path).procedures(PID)[0]['forms'] if form['action'] == 'check')
    assert {'d20', 'advantage_d20', 'roll_provenance'} <= {field['name'] for field in check_form['fields']}
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 3,
                              'roll_provenance': 'GM confirms the physical roll.'}, 'one-die', gm=True)
    result = call(table, 'check', {'discovery_id': 'study-1', 'd20': 3, 'advantage_d20': 18,
                                  'roll_provenance': 'GM confirms physical dice 3 and 18; higher is kept.'},
                  'advantaged-check', gm=True)
    project = result['procedure']['projects'][0]
    assert project['check']['d20'] == project['check']['kept_d20'] == 18
    assert project['check']['advantage_d20'] == 18
    assert project['check']['total'] == 21
    assert project['status'] == 'learned'
    cold_project = cold(tmp_path).procedures(PID)[0]['projects'][0]
    assert cold_project['check'] == project['check']


def test_external_facts_and_stale_revisions_cannot_change_state(tmp_path):
    table = install(tmp_path)
    with pytest.raises(TabletopError):
        call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': 'no-source'}, 'bad-discovery', gm=True)
    discover(table)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'not-gm')
    with pytest.raises(TabletopError):
        call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'stale', gm=True, revision=0)
    with pytest.raises(TabletopError):
        call(table, 'discover', {'formula_id': COMMON, 'discovery_id': 'x', 'provenance': 'GM'}, 'study-1', gm=True)
    assert table.buttons.get(PID) == before


def test_untracked_paid_cp_requires_external_receipt_and_is_not_invented(tmp_path):
    table = install(tmp_path)
    discover(table)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'elapsed', gm=True)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 8, 'roll_provenance': 'GM die', 'paid_cp': 3}, 'no-payment', gm=True)
    assert table.buttons.get(PID) == before
    result = call(table, 'check', {'discovery_id': 'study-1', 'd20': 8, 'roll_provenance': 'GM die', 'paid_cp': 3,
                                 'payment_provenance': 'GM confirms 3 CP paid at the physical table.'}, 'paid', gm=True)
    assert result['procedure']['projects'][0]['check']['total'] == 14
    assert result['procedure']['projects'][0]['status'] == 'learned'


def test_unrelated_stale_advancement_cannot_erase_committed_procedure(tmp_path):
    from combat.table_advance import normalized
    table = install(tmp_path)
    old = normalized(table.buttons.get(PID).get('advancement'))
    call(table, 'choose', {'formula_id': COMMON}, 'common')
    old['talents'].append({'id': ADVANCED})
    table.buttons.save_advancement(PID, old)
    assert COMMON in cold(tmp_path).combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']


@pytest.mark.parametrize('key,value', [('tool_name', 0.0), ('tool_provenance', False), ('payment_provenance', [])])
def test_malformed_external_facts_never_persist(tmp_path, key, value):
    table = install(tmp_path)
    discover(table)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'elapsed', gm=True)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 20,
                             'roll_provenance': 'GM physical die', key: value}, 'malformed', gm=True)
    assert table.buttons.get(PID) == before
