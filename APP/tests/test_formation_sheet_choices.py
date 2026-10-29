"""The printed Formations cards must lead to the real combat choices."""

from combat.ext import formations as F
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, sheet_library, sheet_summary
from tests.test_formations import _sheet, _engine, _names


def test_formation_cards_offer_real_choices_instead_of_the_generic_action():
    sheet = _sheet([])
    sheet['spheres_and_talents']['formation_patterns'] = ['locking_gate', 'nourishing_cycle']
    sheet['selected_record_sections'] = {
        'spheres': [{'record_id': F.SPHERE, 'display_name': 'Formations'}],
        'sphere_automatic_components': [
            {'record_id': key, 'display_name': name, 'full_description': name}
            for key, name in [(F.BASE_SET, 'Set Array'), (F.BASE_PULSE, 'Pulse Array'),
                              (F.BASE_COLLAPSE, 'Collapse Array')]],
    }
    bundle = compile_character(sheet, actor_id='actor:factory.ning')
    buttons = auto_buttons(bundle, sheet_summary(sheet))
    by_id = {button['id']: button for button in buttons}
    library = sheet_library(sheet, buttons, set())
    entries = {entry['id']: entry for group in library['groups']
               for sphere in group.get('spheres', []) for entry in sphere['entries']}
    for key in (F.BASE_SET, F.BASE_PULSE, F.BASE_COLLAPSE):
        assert entries[key]['status'] == 'action'
        assert by_id[entries[key]['button_id']]['option_of'] == key
    set_choices = [by_id[key] for key in entries[F.BASE_SET]['button_ids']]
    assert {choice['label'] for choice in set_choices} == {
        'Combat Array: Locking Gate', 'Combat Array: Nourishing Cycle'}
    assert all(choice['combat']['target_kind'] == 'CELL' for choice in set_choices)
    assert all(not row['parameters'].get('player_only') for row in bundle['action_catalog']
               if row['display_name'] == 'Pulse: Locking Gate')
    engine, _ = _engine([])
    assert 'Set Array' not in _names(engine)
