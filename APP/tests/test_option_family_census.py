"""Presentation census for the compiled Formations fixture."""

from collections import defaultdict
from unittest.mock import patch

from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, sheet_summary
from tests.test_formations import _sheet
from tests.h1_support import mechanics, sheet as mechanic_sheet
from tests.test_mmx109_menu_text import _engine_for
from combat.tabletop_service import TabletopService


def test_compiled_formation_option_families_are_presented_without_losing_rows():
    sheet = _sheet([])
    sheet['spheres_and_talents']['formation_patterns'] = ['locking_gate', 'nourishing_cycle']
    bundle = compile_character(sheet, actor_id='actor:factory.family')
    summary = sheet_summary(sheet)
    buttons = auto_buttons(bundle, summary)
    # Compare the same compiled actions with the pre-projection presentation.
    # The projection may add variant metadata but must not change or drop rows.
    with patch('combat.tabletop.option_variant', return_value=None, create=True):
        before = auto_buttons(bundle, summary)
    assert len(buttons) == len(before)
    changed = []
    for old, new in zip(before, buttons):
        old_without_variant = {key: value for key, value in old.items() if key != 'variant'}
        new_without_variant = {key: value for key, value in new.items() if key != 'variant'}
        assert old_without_variant == new_without_variant
        if old.get('variant') != new.get('variant'):
            assert not old.get('variant') and new.get('variant')
            changed.append(new['combat']['source_definition_id'])
    by_id = {b['combat']['source_definition_id']: b for b in buttons
             if (b.get('combat') or {}).get('source_definition_id')}
    families = defaultdict(list)
    for row in bundle['action_catalog']:
        typed = (row.get('parameters') or {}).get('typed') or {}
        if typed.get('option_of'):
            families[typed['option_of']].append(row)
    assert len(families['FORMATIONS_BASE_SET_ARRAY']) >= 2
    for base, rows in families.items():
        if len(rows) < 2:
            continue
        for row in rows:
            if (row.get('parameters') or {}).get('item_action'):
                continue
            button = by_id[row['source_definition_id']]
            if button['group'] == 'attacks':
                continue  # weapon cards already own their grouping
            assert button.get('parent') or button.get('variant'), (base, row['display_name'])
    assert changed, 'the fixture must exercise the new projection'


def test_mechanics_preserve_presented_rows_and_group_option_families():
    """Compare both presentation surfaces across the entire public mechanic corpus."""
    sample = list(mechanics())
    assert sample
    changed = []
    missing = []
    for mid in sample:
        bundle = compile_character(mechanic_sheet(mid, cl=10, kit={'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}),
            actor_id='actor:family.census')
        catalog = bundle['action_catalog']
        def present():
            buttons = auto_buttons(bundle, {})
            menu = {'actions': [{'source_definition_id': row['source_definition_id'],
                                 'label': row['display_name']} for row in catalog]}
            TabletopService._menu_descriptions(menu, _engine_for(bundle))
            return buttons, menu['actions']
        with patch('combat.tabletop.option_variant', return_value=None, create=True):
            old_buttons, old_menu = present()
        buttons, menu = present()
        for surface, before, after in (('sheet', old_buttons, buttons), ('menu', old_menu, menu)):
            assert len(before) == len(after), (mid, surface)
            for old, new in zip(before, after):
                assert {k: v for k, v in old.items() if k != 'variant'} == {
                    k: v for k, v in new.items() if k != 'variant'}, (mid, surface, old, new)
                if old.get('variant') != new.get('variant'):
                    assert not old.get('variant') and new.get('variant'), (mid, surface, old, new)
                    changed.append((mid, surface, new.get('label')))
        assert [b for b in old_buttons if b.get('group') == 'attacks'] == [
            b for b in buttons if b.get('group') == 'attacks'], mid
        by_id = {b['combat']['source_definition_id']: b for b in buttons
                 if (b.get('combat') or {}).get('source_definition_id')}
        menu_by_id = {row['source_definition_id']: row for row in menu}
        for row in catalog:
            parameters = row.get('parameters') or {}
            typed = parameters.get('typed') or {}
            if not (typed.get('option_of') or parameters.get('menu_parent') or row.get('variant')):
                continue
            source = row['source_definition_id']
            button = by_id.get(source)
            # Weapon cards are already grouped by their structured attack group.
            if button and button.get('group') == 'attacks':
                continue
            for surface, presented in (('sheet', button), ('menu', menu_by_id.get(source))):
                if presented and not (presented.get('parent') or presented.get('variant')):
                    missing.append((mid, surface, source, row['display_name']))
    assert changed, 'corpus must exercise option projection'
    assert not missing, missing
