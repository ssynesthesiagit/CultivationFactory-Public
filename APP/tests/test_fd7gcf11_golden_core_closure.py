"""FD7GCF11 review fixes: the printed replacement window closes on Nascent Soul use, and the
permanent Grow choices say what they do.

Review finding 1: "You may replace the chosen Form after a successful CL15 breakthrough before
using your CL15 Nascent Soul feature." The window's second edge was never enforced, so a CL15
character could use Nascent Continuity and then still replace the Form through Grow. The use is now
recorded in the growth record (``record_feature_use``) and ``validate`` refuses afterwards.

Review finding 3: the Grow buttons showed only the Form's name and a bare reason, so a player chose
a permanent Form without seeing its benefit, its limit or its Perfected behaviour. The panel now
carries both, in the printed words.
"""
import copy
from types import SimpleNamespace

import pytest
from combat import table_advance
from combat.ext.qi_path import NASCENT_SOUL
from combat.tabletop_service import TabletopError, TabletopService

GOLDEN = 'tianxia.path.qi_cultivation.feature.golden_core_form'
MERIDIAN = 'tianxia.path.qi_cultivation.feature.meridian_regulation'


def _service(cl, base=(), store=None, features=(GOLDEN, NASCENT_SOUL, MERIDIAN)):
    """A TabletopService over a real sheet and a real saved growth record, with no fight or database.

    The sheet owns the Golden Core Form feature and the Path features these tests use (Nascent Soul and
    Meridian Regulation), so the printed CL/slot/use rules are exercised for a character that really has them.
    A feature use the sheet does not grant is refused by record_feature_use."""
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
    """What a fight sees: the saved growth record overlaid on the base sheet, after a cold reload."""
    return table_advance.apply(copy.deepcopy(sheet), store['advancement'], mechanics={})


# --------------------------------------------------------------- finding 1: the window closes on Nascent Soul use

def test_the_replacement_is_allowed_before_the_nascent_soul_use():
    """Before the use, the printed window is still open (CL15 breakthrough recorded, first Form held)."""
    table, sheet, store = _service(15, base=['circulating'],
                                  store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['reservoir']


def test_recording_the_nascent_soul_use_survives_reload_and_closes_the_replacement():
    """Use the CL15 feature, commit, reload, then a replacement is refused and the Form is unchanged."""
    table, sheet, store = _service(15, base=['circulating'],
                                  store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    table.record_feature_use('char', NASCENT_SOUL)
    # the use is persisted beside the character, not only in the fight that saw it
    assert [row['feature_id'] for row in store['advancement']['feature_uses']] == [NASCENT_SOUL]
    reloaded = table_advance.normalized(store['advancement'])  # cold reload of the saved record
    assert [row['feature_id'] for row in reloaded['feature_uses']] == [NASCENT_SOUL]

    with pytest.raises(TabletopError) as refused:
        table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert refused.value.code == 'TABLETOP_GOLDEN_CLOSED'
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['circulating']


def test_an_unrelated_feature_use_does_not_close_the_golden_core_window():
    table, sheet, store = _service(15, base=['circulating'],
                                  store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    table.record_feature_use('char', 'tianxia.path.qi_cultivation.feature.meridian_regulation')
    table.set_build_choice('char', 'golden_core', choice='reservoir', slot=1)
    assert _reloaded(sheet, store)['path_and_subpath']['golden_core_forms'] == ['reservoir']


def test_the_panel_reports_the_closed_window_so_the_grow_tab_can_explain_it():
    from combat.ext import build_choice
    table, sheet, store = _service(15, base=['circulating'],
                                  store={'advancement': {'breakthroughs': [{'cl': 15}]}})
    rule = build_choice('golden_core')
    before = rule.panel(sheet, store['advancement'].get('golden_core') or [], 15, table=store['advancement'])
    assert before['nascent_used'] is False
    table.record_feature_use('char', NASCENT_SOUL)
    after = rule.panel(sheet, store['advancement'].get('golden_core') or [], 15, table=store['advancement'])
    assert after['nascent_used'] is True
    assert not [o for o in after['options'] if o['slot'] == 1 and o['allowed']]


# --------------------------------------------------------------- finding 3: the permanent choices explain themselves

def test_every_golden_core_choice_states_its_benefit_and_perfected_behaviour():
    from combat.ext import build_choice
    table, sheet, _store = _service(10)
    panel = build_choice('golden_core').panel(sheet, {}, 10, table={})
    by_id = {o['id']: o for o in panel['options'] if o['slot'] == 1}
    assert set(by_id) == {'stable', 'circulating', 'reservoir'}
    for key, option in by_id.items():
        assert option['benefit'], f'{key} choice says nothing about what it does'
        assert option['perfected'], f'{key} choice says nothing about its Cultivation Level 17 behaviour'
    # plain wording for a player who knows only basic D&D: no internal ids or code names
    assert 'Proficiency Bonus' in by_id['stable']['benefit']
    assert 'Bonus Action' in by_id['reservoir']['benefit'] and 'once per scene' in by_id['reservoir']['benefit']
    assert 'Cultivation Level 17' in by_id['circulating']['perfected']


def test_the_grow_tab_renders_those_benefit_lines():
    """The button text alone was the defect; the Grow block must show the benefit under each choice."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / 'static/tabletop/grow.js').read_text(encoding='utf-8')
    assert 'o.benefit' in source and 'o.perfected' in source
    assert 'grow-form-why' in source