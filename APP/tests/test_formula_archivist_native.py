"""Native source acquisition through a real seeded build, without GUI consumers.

An observer stops after the actual Stage 2 commit/projection/owner sheet, before
GM/export consumers. It neither manufactures acquisition events nor certifies
portable release. That real acquired sheet then enters the ordinary table path.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile
import pytest

from app.core import FoundryError
from character_builder import CharacterBuilderService
from character_creation.service import CharacterCreationExecutionService
from character_sheet import CharacterSheetService
from project_store.service import ProjectStore
from projector.service import ProjectionService
from stage1.service import Stage1ClipboardService
from stage2 import Stage2AdvancementService

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_content import AN
from tests.r10_fixup_support import cast_sender, commit
from tests.test_lock2_persistence import act
from tests.test_formula_archivist_table import ROOT, ARCHIVIST, SPHERE, ADVANCED, COMMON, UNCOMMON, DISCOVERED, NAMESPACE


def test_native_acquisition_table_commit_cold_reload_and_mechanical_replay(catalog_environment, tmp_path, monkeypatch):
    # Native build scratch must stay on disk, inside this test's basetemp.
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    db = catalog_environment['db']
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name='Formula Archivist acceptance', concept='A talisman scholar who archives discovered formulae.',
        target_cl=8, power_band='standard', source_reference=None, creation_mode='detailed',
        generation_route='ai_bootstrap', ability_scores={},
        selections={'path_choice': ['tianxia.path.qi_cultivation'], 'insight_priorities': [ARCHIVIST]},
        canonical_sphere_ids=[SPHERE], sphere_free_talent_grants={SPHERE: COMMON},
        sphere_priority_ids=[SPHERE], talent_priority_ids=[ADVANCED], autogen_seed='QB-AAA111')
    pid = created['project_id']
    milestone = 'tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight.cl8'
    ordinary = ['hidden_sleeve_preparation', 'rapid_talisman', 'seal_breaker_s_eye', 'triggered_talisman',
                'advanced_talisman_crafting', 'battle_stroke_scripture', 'formula_copyist', 'talisman_recall']
    ProjectStore(db).append_user_locks(pid, [
        {'field': 'asi_or_insight:' + milestone, 'value': 'cultivation_insight'},
        {'field': 'insight_occurrence:' + milestone, 'value': {'insight_id': ARCHIVIST, 'parameters': {'ability': 'WIS'}}},
        *[{'field': f'ordinary_talent:{cl}', 'value': 'tianxia.talent.talismans.' + name}
          for cl, name in enumerate(ordinary, start=1)],
    ])
    builder.commit_normal_first_cycle_catalog_choices(pid)
    captured = {}

    def pipeline(scratch_db):
        sheets = CharacterSheetService(scratch_db)

        class StopBeforeExports:
            def build(self, project_id):
                captured['sheet'] = deepcopy(sheets.sheet(project_id)['owner_character_sheet'])
                with scratch_db.connection() as connection:
                    captured['events'] = [json.loads(row[0]) for row in connection.execute(
                        'SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no', (project_id,))]
                raise FoundryError('FORMULA_NATIVE_CAPTURE_COMPLETE', 'Native acquisition and owner sheet captured before GUI/export consumers.')

        return {'stage1': Stage1ClipboardService(scratch_db), 'stage2': Stage2AdvancementService(scratch_db),
                'projections': ProjectionService(scratch_db), 'character_sheets': sheets,
                'factory_authoring': StopBeforeExports(), 'gm_exports': None, 'gm_consumer': None,
                'portable_characters': None, 'production_release': None, 'combat_readiness': None}

    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None,
                                               project_store=ProjectStore(db), pipeline_factory=pipeline)
    try:
        result = creator.start(pid, execution_mode='STANDARD_API', idempotency_key='formula-native-acquisition',
                               controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    except FoundryError as exc:
        assert exc.code == 'FORMULA_NATIVE_CAPTURE_COMPLETE'
        result = {'diagnostics': [exc.code]}
    assert 'sheet' in captured, result.get('diagnostics', result)
    source_events = [event for event in captured['events']
                     if event.get('subject', {}).get('record_id') == ARCHIVIST
                     and event.get('advancement', {}).get('kind') == 'cultivation_insight_acquisition']
    assert len(source_events) == 1
    index = captured['events'].index(source_events[0])
    earlier = next(event['advancement']['calculation']['outputs']['ability_scores']
                   for event in reversed(captured['events'][:index])
                   if event.get('advancement', {}).get('calculation', {}).get('outputs', {}).get('ability_scores'))
    after = source_events[0]['advancement']['calculation']['outputs']['ability_scores']
    assert after == {**earlier, 'WIS': earlier['WIS'] + 1}
    assert after['WIS'] <= 20
    sheet = captured['sheet']
    assert ARCHIVIST in sheet['spheres_and_talents']['cultivation_insight_record_ids']
    assert SPHERE in sheet['spheres_and_talents']['sphere_record_ids']
    assert ADVANCED in sheet['spheres_and_talents']['learned_talent_record_ids']
    data = tmp_path / 'table-data'
    combat = CombatService(ROOT, data)
    package = combat.combatant_library.install_root / pid / 'current.zip'
    package.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    table = TabletopService(combat, data)

    def command(action, payload, key, gm=False):
        state = (table.buttons.get(pid).get('advancement') or {}).get('procedures', {}).get(NAMESPACE, {})
        return table.procedure(pid, NAMESPACE, action, payload, state.get('revision', 0), key, gm=gm)

    [menu] = [row for row in table.procedures(pid) if row['id'] == NAMESPACE]
    common = next(row['id'] for row in menu['grants'][0]['options'])
    uncommon = next(row['id'] for row in menu['grants'][1]['options'] if row['id'] == UNCOMMON) if any(
        row['id'] == UNCOMMON for row in menu['grants'][1]['options']) else menu['grants'][1]['options'][0]['id']
    command('choose', {'formula_id': common}, 'common')
    command('choose', {'formula_id': uncommon}, 'uncommon')
    [menu] = table.procedures(pid)
    discovered = menu['discoverable'][0]['id']
    command('discover', {'formula_id': discovered, 'discovery_id': 'found-tag',
                         'provenance': 'GM records this actual printed talisman found in the table scene.'}, 'discovery', gm=True)
    command('study', {'discovery_id': 'found-tag', 'minutes': 240}, 'study', gm=True)
    command('check', {'discovery_id': 'found-tag', 'd20': 20,
                     'roll_provenance': 'GM-confirmed physical crafting-check die.'}, 'check', gm=True)
    combat = CombatService(ROOT, data)
    table = TabletopService(combat, data)
    owner = FACTORY_ACTOR_PREFIX + pid
    known = combat._factory_owner_sheet(pid)['spheres_and_talents']['learned_talent_record_ids']
    assert {common, uncommon, discovered, UNCOMMON} <= set(known)
    combat.tabletop_maps.save({'display_name': 'Formula study yard', 'width_squares': 12, 'height_squares': 8,
                               'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[6, 4]]}})
    mid = combat.create_factory_match(project_ids=[pid], opponent_actor_ids=[AN], match_seed='FORMULA-NATIVE',
                                      arena_id='battlefield:map.formula-study-yard',
                                      control_modes={owner: 'MANUAL', AN: 'MANUAL'})['match_id']
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == owner:
            break
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Binding Talisman', target=AN))
    cold = CombatService(ROOT, data)
    assert cold.verify(mid)['status'] == 'PASS'
    assert cold.replay(mid)['status'] == 'PASS'


@pytest.mark.parametrize('ability', ['INT', 'WIS', 'CHA'])
def test_real_catalog_acquisition_menu_keeps_each_printed_ability(catalog_environment, ability):
    """Real source authority and native menu commits; no full-package claim."""
    from character_creation.creative_controller.linear_menus import CommittedState, build_insight_occurrence_menu
    from character_creation.creative_controller.linear_walk import commit_option
    from tests.test_insights_are_chosen import _envelope, _request, _starting_state, _milestone_id
    db = catalog_environment['db']
    with db.connection() as connection:
        rows = [json.loads(row[0]) for row in connection.execute(
            'SELECT data_json FROM catalog_records WHERE selected_authority=1')]
    [record] = [row for row in rows if row.get('record_id') == ARCHIVIST]
    authority = record['compatibility']['factory']['stage2_authority']
    assert authority['minimum_cl'] == 6
    assert set(authority['ability_change']['allowed_abilities']) == {'INT', 'WIS', 'CHA'}
    env = _envelope(8, insight_ids=())
    env['selection_limits_by_slot']['insight_priorities'].update(final_max=1, max_choices=1)
    env['choices_by_slot']['insight_priorities'] = {ARCHIVIST: {
        **Stage1ClipboardService._choice(record), 'stage2_authority': deepcopy(authority)}}
    for row in env['linear_provider_payload']['response_contract']['required_milestone_resolutions'].values():
        resolution = row['resolution_options']['cultivation_insight_acquisition']
        resolution['allowed_insight_ids'] = [ARCHIVIST]
        resolution['parameters_by_insight_id'] = {ARCHIVIST: {
            'allowed_abilities': authority['ability_change']['allowed_abilities'], 'amount': 1}}
    original = _starting_state(8)
    state = CommittedState(by_slot=original.by_slot,
                           pairs=({'sphere_id': SPHERE, 'talent_id': COMMON},),
                           bounded=deepcopy(original.bounded), ordinary_by_cl={}, insight_occurrences=(),
                           route_id=original.route_id)
    request, milestone = _request(8), _milestone_id(8)
    initial = state
    menu = build_insight_occurrence_menu(request, env, state, milestone_id=milestone)
    option = next(row for row in menu.options if row.choice_ids == (ARCHIVIST,))
    state = commit_option(menu, option.option_id, state)
    followup = build_insight_occurrence_menu(request, env, state, milestone_id=milestone, ability_follow_up=True)
    assert {row.choice_ids[0] for row in followup.options} == {'INT', 'WIS', 'CHA'}
    option = next(row for row in followup.options if row.choice_ids == (ability,))
    state = commit_option(followup, option.option_id, state)
    assert state.insight_occurrences[0]['parameters']['ability'] == ability
    capped_bounded = deepcopy(initial.bounded)
    capped_bounded['ability_scores'][ability] = 20
    capped = CommittedState(by_slot=initial.by_slot, pairs=initial.pairs,
                            bounded=capped_bounded, ordinary_by_cl={}, insight_occurrences=(),
                            route_id=initial.route_id)
    menu = build_insight_occurrence_menu(request, env, capped, milestone_id=milestone)
    option = next(row for row in menu.options if row.choice_ids == (ARCHIVIST,))
    capped = commit_option(menu, option.option_id, capped)
    menu = build_insight_occurrence_menu(request, env, capped, milestone_id=milestone, ability_follow_up=True)
    assert ability not in {row.choice_ids[0] for row in menu.options}
