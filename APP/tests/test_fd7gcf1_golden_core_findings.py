"""FD7GCF1 review fixes for the Golden Core build choice.

Finding 1 (blocking): the core table service hardcoded a "golden_core" operation. The fix is a generic
set_build_choice(kind) that looks up the registered plug-in rule and stores the row it accepts.
Finding 2 (blocking): the CL15 replacement must also require a recorded successful breakthrough, and it stays one
replacement only.

No live server, model or embedding service is used; the service is built with a stub sheet and an in-memory store.
Each test fails on the pre-fix tree (the old service had no set_build_choice / record_breakthrough, and the old
CL15 rule accepted a replacement with no breakthrough).
"""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from combat import table_advance
from combat.ext import build_choice
from combat.tabletop_service import TabletopError, TabletopService

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = 'tianxia.path.qi_cultivation.feature.golden_core_form'


def _service(cl, base=(), advancement=None):
    sheet = {'identity': {'cultivation_level': cl},
             'path_and_subpath': {'golden_core_forms': list(base), 'path_feature_record_ids': [GOLDEN]}}
    store = {'advancement': advancement if advancement is not None else {}}
    table = object.__new__(TabletopService)
    table.combat = SimpleNamespace(_factory_owner_sheet=lambda _p, apply_table=False: copy.deepcopy(sheet))
    table.buttons = SimpleNamespace(
        get=lambda _p: store,
        save_advancement=lambda _p, record: store.__setitem__('advancement', record))
    table.advancement = lambda _p: {}
    return table, sheet, store


def _forms(sheet, store):
    return table_advance.apply(copy.deepcopy(sheet), store['advancement'], mechanics={})[
        'path_and_subpath']['golden_core_forms']


# Finding 1: the core dispatches any registered build-choice kind; it does not name golden_core.

def test_core_service_records_golden_core_through_the_generic_operation():
    table, sheet, store = _service(10)
    table.set_build_choice('char', 'golden_core', choice='stable', slot=1)
    assert _forms(sheet, store) == ['stable']


def test_core_service_refuses_an_unregistered_choice_kind():
    table, _sheet, store = _service(10)
    with pytest.raises(TabletopError) as error:
        table.set_build_choice('char', 'not_a_registered_kind', choice='stable', slot=1)
    assert error.value.code == 'TABLETOP_CHOICE_KIND'
    assert store['advancement'] == {}


def test_core_service_routes_any_registered_kind_to_its_own_rule(monkeypatch):
    """The core passes the request fields to the registered rule and stores the row it returns; no golden knowledge."""
    import combat.ext as ext
    calls = []

    class Rule:
        def validate(self, base, rows, cl, *, table=None, **fields):
            calls.append((cl, fields, table is not None))
            return {'id': fields['choice']}

    monkeypatch.setattr(ext, 'build_choice_kinds', lambda: ('fake_kind',))
    monkeypatch.setattr(ext, 'build_choice', lambda kind: Rule())
    table, _sheet, store = _service(12)
    table.set_build_choice('char', 'fake_kind', choice='x', slot=7)
    assert calls == [(12, {'choice': 'x', 'slot': 7}, True)]
    assert store['advancement']['fake_kind'][0]['id'] == 'x'


def test_core_table_service_names_no_golden_core_operation():
    source = (ROOT / 'combat/tabletop_service.py').read_text()
    assert 'def set_golden_core' not in source
    assert 'build_choice("golden_core")' not in source and "build_choice('golden_core')" not in source


# Finding 2: the CL15 replacement needs a recorded successful breakthrough, and stays one replacement.

def test_cl15_replacement_is_refused_without_a_recorded_breakthrough():
    table, sheet, store = _service(15, base=['circulating'])
    with pytest.raises(TabletopError) as error:
        table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert error.value.code == 'TABLETOP_GOLDEN_BREAKTHROUGH'
    assert store['advancement'] == {}
    assert _forms(sheet, store) == ['circulating']


def test_cl15_replacement_is_accepted_after_the_breakthrough_is_recorded():
    table, sheet, store = _service(15, base=['circulating'])
    table.record_breakthrough('char', 15)
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert _forms(sheet, store) == ['reservoir']


def test_cl15_second_replacement_is_still_refused_after_the_breakthrough():
    table, sheet, store = _service(15, base=['circulating'])
    table.record_breakthrough('char', 15)
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    with pytest.raises(TabletopError) as error:
        table.set_build_choice('char', 'golden_core', choice='stable', slot=1)
    assert error.value.code == 'TABLETOP_GOLDEN_SLOT'
    assert _forms(sheet, store) == ['reservoir']


def test_rule_refuses_the_cl15_replacement_without_breakthrough_records():
    rule = build_choice('golden_core')
    base = {'identity': {'cultivation_level': 15},
            'path_and_subpath': {'golden_core_forms': ['circulating'], 'path_feature_record_ids': [GOLDEN]}}
    with pytest.raises(Exception) as error:
        rule.validate(base, [], 15, slot=1, choice='reservoir', table={'breakthroughs': []})
    assert getattr(error.value, 'code', '') == 'TABLETOP_GOLDEN_BREAKTHROUGH'
    row = rule.validate(base, [], 15, slot=1, choice='reservoir', table={'breakthroughs': [{'cl': 15}]})
    assert row['id'] == 'reservoir'


def test_breakthrough_is_recorded_only_at_a_reached_realm_level():
    table, _sheet, store = _service(12)
    with pytest.raises(TabletopError) as error:
        table.record_breakthrough('char', 15)  # not yet reached
    assert error.value.code == 'TABLETOP_BREAKTHROUGH_CL'
    assert store['advancement'] == {}


def test_breakthrough_is_recorded_once():
    table, _sheet, store = _service(15)
    table.record_breakthrough('char', 15)
    table.record_breakthrough('char', 15)
    assert [row['cl'] for row in store['advancement']['breakthroughs']] == [15]
