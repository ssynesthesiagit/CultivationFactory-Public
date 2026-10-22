"""Native Foundation projection, typed GM inputs, table commits and cold replay.

No direct ability calls, resource/condition/ownership flags, GUI or model server.
"""
import hashlib
import json
import pytest

from combat import protected_subjects
from combat.ext import foundation_combat as f
from combat.ext.iron_oath import POWER, FRAME
from combat.tabletop_service import TabletopError
from tests.iron_oath_support import duty
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn, settle
from tests.h1_support import ROOT
from tests.test_initial_foundation_versions import foundation_project


def native_acquired_sheet(foundation_project, tmp_path):
    """Actual CL5 causal acquisition, source validation and cold event replay."""
    from tests.test_initial_method_versions import _initial_method_events
    from tests.test_rec1_p1cr5_owner_authority import _private_scope
    from character_creation.path_attainment import native_path_progressions
    from projector.foundation_mechanics import validate_initial_foundation_mechanics
    from tests.h1_support import sheet
    creator, project, run, intent, _ = foundation_project
    paths = ['tianxia.path.body_refining', 'tianxia.path.spirit_awakening']
    stage2, events, state = _initial_method_events(creator, project, run, intent, 'METHOD-083', paths)
    proposal = {'project_id': project['project_id'], 'proposal_id': 'iron-oath-native-acquisition',
                'expected_project_revision': project['revision'], 'idempotency_key': 'iron-oath-native',
                'created_at': '2026-09-07T00:00:00+00:00'}
    with _private_scope(stage2, run['request'], run['run_id'], set(paths)), creator.db.connection() as conn:
        record = stage2._resolve_record_after_proof(conn, project['project_id'], 'iron_oath_skin_v0_2B')
        path_records = [stage2._resolve_record_after_proof(conn, project['project_id'], p) for p in paths]
        for cl in range(2, 6):
            feature = path_records[0]['compatibility']['factory']['stage2_authority']['progression_by_cl'][str(cl)]['feature_record_ids'][0]
            channel = events[-1]['legal_channel'] if cl == 2 else level_channel
            level_channel = channel
            choices = [{'kind': 'level_advance', 'record_id': feature, 'effective_cl': cl,
                        'acquisition_channel': channel, 'parameters': {'native_path_progressions': native_path_progressions(path_records, cl)}}]
            if cl == 5:
                choices.append({'kind': 'foundation_acquisition', 'record_id': 'iron_oath_skin_v0_2B',
                    'effective_cl': 5, 'acquisition_channel': 'foundation-selection', 'parameters': {'stage': 'Awakened'}})
            for choice in choices:
                event, state, blockers = stage2._choice_event(conn=conn, row=proposal, project=project, state=state,
                    choice=choice, index=len(events), sequence=len(events) + 1, previous_hash=events[-1]['event_hash'],
                    generic_prefix=events, record_cache={})
                assert not blockers, blockers
                assert event is not None
                events.append(event)
    path = tmp_path / 'acquisition.json'
    path.write_text(json.dumps(events))
    events = json.loads(path.read_text())
    replayed, _, _ = stage2._rows(events, project['project_id'])
    assert replayed['hp'] == state['hp']
    foundation = validate_initial_foundation_mechanics(record, events)
    assert foundation['resource']['current'] == 0
    document = sheet([], cl=5, primary='Stamina', kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}})
    document['foundation'] = foundation
    document['path_and_subpath'] = {'path_record_ids': paths, 'path_feature_record_ids': list(dict.fromkeys(
        feature for event in events for feature in ((event.get('advancement', {}).get('calculation') or {}).get('outputs') or {}).get('automatic_feature_record_ids', [])))}
    document['identity']['project_id'] = project['project_id']
    document['identity']['proficiency_bonus'] = 3
    document['ability_scores_and_statistics']['hit_points']['maximum'] = state['hp']['total']
    assert state['hp']['foundation_delta'] == 3
    return document


@pytest.fixture(scope='module')
def native_oath_document(catalog_environment, tmp_path_factory):
    """One real immutable acquisition shared by independent native play arms.

    Rebuilding the full creator's locked source catalogue for each damage/choice
    variant adds no acquisition evidence. Each arm cold-copies the same actual
    source-produced sheet into an isolated campaign and still commits/replays.
    """
    from tests.test_creation_training_r4 import _real_creation_intent
    project = _real_creation_intent(catalog_environment)
    return native_acquired_sheet(project, tmp_path_factory.mktemp('iron-oath-acquisition'))




@pytest.mark.parametrize('kind', ['ally', 'doorway', 'warded_place', 'helpless_creature', 'duty'])
def test_whole_declaration_subjects_generation_and_cold_replay(tmp_path, kind):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    subject = ALLY if kind in {'ally', 'helpless_creature'} else 'scene:eastern-gate'
    duty(s, t, m, kind=kind, subject=subject)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [subject]})
    e = reload(tmp_path, m)
    owner = e.state.actors[OWNER]
    assert f.held(owner, 'protected_subject').data['subject_kind'] == kind
    assert owner.action_available and owner.bonus_action_available
    assert protected_subjects.defending(e, owner, subject)
    turn(t, m, FOE)
    use(s, t, m, 'Hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == POWER + '.iron_oath_guard' for ev in e.events)


@pytest.mark.parametrize('status', ['separated', 'obscured', 'conflicted', 'abandoned', 'not_defending'])
def test_defense_correction_blocks_generation_and_guard_without_spending(tmp_path, status):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    duty(s, t, m, status=status)
    turn(t, m, FOE)
    prompts = use(s, t, m, 'Hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert not any('Iron Oath Guard' in str(p) for p in prompts)


def test_fact_correction_cannot_silently_rename_the_declared_subject(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    duty(s, t, m, kind='doorway', subject='scene:replacement-gate', record_id=ALLY)
    turn(t, m, FOE)
    use(s, t, m, 'Hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert f.held(e.state.actors[OWNER], 'protected_subject').data['subject'] == ALLY
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0


def test_meaningful_unknown_expired_and_wrong_audience_are_not_defense(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    doc = duty(s, t, m, meaningful=False)
    e = reload(tmp_path, m)
    assert not protected_subjects.duties(e, e.state.actors[OWNER])
    assert not protected_subjects.defending(e, e.state.actors[OWNER], 'unknown')
    assert not protected_subjects.duties(e, e.state.actors[FOE])
    doc['witness_ids'] = [FOE]
    with pytest.raises(TabletopError):
        t.record_fact(m, doc, expected_state_version=e.state.state_version)


def test_native_separation_invalidates_actual_defense(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    e = s._load_session(m).engine
    move = next(c for c in e.legal_candidates() if c.source_definition_id == 'system:combat.movement'
                and c.destination and (c.destination.x, c.destination.y) == (1, 6))
    settle(t, m, move.candidate_id)
    e = reload(tmp_path, m)
    assert not protected_subjects.defending(e, e.state.actors[OWNER], ALLY)


def test_native_map_object_is_a_real_protected_subject(tmp_path):
    def furnish(arena):
        arena['map_objects'] = [{'id': 1, 'kind': 'crate', 'x': 3, 'y': 7}]
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened', battlefield_transform=furnish)
    e = reload(tmp_path, m)
    obj = next(iter(e.state.objects.values()))
    duty(s, t, m, kind='object', subject=obj.object_id)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [obj.object_id]})
    turn(t, m, FOE)
    use(s, t, m, 'Hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert f.held(e.state.actors[OWNER], 'protected_subject').data['subject'] == obj.object_id


@pytest.mark.parametrize('kind,qualifies', [('object', False), ('doorway', True)])
def test_destroyed_marker_does_not_erase_an_admitted_doorway(tmp_path, monkeypatch, kind, qualifies):
    from combat.factory_compiler import compile_character
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.canonical import canonical_sha256
    from tests.h1_support import sheet
    from tests.worker2_support import sealed_native_attack
    from tests.equipment_readiness import ready_table_weapon
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(18, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    def furnish(arena):
        arena['map_objects'] = [{'id': 1, 'kind': 'crate', 'x': 4, 'y': 5}]
    def enemy(bundles):
        doc = sheet([], cl=5, kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu'}]}})
        foe = compile_character(doc, actor_id=FOE, reaction_plan={'ask': True})
        sealed_native_attack(foe, 'Pressure after breaking the marker', count=1, sides=2, modifier=1, attack_bonus=100, range_ft=5)
        foe['action_catalog'][-1]['economy'] = 'BONUS_ACTION'
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)
        bundles[2] = foe
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened', transform=enemy, battlefield_transform=furnish)
    oid = 'object:map.1'
    # The GM distinguishes an object from the doorway it marks; no destroyed
    # flag, damage or ownership is injected. The enemy really breaks the marker.
    duty(s, t, m, kind=kind, subject=oid)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [oid]})
    turn(t, m, FOE)
    e = s._load_session(m).engine
    weapon = next(a for a in e.action_catalog.values() if a.owner_id == FOE and (a.parameters.get('typed') or {}).get('weapon'))
    ready_table_weapon(t, m, weapon.source_definition_id)
    e = s._load_session(m).engine
    attack = next(a for a in e.action_catalog.values() if a.owner_id == FOE and a.parameters.get('object_attack'))
    use(s, t, m, attack.display_name, oid)
    assert reload(tmp_path, m).state.objects[oid].destroyed
    use(s, t, m, 'Pressure after breaking the marker', OWNER)
    e = reload(tmp_path, m)
    assert protected_subjects.defending(e, e.state.actors[OWNER], oid) is qualifies
    assert e.state.actors[OWNER].resources[f.pool('oath')] == int(qualifies)


def test_existing_guard_spend_cannot_regenerate_in_the_same_round(tmp_path):
    from tests.test_mgr_t14_iron_oath_2 import encounter
    s, t, m = encounter(tmp_path, stage='Awakened', expression=None)
    use(s, t, m, 'Second hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert not e.state.actors[OWNER].reaction_available
    spends = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == POWER + '.iron_oath_guard']
    assert len(spends) == 1




def test_explicit_power_suppression_preserves_frame_and_blocks_resource(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    before = reload(tmp_path, m).state.actors[OWNER].maximum_hp
    effect = {'actor_id': OWNER, 'power_id': POWER, 'state': 'suppressed', 'effect_kind': 'suppression',
              'scope': 'resources', 'resource_ids': [f.pool('oath')], 'reason': 'Broken Guard prevents Guarding Iron for this recorded scene effect.'}
    duty(s, t, m, power_states=[effect])
    turn(t, m, FOE)
    use(s, t, m, 'Hostile blow', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].maximum_hp == before
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0
    effect.update(state='fully_severed', effect_kind='story_severance', scope='power', reason='The named story ritual fully severs the Foundation.')
    duty(s, t, m, power_states=[effect])
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].maximum_hp == before - 4
    duty(s, t, m, power_states=[effect])
    assert reload(tmp_path, m).state.actors[OWNER].maximum_hp == before - 4


def test_native_movement_qualifies_pressure_without_fabricated_threat(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    e = reload(tmp_path, m)
    assert not protected_subjects.qualified_pressure(e, e.state.actors[OWNER], ALLY, e.state.actors[FOE])
    turn(t, m, FOE)
    e = s._load_session(m).engine
    move = next(c for c in e.legal_candidates() if c.source_definition_id == 'system:combat.movement'
                and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    settle(t, m, move.candidate_id)
    e = reload(tmp_path, m)
    assert protected_subjects.qualified_pressure(e, e.state.actors[OWNER], ALLY, e.state.actors[FOE])
    duty(s, t, m, pressures=[{'actor_id': FOE, 'kind': 'attempted_bypass', 'verdict': 'artificial_denied',
                            'evidence': 'The GM rejects this staged approach as an artificial attempt to qualify the target.'}])
    e = reload(tmp_path, m)
    assert not protected_subjects.qualified_pressure(e, e.state.actors[OWNER], ALLY, e.state.actors[FOE])


def test_native_damage_to_subject_qualifies_the_actual_attacker(tmp_path):
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    turn(t, m, FOE)
    use(s, t, m, 'Hostile blow', ALLY)
    e = reload(tmp_path, m)
    assert protected_subjects.qualified_pressure(e, e.state.actors[OWNER], ALLY, e.state.actors[FOE])
    assert not protected_subjects.qualified_pressure(e, e.state.actors[OWNER], ALLY, e.state.actors[OWNER])
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0


def test_source_local_restoration_preserves_other_power_suppressions(tmp_path):
    from combat.ext.iron_oath import available
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened')
    suppression = {'actor_id': OWNER, 'power_id': POWER, 'state': 'suppressed', 'effect_kind': 'suppression',
                   'scope': 'power', 'resource_ids': [], 'reason': 'A recorded hostile ritual suppresses the whole Foundation.'}
    duty(s, t, m, record_id='hostile-ritual', power_states=[suppression])
    restoration = {**suppression, 'state': 'available', 'effect_kind': 'restoration',
                   'reason': 'A different, resource-only suppression has ended.'}
    duty(s, t, m, record_id='separate-effect', power_states=[restoration])
    e = reload(tmp_path, m)
    assert not available(e, e.state.actors[OWNER], require_resource=False)
    duty(s, t, m, record_id='hostile-ritual', power_states=[restoration])
    e = reload(tmp_path, m)
    assert available(e, e.state.actors[OWNER], require_resource=False)


def test_native_opportunity_attack_generates_after_real_acquisition_and_movement(tmp_path, native_oath_document, monkeypatch):
    from combat.factory_compiler import compile_character
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.gate2_runtime_content import AN
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    document = json.loads(json.dumps(native_oath_document))
    document['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    bundles = [compile_character(document, actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(sheet([], cl=5), actor_id=ALLY, reaction_plan={'ask': True})]
    s = CombatService(ROOT, tmp_path)
    t = TabletopService(s, tmp_path)
    m = s._finish_factory_match(bundles, [OWNER, ALLY, AN],
        {OWNER: 'team:a', ALLY: 'team:a', AN: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, AN: {'x': 3, 'y': 5}},
        s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [AN],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', AN: 'MANUAL'},
        match_seed='IRON-OATH-NATIVE-OPPORTUNITY', display_name='Native oath defense', maximum_rounds=15)['match_id']
    turn(t, m, OWNER)
    s.set_controller_mode(m, actor_id=AN, controller_mode='LOCAL_AUTO')
    duty(s, t, m)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    e = s._load_session(m).engine
    move = next(c for c in e.legal_candidates() if c.source_definition_id == 'system:combat.movement'
                and c.destination and (c.destination.x, c.destination.y) == (3, 7))
    settle(t, m, move.candidate_id, choices={'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    e = reload(tmp_path, m)
    damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED'
              and ev.source_definition_id == SYSTEM_OPPORTUNITY and OWNER in ev.target_ids]
    assert damage and damage[-1].payload['hp_damage'] > 0
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 1




def test_exact_six_controlling_sources():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    expected = {
        'declare_protected_subject': '5b6c8e259bec0768c374d9b37d2ed0d528990128f445de3235ecd6e929326231',
        'generate_guarding_iron': '740597f6cd45f1fc477c2491b603c286ff0cef2b86ca875d4d4df96d62c0000a',
        'oath_skin_frame': '77f358d41a5453c702cf0bc2045cc856f356c79723e17aa4183e481aecbd2098',
        'iron_interposition': '790d6f965fa8e098e6daaf1dcae738887a21ba3feae841c2e916fcdecbe3aaf8',
        'iron_oath_guard': 'd960b9e12b9eb88d384958c593c1f536c981ac088e7f5a2ef9e5353d68835c68',
        'oath_mark_strike': '8f4c50fdbf6decc57b4c3753e4ea5332475ba1cd31ec160066b3d896f608cc05',
    }
    for leaf, digest in expected.items():
        assert hashlib.sha256(text[POWER + '.' + leaf].encode()).hexdigest() == digest
