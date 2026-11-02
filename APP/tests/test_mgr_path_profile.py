"""The owning-Path number projection shared by this lane's ext plug-ins.

A feature compiles with its own Path's CL, Proficiency Bonus and key ability; a
sheet that cannot name one keeps the numbers it already had, because a missing or
malformed profile is a legacy sheet, not a character-compilation failure.
"""
from combat.ext.path_profiles import path_numbers

BODY = 'tianxia.path.body_refining'


def sheet(paths=None, abilities=()):
    document = {'ability_scores_and_statistics': {'abilities': list(abilities)}}
    if paths is not None:
        document['path_and_subpath'] = {'paths': paths}
    return document


def info(owner_sheet, **numbers):
    return {'numbers': dict({'cl': 5, 'pb': 3, 'key_mod': 1, 'attack_bonus': 4, 'save_dc': 12}, **numbers),
            'owner_sheet': owner_sheet}


def test_projects_the_owning_paths_level_bonus_and_key_ability():
    numbers = path_numbers(info(sheet([{'path_id': BODY, 'effective_cl': 9, 'key_ability': 'CON'}],
                                     [{'ability': 'CON', 'modifier': 4}, {'ability': 'WIS', 'modifier': 1}])), BODY)
    assert (numbers['cl'], numbers['pb'], numbers['key_mod']) == (9, 4, 4)
    assert (numbers['attack_bonus'], numbers['save_dc']) == (8, 16)


def test_derives_a_missing_modifier_from_the_score_and_ignores_unknown_abilities():
    numbers = path_numbers(info(sheet([{'path_id': BODY, 'effective_cl': 3, 'key_ability': 'DEX'}],
                                     [{'ability': 'DEX', 'score': 17}])), BODY)
    assert (numbers['key_mod'], numbers['pb']) == (3, 2)
    unchanged = path_numbers(info(sheet([{'path_id': BODY, 'effective_cl': 3, 'key_ability': 'CHA'}])), BODY)
    assert unchanged['key_mod'] == 1 and unchanged['attack_bonus'] == 4


def test_missing_or_malformed_rows_leave_the_sheets_own_numbers():
    baseline = info(sheet())
    assert path_numbers(baseline, BODY) == baseline['numbers']
    for paths in ([], [None], [{'path_id': BODY}], [{'path_id': BODY, 'effective_cl': 'nine'}],
                  [{'path_id': BODY, 'effective_cl': -1}], [{'path_id': BODY, 'effective_cl': 21}]):
        assert path_numbers(info(sheet(paths)), BODY) == baseline['numbers']


def test_first_usable_row_wins_over_a_duplicate_profile():
    numbers = path_numbers(info(sheet([
        {'path_id': BODY, 'effective_cl': 7, 'key_ability': 'CON'},
        {'path_id': BODY, 'effective_cl': 19, 'key_ability': 'CON'}])), BODY)
    assert numbers['cl'] == 7 and numbers['pb'] == 3
