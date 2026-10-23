"""Public-runnable regression: Oath-Skin Frame across saved table levels.

An installed CL8 / PB3 character with a saved CL9 (PB4) level and an accepted
Integrated source event must carry the Integrated additional PB at the advanced
PB (4), not the installed PB (3). Uses only the pinned Foundation release, the
table projection and the Frame calculator; no private harness.
"""
import hashlib
from copy import deepcopy

import pytest

from combat import status_text
from combat import table_advance as ta
from combat.canonical import canonical_sha256
from combat.ext import oath_skin_frame as frame
from combat.factory_compiler import compile_character
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
)

PATHS = ['tianxia.path.body_refining']
OWNER = 'actor:factory.0a1b2c3d4e5f6071'
BASE_HP = 50


@pytest.fixture(autouse=True)
def printed_text_in_this_checkout(monkeypatch):
    """Authenticate Frame against the printed text this checkout carries.

    The exact-text digest is enforced by the owner's rules file; public mirrors carry a
    different copy of that file. This test pins the digest to the local text so the
    projection, replay and compilation are exercised in both environments. The digest
    check itself is not what these regressions test.
    """
    text = status_text.printed_rules()[frame.FRAME]
    monkeypatch.setattr(frame, 'HASH', hashlib.sha256(text.encode()).hexdigest())


def installed_cl8_sheet():
    source = verified_foundation_records()[frame.FOUNDATION]
    mechanics = resolve_initial_foundation_mechanics(source, PATHS)
    event_id = 'import:' + canonical_sha256(mechanics)
    foundation = installed_foundation_state(mechanics, frame.FOUNDATION, event_id)
    foundation.update(mechanical_projection=True, acquisition_event_id=event_id, mechanics=mechanics,
                      source_packet_ids=['import:' + canonical_sha256(source)])
    pb = 3
    scores = {'STR': 12, 'DEX': 14, 'CON': 16, 'INT': 16, 'WIS': 12, 'CHA': 8}
    modifiers = {a: ta.ability_modifier(v) for a, v in scores.items()}
    return {
        'identity': {'name': 'Oath bearer', 'cultivation_level': 8, 'proficiency_bonus': pb,
                     'key_ability': 'CON', 'path_ids': list(PATHS),
                     'paths': [{'path_id': PATHS[0], 'effective_cl': 8}]},
        'path_and_subpath': {'path_record_ids': list(PATHS)},
        'spheres_and_talents': {'sphere_record_ids': [], 'learned_talent_record_ids': []},
        'foundation': foundation,
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': v, 'modifier': modifiers[a]} for a, v in scores.items()],
            'hit_points': {'maximum': BASE_HP + frame.hp_value(mechanics, pb), 'build_state_current': BASE_HP,
                           'progression': {'levels': [{'cl': 1, 'gain': BASE_HP, 'maximum': BASE_HP}]}},
            'primary_resource': {'name': 'Qi', 'maximum': 4, 'build_state_current': 4, 'definitions': []},
            'saving_throw_proficiencies': ['CON', 'INT'],
            'saving_throws': {a: modifiers[a] + (pb if a in ('CON', 'INT') else 0) for a in scores},
            'armor_class': {'base_value': 12, 'value': 12},
            'technique_attack_bonus': 5, 'technique_save_dc': 13,
            'initiative': {'ability': 'DEX', 'bonus': modifiers['DEX']},
            'skills': [{'skill': 'Lore', 'ability': 'INT', 'bonus': modifiers['INT'] + pb, 'proficient': True}],
            'speed': {'walking_ft': 30},
        },
    }


def receipt(sheet, kind, order):
    event = {'event_id': f'frame-{kind}-{order}', 'source_id': frame.FRAME,
             'acquisition_id': sheet['foundation']['acquisition_event_id'], 'kind': kind,
             'commit_order': order}
    return {'event': event, 'match_id': 'match-frame-levels', 'journal_sha256': 'b' * 64, 'sequence': order}


def test_integrated_after_saved_level_uses_advanced_proficiency_bonus():
    installed = installed_cl8_sheet()
    table = {'levels': [{'cl': 9}], 'source_events': [receipt(installed, 'integrated', 1)]}
    advanced = ta.apply(deepcopy(installed), table)
    level_only = ta.apply(deepcopy(installed), {'levels': [{'cl': 9}]})

    assert advanced['identity']['proficiency_bonus'] == 4
    # Frame total at PB4 is 2 x PB = 8 (base 4 + Integrated 4); the no-event level-up already carries the base 4.
    assert advanced['ability_scores_and_statistics']['hit_points']['maximum'] == \
        level_only['ability_scores_and_statistics']['hit_points']['maximum'] + 4
    assert advanced['ability_scores_and_statistics']['hit_points']['source_contributions'][frame.FRAME] == 2 * 4


def test_integrated_projection_matches_compiled_frame_row_after_advancement():
    installed = installed_cl8_sheet()
    table = {'levels': [{'cl': 9}], 'source_events': [receipt(installed, 'integrated', 1)]}
    advanced = ta.apply(deepcopy(installed), table)
    bundle = compile_character(advanced, actor_id=OWNER)
    row = next(row for row in bundle['typed_passives'] if row.get('block') == frame.BLOCK)
    assert row['amount'] == 2 * 4
    assert bundle['actor_template']['maximum_hp'] == advanced['ability_scores_and_statistics']['hit_points']['maximum']


def test_receipt_replay_after_advancement_is_idempotent():
    installed = installed_cl8_sheet()
    integrated = receipt(installed, 'integrated', 1)
    once = ta.apply(deepcopy(installed), {'levels': [{'cl': 9}], 'source_events': [integrated]})
    twice = ta.apply(deepcopy(installed), {'levels': [{'cl': 9}], 'source_events': [integrated, dict(integrated)]})
    assert twice == once
