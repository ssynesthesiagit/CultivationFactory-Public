"""The Golden Core Form is a fixed build choice, not an in-fight switch.

Covers: no in-fight Form rows at any CL; the recorded Form compiles as a fixed condition; CL20 holds two;
an unrecorded character gets no Form (no Stable default); the growth-record rules (CL10 first pick,
CL15 replacement, CL20 second).
"""
from types import SimpleNamespace

import pytest
from combat import table_advance
from combat.ext import build_choice
from combat.ext import qi_path
from combat.tabletop_service import TabletopError, TabletopService
from tests.worker2_support import fixture, reload, OWNER

Q = 'tianxia.path.qi_cultivation.feature.'
FORM = 'condition:typed.golden_core_form'


def offered_forms(engine):
    return sorted(c.display_name for aid, c in engine.action_catalog.items()
                  if c.display_name.startswith('Golden Core Form:') and c.owner_id == OWNER)


@pytest.mark.parametrize('cl', [10, 17])
def test_recorded_form_is_fixed_and_offers_no_switch(tmp_path, cl):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=cl, owner_golden=['circulating'],
                                 seed=f'GOLDEN-FIXED-{cl}')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert offered_forms(engine) == []
    assert qi_path.forms(owner, permanent_only=True) == ('circulating',)
    assert qi_path.form(owner) == 'circulating'
    held = next(c for c in owner.conditions.values() if c.condition_id == FORM)
    assert held.data['fixed'] is True and 'fixed build choice' in held.data['label']


def test_cl20_shows_both_recorded_forms_read_only(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form', Q + 'second_golden_core_form'], cl=20,
                                 owner_golden=['circulating', 'reservoir'], seed='GOLDEN-FIXED-20')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert offered_forms(engine) == []
    assert qi_path.forms(owner, permanent_only=True) == ('circulating', 'reservoir')


def test_unrecorded_character_has_no_form_and_no_default_condition(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, seed='GOLDEN-FIXED-NONE')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert offered_forms(engine) == []
    # No recorded Form means no Form benefit and no labelled default Stable condition.
    assert qi_path.forms(owner) == () and qi_path.form(owner) is None
    assert [c for c in owner.conditions.values() if c.condition_id == FORM] == []


def test_recorded_form_is_not_replaced_by_an_in_fight_pick(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q + 'golden_core_form'], cl=10, owner_golden=['stable'], seed='GOLDEN-FIXED-NOSW')
    engine = reload(tmp_path, mid)
    names = {getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') for c in engine.legal_candidates()}
    assert not any(n.startswith('Golden Core Form:') for n in names)


def test_growth_record_first_pick_needs_cl10_and_replacement_needs_cl15():
    rows = [{"id": "stable", "slot": 1, "cl": 10}]
    assert build_choice('golden_core').effective({}, rows, 10) == ["stable"]
    # a replacement recorded at CL15 supersedes the CL10 pick from CL15 on
    rows.append({"id": "reservoir", "slot": 1, "cl": 15})
    assert build_choice('golden_core').effective({}, rows, 16) == ["reservoir"]
    assert build_choice('golden_core').effective({}, rows, 12) == ["stable"]  # before the replacement's CL nothing changes


def test_second_form_needs_cl20_and_is_kept_with_the_first():
    rows = [{"id": "circulating", "slot": 1, "cl": 10}, {"id": "reservoir", "slot": 2, "cl": 20}]
    assert build_choice('golden_core').effective({}, rows, 19) == ["circulating"]
    assert build_choice('golden_core').effective({}, rows, 20) == ["circulating", "reservoir"]


def test_invalid_golden_core_slot_is_rejected_without_recording_a_form():
    saved = {'advancement': {'golden_core': []}}
    writes = []
    table = object.__new__(TabletopService)
    table.combat = SimpleNamespace(
        _factory_owner_sheet=lambda _project_id, apply_table=False: {
            'identity': {'cultivation_level': 15},
            'path_and_subpath': {'path_feature_record_ids': [Q + 'golden_core_form']}})
    table.buttons = SimpleNamespace(get=lambda _project_id: saved,
                                    save_advancement=lambda _project_id, record: writes.append(record))
    table.advancement = lambda _project_id: {}

    with pytest.raises(TabletopError, match='Form slot 1 or 2') as error:
        table.set_build_choice('synthetic-character', 'golden_core', choice='reservoir', slot=3)

    assert error.value.code == 'TABLETOP_GOLDEN_SLOT'
    assert writes == []
    assert table_advance.normalized(saved['advancement'])['golden_core'] == []


def test_replacing_first_form_cannot_duplicate_second_active_form():
    saved = {'advancement': {'golden_core': [
        {'id': 'circulating', 'slot': 1, 'cl': 10}, {'id': 'reservoir', 'slot': 2, 'cl': 20}]}}
    writes = []
    table = object.__new__(TabletopService)
    table.combat = SimpleNamespace(
        _factory_owner_sheet=lambda _project_id, apply_table=False: {
            'identity': {'cultivation_level': 20},
            'path_and_subpath': {'path_feature_record_ids': [Q + 'golden_core_form']}})
    table.buttons = SimpleNamespace(get=lambda _project_id: saved,
                                    save_advancement=lambda _project_id, record: writes.append(record))

    with pytest.raises(TabletopError, match='first Form must differ') as error:
        table.set_build_choice('synthetic-character', 'golden_core', choice='reservoir', slot=1)

    assert error.value.code == 'TABLETOP_GOLDEN_SLOT'
    assert writes == []


def test_golden_core_record_is_normalized_and_overlaid_without_mutating_input():
    sheet = {"identity": {"cultivation_level": 10}, "path_and_subpath": {"path_record_ids": []}}
    document = {"golden_core": [{"id": "circulating", "slot": 1, "cl": 10}]}
    overlaid = table_advance.apply(sheet, document, mechanics={})
    assert overlaid["path_and_subpath"]["golden_core_forms"] == ["circulating"]
    assert "golden_core_forms" not in sheet["path_and_subpath"]
