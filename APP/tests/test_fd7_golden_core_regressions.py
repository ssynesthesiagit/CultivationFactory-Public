"""FD-7 review regressions: sheet-recorded Golden Core Forms, the one CL15 replacement window, and strict HTTP slots.

Each test fails on the pre-fix tree (see the report) and passes once the fix is in.
"""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from combat import table_advance
from combat.tabletop_service import TabletopError, TabletopService

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = 'tianxia.path.qi_cultivation.feature.golden_core_form'


def _service(cl, base=(), store=None, features=(GOLDEN,)):
    """A TabletopService with a real sheet and saved growth record, no fight or database behind it.

    The sheet grants the Golden Core Form feature by default: these tests exercise the CL/slot rules for a character
    that has the feature (a character without it is refused earlier; see test_fd7_golden_core_ownership.py)."""
    paths = {'golden_core_forms': list(base)}
    if features:
        paths['path_feature_record_ids'] = list(features)
    sheet = {'identity': {'cultivation_level': cl}, 'path_and_subpath': paths}
    store = store if store is not None else {'advancement': {}}
    table = object.__new__(TabletopService)
    table.combat = SimpleNamespace(_factory_owner_sheet=lambda _p, apply_table=False: copy.deepcopy(sheet))
    table.buttons = SimpleNamespace(
        get=lambda _p: store,
        save_advancement=lambda _p, record: store.__setitem__('advancement', record))
    table.advancement = lambda _p: {}
    return table, sheet, store


def _reloaded(sheet, store):
    """What a fight sees: the saved growth record overlaid on the base sheet."""
    return table_advance.apply(copy.deepcopy(sheet), store['advancement'], mechanics={})


# Finding 1: a Form recorded on the sheet counts as chosen.

def test_sheet_recorded_form_allows_the_cl20_second_form():
    table, sheet, store = _service(20, base=['circulating'])
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=2)  # must record, not raise
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['circulating', 'reservoir']


def test_sheet_recorded_form_blocks_overwriting_it_below_cl15():
    table, sheet, store = _service(10, base=['circulating'])
    with pytest.raises(TabletopError):
        table.set_build_choice('char', 'golden_core', choice='stable', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['circulating']


# Finding 2: one replacement, only after the CL15 breakthrough.

def test_only_one_replacement_is_recorded_at_cl15():
    table, sheet, store = _service(15, base=['circulating'], store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)  # the one replacement
    with pytest.raises(TabletopError):
        table.set_build_choice('char', 'golden_core', choice='stable', slot=1)  # a second change at the same breakthrough
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['reservoir']


def test_replacement_is_closed_at_cl17_without_a_cl15_replacement():
    table, sheet, store = _service(17, base=['circulating'])
    with pytest.raises(TabletopError):
        table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert store['advancement'] == {}


# Finding 3: the HTTP slot is validated as a strict integer and never coerced.

def _post_golden(tmp_path, monkeypatch, slot):
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator
    from app.api import create_app
    from app.core import Settings

    seen = []
    monkeypatch.setattr(TabletopService, 'set_build_choice',
                        lambda self, project_id, kind, **fields: seen.append((fields['choice'], fields['slot'])) or {})
    monkeypatch.setattr(Draft202012Validator, 'check_schema', classmethod(lambda cls, schema, format_checker=None: None))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    with TestClient(app) as client:
        headers = {'x-foundry-token': client.get('/api/session').json()['token']}
        response = client.post('/api/tabletop/characters/char/advancement/golden-core',
                               json={'form': 'reservoir', 'slot': slot}, headers=headers)
    return response, seen


@pytest.mark.parametrize('slot', [1.8, '1', True, None])
def test_http_golden_core_rejects_a_non_integer_slot_without_coercion(tmp_path, monkeypatch, slot):
    response, seen = _post_golden(tmp_path, monkeypatch, slot)
    assert response.status_code == 422, (slot, response.status_code)
    assert seen == [], seen


def test_http_golden_core_passes_a_strict_integer_slot_through_unchanged(tmp_path, monkeypatch):
    response, seen = _post_golden(tmp_path, monkeypatch, 2)
    assert seen == [('reservoir', 2)] and type(seen[0][1]) is int, (response.status_code, seen)


def test_build_choice_seam_resolves_the_golden_core_rule_from_the_plug_in():
    from combat.ext import BuildChoiceRefused, build_choice, build_choice_kinds
    assert 'golden_core' in build_choice_kinds()
    rule = build_choice('golden_core')
    assert type(rule).__module__ == 'combat.ext.qi_path'
    with pytest.raises(BuildChoiceRefused) as exc:
        rule.validate({'identity': {'cultivation_level': 10},
                       'path_and_subpath': {'path_feature_record_ids': [GOLDEN]}}, [], 10, slot=3, choice='stable')
    assert exc.value.code == 'TABLETOP_GOLDEN_SLOT' and exc.value.status == 400


# Finding 5 (Grow): the Grow block must read the sheet's recorded Forms and the server's eligibility.

def test_grow_block_uses_the_server_panel_for_eligibility():
    source = (ROOT / 'static/tabletop/grow.js').read_text()
    assert 'build_choices' in source
    assert 'active.length !== 1' not in source
