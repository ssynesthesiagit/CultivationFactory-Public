"""R5 service regressions: current advancement, real forms and owned Path choices."""
from contextlib import contextmanager
from copy import deepcopy
import json
import threading
from zipfile import ZipFile

import pytest

from types import SimpleNamespace
from combat.table_procedure_seats import suggest
from combat.table_advance import normalized
from combat.tabletop import TabletopError
from tests.test_formula_archivist_table import (
    install, cold, call, discover, PID, NAMESPACE, ADVANCED, COMMON, DISCOVERED)


def with_paths(table, *paths, wisdom=18):
    package = table.combat.combatant_library.install_root / PID / 'current.zip'
    with ZipFile(package) as archive:
        sheet = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    sheet['path_and_subpath'] = {'path_record_ids': list(paths)}
    abilities = json.loads(sheet['ability_scores_and_statistics']['abilities'])
    next(a for a in abilities if a['ability'] == 'WIS')['score'] = wisdom
    sheet['ability_scores_and_statistics']['abilities'] = json.dumps(abilities)
    with ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))


def ready(table, key='study-1'):
    if key == 'study-1':
        discover(table, key)
    else:
        call(table, 'discover', {'formula_id': COMMON, 'discovery_id': key,
                                'provenance': 'GM confirms a Message Talisman discovered in play'}, key, gm=True)
    call(table, 'study', {'discovery_id': key, 'minutes': 240}, key + '-elapsed', gm=True)


@pytest.mark.parametrize('remove', [False, True])
def test_reverse_interleaving_never_erases_or_resurrects_advancement(tmp_path, monkeypatch, remove):
    table = install(tmp_path)
    other = cold(tmp_path)
    record = {'id': 'tianxia.talent.talismans.rapid_talisman'}
    initial = normalized(None)
    initial['talents'] = [record] if remove else []
    table.buttons.save_advancement(PID, initial)
    sheet_read, release, writer_started, writer_done = [threading.Event() for _ in range(4)]
    original = table.buttons.get
    reads = 0
    errors = []

    def pause_after_read(pid):
        nonlocal reads
        snapshot = original(pid)
        reads += 1
        # First read validates the ID. The second is the advancement snapshot:
        # the old dispatcher reads it before its save lock; the fixed store
        # reads it while already holding the shared advancement transaction.
        if reads == 2:
            sheet_read.set()
            assert release.wait(5)
        return snapshot

    monkeypatch.setattr(table.buttons, 'get', pause_after_read)
    def procedure():
        try:
            call(table, 'choose', {'formula_id': COMMON}, 'concurrent', revision=0)
        except BaseException as exc:
            errors.append(exc)
    def advancement():
        try:
            updated = normalized(other.buttons.get(PID).get('advancement'))
            updated['talents'] = [] if remove else [record]
            writer_started.set()
            other.buttons.save_advancement(PID, updated)
            writer_done.set()
        except BaseException as exc:
            errors.append(exc)
    procedure_thread = threading.Thread(target=procedure)
    writer_thread = threading.Thread(target=advancement)
    procedure_thread.start()
    try:
        assert sheet_read.wait(5)
        writer_thread.start()
        assert writer_started.wait(5)
        # Old code lets the ordinary save complete here, then erases it with
        # the paused procedure snapshot. The shared transaction blocks it.
        writer_done.wait(.15)
    finally:
        release.set()
        procedure_thread.join(5)
        if writer_thread.ident:
            writer_thread.join(5)
    assert not errors and not procedure_thread.is_alive() and not writer_thread.is_alive()
    saved = cold(tmp_path).buttons.get(PID)['advancement']
    assert saved['talents'] == ([] if remove else [record])
    assert saved['procedures'][NAMESPACE]['choices'][0]['formula_id'] == COMMON


def test_ownership_is_validated_after_waiting_for_current_advancement(tmp_path, monkeypatch):
    table = install(tmp_path, advanced=False)
    grant = normalized(None)
    grant['talents'] = [{'id': ADVANCED}]
    table.buttons.save_advancement(PID, grant)
    ready(table)
    # A grant is removed before this command can enter its transaction. The
    # sheet must be loaded after acquisition, rather than cached before waiting.
    original = table.buttons.advancement_transaction
    @contextmanager
    def remove_before_lock(pid, **kwargs):
        saved = normalized(table.buttons.get(pid)['advancement'])
        saved['talents'] = []
        with original(pid) as current:
            current.clear()
            current.update(saved)
        with original(pid, **kwargs) as current:
            yield current
    monkeypatch.setattr(table.buttons, 'advancement_transaction', remove_before_lock)
    with pytest.raises(TabletopError, match='Advanced Talisman Crafting'):
        call(table, 'check', {'discovery_id': 'study-1', 'd20': 20, 'roll_provenance': 'GM die'}, 'removed', gm=True)
    assert cold(tmp_path).procedures(PID)[0]['projects'][0]['status'] == 'awaiting_crafting_check'


def test_procedure_commit_retains_independent_character_edits_during_validation(tmp_path, monkeypatch):
    table = install(tmp_path)
    other = cold(tmp_path)
    table.buttons.save_display_name(PID, 'Original table name')
    original = table.combat._factory_owner_sheet
    def rename_after_read(pid):
        sheet = original(pid)
        # This writer updates a different field and does not take the
        # advancement lock. Its completed edit must survive the procedure.
        other.buttons.save_display_name(pid, 'Name changed while choosing')
        return sheet
    monkeypatch.setattr(table.combat, '_factory_owner_sheet', rename_after_read)
    call(table, 'choose', {'formula_id': COMMON}, 'choice-and-rename')
    saved = cold(tmp_path).buttons.get(PID)
    assert saved['display_name'] == 'Name changed while choosing'
    assert saved['advancement']['procedures'][NAMESPACE]['choices'][0]['formula_id'] == COMMON


@pytest.mark.parametrize('ability,total,status', [('INT', 10, 'failed'), ('WIS', 14, 'learned')])
def test_spirit_awakening_uses_the_owned_chosen_ability_on_service(tmp_path, ability, total, status):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.spirit_awakening')
    ready(table)
    assert {a['value'] for a in table.procedures(PID)[0]['check_abilities']} == {'INT', 'WIS'}
    result = call(table, 'check', {'discovery_id': 'study-1', 'ability': ability, 'd20': 7,
                                  'roll_provenance': 'GM observed 7'}, 'ability', gm=True)
    project = result['procedure']['projects'][0]
    assert project['check']['total'] == total and project['status'] == status
    assert (DISCOVERED in cold(tmp_path).combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']) == (status == 'learned')


def test_unowned_wisdom_is_rejected_without_writing(tmp_path):
    table = install(tmp_path)
    ready(table)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'check', {'discovery_id': 'study-1', 'ability': 'WIS', 'd20': 7,
                              'roll_provenance': 'GM observed 7'}, 'unowned', gm=True)
    assert table.buttons.get(PID) == before


@pytest.mark.parametrize('decision,new_die,status', [('reroll', 20, 'learned'), ('reroll', 1, 'destroyed'), ('decline', None, 'destroyed')])
def test_qi_failure_waits_for_owner_then_rerolls_or_declines_cold(tmp_path, decision, new_die, status):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.qi_cultivation')
    ready(table)
    result = call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM first die'}, 'first', gm=True)
    assert result['procedure']['projects'][0]['status'] == 'awaiting_reroll'
    table = cold(tmp_path)
    payload = {'discovery_id': 'study-1', 'decision': decision}
    if new_die:
        payload.update(d20=new_die, roll_provenance='GM second die')
    before = table.buttons.get(PID)
    assert call(table, 'resolve_failure', payload, 'decision', gm=True, preview=True)['procedure']['projects'][0]['status'] == status
    assert table.buttons.get(PID) == before
    result = call(table, 'resolve_failure', payload, 'decision', gm=True)
    assert result['procedure']['projects'][0]['status'] == status
    assert result['procedure'].get('qi_reroll_used', 0) == int(decision == 'reroll')
    assert call(table, 'resolve_failure', payload, 'decision', gm=True, revision=3) == result
    assert cold(tmp_path).procedures(PID)[0]['projects'][0]['status'] == status
    if decision == 'reroll':
        assert result['procedure']['projects'][0]['check']['first_roll']['d20'] == 1
        ready(table, 'study-2')
        used = call(table, 'check', {'discovery_id': 'study-2', 'd20': 1, 'roll_provenance': 'GM die'}, 'second', gm=True)
        assert used['procedure']['projects'][1]['status'] == 'destroyed'
        rest = {'rest_id': 'night-1', 'provenance': 'GM confirms completed long rest'}
        call(table, 'long_rest', rest, 'rest', gm=True)
        assert cold(tmp_path).procedures(PID)[0]['qi_reroll_available']
        with pytest.raises(TabletopError):
            call(table, 'long_rest', rest, 'same-rest-new-id', gm=True)


@pytest.mark.parametrize('kind', ['local', 'd1'])
def test_model_and_builtin_preparation_receive_every_owned_option_and_no_facts(tmp_path, kind):
    table = install(tmp_path)
    menu = table.procedures(PID)[0]
    assert {g['rank'] for g in menu['grants']} == {'Common', 'Uncommon'}
    prompts = []
    def provider(settings, prompt):
        assert settings['vision'] is False
        if kind == 'd1':
            prompts.append(prompt)
            return [line[0] for line in prompt.splitlines() if ') ' in line][-1], {}
        frame = json.loads(prompt)
        prompts.append(frame)
        return json.dumps({f['name']: f['options'][-1]['value'] for f in frame['fields']}), {}
    seats = SimpleNamespace(registry=SimpleNamespace(load=lambda: {'fake': {'id': 'fake', 'kind': kind, 'vision': True}}),
                            suggest_preparation=provider)
    for grant in menu['grants']:
        form_id = 'grant-' + grant['rank']
        result = suggest(table, seats, PID, NAMESPACE, form_id, menu['revision'], 'fake')
        assert result['values']['formula_id'] == grant['options'][-1]['id']
        if kind == 'd1':
            assert all(o['name'] in prompts[-1] for o in grant['options'])
        else:
            assert {o['value'] for o in prompts[-1]['fields'][0]['options']} == {o['id'] for o in grant['options']}
        assert 'provenance' not in json.dumps(prompts[-1]) and 'actors' not in prompts[-1]
        assert suggest(table, seats, PID, NAMESPACE, form_id, menu['revision'], 'builtin')['values']['formula_id'] in {o['id'] for o in grant['options']}
    assert not table.buttons.get(PID).get('advancement')  # suggestions are previews
    with pytest.raises(TabletopError):
        suggest(table, seats, PID, NAMESPACE, 'grant-Common', 99, 'fake')
    for provider_id in ('builtin', 'fake'):
        with pytest.raises(TabletopError, match='actual table facts'):
            suggest(table, seats, PID, NAMESPACE, 'discover', menu['revision'], provider_id)


def test_forms_cover_complete_grants_and_study_decisions(tmp_path):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.qi_cultivation', 'tianxia.path.spirit_awakening')
    menu = table.procedures(PID)[0]
    for grant in menu['grants']:
        form = next(f for f in menu['forms'] if f['id'] == 'grant-' + grant['rank'])
        assert {o['value'] for o in form['fields'][0]['options']} == {o['id'] for o in grant['options']}
    ready(table)
    check = next(f for f in table.procedures(PID)[0]['forms'] if f['action'] == 'check')
    assert {o['value'] for o in check['fields'][0]['options']} == {'INT', 'WIS'}
    call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die'}, 'first', gm=True)
    pending = next(f for f in table.procedures(PID)[0]['forms'] if f['action'] == 'resolve_failure')
    assert {o['value'] for o in pending['fields'][0]['options']} == {'reroll', 'decline'}


@pytest.mark.parametrize('kind', ['local', 'd1'])
def test_check_and_reroll_suggestions_never_send_gm_project_labels(tmp_path, kind):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.qi_cultivation', 'tianxia.path.spirit_awakening')
    secret_label = 'GM-only sealed subject label'
    ready(table, secret_label)
    prompts = []
    def transport(settings, prompt):
        prompts.append(prompt)
        assert secret_label not in prompt
        assert 'Message Talisman' not in prompt
        if kind == 'd1':
            return next(line[0] for line in prompt.splitlines() if ') ' in line), {}
        frame = json.loads(prompt)
        return json.dumps({f['name']: f['options'][0]['value'] for f in frame['fields']}), {}
    seats = SimpleNamespace(registry=SimpleNamespace(load=lambda: {'fake': {'kind': kind}}),
                            suggest_preparation=transport)
    menu = table.procedures(PID)[0]
    form = next(f for f in menu['forms'] if f['action'] == 'check')
    suggest(table, seats, PID, NAMESPACE, form['id'], menu['revision'], 'fake')
    call(table, 'check', {'discovery_id': secret_label, 'd20': 1, 'roll_provenance': 'GM-only physical die receipt'},
         'failed-private-project', gm=True)
    menu = table.procedures(PID)[0]
    form = next(f for f in menu['forms'] if f['action'] == 'resolve_failure')
    suggest(table, seats, PID, NAMESPACE, form['id'], menu['revision'], 'fake')
    assert len(prompts) == 2
    assert all('GM-only physical die receipt' not in p for p in prompts)
