"""Native table source admission, event provenance and cold mechanical replay."""
from copy import deepcopy
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import foundation_combat as f
from tests.h1_support import ROOT, sheet
from tests.test_a2_foundations_two import table_fixture, use
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import FOE, ALLY, turn, reload, sealed_native_attack, settle
from tests.test_mgr_t14_heavenly_rejection import fixed, RID

POOL = f.pool('integrity')
SOURCE = 'foundation.heavenly_body_v0_2F'
BODY_SOURCE = SOURCE + '.integrity_rejection.body_source'
STATE_SOURCE = SOURCE + '.source_state'
PROJECT = '8a42be18-6fa2-4c53-b84e-8ed6853b01c2'
OWNER = 'actor:factory.' + PROJECT


@pytest.fixture(autouse=True)
def native_rolls(monkeypatch):
    # Stable native initiative/attack/save dice, not fabricated hit receipts.
    ordered_rolls(monkeypatch)


def test_source_classification_does_not_waive_numeric_authority_requirements():
    from combat.table_facts import FactAnswer
    with pytest.raises(ValueError, match='known source level'):
        FactAnswer.model_validate({'fact': 'danger', 'category': 'danger',
            'visible_sign': 'A visible sign', 'source_cl': None})


def installation(stage='Perfected', expression=''):
    stages = ['Refined', 'Perfected'][:{'Awakened': 0, 'Refined': 1, 'Perfected': 2}[stage]]
    return {'kind': 'foundation_installation', 'reference': 'campaign:heavenly-installation:1',
        'classification': 'Foundation', 'authority': 'GM', 'refined_expression': expression,
        'attainments': [{'stage': s, 'challenge': 'Purify Without Arrogance',
            'finding': 'bodily_integrity_proven_without_rejecting_lives',
            'scene_reference': 'campaign:challenge:' + s,
            'bodily_integrity_demonstrated': 'Withstood the actual purification ordeal without rejecting the injured.',
            'treatment_of_wounded_ordinary_deviant_or_impure_lives': 'Treated the wounded impure survivor as worthy of correction.',
            'active_severity': 0, 'adjudication_reference': 'campaign:GM-findings:' + s} for s in stages]}


def install_library(tmp_path, document, *, foe_talents=()):
    """Install test characters before acquisition, without a disposable fight."""
    documents = {OWNER: document, ALLY: sheet([], cl=15), FOE: sheet(list(foe_talents), cl=15)}
    for actor_id, content in documents.items():
        package = tmp_path / 'portable_characters' / actor_id.removeprefix('actor:factory.') / 'current.zip'
        package.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(content))
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path)


def acquired_fight(tmp_path, *, stage='Perfected', expression='', delivery=None, foe_hp=500, foe_talents=(), con_score=14):
    # This is an ordinary test character with a Path, not a fabricated Foundation.
    # Install the source through the owner service, cold-read the actual durable
    # character overlay, then use the production compiler and match producer.
    document = sheet([], cl=15, name='Wren')
    document['identity']['path_ids'] = ['tianxia.path.qi_cultivation']
    for ability in document['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'CON':
            ability.update(score=con_score, modifier=(con_score - 10) // 2)
    document['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    document['ability_scores_and_statistics']['technique_attack_bonus'] = 50
    combat, table = install_library(tmp_path, document, foe_talents=foe_talents)
    table.acquire_feature(PROJECT, SOURCE, installation(stage, expression))
    cold = CombatService(ROOT, tmp_path)
    acquired = cold._factory_owner_sheet(PROJECT)
    assert acquired['foundation']['stage'] == stage
    assert acquired['foundation']['resource']['current'] == 0
    assert acquired['feature_access'][SOURCE]['reference'] == installation()['reference']
    assert acquired['foundation']['source_record_sha256']
    bundles = [compile_character(acquired if aid == OWNER else sheet(list(foe_talents) if aid == FOE else [], cl=15),
                actor_id=aid, reaction_plan={'ask': True}) for aid in (OWNER, ALLY, FOE)]
    for index, name in [(0, 'Return blow'), (2, 'Hostile blow')]:
        sealed_native_attack(bundles[index], name, damage_type='POISON',
            attack_bonus=100, range_ft=5, sides=4, modifier=40)
        attack = next(a for a in bundles[index]['action_catalog'] if a['display_name'] == name)
        attack['economy'] = 'NONE'
        # These repeatable pressure actions intentionally spend no turn economy.
        # NONE alone is storage/trigger-only; use the public free-action contract.
        attack['parameters']['free_primary'] = True
    if delivery:
        delivery(bundles)
    for bundle in bundles:
        bundle['actor_template']['maximum_hp'] = foe_hp if bundle['actor_id'] == FOE else 500
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    arena = cold.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid = cold._finish_factory_match(bundles, [OWNER, ALLY, FOE],
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        arena, [OWNER, ALLY], [FOE], control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        match_seed='A2GFOU2', display_name='Heavenly source', maximum_rounds=15)['match_id']
    return cold, TabletopService(cold, tmp_path), mid


def test_native_installation_and_attainment_preserve_unrelated_foundation_notes(tmp_path):
    document = sheet([], cl=15)
    document['identity']['path_ids'] = ['tianxia.path.qi_cultivation']
    # Notes confer no ownership, stage, resource or source receipt.
    document['foundation'] = {'personal_notes': 'Keep the original campaign notes.'}
    combat, table = install_library(tmp_path, document)
    for stage in ('Awakened', 'Refined', 'Perfected'):
        table.acquire_feature(PROJECT, SOURCE, installation(stage))
        cold = CombatService(ROOT, tmp_path)
        acquired = cold._factory_owner_sheet(PROJECT)
        assert acquired['foundation']['personal_notes'] == document['foundation']['personal_notes']
        assert acquired['foundation']['stage'] == stage
        assert acquired['foundation']['resource']['current'] == 0
        combat, table = cold, TabletopService(cold, tmp_path)


def record(table, combat, mid, *, status='suppressed', stage='Perfected', **updates):
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    document = {'record_id': 'heavenly-source-ruling', 'subject_id': OWNER,
        'subject_name': actor.display_name, 'subject_kind': 'creature',
        'position': actor.position.model_dump(mode='json'),
        'source_reference': 'GM source ruling: hostile Foundation suppression',
        'witness_ids': [OWNER], 'valid_through_round': engine.state.round_number + 10,
        'answers': {SOURCE: {'fact': status, 'category': 'foundation_availability',
            'visible_sign': 'The cultivator knows which features remain available.',
            'source_cl': 15, 'condition': stage}}}
    document.update(updates)
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)


def body_declaration(combat, table, mid, family, *, options=(), requires_facts=()):
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Hostile bodily technique')
    kind = next(c.kind.value for c in engine.legal_candidates()
                if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    document = {'record_id': 'bodily-source-intent', 'subject_id': action.source_definition_id,
        'subject_name': action.display_name, 'subject_kind': 'event',
        'position': engine.state.actors[FOE].position.model_dump(mode='json'),
        'source_reference': 'campaign:bodily-source-finding:' + family,
        'witness_ids': [OWNER], 'valid_through_round': engine.state.round_number + 1,
        'answers': {BODY_SOURCE: {'fact': 'bodily_effect', 'category': 'source_classification',
            'visible_sign': 'The declared bodily disruption is the cause of the impending collapse.',
            'source_cl': None, 'condition': family, 'predictions': [{
                'actor_id': FOE, 'kind': kind, 'source_definition_id': action.source_definition_id,
                'target_ids': [OWNER], 'option_ids': list(options), 'aware_actor_ids': [OWNER],
                'requires_facts': list(requires_facts),
                'description': 'The source actor directs this exact bodily effect at the cultivator.'}]}}}
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)


def record_state(combat, table, mid, *, severity=1, generation_only=False,
                 record_id='heavenly-state', active=True, **updates):
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    document = {'record_id': record_id, 'subject_id': OWNER, 'subject_name': actor.display_name,
        'subject_kind': 'creature', 'position': actor.position.model_dump(mode='json'),
        'source_reference': 'campaign:GM:actual-heavenly-vessel-pressure:' + record_id,
        'witness_ids': [OWNER], 'horizon': 'until_withdrawn', 'active': active,
        'answers': {STATE_SOURCE: {'fact': 'suppressed_heavenly_integrity' if generation_only else 'heavenly_vessel_strain',
            'category': 'source_classification', 'source_cl': None,
            'condition': 'active' if generation_only else str(severity),
            'visible_sign': 'The GM records the actual bodily strain and its severity after the vessel ordeal.'}}}
    document.update(updates)
    return table.record_fact(mid, document, expected_state_version=engine.state.state_version)


def setup(tmp_path, *, stage='Perfected'):
    def delivery(bundles):
        add_action(bundles[2], 'Unclassified damage', [
            {'type': 'damage', 'flat': 2, 'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
        add_action(bundles[2], 'Bodily pressure', [{'type': 'save', 'ability': 'DEX',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
        add_action(bundles[2], 'Make unconscious', [
            {'type': 'condition', 'condition': 'unconscious', 'applies_to': 'target'}], economy='NONE')
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = acquired_fight(tmp_path, stage=stage, delivery=delivery)
    turn(table, mid, FOE)
    return combat, table, mid


@pytest.mark.parametrize('case', ['suppressed', 'unavailable', 'unclassified', 'unconscious'])
def test_generation_requires_available_conscious_hostile_attack_or_technique(tmp_path, case):
    combat, table, mid = setup(tmp_path)
    if case in {'suppressed', 'unavailable'}:
        record(table, combat, mid, status=case)
    if case == 'unconscious':
        use(combat, table, mid, 'Make unconscious', OWNER)
    use(combat, table, mid, 'Unclassified damage' if case == 'unclassified' else 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]


@pytest.mark.parametrize('conversion', ['guard', 'rejection', 'strike'])
def test_suppression_blocks_all_conversions_and_recovers_without_refill(tmp_path, monkeypatch, conversion):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path)
    spend = {RID: ['use'], f.CHOICE + 'foundation_combat': ['use'],
             'reaction:typed.' + SOURCE + '.integrity_strike': 'first'}
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    record(table, combat, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    if conversion == 'strike':
        turn(table, mid, OWNER)
        use(combat, table, mid, 'Return blow', FOE, choices=spend)
    else:
        use(combat, table, mid, 'Bodily pressure' if conversion == 'rejection' else 'Hostile blow', OWNER, choices=spend)
    suppressed = reload(tmp_path, mid)
    assert suppressed.state.actors[OWNER].resources[POOL] == 1
    record(table, combat, mid, status='available')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    if conversion == 'strike':
        use(combat, table, mid, 'Return blow', FOE, choices=spend)
    else:
        use(combat, table, mid, 'Bodily pressure' if conversion == 'rejection' else 'Hostile blow', OWNER, choices=spend)
    final = reload(tmp_path, mid)
    assert [e for e in final.events if e.event_type == 'RESOURCE_SPENT'
            and e.actor_id == OWNER and e.payload.get('resource_id') == POOL
            and e.sequence > suppressed.state.event_sequence]


def test_realm_limit_removes_only_higher_stage_benefits_and_cold_replays(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Foundation expression: Jade-Gold Guard')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    record(table, combat, mid, status='available', stage='Awakened')
    use(combat, table, mid, 'Hostile blow', OWNER)
    engine = reload(tmp_path, mid)
    damages = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    # Base Guard remains, but neither selected Jade nor Perfected Vessel does.
    assert damages[-1].payload['rolled_or_pending_damage'] - damages[-1].payload['hp_damage'] == 6
    assert 'foundation_round_vessel' not in engine.state.actors[OWNER].turn_flags
    assert any(e.event_type == 'TABLE_FACT_RECORDED' for e in engine.events)


@pytest.mark.parametrize('scenario', ['new_integrity', 'reaction_blocked_guard', 'reaction_blocked_rejection'])
def test_native_guard_resource_and_reaction_boundaries(tmp_path, scenario):
    def delivery(bundles):
        add_action(bundles[2], 'Prevent actions and reactions', [
            {'type': 'condition', 'condition': 'incapacitated', 'applies_to': 'target',
             'expires_on': 'END_OF_HOLDER_NEXT_TURN'}], economy='NONE')
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, expression='jade_gold_guard', delivery=delivery)
    turn(table, mid, FOE)
    guard_choice = f.CHOICE + 'foundation_combat'
    prompts = use(combat, table, mid, 'Hostile blow', OWNER, choices={guard_choice: 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not any(p['context']['reaction_source_id'] == guard_choice for p in prompts)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
                   and e.payload.get('resource_id') == POOL for e in engine.events)
    if scenario == 'new_integrity':
        return
    use(combat, table, mid, 'Prevent actions and reactions', OWNER)
    engine = reload(tmp_path, mid)
    condition = next(c for c in engine.state.actors[OWNER].conditions.values()
                     if c.condition_id.endswith('incapacitated'))
    assert condition.expires_on == 'END_OF_HOLDER_NEXT_TURN'
    before = engine.state.event_sequence
    action = 'Hostile blow' if scenario == 'reaction_blocked_guard' else 'Constitution ordeal'
    prompts = use(combat, table, mid, action, OWNER, choices={guard_choice: 'first', RID: ['use']})
    engine = reload(tmp_path, mid)
    spends = [e for e in engine.events if e.sequence > before and e.event_type == 'RESOURCE_SPENT'
              and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    if scenario == 'reaction_blocked_guard':
        assert not any(p['context']['reaction_source_id'] == guard_choice for p in prompts)
        assert not spends
        assert engine.state.actors[OWNER].resources[POOL] == 1
    else:
        # Rejection is No Action, not a Reaction; the conscious saver retains it.
        assert any(p['context']['reaction_source_id'] == RID for p in prompts)
        assert len(spends) == 1 and spends[0].payload['amount'] == 1
        assert engine.state.actors[OWNER].resources[POOL] == 0
        assert any(e.sequence > before and e.event_type == 'SAVE_ROLLED'
                   and e.actor_id == OWNER and e.payload.get('success') for e in engine.events)
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id.endswith('incapacitated')
                   for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('invalid', ['higher_stage', 'wrong_owner', 'unknown_state', 'private_from_owner'])
def test_source_declarations_validate_ownership_stage_and_audience(tmp_path, invalid):
    combat, table, mid = setup(tmp_path, stage='Awakened')
    kwargs = {'stage': 'Awakened'}
    if invalid == 'higher_stage': kwargs['stage'] = 'Perfected'
    if invalid == 'wrong_owner': kwargs['subject_id'] = ALLY
    if invalid == 'unknown_state': kwargs['status'] = 'approved'
    if invalid == 'private_from_owner': kwargs['witness_ids'] = [FOE]
    with pytest.raises(Exception, match='Foundation|Heavenly|cultivator'):
        record(table, combat, mid, **kwargs)
    assert not [e for e in reload(tmp_path, mid).events if e.event_type == 'TABLE_FACT_RECORDED']


@pytest.mark.parametrize('stage,expression,conversion,expected', [
    ('Awakened', '', 'guard', 6),
    ('Refined', 'jade_gold_guard', 'guard', 10),
    ('Perfected', 'jade_gold_guard', 'guard', 14),
    ('Awakened', '', 'strike', 4),
    ('Refined', 'orthodox_answering_strike', 'strike', 8),
    ('Perfected', 'orthodox_answering_strike', 'strike', 12),
    ('Awakened', '', 'rejection', 4),
    ('Refined', 'heaven_rejecting_marrow', 'rejection', 4),
    ('Perfected', 'heaven_rejecting_marrow', 'rejection', 8),
])
def test_acquisition_to_native_spend_all_eight_rows_and_cold_replay(tmp_path, monkeypatch, stage, expression, conversion, expected):
    fixed(monkeypatch)
    def delivery(bundles):
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage=stage, expression=expression, delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[POOL] == 1
    start = before.state.event_sequence
    if conversion == 'strike':
        turn(table, mid, OWNER)
        use(combat, table, mid, 'Return blow', FOE,
            choices={'reaction:typed.' + SOURCE + '.integrity_strike': 'first'})
    else:
        use(combat, table, mid, 'Constitution ordeal' if conversion == 'rejection' else 'Hostile blow', OWNER,
            choices={RID: ['use'], f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    if expression:
        label = f.held(actor, 'expression').data['label']
        assert expression.replace('_', ' ').replace('-', ' ') in label.lower().replace('-', ' ')
        assert '1' in label and 'Heavenly Integrity' in label
    spends = [e for e in engine.events if e.sequence > start and e.event_type == 'RESOURCE_SPENT'
              and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1
    # External installation/challenge references belong to the private owner
    # sheet, not publicly observable condition data or runtime source metadata.
    reference = installation()['reference']
    assert reference not in json.dumps([c.data for c in actor.conditions.values()])
    runtime_source = next(b['foundation_runtime_source'] for b in engine.typed_bundle_documents
                          if b.get('actor_id') == OWNER)
    assert reference not in json.dumps(runtime_source)
    assert actor.resources[POOL] == 0
    assert actor.reaction_available is (conversion != 'guard')
    if conversion == 'guard':
        damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
        assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == expected
    elif conversion == 'strike':
        assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == SOURCE + '.integrity_strike'
                   and f'adds {expected} damage' in e.payload.get('log', '') for e in engine.events if e.sequence > start)
    else:
        receipt = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED'
                       and e.source_definition_id == SOURCE + '.integrity_rejection')
        assert receipt.payload['bonus'] == expected
        assert receipt.payload['checkpoint'] == ('after_failure' if expression else 'before_outcome')


@pytest.mark.parametrize('category', ['poison', 'sickened', 'exhaustion', 'body_corruption',
    'body_seizure', 'forced_transformation', 'internal_disruption'])
def test_all_printed_bodily_save_families_use_native_source_intent(tmp_path, monkeypatch, category):
    fixed(monkeypatch)
    def delivery(bundles):
        add_action(bundles[2], 'Hostile bodily technique', [{'type': 'save', 'ability': 'DEX',
            'applies_to': 'target',
            'on_fail': [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}],
            'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='heaven_rejecting_marrow', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    body_declaration(combat, table, mid, category)
    use(combat, table, mid, 'Hostile bodily technique', OWNER, choices={RID: ['use']})
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources[POOL] == 0
    assert not any(c.condition_id.endswith('.prone') for c in actor.conditions.values())


@pytest.mark.parametrize('declaration', ['absent', 'wrong_options', 'missing_prerequisite'])
def test_unknown_or_different_source_intent_does_not_authorize_bodily_rejection(tmp_path, monkeypatch, declaration):
    fixed(monkeypatch)
    def delivery(bundles):
        add_action(bundles[2], 'Hostile bodily technique', [{'type': 'save', 'ability': 'DEX',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'prone',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='heaven_rejecting_marrow', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    if declaration == 'wrong_options':
        body_declaration(combat, table, mid, 'body_seizure', options=['another-mode'])
    elif declaration == 'missing_prerequisite':
        body_declaration(combat, table, mid, 'body_seizure', requires_facts=['unrecorded-source-condition'])
    prompts = use(combat, table, mid, 'Hostile bodily technique', OWNER, choices={RID: ['use']})
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources[POOL] == 1
    assert any(c.condition_id.endswith('.prone') for c in actor.conditions.values())
    assert not any(p['context']['reaction_source_id'] == RID for p in prompts)


@pytest.mark.parametrize('bad', ['too_early', 'wrong_path', 'second_foundation', 'stage_skip', 'no_proof',
    'wrong_authority', 'failed_finding', 'reused_adjudication'])
def test_native_acquisition_rejects_unearned_or_incomplete_sources(tmp_path, bad):
    document = sheet([], cl=4 if bad == 'too_early' else 15)
    document['identity']['path_ids'] = ['tianxia.path.spirit_awakening' if bad == 'wrong_path' else 'tianxia.path.qi_cultivation']
    if bad == 'second_foundation': document['foundation'] = {'foundation_id': 'iron_oath_skin_v0_2B'}
    combat, table = install_library(tmp_path, document)
    source = installation()
    if bad == 'stage_skip': source['attainments'] = source['attainments'][1:]
    if bad == 'no_proof': source['attainments'][0]['bodily_integrity_demonstrated'] = ''
    if bad == 'wrong_authority': source['authority'] = 'AI'
    if bad == 'failed_finding': source['attainments'][0]['finding'] = 'rejected_lives'
    if bad == 'reused_adjudication':
        source['attainments'][1]['adjudication_reference'] = source['attainments'][0]['adjudication_reference']
    with pytest.raises(ValueError):
        table.acquire_feature(PROJECT, SOURCE, source)
    assert 'feature_access' not in combat._factory_owner_sheet(PROJECT)


@pytest.mark.parametrize('relation,expected', [('ALLY', 0), ('NEUTRAL', 0), ('ENEMY', 1)])
def test_hostility_comes_from_committed_relations_not_team_names(tmp_path, relation, expected):
    def delivery(bundles):
        next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Hostile blow')['target_kind'] = 'ANY_CREATURE'
    combat, table, mid = acquired_fight(tmp_path, stage='Awakened', delivery=delivery)
    engine = combat._load_session(mid).engine
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
        'other': FOE, 'relation': relation}, expected_state_version=engine.state.state_version)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == expected


@pytest.mark.parametrize('conversion', ['guard', 'strike'])
def test_vessel_can_be_kept_for_another_conversion_without_second_cost(tmp_path, conversion):
    combat, table, mid = acquired_fight(tmp_path, expression='jade_gold_guard' if conversion == 'guard' else 'orthodox_answering_strike')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    if conversion == 'strike':
        turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.event_sequence
    use(combat, table, mid, 'Hostile blow' if conversion == 'guard' else 'Return blow',
        OWNER if conversion == 'guard' else FOE, choices={f.CHOICE + 'foundation_combat': ['use'],
            'reaction:typed.' + SOURCE + '.integrity_strike': 'first', f.CHOICE + 'heavenly_vessel': ['keep']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags.get('foundation_round_vessel') != engine.state.round_number
    spends = [e for e in engine.events if e.sequence > before and e.event_type == 'RESOURCE_SPENT'
        and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1


def test_selected_marrow_preserves_the_base_preoutcome_option(tmp_path, monkeypatch):
    fixed(monkeypatch)
    def delivery(bundles):
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='heaven_rejecting_marrow', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    use(combat, table, mid, 'Constitution ordeal', OWNER,
        choices={f.CHOICE + 'heavenly_rejection_timing': ['use']})
    engine = reload(tmp_path, mid)
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == SOURCE + '.integrity_rejection')
    assert receipt.payload['checkpoint'] == 'before_outcome'
    assert receipt.payload['bonus'] == 4


@pytest.mark.parametrize('lethal', [False, True])
def test_native_strike_adds_to_the_hit_before_resistance_or_defeat(tmp_path, lethal):
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='orthodox_answering_strike',
        foe_hp=1 if lethal else 500, foe_talents=['tianxia.talent.poison.venom_body_method'])
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.event_sequence
    use(combat, table, mid, 'Return blow', FOE,
        choices={'reaction:typed.' + SOURCE + '.integrity_strike': 'first'})
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_COMMITTED'
              and e.actor_id == OWNER and FOE in e.target_ids]
    rolled = next(e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER)
    assert len(damage) == 1
    assert damage[0].payload['rolled_or_pending_damage'] == rolled.payload['total'] + 8
    assert damage[0].payload['hp_damage'] == (rolled.payload['total'] + 8) // 2
    assert engine.state.actors[OWNER].resources[POOL] == 0
    if lethal:
        assert engine.state.actors[FOE].current_hp == 0


def test_owner_http_guards_acquisition_and_source_facts_without_model_leakage(tmp_path):
    """In-process ASGI only; no sockets, models, browser or GUI."""
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    from combat.target_knowledge import recent_events

    combat, table, mid = acquired_fight(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            url = f'/api/tabletop/characters/{PROJECT}/features'
            request = {'feature_id': SOURCE, 'source': installation()}
            denied = await client.post(url, json=request)
            assert denied.status_code in (401, 403)
            invalid = await client.post(url, headers=headers,
                json={**request, 'source': {**installation(), 'authority': 'AI'}})
            assert invalid.status_code == 422
            acquired = await client.post(url, headers=headers, json=request)
            assert acquired.status_code == 200, acquired.text
            assert app.state.combat._factory_owner_sheet(PROJECT)['foundation']['stage'] == 'Perfected'
            engine = app.state.combat._load_session(mid).engine
            document = {'record_id': 'http-source-state', 'subject_id': OWNER, 'subject_name': 'Wren',
                'subject_kind': 'creature', 'position': engine.state.actors[OWNER].position.model_dump(mode='json'),
                'source_reference': 'campaign:private-GM-source-ruling', 'witness_ids': [OWNER],
                'valid_through_round': engine.state.round_number + 2,
                'answers': {SOURCE: {'fact': 'suppressed', 'category': 'foundation_availability',
                    'visible_sign': 'The Foundation cannot generate or spend Integrity.', 'source_cl': 15,
                    'condition': 'Perfected'}}}
            request = {'document': document, 'expected_state_version': engine.state.state_version}
            url = f'/api/tabletop/matches/{mid}/facts'
            denied = await client.post(url, json=request)
            assert denied.status_code in (401, 403)
            result = await client.post(url, headers=headers, json=request)
            assert result.status_code == 200, result.text
            stale = await client.post(url, headers=headers, json=request)
            assert stale.status_code == 409
    run_asgi(exercise())
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'TABLE_FACT_RECORDED' for e in engine.events)
    for actor in (engine.state.actors[OWNER], engine.state.actors[FOE]):
        assert not any(e['event_type'] == 'TABLE_FACT_RECORDED' for e in recent_events(engine, actor, engine.events))


def test_unreadable_recorded_feature_explains_record_and_manual_removal():
    from app.core import FoundryError
    from combat import table_advance

    with pytest.raises(FoundryError) as caught:
        table_advance.apply_features(sheet([], cl=15, name='Wren'), [
            {'id': 'tianxia.foundation.heavenly_integrity', 'source': {}}])
    message = caught.value.message
    assert 'heavenly integrity' in message.lower()
    assert 'kept the record' in message
    assert 'owner may remove it' in message
    assert 'Table Advancement' in message


def test_recorded_acquisition_survives_normalization_and_a_cold_read(tmp_path):
    """A recorded acquisition is the owner's evidence, replayed on every cold read.

    Before the fix, normalization dropped the collection entirely and apply() never
    replayed it, so a valid acquisition either raised KeyError on save or was silently
    lost on the next read. This pins both halves at the module boundary.
    """
    from combat import table_advance

    document = sheet([], cl=15, name='Wren')
    document['identity']['path_ids'] = ['tianxia.path.qi_cultivation']
    combat, table = install_library(tmp_path, document)
    table.acquire_feature(PROJECT, SOURCE, installation('Refined'))

    # Normalization must keep the row: dropping it made the save unreadable.
    stored = table.buttons.get(PROJECT)['advancement']
    assert [row['id'] for row in table_advance.normalized(stored)['features']] == [SOURCE]

    # A cold service rebuilds the sheet from the stored row alone.
    cold = CombatService(ROOT, tmp_path)
    projected = cold._factory_owner_sheet(PROJECT)
    assert projected['foundation']['stage'] == 'Refined'
    assert projected['feature_access'][SOURCE]['reference'] == installation()['reference']
    assert projected['foundation']['resource']['current'] == 0

    # A later recorded attainment builds on the installed state instead of resetting it.
    table.acquire_feature(PROJECT, SOURCE, installation('Perfected', 'heaven_rejecting_marrow'))
    advanced = CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT)
    assert advanced['foundation']['stage'] == 'Perfected'
    assert advanced['foundation']['refined_expression'] == 'heaven_rejecting_marrow'


def test_owner_routes_for_acquisition_and_source_facts_are_served(tmp_path):
    """The owner commands must be reachable over the authenticated app API.

    Before the fix these existed only as service methods with no request model and no
    route, so an owner could never install a Foundation or record a source fact.
    """
    from app.api import create_app
    from app.core import Settings

    app = create_app(Settings.from_env(ROOT, tmp_path))
    served = {(route.path, method) for route in app.routes if hasattr(route, 'path')
              for method in getattr(route, 'methods', ())}
    assert ('/api/tabletop/characters/{project_id}/features', 'POST') in served
    assert ('/api/tabletop/matches/{match_id}/facts', 'POST') in served


def ordered_rolls(monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.raw_d20
    def draw(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id not in {FOE, OWNER, ALLY}:
            return roll  # persistence creates stock bootstrap actors first
        natural = ({FOE: 19, OWNER: 10, ALLY: 2}[actor_id] if reason == 'INITIATIVE' else
                   19 if reason.startswith('ATTACK:') else 8 if reason.startswith('SAVE:') else None)
        return roll if natural is None else roll.model_copy(update={
            'dice': (natural,), 'natural_result': natural, 'total': natural + modifier})
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', draw)


def previous_round_integrity(tmp_path, monkeypatch, *, expression='jade_gold_guard', extra_delivery=None):
    ordered_rolls(monkeypatch)
    def delivery(bundles):
        sealed_native_attack(bundles[1], 'Minion blow', damage_type='POISON', attack_bonus=100, range_ft=5, modifier=3)
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
        if extra_delivery:
            extra_delivery(bundles)
    combat, table, mid = acquired_fight(tmp_path, expression=expression, delivery=delivery)
    engine = combat._load_session(mid).engine
    assert engine.state.initiative_order == [FOE, OWNER, ALLY]
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
        'other': ALLY, 'relation': 'ENEMY'}, expected_state_version=engine.state.state_version)
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Minion blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == 1 and engine.state.actors[OWNER].resources[POOL] == 1
    return combat, table, mid


def test_native_prior_round_gain_then_two_conversions_share_one_vessel_bonus(tmp_path, monkeypatch):
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == 2
    assert engine.state.actors[OWNER].resources[POOL] == 1  # new round's real hostile damage
    assert engine.state.actors[OWNER].turn_flags['foundation_round_vessel'] == 2
    use(combat, table, mid, 'Constitution ordeal', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    rejection = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED'
                     and e.source_definition_id == SOURCE + '.integrity_rejection')
    assert rejection.payload['bonus'] == 4
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not engine.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('conversion,expression', [('guard', 'jade_gold_guard'),
    ('strike', 'orthodox_answering_strike'), ('rejection', 'heaven_rejecting_marrow')])
@pytest.mark.parametrize('severity,generation_only', [(1, False), (2, False), (3, False), (1, True)])
def test_native_fixed_strain_and_generation_only_suppression_keep_held_base_spends(
        tmp_path, monkeypatch, conversion, expression, severity, generation_only):
    from combat.table_facts import records
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, expression=expression)
    record_state(combat, table, mid, severity=severity, generation_only=generation_only)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert before.state.round_number == 2
    assert 'heavenly-state' in records(before, before.state.actors[OWNER])
    assert not records(before, before.state.actors[FOE])
    start = before.state.event_sequence
    if conversion == 'guard':
        use(combat, table, mid, 'Hostile blow', OWNER,
            choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['use']})
    else:
        use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
        if conversion == 'strike':
            turn(table, mid, OWNER)
            use(combat, table, mid, 'Return blow', FOE,
                choices={'reaction:typed.' + SOURCE + '.integrity_strike': 'first',
                         f.CHOICE + 'heavenly_vessel': ['use']})
        else:
            use(combat, table, mid, 'Constitution ordeal', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    spends = [e for e in engine.events if e.sequence > start and e.event_type == 'RESOURCE_SPENT'
              and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1 and actor.resources[POOL] == 0
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]) == 1
    rank = 1 if generation_only else severity
    expected = {'guard': {1: 14, 2: 10, 3: 6}, 'strike': {1: 12, 2: 8, 3: 4},
                'rejection': {1: 8, 2: 8, 3: 4}}[conversion][rank]
    if conversion == 'guard':
        damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
        assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == expected
    elif conversion == 'strike':
        assert any(e.sequence > start and e.event_type == 'PASSIVE_TRIGGERED'
                   and e.source_definition_id == SOURCE + '.integrity_strike'
                   and f'adds {expected} damage' in e.payload.get('log', '') for e in engine.events)
    else:
        receipt = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED'
                       and e.source_definition_id == SOURCE + '.integrity_rejection')
        assert receipt.payload['bonus'] == expected
        assert receipt.payload['checkpoint'] == ('after_failure' if rank == 1 else 'before_outcome')
    record_state(combat, table, mid, severity=severity, generation_only=generation_only, active=False)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_withdrawing_one_native_state_preserves_independent_generation_suppression(tmp_path, monkeypatch):
    from combat.table_facts import records
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch)
    record_state(combat, table, mid, severity=3, record_id='strain')
    record_state(combat, table, mid, generation_only=True, record_id='generation')
    record_state(combat, table, mid, severity=3, record_id='strain', active=False)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['use']})
    engine = reload(tmp_path, mid)
    assert set(records(engine, engine.state.actors[OWNER])) == {'generation'}
    assert engine.state.actors[OWNER].resources[POOL] == 0
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == 14


@pytest.mark.parametrize('invalid', ['severity', 'wrong_owner', 'private', 'round_deadline'])
def test_state_source_rejects_unlisted_severity_unowned_or_uninformed_subjects(tmp_path, invalid):
    combat, table, mid = acquired_fight(tmp_path)
    kwargs = {'severity': 4} if invalid == 'severity' else (
        {'subject_id': ALLY} if invalid == 'wrong_owner' else
        {'witness_ids': [FOE]} if invalid == 'private' else {'valid_through_round': 2})
    with pytest.raises(Exception, match='Heavenly|cultivator|persistent'):
        record_state(combat, table, mid, **kwargs)
    assert not [e for e in reload(tmp_path, mid).events if e.event_type == 'TABLE_FACT_RECORDED']


def test_native_refresh_does_not_stack_and_expires_at_end_of_next_turn(tmp_path, monkeypatch):
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == 2 and engine.state.actors[OWNER].resources[POOL] == 1
    foe = engine.state.actors[FOE]
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
                and engine.grid.distance_ft(c.destination, foe.position) > 5)
    settle(table, mid, move.candidate_id, choices={'reaction:typed.opportunity_attack': 'first',
        'system:combat.opportunity_attack': 'first', f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    grants = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
              and e.payload.get('resource_id') == POOL]
    assert len(grants) == 1 and engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].turn_flags['pressure_round_clock'][POOL]['ends_left'] == 2
    assert engine.state.actors[OWNER].turn_flags['pressure_round_clock'][POOL]['count'] == 1
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0


@pytest.mark.parametrize('natural', [1, 20])
def test_manual_death_save_retains_legal_spend_without_changing_natural_outcome(tmp_path, monkeypatch, natural):
    fixed(monkeypatch, natural)
    def delivery(bundles):
        add_action(bundles[2], 'Knock down', [{'type': 'damage', 'flat': 500,
            'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='heaven_rejecting_marrow', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    use(combat, table, mid, 'Knock down', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].life_state == 'DYING'
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={f.CHOICE + 'heavenly_rejection_timing': ['use'], RID: ['use']})
    engine = reload(tmp_path, mid)
    death = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED'
                 and e.actor_id == OWNER and e.payload.get('skill') == 'Death Saving Throw')
    assert death.payload['actor']['natural_result'] == natural
    assert death.payload['actor']['modifier'] == 4
    assert death.payload['success'] is (natural == 20)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == SOURCE + '.integrity_rejection']
    assert len(spends) == 1


@pytest.mark.parametrize('expression', ['', 'heaven_rejecting_marrow'])
def test_actual_negative_roll_is_not_confused_with_automatic_failure(tmp_path, monkeypatch, expression):
    fixed(monkeypatch, 1)
    def delivery(bundles):
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression=expression,
        con_score=3, delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    modifier = reload(tmp_path, mid).state.actors[OWNER].saving_throws['CON']
    assert 1 + modifier < 0
    use(combat, table, mid, 'Constitution ordeal', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == SOURCE + '.integrity_rejection')
    assert receipt.payload['bonus'] == 4
    assert receipt.payload['checkpoint'] == ('after_failure' if expression else 'before_outcome')
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_real_automatic_failure_does_not_become_a_numeric_rejection_roll(tmp_path, monkeypatch):
    fixed(monkeypatch)
    def delivery(bundles):
        add_action(bundles[2], 'Paralyze body', [{'type': 'condition', 'condition': 'paralyzed',
            'applies_to': 'target'}], economy='NONE')
        add_action(bundles[2], 'Bodily poison', [{'type': 'save', 'ability': 'DEX',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=14)
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='heaven_rejecting_marrow', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    use(combat, table, mid, 'Paralyze body', OWNER)
    prompts = use(combat, table, mid, 'Bodily poison', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_AUTO_FAILED' and e.actor_id == OWNER for e in engine.events)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not any(p['context']['reaction_source_id'] == RID for p in prompts)

def native_restriction_delivery(bundles, *, kind='heavenly_vessel_strain', severity=3, parent_clock=False, no_clock=False):
    effect = {'type': 'heavenly_body_state', 'kind': kind, 'severity': severity, 'applies_to': 'target'}
    if not parent_clock and not no_clock:
        effect['expires_on'] = 'END_OF_HOLDER_NEXT_TURN'
    add_action(bundles[2], 'Apply bodily restriction', [effect], economy='NONE')
    if parent_clock:
        action = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Apply bodily restriction')
        action['parameters']['typed']['duration'] = {'kind': 'until_end_of_turn'}


@pytest.mark.parametrize('kind,severity,parent_clock,expected', [
    ('heavenly_vessel_strain', 3, False, 6),
    ('suppressed_heavenly_integrity', 0, True, 14),
])
def test_native_restriction_effect_preserves_actual_source_and_holder_or_parent_clock(
        tmp_path, monkeypatch, kind, severity, parent_clock, expected):
    from combat.ext.heavenly_body_states import CONDITION
    def delivery(bundles):
        native_restriction_delivery(bundles, kind=kind, severity=severity, parent_clock=parent_clock)
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, extra_delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Apply bodily restriction', OWNER)
    engine = reload(tmp_path, mid)
    condition = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == CONDITION)
    source = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Apply bodily restriction')
    assert condition.source_actor_id == FOE and condition.source_definition_id == source
    assert condition.data['state_kind'] == kind and condition.data['severity'] == severity
    assert condition.expires_on == ('END_OF_CURRENT_TURN' if parent_clock else 'END_OF_HOLDER_NEXT_TURN')
    maximum = engine.state.actors[OWNER].maximum_hp
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['use']})
    engine = reload(tmp_path, mid)
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == expected
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]) == 1
    assert not [e for e in engine.events if e.event_type == 'TABLE_FACT_RECORDED']
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == CONDITION for c in engine.state.actors[OWNER].conditions.values()) is not parent_clock
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].maximum_hp == maximum
    assert engine.state.actors[OWNER].resources[POOL] == 0
    use(combat, table, mid, 'Minion blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_native_source_restriction_is_inert_on_non_heavenly_target(tmp_path, monkeypatch):
    from combat.ext.heavenly_body_states import CONDITION
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, extra_delivery=native_restriction_delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Apply bodily restriction', ALLY)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == CONDITION for actor in engine.state.actors.values() for c in actor.conditions.values())
    assert engine.state.actors[OWNER].resources[POOL] == 1


def test_native_source_restriction_rejects_missing_lifetime_without_creating_state(tmp_path, monkeypatch):
    from combat.ext.heavenly_body_states import CONDITION
    def delivery(bundles):
        native_restriction_delivery(bundles, no_clock=True)
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, extra_delivery=delivery)
    turn(table, mid, FOE)
    from combat.gate5_service import CombatServiceError
    with pytest.raises(CombatServiceError, match='completed intent was rejected') as rejected:
        use(combat, table, mid, 'Apply bodily restriction', OWNER)
    assert 'expiry' in str(rejected.value.__cause__)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources[POOL] == 1


def test_private_state_withdrawal_does_not_end_native_source_restriction(tmp_path, monkeypatch):
    from combat.ext.heavenly_body_states import CONDITION
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, extra_delivery=native_restriction_delivery)
    record_state(combat, table, mid, generation_only=True, record_id='private-generation')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Apply bodily restriction', OWNER)
    record_state(combat, table, mid, generation_only=True, record_id='private-generation', active=False)
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['use']})
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == CONDITION for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources[POOL] == 0
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == 6


def test_native_acquired_ai_owner_spends_strike_without_player_prompt(tmp_path):
    def delivery(bundles):
        add_action(bundles[0], 'AI return attack', [{'type': 'attack', 'attack_kind': 'weapon',
            'on_hit': [{'type': 'damage', 'flat': 40, 'damage_types': ['poison'], 'applies_to': 'target'}]}], bonus=100)
        # Give the native ranker the actual flat damage of this fixture attack.
        bundles[0]['action_catalog'][-1]['parameters']['expected_damage'] = 40
    combat, table, mid = acquired_fight(tmp_path, stage='Refined', expression='orthodox_answering_strike', delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.event_sequence
    prompts = []
    for _ in range(16):
        prompts.extend(settle(table, mid, 'real-ai-step', auto=True, choices={}))
        engine = reload(tmp_path, mid)
        if engine.state.actors[OWNER].resources[POOL] == 0 or engine.state.current_actor_id != OWNER:
            break
    assert not prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert any(e.sequence > before and e.event_type == 'PASSIVE_TRIGGERED'
               and e.source_definition_id == SOURCE + '.integrity_strike'
               and 'adds 8 damage' in e.payload.get('log', '') for e in engine.events)


def test_native_canonical_non_attack_technique_generates_from_actual_damage_source(tmp_path):
    combat, table, mid = acquired_fight(tmp_path, stage='Awakened', foe_talents=['FIRE_TAL_FIREBALL_ART'])
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    spell = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == 'Fireball Art')
    before = engine.state.event_sequence
    use(combat, table, mid, 'Fireball Art', at=(3, 6), choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id == spell.source_definition_id and OWNER in e.target_ids]
    assert damage and sum(e.payload['hp_damage'] for e in damage) > 0
    assert not [e for e in engine.events if e.sequence > before and e.event_type == 'ATTACK_ROLLED'
                and e.source_definition_id == spell.source_definition_id]
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert len([e for e in engine.events if e.sequence > before and e.event_type == 'RESOURCE_GAINED'
                and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]) == 1


def test_native_acquired_ai_guard_uses_its_own_reaction_without_player_prompt(tmp_path):
    combat, table, mid = acquired_fight(tmp_path, expression='jade_gold_guard')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={f.CHOICE + 'foundation_combat': None})
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Hostile blow', OWNER)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not engine.state.actors[OWNER].reaction_available
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['rolled_or_pending_damage'] - damage.payload['hp_damage'] == 14


def test_native_acquired_human_keeps_guard_and_vessel_choices_on_actual_ai_turn(tmp_path, monkeypatch):
    def delivery(bundles):
        add_action(bundles[2], 'AI pressure attack', [{'type': 'attack', 'attack_kind': 'weapon',
            'on_hit': [{'type': 'damage', 'flat': 40, 'damage_types': ['poison'], 'applies_to': 'target'}]}], bonus=100)
        bundles[2]['action_catalog'][-1]['parameters']['expected_damage'] = 40
    combat, table, mid = previous_round_integrity(tmp_path, monkeypatch, extra_delivery=delivery)
    turn(table, mid, FOE)
    # A real relationship command leaves the AI one hostile creature, while
    # preserving every option legal in that scenario.
    engine = reload(tmp_path, mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': FOE,
        'other': ALLY, 'relation': 'ALLY'}, expected_state_version=engine.state.state_version)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.event_sequence
    prompts = []
    for _ in range(16):
        prompts.extend(settle(table, mid, 'real-ai-step', auto=True,
            choices={f.CHOICE + 'foundation_combat': ['use'], f.CHOICE + 'heavenly_vessel': ['keep']}))
        engine = reload(tmp_path, mid)
        if any(p['context']['reaction_source_id'] == f.CHOICE + 'foundation_combat' for p in prompts) \
                or engine.state.current_actor_id != FOE:
            break
    guard = next(p for p in prompts if p['context']['reaction_source_id'] == f.CHOICE + 'foundation_combat')
    engine = reload(tmp_path, mid)
    accepted = next(e for e in engine.events if e.sequence > before and e.event_type == 'INTENT_ACCEPTED'
                    and e.actor_id == FOE and e.source_definition_id in engine.action_catalog)
    action = engine.action_catalog[accepted.source_definition_id]
    assert guard['context']['reactor_id'] == OWNER
    assert action.display_name in guard['moment']
    assert engine.state.actors[OWNER].display_name in guard['moment']
    assert any(p['context']['reaction_source_id'] == f.CHOICE + 'heavenly_vessel' for p in prompts)
    assert len([e for e in engine.events if e.sequence > before and e.event_type == 'RESOURCE_SPENT'
                and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]) == 1
    # Guard spent the real previous-round reserve. This round's damage then
    # generates a new reserve, never a second same-event Guard payment.
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert 'foundation_round_vessel' not in engine.state.actors[OWNER].turn_flags
