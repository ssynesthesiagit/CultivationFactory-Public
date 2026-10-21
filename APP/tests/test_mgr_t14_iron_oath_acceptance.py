"""Focused native Iron Oath acceptance; one acquisition fixture, exact scope.

Kept separate because the private-CI adapter currently executes whole files
before filtering requested selectors. These are moved assertions, not copies.
"""
import hashlib
import json
import pytest
from combat.ext import foundation_combat as f
from combat.ext.iron_oath_consumers import SCAR, SCAR_BAR
from combat.tabletop_service import TabletopError
from tests.test_mgr_t14_iron_oath_consumers import (
    ROOT, ALLY, FOE, OWNER, duty, use, turn, reload, oath_table, record_project,
)
from tests.test_mgr_t14_iron_oath_producer import POWER, native_oath_document
from tests.test_a2_foundations_two import table_fixture
from tests.worker2_support import settle


def test_witness_native_project_check_on_own_turn(tmp_path):
    combat, table, mid = oath_table(tmp_path)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    record_project(combat, table, mid, kind='foundation_challenge')
    prompts = use(combat, table, mid, 'Resolve a project check', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert any('Stand Fast Witness' in str(prompt) for prompt in prompts)
    assert any(e.event_type == 'D20_REWRITTEN' and e.payload.get('bonus') == 4 for e in engine.events)



def test_witness_uses_printed_sphere_from_actual_technique(tmp_path):
    combat, table, mid = oath_table(tmp_path, foe_talents=['TAL_GUARDIAN_BODYGUARD'], pressure_economy='ACTION')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    prompts = use(combat, table, mid, 'Challenge Practice', OWNER,
                  choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    assert any('Stand Fast Witness' in str(prompt) for prompt in prompts)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert any(e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')
               and e.payload['bonus'] == 4 for e in engine.events)



def test_project_scope_and_pressure_do_not_leak_to_other_plans(tmp_path):
    combat, table, mid = oath_table(tmp_path)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    first = record_project(combat, table, mid, kind='foundation_challenge', sphere=None,
                           limitation=False, fixed_scope=True, record_id='project:iron-oath-trial')
    source = first['technique_scopes'][0]['source_definition_id']
    bad = json.loads(json.dumps(first))
    bad['technique_scopes'][0]['source_definition_id'] = next(
        a.source_definition_id for a in reload(tmp_path, mid).action_catalog.values()
        if a.owner_id == FOE and a.display_name == 'Frightful Roar')
    with pytest.raises(TabletopError):
        table.record_fact(mid, bad, expected_state_version=reload(tmp_path, mid).state.state_version)
    first['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['check'], 'categories': ['oath_interpretation'],
        'toward_subject': False, 'evidence': 'Only this recorded hearing interprets the bearer’s protection oath.'}]
    table.record_fact(mid, first, expected_state_version=reload(tmp_path, mid).state.state_version)
    second = record_project(combat, table, mid, kind='foundation_challenge', sphere='magma',
                            limitation=False, record_id='project:unrelated-magma')
    second['project_check'].update(limitation_kind='defensive_drawback',
        limitation='The unrelated magma trial requires one empty hand, without an oath, ward or protected subject.')
    table.record_fact(mid, second, expected_state_version=reload(tmp_path, mid).state.state_version)
    third = record_project(combat, table, mid, kind='scene_check', limitation=False,
                           record_id='project:unrelated-scene')
    for other in (second, third):
        use(combat, table, mid, 'Resolve a project check', choices={
            f.CHOICE + 'project_check': [other['record_id']], f.CHOICE + 'foundation_combat': ['use']})
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[f.pool('oath')] == 1
        assert not any(e.event_type == 'D20_REWRITTEN'
                       and e.source_definition_id == f.feature('oath', 'stand_fast_witness') for e in engine.events)
    first['roll_pressures'] = []  # the final offer must come from this project's source interpretation
    table.record_fact(mid, first, expected_state_version=reload(tmp_path, mid).state.state_version)
    use(combat, table, mid, 'Resolve a project check', choices={
        f.CHOICE + 'project_check': [first['record_id']], f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]) == 1



def test_project_unknown_scope_wrong_audience_and_invalid_recipe(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Refined')
    document = record_project(combat, table, mid, owner=FOE, kind='foundation_challenge')
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog.get(c.source_definition_id) and
                   engine.action_catalog[c.source_definition_id].display_name == 'Resolve a project check'
                   for c in engine.legal_candidates())
    document['project_check']['challenge_dc'] = None
    with pytest.raises(TabletopError):
        table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)



@pytest.mark.parametrize('known_source', [False, True])
def test_scar_scene_pressure_uses_admitted_counterparty_without_inventing_a_roll_issuer(tmp_path, known_source):
    combat, table, mid = oath_table(tmp_path, stage='Refined')
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    document = record_project(combat, table, mid, kind='scene_check', challenge_dc=1)
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Resolve a project check')
    document['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['check'], 'categories': ['frightened'],
        'toward_subject': False, 'evidence': 'The recorded scene check contests fear during the interrogation of the protected oath.'}]
    if known_source:
        document['project_check'].update(pressure_source_actor_id=FOE,
            pressure_evidence='The invader personally made the recorded threat during the interrogation; the bearer heard and identified it.')
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)
    use(combat, table, mid, 'Resolve a project check', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    event = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED')
    assert event.actor_id == OWNER and event.source_definition_id == source
    assert event.payload.get('pressure_fact_record_id') == (document['record_id'] if known_source else None)
    assert 'pressure_evidence' not in event.payload and 'pressure_source_actor_id' not in event.payload
    assert any(event.event_type == 'CONDITION_APPLIED' and event.source_definition_id == SCAR
               and FOE in event.target_ids for event in engine.events) is known_source
    assert not any(c.condition_id.startswith(SCAR_BAR) for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0



def test_native_causal_acquisition_to_witness_project_commit_reload(tmp_path, native_oath_document):
    from tests.worker2_support import fixture, sealed_native_attack
    from combat.factory_compiler import compile_character
    from combat.canonical import canonical_sha256
    from tests.h1_support import sheet
    document = json.loads(json.dumps(native_oath_document))
    OWNER = 'actor:factory.' + document['identity']['project_id']
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    def attacks(bundles):
        sealed_native_attack(bundles[2], 'Invader strike', modifier=4, attack_bonus=50, range_ft=5)
        bundles[2]['action_catalog'][-1]['economy'] = 'ACTION'
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    root = tmp_path / 'native-play'
    combat, table, mid = fixture(root, [], owner_bundle=bundle, owner_document=document,
        foe_sheet=sheet(['TAL_GUARDIAN_BODYGUARD'], cl=15, dc=100),
        foe_position={'x': 3, 'y': 5}, bundle_transform=attacks, seed='IRON-OATH-CONSUMER-ACQUIRED', owner_id=OWNER)
    assert combat._factory_owner_sheet(document['identity']['project_id'])['foundation'] == document['foundation']
    duty(combat, table, mid, owner_id=OWNER)
    use(combat, table, mid, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    turn(table, mid, FOE)
    decline_guard = {'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None}
    use(combat, table, mid, 'Invader strike', OWNER, choices=decline_guard)
    turn(table, mid, OWNER)
    assert reload(root, mid).state.actors[OWNER].resources[f.pool('oath')] == 1
    first = record_project(combat, table, mid, kind='foundation_challenge', sphere=None,
        limitation=False, fixed_scope=True, owner=OWNER, record_id='project:native-iron-oath-trial')
    source = first['technique_scopes'][0]['source_definition_id']
    bad = json.loads(json.dumps(first))
    bad['technique_scopes'][0]['source_definition_id'] = next(
        a.source_definition_id for a in reload(root, mid).action_catalog.values()
        if a.owner_id == FOE and a.display_name == 'Challenge Practice')
    with pytest.raises(TabletopError):
        table.record_fact(mid, bad, expected_state_version=reload(root, mid).state.state_version)
    first['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['check'], 'categories': ['oath_interpretation'],
        'toward_subject': False, 'evidence': 'Only this recorded hearing interprets the bearer’s protection oath.'}]
    table.record_fact(mid, first, expected_state_version=reload(root, mid).state.state_version)
    second = record_project(combat, table, mid, kind='foundation_challenge', sphere='magma',
        limitation=False, owner=OWNER, record_id='project:native-unrelated-magma')
    second['project_check'].update(limitation_kind='defensive_drawback',
        limitation='This unrelated magma trial requires an empty hand, without an oath, ward or protected subject.')
    table.record_fact(mid, second, expected_state_version=reload(root, mid).state.state_version)
    third = record_project(combat, table, mid, kind='scene_check', limitation=False,
        owner=OWNER, record_id='project:native-unrelated-scene')
    for other in (second, third):
        use(combat, table, mid, 'Resolve a project check', choices={
            f.CHOICE + 'project_check': [other['record_id']], f.CHOICE + 'foundation_combat': ['use']})
        e = reload(root, mid)
        assert e.state.actors[OWNER].resources[f.pool('oath')] == 1
        assert not any(event.event_type == 'D20_REWRITTEN'
                       and event.source_definition_id == f.feature('oath', 'stand_fast_witness') for event in e.events)
    first['roll_pressures'] = []
    table.record_fact(mid, first, expected_state_version=reload(root, mid).state.state_version)
    use(combat, table, mid, 'Resolve a project check', choices={
        f.CHOICE + 'project_check': [first['record_id']], f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(root, mid)
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                 and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert len(rewritten) == 1 and rewritten[-1].payload['bonus'] == 3
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0
    turn(table, mid, FOE)
    use(combat, table, mid, 'Invader strike', OWNER, choices=decline_guard)
    assert reload(root, mid).state.actors[OWNER].resources[f.pool('oath')] == 1
    use(combat, table, mid, 'Challenge Practice', OWNER,
        choices={**decline_guard, f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(root, mid)
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                 and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert len(rewritten) == 2 and rewritten[-1].payload['bonus'] == 3
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0



@pytest.mark.parametrize('expressions', [('oath_skin_mantle', 'scar_ledger_defense'),
                                         ('iron_interposition', 'shield_body_forging')])
def test_native_causal_acquisition_and_recorded_attainment_reach_all_consumers(tmp_path, native_oath_document, expressions):
    """Real acquisition, source assessments, native outcomes and sealed choices."""
    import zipfile
    from combat.factory_compiler import compile_character
    from tests.test_mgr_t14_iron_oath_producer import native_acquired_sheet
    from tests.worker2_support import fixture, sealed_native_attack
    from combat.canonical import canonical_sha256
    from tests.h1_support import sheet
    native = json.loads(json.dumps(native_oath_document))
    OWNER = 'actor:factory.' + native['identity']['project_id']
    bundle = compile_character(native, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path / 'attainment', [], owner_id=OWNER, owner_bundle=bundle, owner_document=native, seed='IRON-OATH-ATTAINMENT')
    pid = OWNER.removeprefix('actor:factory.')
    # Store the actual creator-produced sheet, not a literal higher-stage fixture.
    package = tmp_path / 'attainment' / 'portable_characters' / pid / 'current.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(native))
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    app = create_app(Settings.from_env(ROOT, tmp_path / 'attainment'))
    app.state.agent_seats.background = False
    def record_attainment(document):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
                url = f'/api/tabletop/characters/{pid}/foundation-attainments'
                denied = await client.post(url, json={'document': document})
                assert denied.status_code in (401, 403)
                token = (await client.get('/api/session')).json()['token']
                accepted = await client.post(url, headers={'x-foundry-token': token}, json={'document': document})
                assert accepted.status_code == 200, accepted.text
                return accepted.json()
        return run_asgi(request())
    previous = 'Awakened'
    for index, stage in enumerate(('Integrated', 'Refined', 'Perfected')):
        reference = ('Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md#26; '
                     'Iron_Oath_Skin_R1G_Runtime_Rewrite_v0_2B.md#Foundation-Challenge-Routes; '
                     f'campaign:actual-attainment:{stage}')
        record_id = f'project:iron-oath-attainment:{index}'
        record_project(combat, table, mid, kind='foundation_challenge', record_id=record_id,
                       challenge_dc=5, source_reference=reference, owner=OWNER)
        request = {'foundation_id': f.GROUPS['oath'][0], 'previous_stage': previous, 'stage': stage,
            'source_reference': reference,
            'requirements_met': (['Protected without controlling', 'Accepted protection', 'Clarified the oath']
                if stage == 'Integrated' else ['Actual protective duty', 'Body tempering completed',
                    'Oath clarified', 'Compatible Sphere training completed', 'Rigidity/scar pressure treated']),
            'time_spent': 'The recorded Foundation scene and compatible training time were completed.',
            'costs_paid': ['Scene time, compatible oath/guard practice and witness support'],
            'success_result': f'The printed route has resulted in attained {stage} Iron Oath Skin.',
            'failure_result': 'No attainment on failure; source-specific injury or strain consequences remain in force.',
            'proof_match_id': mid, 'proof_project_record_id': record_id}
        if stage == 'Refined':
            request['selected_expression_ids'] = [f.feature('oath', leaf) for leaf in expressions]
        if stage == 'Integrated':
            with pytest.raises(TabletopError):
                table.record_foundation_attainment(pid, {**request, 'stage': 'Perfected'})
        with pytest.raises(TabletopError):
            table.record_foundation_attainment(pid, request)
        use(combat, table, mid, 'Resolve a project check')
        if stage == 'Refined':
            with pytest.raises(TabletopError):
                table.record_foundation_attainment(pid, {**request, 'selected_expression_ids': request['selected_expression_ids'][:1]})
        assert record_attainment(request)['stage'] == stage
        with pytest.raises(TabletopError):
            table.record_foundation_attainment(pid, request)
        with pytest.raises(TabletopError):
            table.record_foundation_attainment(ALLY.removeprefix('actor:factory.'), request)
        previous = stage
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    cold_table = TabletopService(CombatService(ROOT, tmp_path / 'attainment'), tmp_path / 'attainment')
    attained = cold_table.combat._factory_owner_sheet(pid)
    assert attained['foundation']['stage'] == 'Perfected'
    assert attained['foundation']['selected_refined_expression_ids'] == [f.feature('oath', leaf) for leaf in expressions]
    assert len(cold_table.buttons.get(pid)['advancement']['foundation_attainments']) == 3
    reload(tmp_path / 'attainment', mid)  # asserts cold mechanical replay
    root = tmp_path / 'attained-combat'
    owner = compile_character(attained, actor_id=OWNER, reaction_plan={'ask': True})
    def attack(bundles):
        sealed_native_attack(bundles[2], 'Pressure hit', modifier=1, count=1, sides=2, attack_bonus=100, range_ft=5)
        bundles[2]['action_catalog'][-1]['economy'] = 'BONUS_ACTION'
        sealed_native_attack(bundles[2], 'Protected ally strike', modifier=30, count=1, sides=2, attack_bonus=100, range_ft=5)
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    s, t, m = fixture(root, [], owner_bundle=owner, owner_document=attained,
        foe_sheet=sheet(['tianxia.talent.warleader.frightful_roar'], cl=5, dc=1),
        foe_position={'x': 3, 'y': 5}, bundle_transform=attack, seed='IRON-OATH-ATTAINED-CONTACT', owner_id=OWNER)
    assert s._factory_owner_sheet(attained['identity']['project_id'])['foundation'] == attained['foundation']
    duty(s, t, m, owner_id=OWNER)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    e = reload(root, m)
    assert all(f.selected(e, e.state.actors[OWNER], f.feature('oath', leaf)) for leaf in expressions)
    assert not any(a.owner_id == OWNER and a.display_name.startswith('Foundation expression:') for a in e.action_catalog.values())
    turn(t, m, FOE)
    use(s, t, m, 'Pressure hit', OWNER, choices={'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    assert reload(root, m).state.actors[OWNER].resources[f.pool('oath')] == 1, 'First actual hit did not generate Guarding Iron'
    turn(t, m, OWNER)
    if 'shield_body_forging' in expressions:
        record_project(s, t, m, kind='foundation_challenge', owner=OWNER)
        use(s, t, m, 'Resolve a project check', choices={f.CHOICE + 'foundation_combat': None})
        e = reload(root, m)
        assert any(event.event_type == 'CHECK_ROLLED' and event.payload.get('dc_adjustment') == -2 for event in e.events)
    if 'oath_skin_mantle' in expressions:
        assert reload(root, m).state.actors[OWNER].temporary_hp == 3
    boundary_choices = {}
    if 'shield_body_forging' in expressions:
        duty(s, t, m, kind='doorway', subject='scene:attained-eastern-gate', record_id='scene:attained-eastern-gate', owner_id=OWNER)
        boundary_choices[f.CHOICE + 'iron_boundary_subject'] = ['scene:attained-eastern-gate']
    use(s, t, m, 'Iron Oath Boundary', choices=boundary_choices)
    e = reload(root, m)
    assert f.held(e.state.actors[OWNER], 'protected_subject').data['subject'] == ALLY
    assert f.held(e.state.actors[OWNER], 'iron_oath_boundary').data['subject'] == (
        'scene:attained-eastern-gate' if 'shield_body_forging' in expressions else ALLY)
    turn(t, m, FOE)
    use(s, t, m, 'Pressure hit', OWNER, choices={f.CHOICE + 'foundation_subject': None, 'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    assert reload(root, m).state.actors[OWNER].resources[f.pool('oath')] == 1, 'Pre-Guard hit did not generate Guarding Iron'
    use(s, t, m, 'Protected ally strike', ALLY, choices={f.CHOICE + 'iron_interposition': 'first'})
    e = reload(root, m)
    damages = [event for event in e.events if event.event_type == 'DAMAGE_COMMITTED' and ALLY in event.target_ids]
    assert damages, 'Protected ally strike produced no damage receipt: ' + str([(x.event_type, x.source_definition_id) for x in e.events[-12:]])
    damage = damages[-1]
    windows = [event for event in e.events if event.event_type == 'REACTION_WINDOW_OPENED'
               and event.payload.get('checkpoint') == 'DAMAGE_APPLICATION']
    assert windows, 'Protected ally strike produced no damage application window'
    window = windows[-1]
    pb, cultivation = f.values(e, e.state.actors[OWNER])
    assert (window.payload['pending_damage'] - damage.payload['hp_damage']
            - damage.payload.get('temporary_hp_absorbed', 0)) == pb * (3 if 'iron_interposition' in expressions else 2) + cultivation
    assert e.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert f.held(e.state.actors[OWNER], 'protected_subject').data['subject'] == ALLY
    turn(t, m, OWNER)
    turn(t, m, FOE)
    use(s, t, m, 'Pressure hit', OWNER, choices={f.CHOICE + 'foundation_subject': None, 'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    probe = reload(root, m)
    bearer = probe.state.actors[OWNER]
    from combat.ext.iron_oath import defending, available
    assert bearer.resources[f.pool('oath')] == 1, 'Pre-Witness hit did not generate Guarding Iron: ' + str({
        'round': probe.state.round_number, 'hp': bearer.current_hp,
        'position': bearer.position.model_dump(mode='json'),
        'defending': defending(probe, bearer), 'available': available(probe, bearer),
        'flags': {k: v for k, v in bearer.turn_flags.items() if 'pressure' in k or 'oath' in k},
        'conditions': [c.condition_id for c in bearer.conditions.values()],
        'receipts': [(x.event_type, x.source_definition_id, x.actor_id, x.target_ids, x.payload)
                     for x in probe.events if x.event_type in {'DAMAGE_COMMITTED', 'RESOURCE_GAINED', 'RESOURCE_SPENT'}][-6:]})
    use(s, t, m, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    e = reload(root, m)
    bonuses = [event.payload['bonus'] for event in e.events if event.event_type == 'D20_REWRITTEN'
               and event.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert bonuses, 'No Witness bonus after Roar; Guarding Iron=' + str(e.state.actors[OWNER].resources.get(f.pool('oath'))) + '; flags=' + str(e.state.actors[OWNER].turn_flags)
    assert bonuses[-1] == (9 if 'scar_ledger_defense' in expressions else 6)
    assert f.held(e.state.actors[OWNER], 'iron_oath_boundary') is not None
    if 'scar_ledger_defense' in expressions:
        assert any(c.condition_id == SCAR_BAR + '.' + OWNER for c in e.state.actors[FOE].conditions.values())



@pytest.mark.parametrize('save_failure', [False, True], ids=['native-settlement', 'retry-after-io-error'])
def test_native_attainment_interposition_and_permanent_frame_severance(tmp_path, native_oath_document, monkeypatch, save_failure):
    """Acquisition -> real stage rolls -> next scene -> Guard -> story -> new scene."""
    from tests.test_a2_foundations_two import use  # retain the original settlement helper
    import zipfile
    from combat import table_advance
    from combat.factory_compiler import compile_character
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    from tests.worker2_support import fixture, sealed_native_attack
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    native = json.loads(json.dumps(native_oath_document))
    OWNER = 'actor:factory.' + native['identity']['project_id']
    native['identity']['name'] = 'Oath bearer'
    root = tmp_path / 'campaign'
    s, t, m = fixture(root, [], owner_id=OWNER, owner_document=native, owner_bundle=compile_character(native, actor_id=OWNER, reaction_plan={'ask': True}))
    pid = OWNER.removeprefix('actor:factory.')
    archive = root / 'portable_characters' / pid / 'current.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(native))
    original_archive = hashlib.sha256(archive.read_bytes()).hexdigest()
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    app = create_app(Settings.from_env(ROOT, root))
    app.state.agent_seats.background = False
    def owner_post(url, payload=None):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
                denied = await client.post(url, json=payload)
                assert denied.status_code in (401, 403)
                token = (await client.get('/api/session')).json()['token']
                result = await client.post(url, headers={'x-foundry-token': token}, json=payload)
                assert result.status_code == 200, result.text
                return result.json()
        return run_asgi(request())
    duty(s, t, m, owner_id=OWNER)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    previous = 'Awakened'
    for stage in ('Integrated', 'Refined'):
        e = s._load_session(m).engine
        reference = 'Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md#26;campaign:attained:' + stage
        project = 'project:attain-' + stage
        doc = {'record_id': project, 'subject_id': project, 'subject_name': stage + ' Iron Oath Foundation Challenge',
            'subject_kind': 'plan', 'position': e.state.actors[OWNER].position.model_dump(mode='json'),
            'source_reference': reference, 'witness_ids': [OWNER], 'valid_through_round': e.state.round_number + 3,
            'answers': {}, 'project_check': {'actor_id': OWNER, 'kind': 'foundation_challenge',
                'sphere_ids': ['tianxia.sphere.guardian'], 'challenge_dc': 1, 'ability': 'CON', 'skill': 'Cultivation',
                'limitation_kind': 'protected_subject', 'limitation': 'Defend the named ally without controlling their choices.'}}
        t.record_fact(m, doc, expected_state_version=e.state.state_version)
        request = {'foundation_id': f.GROUPS['oath'][0], 'previous_stage': previous, 'stage': stage,
            'source_reference': reference, 'requirements_met': ['Protected without controlling', 'Accepted protection', 'Clarified the oath'],
            'time_spent': 'Actual Foundation scene and compatible practice time completed.',
            'costs_paid': ['Scene time, compatible oath/guard method and witness support'],
            'success_result': 'The source-defined requirements and successful challenge attain ' + stage,
            'failure_result': 'Failure grants no stage; actual source strain and injury consequences still apply.',
            'proof_match_id': m, 'proof_project_record_id': project}
        if stage == 'Refined':
            request['selected_expression_ids'] = [f.feature('oath', leaf) for leaf in
                                                  ('iron_interposition', 'shield_body_forging')]
        with pytest.raises(TabletopError):
            t.record_foundation_attainment(pid, request)  # an offered roll is not a successful receipt
        use(s, t, m, 'Resolve a project check')
        if stage == 'Integrated':
            with pytest.raises(TabletopError):
                t.record_foundation_attainment(pid, {**request, 'requirements_met': ['Clarified the oath']})
        assert owner_post(f'/api/tabletop/characters/{pid}/foundation-attainments', {'document': request})['stage'] == stage
        with pytest.raises(TabletopError):
            t.record_foundation_attainment(pid, request)  # no double consumption
        previous = stage
    cold = TabletopService(CombatService(ROOT, root), root)
    attained = cold.combat._factory_owner_sheet(pid)
    assert attained['foundation']['stage'] == 'Refined'
    assert table_advance.apply(attained, cold.buttons.get(pid)['advancement']) == attained
    replacement = json.loads(json.dumps(native))
    replacement['foundation']['acquisition_event_id'] = 'a-different-native-acquisition'
    from combat.foundation_attainment import apply as apply_attainments
    assert apply_attainments(replacement, cold.buttons.get(pid)['advancement']['foundation_attainments']) == replacement
    owner = compile_character(attained, actor_id=OWNER, reaction_plan={'ask': True})
    raw_hp = native['ability_scores_and_statistics']['hit_points']['maximum']
    assert owner['actor_template']['maximum_hp'] == raw_hp + 3
    ally = compile_character(sheet([], cl=5, name='Protected ally'), actor_id=ALLY, reaction_plan={'ask': True})
    foe = compile_character(sheet([], cl=5, name='Invader'), actor_id=FOE, reaction_plan={'ask': True})
    sealed_native_attack(foe, 'Opening strike', count=1, sides=2, modifier=10, attack_bonus=100, range_ft=5)
    foe['action_catalog'][-1]['economy'] = 'BONUS_ACTION'
    sealed_native_attack(foe, 'Second strike', count=1, sides=2, modifier=10, attack_bonus=100, range_ft=5)
    m = s._finish_factory_match([owner, ally, foe], [OWNER, ALLY, FOE],
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 5}, FOE: {'x': 3, 'y': 5}},
        s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [FOE],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}, match_seed='ATTAINED-IRON-OATH',
        display_name='Attained Iron Oath', maximum_rounds=15)['match_id']
    turn(t, m, OWNER)
    duty(s, t, m, owner_id=OWNER)
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    assert f.selected(s._load_session(m).engine, s._load_session(m).engine.state.actors[OWNER],
                      f.feature('oath', 'iron_interposition'))
    turn(t, m, FOE)
    use(s, t, m, 'Opening strike', OWNER, choices={'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    prompts = use(s, t, m, 'Second strike', ALLY, choices={f.CHOICE + 'iron_interposition': 'first'})
    e = reload(root, m)
    damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ALLY in ev.target_ids][-1]
    before = [ev for ev in e.events if ev.event_type == 'REACTION_WINDOW_OPENED'
              and ev.payload.get('checkpoint') == 'DAMAGE_APPLICATION'][-1]
    assert before.payload['pending_damage'] - damage.payload['hp_damage'] == 8  # PB3 + CON2 + PB3
    assert any('Iron Interposition' in str(p) for p in prompts)
    assert (e.state.actors[OWNER].position.x, e.state.actors[OWNER].position.y) == (4, 6)
    effect = {'actor_id': OWNER, 'power_id': POWER, 'state': 'fully_severed', 'effect_kind': 'story_severance',
              'resource_ids': [f.pool('oath')], 'reason': 'The explicit story ritual fully severs this acquired Foundation.'}
    doc = duty(s, t, m, owner_id=OWNER)
    doc['power_states'] = [effect]
    real_save = t.buttons.save_advancement
    if save_failure:
        def disk_error(*args, **kwargs):
            raise OSError('Injected character-store failure')
        monkeypatch.setattr(t.buttons, 'save_advancement', disk_error)
    e = s._load_session(m).engine
    result = t.record_fact(m, doc, expected_state_version=e.state.state_version)
    assert result['status'] == 'COMMITTED'
    assert result['character_effects']['status'] == ('PENDING' if save_failure else 'RECORDED')
    assert reload(root, m).state.actors[OWNER].maximum_hp == raw_hp - 3
    if save_failure:
        monkeypatch.setattr(t.buttons, 'save_advancement', real_save)
        assert owner_post(f'/api/tabletop/matches/{m}/character-effects/reconcile')['status'] == 'RECORDED'
    assert t.reconcile_character_effects(m)['recorded'] == 0
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_archive
    cold = TabletopService(CombatService(ROOT, root), root)
    severed = cold.combat._factory_owner_sheet(pid)
    assert severed['foundation']['available'] is False
    assert severed['ability_scores_and_statistics']['hit_points']['maximum'] == raw_hp - 3
    assert table_advance.apply(severed, cold.buttons.get(pid)['advancement']) == severed
    next_actor = compile_character(severed, actor_id=OWNER, reaction_plan={'ask': True})
    assert next_actor['actor_template']['maximum_hp'] == raw_hp - 3
    assert not any(r.get('feature_id', '').startswith(POWER + '.') for r in next_actor['typed_passives'])
    assert not any(r['resource_id'] == f.pool('oath') for r in next_actor['actor_template']['resources'])
    assert len(cold.buttons.get(pid)['advancement']['source_effects']) == 1
    after = cold.combat._finish_factory_match([next_actor, ally, foe], [OWNER, ALLY, FOE],
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 5}, FOE: {'x': 3, 'y': 5}},
        cold.combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [FOE],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}, match_seed='SEVERED-IRON-OATH',
        display_name='After explicit story severance', maximum_rounds=15)['match_id']
    turn(cold, after, OWNER)
    after_engine = reload(root, after)
    assert after_engine.state.actors[OWNER].maximum_hp == raw_hp - 3
    assert f.pool('oath') not in after_engine.state.actors[OWNER].resources
    assert after_engine.state.actors[ALLY].maximum_hp == ally['actor_template']['maximum_hp']
    assert not any(after_engine.action_catalog.get(c.source_definition_id)
                   and after_engine.action_catalog[c.source_definition_id].display_name == 'Declare Protected Subject'
                   for c in after_engine.legal_candidates())


@pytest.mark.parametrize('mode,spend', [('weapon', True), ('fixed_save', True), ('outside_scope', False), ('declined', False), ('denied_target', False), ('ally_target', True)])
def test_native_acquisition_to_declaration_guard_and_mark_commit_reload(tmp_path, native_oath_document, monkeypatch, mode, spend):
    from tests.test_a2_foundations_two import use  # retain the original settlement helper
    from combat.factory_compiler import compile_character
    from combat.gate2_rolls import DeterministicRollAuthority
    from tests.worker2_support import fixture, sealed_native_attack
    from tests.equipment_readiness import ready_table_weapon
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    document = json.loads(json.dumps(native_oath_document))
    OWNER = 'actor:factory.' + document['identity']['project_id']
    document['ability_scores_and_statistics']['technique_save_dc'] = 100
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    def attacks(bundles):
        sealed_native_attack(bundles[2], 'Invader strike', damage_type='SLASHING', modifier=4, attack_bonus=50, range_ft=5)
    s, t, m = fixture(tmp_path, [], owner_bundle=bundle, owner_document=document, bundle_transform=attacks,
                      foe_position={'x': 3, 'y': 5}, seed='IRON-OATH-ACQUIRED', owner_id=OWNER)
    assert s._factory_owner_sheet(document['identity']['project_id'])['foundation'] == document['foundation']
    target = ALLY if mode == 'ally_target' else FOE
    subject = 'scene:eastern-gate' if mode == 'ally_target' else ALLY
    kind = 'doorway' if mode == 'ally_target' else 'ally'
    duty(s, t, m, kind=kind, subject=subject, owner_id=OWNER, pressures=[{'actor_id': target, 'kind': 'attempted_bypass',
                            'evidence': 'The invader announces its attempt to pass the bearer and seize the protected ally.'}])
    use(s, t, m, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [subject]})
    turn(t, m, FOE)
    use(s, t, m, 'Invader strike', OWNER, choices={'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None})
    assert reload(tmp_path, m).state.actors[OWNER].resources[f.pool('oath')] == 1
    turn(t, m, OWNER)
    e = s._load_session(m).engine
    if mode == 'weapon':
        attack = next(a for a in e.action_catalog.values() if a.owner_id == OWNER
                      and a.source_definition_id.endswith('.weapon.dao'))
        ready_table_weapon(t, m, attack.source_definition_id)
    else:
        attack = next(a for a in e.action_catalog.values() if a.owner_id == OWNER and a.display_name == 'Mind Spike')
        if mode != 'outside_scope':
            doc = duty(s, t, m, kind=kind, subject=subject, owner_id=OWNER, pressures=[{'actor_id': target, 'kind': 'threatened',
                'verdict': 'artificial_denied' if mode == 'denied_target' else 'qualifies',
                'evidence': 'The invader explicitly threatens the named ally.'}])
            doc['technique_scopes'] = [{'actor_id': OWNER, 'source_definition_id': attack.source_definition_id,
                'power_id': POWER, 'scope': 'fixed_scope',
                'reason': 'The GM admits this actual technique as spiritual oath-pressure defending the named ally.'}]
            e = s._load_session(m).engine
            assert t.record_fact(m, doc, expected_state_version=e.state.state_version)['status'] == 'COMMITTED'
    prompts = use(s, t, m, attack.display_name, target,
                  choices={f.CHOICE + 'foundation_combat': None} if mode == 'declined' else {})
    e = reload(tmp_path, m)
    spends = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == POWER + '.oath_mark_strike']
    assert len(spends) == int(spend)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == int(not spend)
    assert any('Oath-Mark Strike' in str(p) for p in prompts) is (mode not in {'outside_scope', 'denied_target'})
    if mode != 'weapon':
        damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and target in ev.target_ids][-1]
        assert damage.payload['hp_damage'] == 18 + 3 * int(spend)
    assert e.state.actors[OWNER].maximum_hp == document['ability_scores_and_statistics']['hit_points']['maximum']



@pytest.mark.parametrize('automatic_enemy,accept', [(False, True), (True, True), (True, False)])
def test_new_duty_is_player_owned_before_enemy_native_action(tmp_path, automatic_enemy, accept):
    from tests.worker2_support import candidate
    from tests.r1i_service_support import force_ai_candidate
    s, t, m = table_fixture(tmp_path, 'oath', current=0, stage='Awakened', admit_oath_duty=False)
    # No duty or declaration is preloaded. The actual opponent's native intent offers
    # the newly appeared duty to the manual bearer, including on an AI turn.
    turn(t, m, FOE)
    duty(s, t, m)  # the actual duty appears after the bearer has finished their turn
    action = candidate(s, m, 'Hostile blow', target=OWNER)
    if automatic_enemy:
        force_ai_candidate(s, m, FOE, action.candidate_id)
    prompts = settle(t, m, action.candidate_id,
        choices={f.CHOICE + 'foundation_subject': [ALLY] if accept else None}, auto=automatic_enemy)
    e = reload(tmp_path, m)
    assert any(p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_subject' for p in prompts)
    assert e.state.actors[OWNER].resources[f.pool('oath')] == int(accept)
    assert bool(f.held(e.state.actors[OWNER], 'protected_subject')) is accept
    if not accept:
        assert e.state.actors[OWNER].action_available
