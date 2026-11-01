"""Presentation checks for compiled Formations and the public mechanic corpus."""

from collections import defaultdict
from unittest.mock import patch

from combat.factory_compiler import compile_character
from combat.tabletop import _authority_index, auto_buttons, sheet_summary
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

    # A compiled action can itself be the base, not only an authority record.
    from copy import deepcopy
    template = next(row for row in bundle['action_catalog']
                    if ((row.get('parameters') or {}).get('typed') or {}).get('option_of') == 'FORMATIONS_BASE_SET_ARRAY')
    base = deepcopy(template)
    base.update(source_definition_id='action.base', display_name='Vacuum Cut')
    base['parameters']['typed'].pop('option_of', None)
    options = []
    for n in (1, 2):
        row = deepcopy(template)
        row.update(source_definition_id=f'action.option.{n}', display_name=f'Cut {n}')
        row['parameters']['typed']['option_of'] = 'action.base'
        options.append(row)
    def projected(rows):
        return {b['combat']['source_definition_id']: b for b in
                auto_buttons({**bundle, 'action_catalog': rows}, summary) if b.get('combat')}
    assert projected([base, *options])['action.option.1']['variant']['base_label'] == 'Vacuum Cut'
    assert 'variant' not in projected([base, options[0]])['action.option.1']


def test_shipped_weapon_fixtures_preserve_attack_rows_on_both_surfaces():
    """Compare real test kits, including a thrown weapon and a treasure bow."""
    from tests.auto8f1_table_support import AXE_KIT, POLEARM_KIT
    from tests.sol56_support import KIT as MIXED_KIT
    from tests.test_a2_barrage_fix_round import THROWN_KIT, ENCHANTED_BOW

    attacks_seen = 0
    for name, kit in [('axe', AXE_KIT), ('polearm', POLEARM_KIT),
                      ('mixed', MIXED_KIT), ('thrown', THROWN_KIT),
                      ('treasure bow', ENCHANTED_BOW)]:
        bundle = compile_character(mechanic_sheet([], cl=10, kit=kit),
                                   actor_id='actor:family.weapons')
        catalog = bundle['action_catalog']
        def present():
            buttons = auto_buttons(bundle, {})
            candidates = [{'kind': 'ACTION', 'candidate_id': str(i),
                           'source_definition_id': row['source_definition_id'],
                           'display_name': row['display_name'],
                           'metadata': {'variant': row['variant']} if row.get('variant') else {}}
                          for i, row in enumerate(catalog)]
            context = {'decision_id': 'census', 'state_version': 1,
                       'active_actor_id': 'actor:family.weapons', 'legal_candidates': candidates}
            menu = TabletopService._menu({'context': context, 'control_mode': 'MANUAL'}, {}, engine=None)
            TabletopService._menu_descriptions(menu, _engine_for(bundle))
            return buttons, menu['actions']
        with patch('combat.tabletop.option_variant', return_value=None, create=True):
            old_buttons, old_menu = present()
        buttons, menu = present()
        weapon_ids = {row['source_definition_id'] for row in catalog
                      if ((row.get('parameters') or {}).get('typed') or {}).get('weapon')}
        attacks_seen += len(weapon_ids)
        for surface, before, after in [('sheet', old_buttons, buttons), ('menu', old_menu, menu)]:
            def weapon_rows(rows):
                return [row for row in rows if (row.get('source_definition_id') or
                        (row.get('combat') or {}).get('source_definition_id')) in weapon_ids]
            assert weapon_rows(before) == weapon_rows(after), (name, surface)
    assert attacks_seen, 'fixtures must compile weapon actions'


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
            # Exercise the actual menu projection with synthetic candidates. Real
            # legality and the persisted menu are checked in test_mgr_t14_set_array.
            candidates = [{'kind': 'ACTION', 'candidate_id': str(i),
                           'source_definition_id': row['source_definition_id'],
                           'display_name': row['display_name'],
                           'metadata': {'variant': row['variant']} if row.get('variant') else {}}
                          for i, row in enumerate(catalog)]
            context = {'decision_id': 'census', 'state_version': 1,
                       'active_actor_id': 'actor:family.census', 'legal_candidates': candidates}
            menu = TabletopService._menu({'context': context, 'control_mode': 'MANUAL'}, {}, engine=None)
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
            base = typed.get('option_of')
            if not (base or parameters.get('menu_parent') or row.get('variant')):
                continue
            # A weapon-bearing ability can be in the actions group: its weapon
            # metadata, not the display group, identifies the attack-card path.
            if typed.get('weapon') or parameters.get('basic'):
                continue
            if base and not (parameters.get('menu_parent') or row.get('variant')):
                # Projection groups only multi-row families with a resolvable base.
                siblings = [other for other in catalog
                            if other.get('owner_id') == row.get('owner_id')
                            and ((other.get('parameters') or {}).get('typed') or {}).get('option_of') == base]
                resolved = (_authority_index().get(base) or {}).get('name') or any(
                    other.get('owner_id') == row.get('owner_id')
                    and other.get('source_definition_id') == base and other.get('display_name')
                    for other in catalog)
                if len(siblings) < 2 or not resolved:
                    continue
            source = row['source_definition_id']
            button = by_id.get(source)
            for surface, presented in (('sheet', button), ('menu', menu_by_id.get(source))):
                if presented and not (presented.get('parent') or presented.get('variant')):
                    missing.append((mid, surface, source, row['display_name']))
    assert not missing, missing
    assert changed, 'corpus must exercise option projection'
