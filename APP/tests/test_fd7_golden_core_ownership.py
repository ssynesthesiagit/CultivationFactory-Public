"""FD-7 ownership regression: a Golden Core Form is a build choice only for a character that owns the feature.

Review FD7GCF7R blocking finding: ``validate`` only checked CL and the Form/slot, and the endpoint accepted any
character sheet, so a character without ``tianxia.path.qi_cultivation.feature.golden_core_form`` could record a Form
that the overlay then wrote onto its sheet.

Each test here fails on the pre-fix tree (no ownership gate: recording succeeds / the panel offers options) and passes
once the gate is in.
"""
import copy
from types import SimpleNamespace

import pytest
from combat import table_advance
from combat.ext import build_choice
from combat.tabletop_service import TabletopError, TabletopService

GOLDEN = 'tianxia.path.qi_cultivation.feature.golden_core_form'


def _service(cl, *, features=(), base=()):
    """A TabletopService over a synthetic sheet; ``features`` are the Path features the sheet actually grants."""
    paths = {'golden_core_forms': list(base)}
    if features:
        paths['path_feature_record_ids'] = list(features)
    sheet = {'identity': {'cultivation_level': cl}, 'path_and_subpath': paths}
    store = {'advancement': {}}
    table = object.__new__(TabletopService)
    table.combat = SimpleNamespace(_factory_owner_sheet=lambda _p, apply_table=False: copy.deepcopy(sheet))
    table.buttons = SimpleNamespace(
        get=lambda _p: store,
        save_advancement=lambda _p, record: store.__setitem__('advancement', record))
    table.advancement = lambda _p: {}
    return table, sheet, store


def _reloaded(sheet, store):
    return table_advance.apply(copy.deepcopy(sheet), store['advancement'], mechanics={})


# The blocking defect: a character with no Golden Core Form feature cannot record a Form.

def test_character_without_the_feature_cannot_record_a_form():
    table, sheet, store = _service(20, features=())  # CL20, but nothing grants the Golden Core Form
    with pytest.raises(TabletopError) as exc:
        table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert exc.value.code == 'TABLETOP_GOLDEN_NO_FEATURE'
    assert store['advancement'] == {}, 'a refused choice must write nothing'
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == []


def test_character_on_another_path_cannot_record_a_form():
    table, _sheet, store = _service(20, features=['some.other.path.feature'])
    with pytest.raises(TabletopError):
        table.set_build_choice('char', 'golden_core', choice='stable', slot=1)
    assert store['advancement'] == {}


def test_feature_owner_can_still_record_a_form():
    """Positive control: the gate must not block a legitimate Qi character."""
    table, sheet, store = _service(10, features=[GOLDEN])
    table.set_build_choice('char', 'golden_core', choice='circulating', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['circulating']


# The Grow panel must not offer the choice to a character that does not own the feature.

def test_panel_offers_no_choices_to_a_character_without_the_feature():
    rule = build_choice('golden_core')
    sheet = {'identity': {'cultivation_level': 20}, 'path_and_subpath': {'path_feature_record_ids': []}}
    panel = rule.panel(sheet, [], 20)
    assert panel['forms'] == [] and panel['options'] == []


def test_panel_offers_choices_to_a_character_that_owns_the_feature():
    rule = build_choice('golden_core')
    sheet = {'identity': {'cultivation_level': 10}, 'path_and_subpath': {'path_feature_record_ids': [GOLDEN]}}
    panel = rule.panel(sheet, [], 10)
    assert panel['options'], 'a real Qi character must still be offered its Forms'
    assert any(option['allowed'] for option in panel['options'])


def test_earned_feature_occurrence_also_grants_ownership():
    """Some sheets record a feature as an earned occurrence rather than a path feature id."""
    rule = build_choice('golden_core')
    sheet = {'identity': {'cultivation_level': 20},
             'path_and_subpath': {'earned_feature_occurrences': [{'feature_id': GOLDEN}]}}
    assert rule.panel(sheet, [], 20)['options']