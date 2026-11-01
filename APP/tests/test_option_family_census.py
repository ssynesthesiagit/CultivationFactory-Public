"""Presentation census for the compiled Formations fixture."""

from collections import defaultdict
from unittest.mock import patch

from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, sheet_summary
from tests.test_formations import _sheet


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
