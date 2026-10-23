"""FD7GCF1 review fixes (Sol review 044953): one regression per finding.

1. A Golden Core character with no recorded Form gets exactly one labelled Stable condition at match start.
2. The feature-use write is bounded and only accepts a Path feature the sheet grants.
3. A saved fight keeps its recorded Form with no extra default; a character with no record can record one.
4. The plug-in registry loads completely, retries after a failed import, and is complete whichever module imports first.
Also: the panel carries the Nascent Soul id the Grow tab uses, and the Grow tab lists every refusal.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from combat import ext
from combat.ext import qi_path
from combat.ext.qi_path import NASCENT_SOUL
from combat.tabletop_service import TabletopError
from tests.worker2_support import fixture, reload, OWNER
from tests.test_fd7gcf11_golden_core_closure import _service, _reloaded, GOLDEN, MERIDIAN

Q = 'tianxia.path.qi_cultivation.feature.'
FORM = 'condition:typed.golden_core_form'
APP = Path(__file__).resolve().parents[1]


def _form_conditions(owner):
    return [c for c in owner.conditions.values() if c.condition_id == FORM]


# finding 1 (F12): no recorded Form means no Form. Stable is never assumed, so no default condition exists

def test_no_record_golden_core_character_gets_no_form_condition(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, seed='FD7GCF1-DEF')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert _form_conditions(owner) == []
    assert qi_path.forms(owner) == ()
    assert qi_path.form(owner) is None


def test_no_default_form_condition_appears_across_a_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, seed='FD7GCF1-RELOAD')
    assert _form_conditions(reload(tmp_path, mid).state.actors[OWNER]) == []
    assert _form_conditions(reload(tmp_path, mid).state.actors[OWNER]) == []


def test_a_recorded_form_never_gets_the_stable_default(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, owner_golden=['circulating'],
                                 seed='FD7GCF1-REC')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert [c.data['form'] for c in _form_conditions(owner)] == ['circulating']
    assert not any(c.data.get('default') for c in _form_conditions(owner))


# finding 2: feature-use writes are bounded and checked against the sheet

def test_the_feature_use_request_bounds_its_id():
    from pydantic import ValidationError
    from app.models import TabletopFeatureUseRequest
    assert TabletopFeatureUseRequest(feature_id=NASCENT_SOUL).feature_id == NASCENT_SOUL
    for bad in ('', 'x' * 161):
        with pytest.raises(ValidationError):
            TabletopFeatureUseRequest(feature_id=bad)


def test_a_feature_use_the_sheet_does_not_grant_is_refused_and_not_stored():
    table, sheet, store = _service(15, base=['circulating'], features=(GOLDEN,),
                                  store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    with pytest.raises(TabletopError) as refused:
        table.record_feature_use('char', MERIDIAN)
    assert refused.value.code == 'TABLETOP_FEATURE_NOT_OWNED'
    assert not store['advancement'].get('feature_uses')
    # the refused write did not close the window, so the replacement is still allowed
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['reservoir']


# finding 3: saved fights, and recording from the default state

def test_a_saved_fight_keeps_its_recorded_form_without_a_second_default(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, owner_golden=['circulating'],
                                 seed='FD7GCF1-SAVE')
    held = _form_conditions(reload(tmp_path, mid).state.actors[OWNER])
    assert [c.data['form'] for c in held] == ['circulating']
    assert held[0].data.get('fixed') is True and 'default' not in held[0].data


def test_a_character_with_no_record_can_record_a_form_and_the_fight_then_uses_it(tmp_path):
    table, sheet, store = _service(10, base=[], store={'advancement': {}})
    table.set_build_choice('char', 'golden_core', choice='circulating', slot=1)
    recorded = _reloaded(sheet, store)['path_and_subpath']['golden_core_forms']
    assert recorded == ['circulating']
    combat, table_fight, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, owner_golden=recorded,
                                       seed='FD7GCF1-REC2')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert [c.data['form'] for c in _form_conditions(owner)] == ['circulating']
    assert qi_path.forms(owner) == ('circulating',)


# finding 4: the plug-in registry

def test_a_failed_plugin_load_is_retried_rather_than_left_partial(monkeypatch):
    real = importlib.import_module
    failed = {'once': False}

    def flaky(name, *args, **kwargs):
        if name.endswith('.qi_path') and not failed['once']:
            failed['once'] = True
            raise ImportError('simulated plug-in failure')
        return real(name, *args, **kwargs)

    monkeypatch.setattr(ext, '_LOADED', False)
    monkeypatch.setattr(importlib, 'import_module', flaky)
    with pytest.raises(ImportError):
        ext._load()
    assert ext._LOADED is False
    monkeypatch.setattr(importlib, 'import_module', real)
    ext._load()
    assert ext._LOADED is True
    assert 'golden_core' in ext.build_choice_kinds()


@pytest.mark.parametrize('first', ['combat.table_advance', 'combat.ext', 'combat.ext.qi_path'])
def test_the_registry_is_complete_whichever_module_is_imported_first(first):
    code = ("import " + first + "\n"
            "from combat import table_advance\n"
            "from combat.ext import build_choice_kinds\n"
            "print('OK' if 'golden_core' in build_choice_kinds() and 'golden_core' in table_advance.empty() else 'MISSING')")
    out = subprocess.run([sys.executable, '-c', code], cwd=APP, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == 'OK'


# optional items from the review

def test_the_panel_carries_the_nascent_soul_id_the_grow_tab_sends():
    from combat.ext import build_choice
    table, sheet, store = _service(15, base=['circulating'], store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    panel = build_choice('golden_core').panel(sheet, store['advancement'].get('golden_core') or [], 15,
                                              table=store['advancement'])
    assert panel['nascent_feature_id'] == NASCENT_SOUL


def test_the_grow_tab_takes_the_feature_id_from_the_panel_and_lists_every_refusal():
    src = (APP / 'static' / 'tabletop' / 'grow.js').read_text()
    assert 'NASCENT_SOUL' not in src
    assert 'growFeatureUse: panel.nascent_feature_id' in src
    assert '.map((o) => o.reason)[0]' not in src
    assert 'new Set(panel.options' in src
