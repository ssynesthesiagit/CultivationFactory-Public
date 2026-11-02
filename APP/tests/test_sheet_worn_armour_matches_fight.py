"""MMX73: the character sheet publishes the Armor Class and Speed the fight actually uses.

AUDIT9b (round 25, ``fa5e61b5``) found two halves of one defect.  ``combat/armour.py`` became the single
reader of both equipment slots and computes Armor Class and the Strength Speed penalty once, for the
fight.  The sheet was never moved onto it, so it kept publishing the unarmored calculation and the
unpenalized Speed:

  NEW-1  Heavy armour needs more Strength than the character has.  The fight moves 10 ft slower
         (``factory_compiler.py``) and the sheet said 30 ft.
  NEW-2  The sheet's Armor Class was the unarmored number only: no worn armour, no Shield's +2, no
         Refinement Bonus, all of which the fight includes.

Each test drives the two real consumers rather than a helper against itself: the owner-facing sheet is
built by ``CharacterSheetService._build_snapshot`` and the fight is compiled by ``compile_character``
(and, for the table test, read back through ``TabletopService.sheet``).  The numbers compared are the
ones a player reads.

The fix publishes the derived values *beside* the projection's own numbers, because this document is
also what the compiler reads: ``_ac_basis`` recovers the unarmored basis from ``armor_class.base_value``
and ``value``, and the Strength penalty is subtracted from ``speed.walking_ft``.  ``test_the_published
_sheet_still_compiles_to_the_same_actor`` is the guard for that: it feeds the finished sheet back into
the compiler and fails if the penalty is counted twice.
"""
from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from combat import armour
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_path_feature_statistics import BASELINE, _context
from tests.test_shield_possession_and_armor import (
    ROOT, AXE, HEAVY, SHIELD, _kit, _sheet,
    DRAGON_SCALES, STONE_SKIN, TEMPERED_FLESH, UNARMORED,
)
from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class

_ARTIFACTS = (
    'Character_Master_Ledger.json', 'Rules_Selection_Packets.json', 'Projection_Provenance_Map.json',
    'Projection_Coverage_Report.json', 'Projection_Diagnostics.json',
)


def _artifacts_for(sheet):
    """The public fixture's ledger, restated to describe the same character as ``sheet``.

    The fixture supplies the sheet's structure; every number the two consumers read is taken from
    ``sheet`` itself, so the ledger cannot drift away from the character under test.
    """
    with zipfile.ZipFile(ROOT / 'fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip') as archive:
        artifacts = {name: json.loads(archive.read(name)) for name in _ARTIFACTS}
    # AC fixtures describe a trained wielder, not permission inferred from carrying gear.
    artifacts['Character_Master_Ledger.json']['automatic_sphere_components'] = [
        {'component_id': 'SHIELD_BASE_SHIELD_TRAINING', 'name': 'Shield Training'}]
    stats = sheet['ability_scores_and_statistics']
    armor_class = stats['armor_class']
    artifacts['Character_Master_Ledger.json']['equipment'] = [{'starting_kit': sheet['equipment'][0]['starting_kit']}]
    artifacts['Character_Master_Ledger.json']['core_stats'].update(
        ac_base=int(armor_class['base_value']),
        ac_active=int(armor_class.get('value') or armor_class['base_value']),
        # The provenance travels with the number: ``armour.sheet_ac_bonuses`` resolves the sheet's AC
        # bonuses from it, so a ledger describing a different character would resolve different bonuses.
        ac_generation=deepcopy(armor_class.get('generation') or {}),
        speed_ft=int(stats['speed']['walking_ft']),
        ability_scores={row['ability']: int(row['score']) for row in stats['abilities']},
        ability_modifiers={row['ability']: int(row['modifier']) for row in stats['abilities']},
    )
    return artifacts


def _published_sheet(tmp_path, sheet, project_id='abcdef12'):
    """The owner-facing sheet exactly as the service publishes it."""
    return _written_sheet(tmp_path, sheet, project_id)[0]['ability_scores_and_statistics']


def _written_sheet(tmp_path, sheet, project_id='abcdef12'):
    """The owner-facing sheet as it is actually SAVED: the snapshot plus the document read back from disk.

    ``_build_snapshot`` writes ``Tianxia_Owner_Character_Sheet_v1.json`` and that file -- not the
    in-memory dict -- is what the compiler is handed on the next fight, so the round-trip tests must
    read it back rather than trust the object the service happened to return.
    """
    from tests.test_character_sheet_complete_character import _service

    service = _service(tmp_path)
    original_contract = service._display_contract
    def trained_contract(ledger, provenance):
        from app.core import sha256_json
        contract, _ = original_contract(ledger, provenance)
        contract = deepcopy(contract)
        printed = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())['SHIELD_BASE_SHIELD_TRAINING']
        # Extend the historical Fire fixture's display mapping with the actual printed component.
        # The production sheet builder still computes and writes every AC number.
        rule = deepcopy(contract['rules'][0])
        rule.update(record_id='SHIELD_BASE_SHIELD_TRAINING', display_name='Shield Training',
                    section='features', one_line_description=printed.splitlines()[1],
                    full_description=printed, display_timing_or_category='Passive',
                    acquisition_source={'packet_ids': [], 'target_cl': 1},
                    source={'path': 'APP/authority/typed_mechanics/rules_text.json',
                            'anchor': 'SHIELD_BASE_SHIELD_TRAINING',
                            'source_hash': __import__('hashlib').sha256(printed.encode()).hexdigest()})
        contract['rules'].append(rule)
        return contract, sha256_json(contract)
    service._display_contract = trained_contract
    _snapshot, artifact = service._build_snapshot(
        project={'project_id': project_id, 'revision': 1, 'user_locks': []},
        artifacts=_artifacts_for(sheet),
        projection_status={'status': 'READY', 'projection_id': f'MMX73-{project_id}'},
    )
    return json.loads(Path(artifact['path']).read_text(encoding='utf-8')), artifact


def _heavy_and_shield(strength):
    return _sheet(_kit(AXE, HEAVY, SHIELD), strength=strength, dex=16)


# ------------------------------------------------------------------ NEW-1: the Strength Speed penalty


def test_sheet_speed_matches_the_fight_when_the_armour_is_too_heavy(tmp_path):
    """Heavy armour needs Strength 15 and this character has 10, so the fight moves at 20 ft.

    Before the fix the sheet published ``speed.walking_ft`` alone -- the unpenalized 30 ft the
    projection recorded -- and no reader could ever see the compiler's own diagnostic.
    """
    sheet = _heavy_and_shield(strength=10)
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    statistics = _published_sheet(tmp_path, sheet)

    assert fight['speed_ft'] == 20
    assert statistics['speed']['effective_walking_ft'] == fight['speed_ft']
    assert statistics['speed']['effective_walking_ft'] == 20


def test_sheet_explains_the_speed_penalty_in_plain_words(tmp_path):
    """The player is told which armour costs Speed, how much, and why."""
    statistics = _published_sheet(tmp_path, _heavy_and_shield(strength=10))
    note = statistics['speed']['worn_note']

    assert "Imperial Plate Battle Dress" in note
    assert "Strength 15" in note and "has 10" in note
    assert "10 ft" in note and "20 ft" in note and "30 ft" in note
    # Readable by someone who knows only basic D&D: no internal ids, no jargon.
    assert "tianxia" not in note and "armor_class" not in note


def test_sheet_keeps_the_full_speed_when_strength_meets_the_requirement(tmp_path):
    """The penalty is a property of failing the requirement, not of wearing heavy armour."""
    sheet = _heavy_and_shield(strength=16)
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    statistics = _published_sheet(tmp_path, sheet)

    assert fight['speed_ft'] == 30
    assert statistics['speed']['effective_walking_ft'] == 30
    assert statistics['speed']['worn_note'] is None


# ------------------------------------------------------------------------- NEW-2: the effective Armor Class


def test_sheet_armor_class_matches_the_fight_with_worn_armour_and_shield(tmp_path):
    """Plate (18) plus a Shield (+2) is 20 in the fight; the sheet used to publish 14."""
    sheet = _heavy_and_shield(strength=10)
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    statistics = _published_sheet(tmp_path, sheet)

    assert fight['armor_class'] == 20
    assert statistics['armor_class']['effective_value'] == fight['armor_class']
    assert statistics['armor_class']['effective_value'] == 20


def test_sheet_explains_where_the_armor_class_comes_from(tmp_path):
    """The sentence names the armour, the Shield and the total, for a player who knows basic D&D."""
    statistics = _published_sheet(tmp_path, _heavy_and_shield(strength=10))
    published = statistics['armor_class']

    assert published['worn'] is True
    assert published['worn_armor'] == 'Imperial Plate Battle Dress'
    assert 'Wearing Imperial Plate Battle Dress' in published['worn_note']
    assert 'Shield' in published['worn_note']
    assert '20' in published['worn_note']
    assert 'tianxia' not in published['worn_note']


def test_sheet_armour_stays_carried_when_unarmored_is_better():
    """The design default is unchanged: worse armour is carried, and the sheet says so.

    This is the case ``test_armor_class_consumers.test_calculation_bonuses_keep_worse_armor_carried``
    pins at the fight; the sheet must reach the same answer from the same seam.  It is driven through
    ``armour.sheet_facts`` on the owner sheet itself rather than through the service, because reaching
    this state needs a Path's own AC calculation (Unarmored Defense) and the public fixture's Path
    cards are sealed -- restating a synthetic Path into the ledger would mean fabricating them.  Both
    consumers read the same document here, which is what the comparison is about.
    """
    features = [UNARMORED, STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH]
    sheet = _sheet(_kit(HEAVY), mids=features)
    result = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), features,
                                 baseline_rule=BASELINE, baseline_value=13, baseline_trace={},
                                 context=_context(con=3, dex=3, pb=4))
    sheet['ability_scores_and_statistics']['armor_class'] = {
        'base_value': result['ac_base'], 'value': result['ac_active'], 'generation': result['ac_generation']}
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    facts = armour.sheet_facts(sheet, sheet['equipment'][0]['starting_kit'])

    assert fight['armor_class'] == 20
    assert facts['armor_class'] == fight['armor_class']
    assert facts['worn'] is False
    assert 'Carrying Imperial Plate Battle Dress' in facts['armor_note']


@pytest.mark.parametrize('strength,expected_speed', [(10, 20), (15, 30), (16, 30)])
def test_sheet_and_fight_agree_across_the_strength_requirement(tmp_path, strength, expected_speed):
    """The agreement holds on both sides of the Strength requirement, not just below it."""
    sheet = _heavy_and_shield(strength=strength)
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    statistics = _published_sheet(tmp_path, sheet)

    assert fight['speed_ft'] == expected_speed
    assert statistics['speed']['effective_walking_ft'] == fight['speed_ft']
    assert statistics['armor_class']['effective_value'] == fight['armor_class']


# --------------------------------------------------------------------------- the published sheet is also the compiler's input


def test_the_published_sheet_still_compiles_to_the_same_actor(tmp_path):
    """The new fields are published *beside* the compiler's inputs, never over them.

    This sheet is written as ``Tianxia_Owner_Character_Sheet_v1.json`` and is exactly what the compiler
    reads next time: ``_ac_basis`` recovers the unarmored basis from ``armor_class.base_value``/``value``
    and the Strength penalty is subtracted from ``speed.walking_ft``.  If the fix had overwritten either,
    the fight would count the penalty twice (10 ft) or fold the armour into the always-on bonuses.

    The document compiled here is the one READ BACK FROM DISK after the service wrote it, not a
    hand-assembled stand-in: the review found this test previously rebuilt a substitute sheet and threw
    the published fields away, so it never exercised the file the fight really reads.
    """
    sheet = _heavy_and_shield(strength=10)
    written, artifact = _written_sheet(tmp_path, sheet)
    statistics = written['ability_scores_and_statistics']
    assert Path(artifact['path']).is_file(), "the service must have written the owner sheet"
    recompiled = compile_character(written, actor_id='actor:mmx73')['actor_template']

    # The fight run from the saved document agrees with the numbers the sheet published beside it.
    assert recompiled['armor_class'] == statistics['armor_class']['effective_value'] == 20
    assert recompiled['speed_ft'] == statistics['speed']['effective_walking_ft'] == 20
    # ...and the compiler's own inputs are still the unarmored projection, so nothing was double-counted.
    assert statistics['armor_class']['base_value'] == 14
    assert statistics['armor_class']['value'] == 14
    assert statistics['speed']['walking_ft'] == 30


def test_the_saved_sheet_survives_a_reload_with_the_same_fight_numbers(tmp_path):
    """A second build from the same ledger writes the same document, so a reload changes no number.

    Checklist item 7: what the sheet stores has to survive being written and read back.  The fight is
    compiled twice -- once from the document as saved, once from a fresh reload of that same file --
    and the two actors must agree on Armor Class and Speed, and match what the sheet published.
    """
    sheet = _heavy_and_shield(strength=10)
    written, artifact = _written_sheet(tmp_path, sheet)
    reloaded = json.loads(Path(artifact['path']).read_text(encoding='utf-8'))
    statistics = written['ability_scores_and_statistics']

    assert reloaded == written, "the saved sheet must round-trip through JSON unchanged"
    for document in (written, reloaded):
        actor = compile_character(document, actor_id='actor:mmx73')['actor_template']
        assert actor['armor_class'] == statistics['armor_class']['effective_value']
        assert actor['speed_ft'] == statistics['speed']['effective_walking_ft']


def test_the_unarmored_total_is_not_the_base_calculation():
    """The unarmored number a player weighs the armour against is the unarmored *total*.

    ``base_value`` is the chosen calculation before the standing bonuses are folded into ``value``: this
    character publishes base 17 and active 18, so "unarmored 17" -- what the lane rendered -- was wrong
    by the standing bonus and gave the player the wrong alternative to compare the armour against.
    """
    from tests.test_armor_class_consumers import projected_sheet

    sheet = projected_sheet(STONE_SKIN)
    sheet['equipment'] = [{'starting_kit': _kit(AXE, HEAVY, SHIELD)}]
    published = sheet['ability_scores_and_statistics']['armor_class']
    facts = armour.sheet_facts(sheet, sheet['equipment'][0]['starting_kit'])

    assert published['base_value'] == 17 and published['value'] == 18
    # The standing +1 that value already folded in belongs to the unarmored total too: 18, not 17.
    assert facts['unarmored'] == 18
    assert facts['unarmored'] != published['base_value']
    assert facts['armor_class'] == 20


def test_the_sheet_publishes_the_unarmored_total_beside_the_fight_number(tmp_path):
    """The saved sheet carries the unarmored alternative a player compares, not just the fighting AC.

    Driven through the real service and read back from the file it wrote, so this is the field the
    renderer actually reads.  It comes from the same ``sheet_facts`` derivation the service used, so the
    sheet and the fight cannot drift apart.
    """
    sheet = _heavy_and_shield(strength=10)
    written, _artifact = _written_sheet(tmp_path, sheet)
    published = written['ability_scores_and_statistics']['armor_class']
    actor = compile_character(written, actor_id='actor:mmx73')['actor_template']

    assert 'unarmored_value' in published
    assert published['effective_value'] == actor['armor_class'] == 20
    # Plate (18) + Shield (+2) is what the player is being weighed against, so the alternative is lower.
    assert published['unarmored_value'] == 14 < published['effective_value']
    # It is the character's own unarmored calculation, and never the projection's active value renamed.
    assert published['unarmored_value'] == armour.sheet_facts(
        written, written['equipment'][0]['starting_kit'])['unarmored']


def test_ac_provenance_the_compiler_and_the_historical_path_rely_on_is_untouched(tmp_path):
    """``base_value``/``value``/``generation`` stay load-bearing.

    ``_ac_basis`` reads ``base_value`` to recover the unarmored basis and ``armour.sheet_ac_bonuses``
    reverse-matches it against the printed formulas for sheets saved before provenance existed, so an
    older saved fight must still resolve.
    """
    from tests.test_armor_class_consumers import projected_sheet

    sheet = projected_sheet(STONE_SKIN)
    sheet['equipment'] = [{'starting_kit': _kit(AXE, HEAVY, SHIELD)}]
    sheet['ability_scores_and_statistics']['abilities'] = [
        {**row, 'score': 10 if row['ability'] == 'STR' else row['score'],
         'modifier': 0 if row['ability'] == 'STR' else row['modifier']}
        for row in sheet['ability_scores_and_statistics']['abilities']]
    projected = sheet['ability_scores_and_statistics']['armor_class']
    statistics = _published_sheet(tmp_path, sheet)
    published = statistics['armor_class']

    assert published['base_value'] == projected['base_value']
    assert published['value'] == projected['value']
    assert published['generation'] == projected['generation']
    # The effective number is the one a fight uses, and it is a different field.
    assert published['effective_value'] == 20
    assert compile_character(sheet, actor_id='actor:mmx73')['actor_template']['armor_class'] == 20


# ------------------------------------------------------------------------------------- inertness


def test_a_sheet_with_no_starting_kit_publishes_no_armour_facts(tmp_path):
    """A character whose sheet records no kit is untouched: the seam is inert and the fight is unchanged.

    The public C1A proof character leaves the optional equipment subsystem absent, which is the shape
    every sheet written before the equipment ledger existed has.
    """
    from tests.test_character_sheet_complete_character import _service

    with zipfile.ZipFile(ROOT / 'fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip') as archive:
        artifacts = {name: json.loads(archive.read(name)) for name in _ARTIFACTS}
    snapshot, _artifact = _service(tmp_path)._build_snapshot(
        project={'project_id': 'abcdef12', 'revision': 1, 'user_locks': []},
        artifacts=artifacts, projection_status={'status': 'READY', 'projection_id': 'MMX73-no-equipment'})
    published = snapshot['ability_scores_and_statistics']

    assert 'effective_value' not in published['armor_class']
    assert 'effective_walking_ft' not in published['speed']
    # Inert at the seam too: nothing worn, so the sheet's own numbers stand.
    assert armour.sheet_facts(snapshot, {})['armor_class'] == published['armor_class']['value']


def test_a_shield_alone_is_reported_with_its_bonus(tmp_path):
    """A Shield is carried, not worn, and still grants its +2 to both readers."""
    sheet = _sheet(_kit(AXE, SHIELD), strength=10, dex=16)
    fight = compile_character(sheet, actor_id='actor:mmx73')['actor_template']
    statistics = _published_sheet(tmp_path, sheet)

    assert fight['armor_class'] == 16  # 10 + Dexterity 3, plus the Shield's 2
    assert statistics['armor_class']['effective_value'] == 16
    assert statistics['armor_class']['worn'] is False
    assert 'Shield' in statistics['armor_class']['worn_note']


# ------------------------------------------------------------------------------ the table is the same number


def test_the_sheet_and_the_table_agree_on_armor_class_and_speed(tmp_path):
    """The bug the player saw: the sheet said one thing, the table rolled another.

    Driven through the real services -- the sheet is built from the ledger, the table's sheet payload is
    compiled from the installed package by the same compiler the fight uses.
    """
    from tests.test_armor_class_consumers import _install_sheet

    project_id = 'abcdef12'
    sheet = _heavy_and_shield(strength=10)
    statistics = _published_sheet(tmp_path, sheet, project_id=project_id)
    _install_sheet(tmp_path, sheet, project_id)
    payload = TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet(project_id)

    assert payload['summary']['armor_class'] == statistics['armor_class']['effective_value']
    assert payload['summary']['armor_class'] == 20
    assert compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + project_id)['actor_template']['speed_ft'] == \
        statistics['speed']['effective_walking_ft']

