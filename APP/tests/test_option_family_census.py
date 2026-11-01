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
    with patch('combat.tabletop.option_variant', return_value=None):
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
    assert changed, 'the fixture must exercise the new projection'
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


def test_sampled_mechanics_preserve_presented_rows_and_group_option_families():
    """Compare both presentation surfaces across the public stride-7 mechanic corpus."""
    sample = list(mechanics())[::7]
    assert sample
    changed = []
    missing = []
    for mid in sample:
        bundle = compile_character(mechanic_sheet(mid, cl=10), actor_id='actor:family.census')
        catalog = bundle['action_catalog']
        def present():
            buttons = auto_buttons(bundle, {})
            menu = {'actions': [{'source_definition_id': row['source_definition_id'],
                                 'label': row['display_name']} for row in catalog]}
            TabletopService._menu_descriptions(menu, _engine_for(bundle))
            return buttons, menu['actions']
        with patch('combat.tabletop.option_variant', return_value=None):
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
        by_id = {b['combat']['source_definition_id']: b for b in buttons
                 if (b.get('combat') or {}).get('source_definition_id')}
        families = defaultdict(list)
        for row in catalog:
            base = ((row.get('parameters') or {}).get('typed') or {}).get('option_of')
            button = by_id.get(row['source_definition_id'])
            if base and button and button.get('group') != 'attacks':
                families[base].append((row, button))
        for base, rows in families.items():
            if len(rows) >= 2:
                missing.extend((mid, base, row['display_name']) for row, button in rows
                               if not button.get('parent') and not button.get('variant'))
    assert changed, 'sample must exercise option projection'
    assert not missing, missing

