"""Last Inch native acquisition, table transactions, persisted facts and seams.

Synthetic source actions below guard the general source-state producer. They
are not substituted for ownership or for the actual acquired tradition row.
No providers, browser, live service or live model transport is used.
"""
from copy import deepcopy

import pytest

from combat.factory_compiler import compile_character
from combat.ext.last_inch_palm import LAST_INCH, SUBJECT, is_subject
from combat.ext.source_state import CATEGORIES
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_foundations3 import add_action
from tests.test_ns1r_non_sphere_authority import authority as admission_authority

PATH = 'tianxia.path.spirit_awakening'
TRADITION = 'tianxia.tradition.spirit.last_inch_palm'
SPIKE = PATH + '.feature.mind_spike'
DESIGNATE = 'choice:needle.last_inch.designate'
STEP = 'choice:needle.last_inch.step'
BENEFIT = 'choice:needle.last_inch.step_benefit'


@pytest.fixture(scope='module')
def acquired(catalog_environment):
    """Use the real frozen catalog, milestone producer and causal acquisition."""
    from character_creation.response_materialization import CanonicalSelectionIntent
    from tests.test_creation_training_r4 import _real_creation_intent
    from tests.test_rec1_p1cr5_owner_authority import _private_scope
    from stage2.service import RulesCausalStage2Service, _state
    from contracts.canonical import ZERO_HASH
    from projector.v3_bridge import _build_earned_feature_occurrences
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment, target_cl=3)
    doc = intent.as_dict()
    doc['selected_by_slot']['path_choice'] = [PATH]
    doc['selected_by_slot']['subpath_choice'] = [TRADITION]
    doc['bounded_choices']['path_progression_by_cl'] = {str(i): PATH for i in (1, 2, 3)}
    records = creator._locked_records_for_project(project['project_id'])
    known = {p['sphere_id'] for p in doc['acquisition_intent']['sphere_free_talent_pairs']}
    # This character needs no constructed training manual. Keep this regression
    # on the ordinary source-backed Path/Tradition acquisition route.
    doc['acquisition_intent']['trained_choices'] = []
    used = set()
    used.update(p['talent_id'] for p in doc['acquisition_intent']['sphere_free_talent_pairs'])
    ordinary = []
    for rid, record in sorted(records.items()):
        auth = record.get('compatibility', {}).get('factory', {}).get('stage2_authority') or {}
        sphere = auth.get('owning_canonical_sphere_id') or auth.get('sphere_id') or record.get('owning_canonical_sphere_id')
        if (rid not in used and sphere in known and 'level_talent_acquisition' in auth.get('allowed_kinds', [])
                and (auth.get('minimum_cl') or 1) <= 1 and not record.get('prerequisites')):
            ordinary.append(rid); used.add(rid)
        if len(ordinary) == 3:
            break
    assert len(ordinary) == 3
    doc['acquisition_intent']['ordinary_talent_ids'] = ordinary
    intent = CanonicalSelectionIntent.from_document(doc)
    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent, include_manual_collection=False)
    assert [(r['effective_cl'], r['record_id']) for r in rows if r['kind'] == 'subpath_acquisition'] == [(3, TRADITION)]
    # Delegated Paths are authenticated source projections, rather than owner
    # locks. Use the same native projection as the materializer and Stage 2.
    from non_sphere_authority.service import NonSphereAuthorityService
    native = NonSphereAuthorityService(creator.db)
    records[PATH] = native.project_locked_path_catalog_record(PATH)
    records[TRADITION] = native.project_locked_subpath_catalog_record(TRADITION)
    for feature in native.path_profiles[PATH]['features']:
        rid = feature['canonical_id']
        records[rid] = native.project_locked_path_feature_catalog_record(PATH, rid)
    stage2 = RulesCausalStage2Service(creator.db)
    state = _state(project['project_id'])
    proposal = {'project_id': project['project_id'], 'proposal_id': 'seamfix-last-inch',
                'expected_project_revision': project['revision'], 'idempotency_key': 'seamfix-last-inch',
                'created_at': '2026-10-15T00:00:00+00:00'}
    events, event_records = [], {}
    with _private_scope(stage2, run['request'], run['run_id'], {PATH}), creator.db.connection() as conn:
        for index, row in enumerate(rows):
            event, state, blockers = stage2._choice_event(conn=conn, row=proposal, project=project, state=state,
                choice=row, index=index, sequence=index+1,
                previous_hash=events[-1]['event_hash'] if events else ZERO_HASH, generic_prefix=events)
            assert blockers == [], (row['kind'], blockers)
            assert event is not None
            events.append(event)
            event_records[event['event_id']] = records.get(row['record_id'], {})
    def of(kind):
        return [e for e in events if e['advancement']['kind'] == kind]
    occurrences = _build_earned_feature_occurrences(path_events=of('path_acquisition'), level_events=of('level_advance'),
        score_change_events=of('ability_score_change'), subpath_events=of('subpath_acquisition'),
        event_records=event_records, locked_records=records, packet_by_event={e['event_id']: e['event_hash'] for e in events},
        selected_path_ids=[PATH], factory_root=catalog_environment['root'])
    assert LAST_INCH in {r['feature_id'] for r in occurrences}
    result = sheet([], cl=3, key='INT', primary='Resonance', name='Wren')
    result['identity']['path'] = 'Spirit Awakening'
    result['path_and_subpath'] = {'path_record_ids': [PATH], 'earned_feature_occurrences': occurrences}
    return result


def setup(tmp_path, acquired, *, owns=True, cl=3, at=(4, 6), transform=None, modes=None, seed='SEAMFIX-LAST-1', foe_features=(), ally_talents=(), owner_talents=(), battlefield=None, owner_plan=None, owner_sheet_transform=None, foe_dc=16):
    doc = deepcopy(acquired)
    doc['identity']['cultivation_level'] = cl
    if not owns:
        doc['path_and_subpath'] = {}
    if owner_talents:
        doc['spheres_and_talents'] = {'sphere_record_ids': ['tianxia.sphere.fate'], 'learned_talent_record_ids': list(owner_talents)}
    stats = doc['ability_scores_and_statistics']
    for ability in stats['abilities']:
        mod = {'WIS': 5, 'STR': 1, 'INT': 0}.get(ability['ability'], 2)
        ability.update(modifier=mod, score=10+2*mod)
    stats['primary_resource']['maximum'] = 60
    stats['technique_save_dc'] = 40
    if owner_sheet_transform:
        owner_sheet_transform(doc)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan=owner_plan or {'ask': True})
    foe = sheet(list(foe_features), cl=3, name='Mara', primary='Resonance')
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['technique_save_dc'] = foe_dc
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    def delivery(bundles):
        if transform:
            transform(bundles)
        from combat.canonical import canonical_sha256
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    return fixture(tmp_path, [], owner_bundle=owner, foe_sheet=foe, named=True, seed=seed, modes=modes, ally_talents=ally_talents,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 7}, FOE: {'x': at[0], 'y': at[1]}},
        bundle_transform=delivery, battlefield=battlefield)


def strike(combat, table, mid, target=FOE, *, choices=None):
    return settle(table, mid, candidate(combat, mid, 'Spirit-Touch Unarmed Strike', target=target).candidate_id,
        choices={DESIGNATE: 'designate', **(choices or {})})


def subjects(engine, target=FOE):
    return [c for c in engine.state.actors[target].conditions.values() if c.condition_id == SUBJECT]


def move(combat, table, mid, at, *, choices=None):
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination and
             (c.destination.x, c.destination.y) == at)
    return settle(table, mid, c.candidate_id, choices=choices or {})


def test_acquired_strike_wisdom_record_diagnosis_commit_cold_reload(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired)
    prompts = strike(combat, table, mid)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    [record] = subjects(engine)
    assert record.data['source_cl'] == 3 and record.data['subject'] == FOE
    assert record.data['origin'] == OWNER and record.data['ownership_kind'] == 'practitioner'
    assert record.data['trigger'].startswith('Your Spirit-Touch') and record.data['line_of_effect'] == 1
    assert record.data['expiration'].startswith('END_OF_SOURCE_TURN_AT:')
    attack = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.parameters.get('spirit_touch'))
    assert attack.parameters['typed']['numbers']['key_mod'] == 5
    assert attack.parameters['typed']['numbers']['attack_bonus'] == 9
    assert not attack.parameters['typed'].get('weapon')
    finding = next(e for e in engine.events if e.payload.get('category_observation'))
    assert finding.payload['categories'] == dict.fromkeys(CATEGORIES, 'unknown')
    assert any(p['context']['reaction_source_id'] == DESIGNATE for p in prompts)
    from combat.target_knowledge import recent_events
    assert any(e['payload'].get('category_observation') for e in recent_events(engine, engine.state.actors[OWNER], engine.events))
    assert not any(e['payload'].get('category_observation') for e in recent_events(engine, engine.state.actors[ALLY], engine.events))
    assert any(e['payload'].get('category_observation') for e in recent_events(engine, engine.state.actors[OWNER], []))
    from combat.ext.source_state import known_categories
    assert known_categories(engine.state.actors[ALLY], FOE) == dict.fromkeys(CATEGORIES, 'unknown')


def test_restricted_admission_requires_level_path_and_actual_source_record(admission_authority):
    from tests.test_ns1r_non_sphere_authority import insert_project
    from tests.ns1r_evidence_helpers import access_evidence, ap_award, commit_authority_event
    from app.core import FoundryError
    service, db = admission_authority
    pid = 'seamfix-last-inch-admission'
    insert_project(db, pid, target_cl=3)
    service.initialize_for_project(pid, target_cl=3, path_ids=[PATH], method_id='METHOD-005',
        access_source_records=access_evidence(db, service, pid, 'METHOD-005'))
    with pytest.raises(FoundryError, match='minimum Path attainment'):
        service.select_subpath(pid, PATH, TRADITION)
    service.allocate_advancement(pid, {PATH: 2}, evidence_id=ap_award(db, service, pid, 'METHOD-005', 3, 2),
        idempotency_key='seamfix-level3')
    with pytest.raises(FoundryError) as missing:
        service.select_subpath(pid, PATH, TRADITION)
    assert missing.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
    with pytest.raises(FoundryError) as wrong:
        service.select_subpath(pid, 'tianxia.path.body_refining', TRADITION)
    assert wrong.value.code == 'NS1R_PATH_SUBPATH_MISMATCH'
    evidence = commit_authority_event(db, service, pid, 'subpath_access', {'path_id': PATH, 'selection_id': TRADITION})
    state = service.select_subpath(pid, PATH, TRADITION, access_source_records=[evidence])
    assert next(p for p in state['paths'] if p['path_id'] == PATH)['subpath_or_tradition_id'] == TRADITION


@pytest.mark.parametrize('owns,cl', [(False, 3), (True, 2)])
def test_wrong_owner_and_level_do_not_gain_strike(tmp_path, acquired, owns, cl):
    combat, table, mid = setup(tmp_path, acquired, owns=owns, cl=cl)
    engine = reload(tmp_path, mid)
    assert not any(a.parameters.get('spirit_touch') and a.owner_id == OWNER for a in engine.action_catalog.values())


def test_strength_spirit_touch_uses_native_fixed_unarmed_damage_without_weapon_identity(tmp_path, acquired, monkeypatch):
    from combat import typed_executor
    notified_kinds = []
    notify = typed_executor._notify_damage_dealt
    def observe(ctx, *args, **kwargs):
        if ctx.action.display_name == 'Spirit-Touch Unarmed Strike (Strength)':
            notified_kinds.append(ctx.damage_packet_kind)
        return notify(ctx, *args, **kwargs)
    monkeypatch.setattr(typed_executor, '_notify_damage_dealt', observe)
    combat, table, mid = setup(tmp_path, acquired)
    hp = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Spirit-Touch Unarmed Strike (Strength)', target=FOE).candidate_id,
        choices={DESIGNATE: 'designate'})
    engine = reload(tmp_path, mid)
    assert hp - engine.state.actors[FOE].current_hp == 2
    assert len(subjects(engine)) == 1
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name.endswith('(Strength)'))
    assert action.parameters['typed']['numbers']['attack_bonus'] == 5
    assert not action.parameters['typed'].get('weapon')
    assert action.parameters['typed']['damage_profile']['fixed_damage'] == 2
    assert notified_kinds and set(notified_kinds) == {'technique'}


def test_spirit_touch_inherits_only_current_native_unarmed_reach(tmp_path, acquired):
    def body_sources(doc):
        path = doc['path_and_subpath']
        path['path_record_ids'].append('tianxia.path.body_refining')
        path['path_feature_record_ids'] = ['tianxia.path.body_refining.feature.iron_fist',
            'tianxia.subpath.body.oni_blood.feature.oni_mask', 'tianxia.subpath.body.oni_blood.feature.oni_form']
        doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [{'name': 'Stamina', 'maximum': 60}]
    combat, table, mid = setup(tmp_path, acquired, cl=14, at=(6, 6), owner_sheet_transform=body_sources)
    engine = reload(tmp_path, mid)
    assert not any(c.display_name == 'Spirit-Touch Unarmed Strike' and c.target_ids == (FOE,) for c in engine.legal_candidates())
    settle(table, mid, candidate(combat, mid, 'Oni Form').candidate_id, choices={})
    engine = reload(tmp_path, mid)
    assert not subjects(engine)
    assert candidate(combat, mid, 'Spirit-Touch Unarmed Strike', target=FOE)


def profiled_arena(objects, source_states=()):
    from combat.tabletop import normalize_map, to_battlefield
    return to_battlefield(normalize_map({'display_name': 'Contact profile guard', 'width_squares': 20, 'height_squares': 14,
        'objects': objects, 'source_states': list(source_states), 'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}}))


def test_map_profile_producer_external_asset_internal_anchor_and_expiry(tmp_path, acquired):
    objects = [
        {'id': 1, 'kind': 'custom', 'x': 4, 'y': 5, 'name': 'External spirit asset', 'hp': 100, 'ac': 1,
         'blocks': False, 'spiritual_profile': {'source_rule': 'test:spiritual_asset_source', 'source_cl': 3, 'identity': 1}},
        {'id': 2, 'kind': 'custom', 'x': 4, 'y': 6, 'name': 'Internal Soul Anchor', 'hp': 100, 'ac': 1,
         'blocks': False, 'spiritual_profile': {'source_rule': 'test:internal_anchor_source', 'source_cl': 3, 'identity': 1, 'anchor': 'internal'}},
        {'id': 3, 'kind': 'crate', 'x': 4, 'y': 7, 'name': 'Ordinary crate', 'blocks': False},
    ]
    combat, table, mid = setup(tmp_path, acquired, at=(6, 6), battlefield=profiled_arena(objects))
    engine = reload(tmp_path, mid)
    targets = {c.target_ids[0] for c in engine.legal_candidates() if c.target_ids and
               engine.action_catalog.get(c.source_definition_id) and engine.action_catalog[c.source_definition_id].parameters.get('spirit_touch')}
    assert 'object:map.1' in targets and 'object:map.2' not in targets and 'object:map.3' not in targets
    strike(combat, table, mid, 'object:map.1')
    engine = reload(tmp_path, mid)
    [record] = engine.state.objects['object:map.1'].component['contact_records']
    assert record['expiration'].startswith('END_OF_TURN_AT:' + OWNER + ':')
    assert engine.state.objects['object:map.2'].component['spiritual_profile']['anchor'] == 'internal'
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.objects['object:map.1'].component['contact_records']
    turn(table, mid, FOE)
    assert not reload(tmp_path, mid).state.objects['object:map.1'].component['contact_records']


def test_visible_sealed_boundary_keeps_identity_but_supplies_no_contact(tmp_path, acquired):
    wall = {'id': 1, 'kind': 'custom', 'x': 4, 'y': 6, 'name': 'Sealed spiritual boundary', 'blocks': False,
        'spiritual_profile': {'source_rule': 'test:sealed_boundary_source', 'source_cl': 3, 'contact_barrier': 1}}
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6), battlefield=profiled_arena([wall]))
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    engine = reload(tmp_path, mid)
    [record] = subjects(engine)
    assert record.data['line_of_effect'] == 0
    assert not is_subject(engine, engine.state.actors[OWNER], engine.state.actors[FOE])


def test_perfect_spiritual_concealment_suppresses_only_conceptual_reach(tmp_path, acquired):
    def effects(bundles):
        add_action(bundles[2], 'Conceal spirit', [{'type': 'source_state', 'applies_to': 'self',
            'perfect_spiritual_concealment': 1, 'duration': {'kind': 'one_minute'}}], target_kind='SELF')
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6), transform=effects)
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Conceal spirit').candidate_id, choices={})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert subjects(engine) and not is_subject(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    assert not any(c.display_name == 'Spirit-Touch Unarmed Strike' and c.target_ids == (FOE,) for c in engine.legal_candidates())
    move(combat, table, mid, (4, 6))
    assert candidate(combat, mid, 'Spirit-Touch Unarmed Strike', target=FOE)


@pytest.mark.parametrize('fact', [
    {'spiritual_contact_denied': 1}, {'perfect_spiritual_concealment': 1}, {'plane': 'ethereal'},
    {'level_limit_path': 'Spirit Awakening', 'level_limit_cl': 2},
])
def test_suppressed_record_survives_and_restores_after_real_source_expires(tmp_path, acquired, fact):
    def effects(bundles):
        add_action(bundles[2], 'Separate contact', [{'type': 'source_state', **fact,
            'applies_to': 'target' if 'level_limit_cl' in fact else 'self',
            'expires_on': 'END_OF_CURRENT_TURN'}], target_kind='HOSTILE_ENTITY' if 'level_limit_cl' in fact else 'SELF')
    combat, table, mid = setup(tmp_path, acquired, transform=effects)
    strike(combat, table, mid)
    turn(table, mid, FOE)
    target = OWNER if 'level_limit_cl' in fact else None
    settle(table, mid, candidate(combat, mid, 'Separate contact', target=target).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    assert len(subjects(engine)) == 1
    assert not is_subject(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    assert subjects(engine)[0].data['line_of_effect'] == 0
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert is_subject(engine, engine.state.actors[OWNER], engine.state.actors[FOE])


def test_source_categories_are_category_only_and_personal(tmp_path, acquired):
    fact = {'target_id': FOE, 'source_rule': 'table:private_spiritual_state', 'source_cl': 3,
            'duration_rounds': 10, 'label': 'SECRET SOURCE AND CURE',
            'facts': {'categories': {key: 'present' if i % 2 == 0 else 'absent' for i, key in enumerate(CATEGORIES)}}}
    combat, table, mid = setup(tmp_path, acquired, battlefield=profiled_arena([], [fact]))
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.payload.get('category_observation'))
    assert event.payload['categories'] == {key: 'present' if i % 2 == 0 else 'absent' for i, key in enumerate(CATEGORIES)}
    assert 'SECRET' not in str(event.payload)
    [finding] = [c for c in engine.state.actors[OWNER].conditions.values() if 'category_observation:' in c.condition_id]
    assert finding.data['subject'] == FOE and finding.data['category:curse'] == 'absent'
    from combat.target_knowledge import recent_events
    from combat.ext.source_state import known_categories
    assert known_categories(engine.state.actors[ALLY], FOE) == dict.fromkeys(CATEGORIES, 'unknown')
    assert not any(e['source_definition_id'] == 'table:private_spiritual_state'
                   for e in recent_events(engine, engine.state.actors[ALLY], engine.events))
    from combat.target_knowledge import actors_for
    projected = {actor.entity_id: actor for actor in actors_for(engine, engine.state.actors[ALLY])}
    assert not any(c.data.get('recipient_id') for actor in projected.values() for c in actor.conditions.values())
    assert any(c.data.get('recipient_id') == 'system:table' for c in engine.state.actors[FOE].conditions.values())
    own = next(actor for actor in actors_for(engine, engine.state.actors[OWNER]) if actor.entity_id == OWNER)
    assert any(c.data.get('recipient_id') == OWNER for c in own.conditions.values())


def test_private_source_expiry_does_not_disclose_its_state_or_source(tmp_path, acquired):
    fact = {'target_id': FOE, 'source_rule': 'table:sealed_private_curse', 'source_cl': 3,
            'duration_rounds': 1, 'facts': {'categories': {'curse': 'present'}}}
    combat, table, mid = setup(tmp_path, acquired, battlefield=profiled_arena([], [fact]))
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.source_definition_id == fact['source_rule'] for c in engine.state.actors[FOE].conditions.values())
    ended = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
             and e.payload.get('condition_id') == 'condition:typed.source_state']
    assert ended and all(e.payload['recipient_id'] == 'system:table' for e in ended)
    from combat.target_knowledge import recent_events
    for viewer in (OWNER, ALLY, FOE):
        visible = recent_events(engine, engine.state.actors[viewer], engine.events)
        assert not any(e['source_definition_id'] == fact['source_rule'] or
                       e['payload'].get('condition_id') == 'condition:typed.source_state' for e in visible)


def test_real_curse_word_state_is_read_without_disclosing_source_or_cure(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired, owner_talents=['TAL_FATE_CURSE_WORD'])
    settle(table, mid, candidate(combat, mid, 'Curse Word', target=FOE).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    from combat.ext.source_state import categories
    finding = categories(engine.state.actors[FOE], engine)
    assert finding['curse'] == 'present'
    assert 'Curse Word' not in str(finding) and OWNER not in str(finding)


@pytest.mark.parametrize('kind,cancel', [('attack', False), ('check', False), ('save', False), ('check', True)])
def test_next_d20_source_state_uses_native_modes_and_consumes_only_on_draw(tmp_path, acquired, kind, cancel):
    def probes(bundles):
        add_action(bundles[2], 'Native probe attack', [{'type': 'attack', 'attack_kind': 'unarmed',
            'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force']}]}])
        add_action(bundles[2], 'Native probe check', [{'type': 'contest_against',
            'actor_check': {'kind': 'check', 'ability': 'STR'}, 'target_check': {'kind': 'dc', 'dc': 1},
            'on_success': [], 'on_fail': []}])
        add_action(bundles[0], 'Native probe save', [{'type': 'save', 'ability': 'WIS', 'dc': 1,
            'on_fail': [], 'on_success': []}], economy='BONUS_ACTION')
        add_action(bundles[0], 'Countervailing source', [{'type': 'advantage', 'applies_to': 'target',
            'on': 'the next d20 Test', 'duration': {'kind': 'one_minute'}}], economy='NONE')
    combat, table, mid = setup(tmp_path, acquired, owner_talents=['TAL_FATE_CURSE_WORD'], transform=probes)
    settle(table, mid, candidate(combat, mid, 'Curse Word', target=FOE).candidate_id, choices={})
    if cancel:
        settle(table, mid, candidate(combat, mid, 'Countervailing source', target=FOE).candidate_id, choices={})
    from combat.ext.d20_test_modes import CONDITION
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == CONDITION for c in engine.state.actors[FOE].conditions.values())
    before = len(engine.rolls)
    if kind == 'save':
        settle(table, mid, candidate(combat, mid, 'Native probe save', target=FOE).candidate_id, choices={})
    else:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Native probe ' + kind, target=OWNER).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    [roll] = [r for r in engine.rolls[before:] if r.actor_id == FOE and r.natural_result is not None]
    assert roll.mode == ('NORMAL' if cancel else 'DISADVANTAGE')
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[FOE].conditions.values())


def test_subject_only_ten_foot_opportunity_and_ordinary_options_remain(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired)
    strike(combat, table, mid)
    turn(table, mid, FOE)
    # First crossing the ordinary 5-foot profile must remain a separate option.
    prompts = move(combat, table, mid, (5, 6), choices={STEP: None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].reaction_available
    prompts = move(combat, table, mid, (6, 6), choices={STEP: None, 'reaction:core.opportunity_attack': 'first'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and e.source_definition_id.endswith('spirit_touch_strike') for e in engine.events)
    from combat.opportunity_profiles import additional
    assert {p[2] for p in additional(engine, engine.state.actors[OWNER], engine.state.actors[FOE])} == {10}
    assert {p[2] for p in additional(engine, engine.state.actors[OWNER], engine.state.actors[ALLY])} == {5}


def test_step_moves_before_pressure_and_expires_on_subject_turn(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6))
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    prompts = move(combat, table, mid, (6, 6), choices={STEP: 'step', BENEFIT: 'pressure',
        'choice:needle.last_inch.step_pressure': 'stilled_intent', 'choice:needle.last_inch_step_move': 'cell:4,6',
        'reaction:core.opportunity_attack': None})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == STEP for p in prompts)
    assert engine.state.actors[OWNER].position.x == 4
    denial = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == 'condition:typed.reaction_denied')
    assert denial.expires_on.startswith('START_OF_TURN_AT:' + FOE + ':')
    movement = next(e.sequence for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    pressure = next(e.sequence for e in engine.events if e.event_type == 'CONDITION_APPLIED' and e.payload.get('condition_id') == 'condition:typed.reaction_denied')
    assert movement < pressure
    turn(table, mid, OWNER)
    assert any(c.condition_id == 'condition:typed.reaction_denied' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    assert not any(c.condition_id == 'condition:typed.reaction_denied' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_human_step_is_asked_during_real_local_ai_step(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6),
        owner_plan={'ask': True, 'off': ['opportunity_attack']})
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    move(combat, table, mid, (6, 6), choices={STEP: None})
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, '', auto=True, choices={STEP: 'step', BENEFIT: 'pressure',
        'choice:needle.last_inch.step_pressure': 'stilled_intent', 'choice:needle.last_inch_step_move': 'cell:4,6'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == STEP and p['context']['reactor_id'] == OWNER for p in prompts)
    assert not engine.state.actors[OWNER].reaction_available


def test_ai_step_owner_chooses_automatically_without_human_prompt(tmp_path, acquired):
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6),
        owner_plan={'ask': True, 'off': ['opportunity_attack']})
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = move(combat, table, mid, (6, 6), choices={})
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.last_inch') for p in prompts)
    assert engine.state.actors[OWNER].turn_flags['last_inch_step_round_'] == engine.state.round_number


@pytest.mark.parametrize('option,destination,start,end', [
    ('adjacent', (4, 6), (6, 6), (5, 6)),
    ('away', (2, 6), (5, 6), (6, 6)),
    ('exchange', (4, 5), (6, 6), (5, 6)),
])
def test_step_spatial_choices_commit_and_reload(tmp_path, acquired, option, destination, start, end):
    combat, table, mid = setup(tmp_path, acquired, at=start)
    # The first target is within Mind Spike's printed range; designation is
    # acquired within 10 feet, so move it into range before its triggering turn.
    if start == (6, 6):
        turn(table, mid, FOE)
        move(combat, table, mid, (5, 6))
        turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    if start == (6, 6):
        move(combat, table, mid, (6, 6), choices={STEP: None})
    prompts = move(combat, table, mid, end, choices={STEP: 'step', BENEFIT: option,
        'choice:needle.last_inch_step_move': f'cell:{destination[0]},{destination[1]}',
        'reaction:core.opportunity_attack': None})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y) == destination
    assert not owner.reaction_available
    assert owner.turn_flags['last_inch_step_round_'] == engine.state.round_number
    assert any(p['context']['reaction_source_id'] == BENEFIT for p in prompts)


def test_restrained_owner_cannot_step_out_of_hold(tmp_path, acquired):
    def effects(bundles):
        add_action(bundles[2], 'Binding source', [{'type': 'condition', 'condition': 'restrained',
            'applies_to': 'target', 'duration': {'kind': 'one_minute'}}])
    combat, table, mid = setup(tmp_path, acquired, at=(5, 6), transform=effects)
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Binding source', target=OWNER).candidate_id, choices={})
    prompts = move(combat, table, mid, (6, 6), choices={STEP: 'step', 'reaction:core.opportunity_attack': None})
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == STEP for p in prompts)
    assert engine.state.actors[OWNER].position.x == 3 and engine.state.actors[OWNER].reaction_available


def test_failed_hidden_passage_still_produces_attempt_checkpoint(tmp_path, acquired):
    def effects(bundles):
        add_action(bundles[0], 'Hidden source', [{'type': 'condition', 'condition': 'invisible',
            'applies_to': 'self', 'duration': {'kind': 'one_minute'}}], target_kind='SELF', economy='BONUS_ACTION')
    combat, table, mid = setup(tmp_path, acquired, transform=effects)
    settle(table, mid, candidate(combat, mid, 'Mind Spike', target=FOE).candidate_id, choices={DESIGNATE: 'designate'})
    settle(table, mid, candidate(combat, mid, 'Hidden source').candidate_id, choices={})
    turn(table, mid, FOE)
    prompts = move(combat, table, mid, (3, 6), choices={STEP: None})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == STEP for p in prompts)
    assert engine.state.actors[FOE].position.x == 4


def test_successful_native_escape_is_a_designation_trigger(tmp_path, acquired):
    def effects(bundles):
        add_action(bundles[2], 'Grappling source', [{'type': 'condition', 'condition': 'grappled',
            'applies_to': 'target', 'until_escape': True}], dc=1)
    combat, table, mid = setup(tmp_path, acquired, transform=effects)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grappling source', target=OWNER).candidate_id, choices={})
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Escape grapple').candidate_id, choices={DESIGNATE: 'designate'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == DESIGNATE for p in prompts)
    assert len(subjects(engine)) == 1
    assert not any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('category,dc,expected', [('bodily_contact', 1, True), ('bodily_contact', 100, False), (None, 1, False)])
def test_native_contact_contest_metadata_designates_only_successful_contact(tmp_path, acquired, category, dc, expected):
    def effects(bundles):
        check = {'kind': 'check', 'ability': 'STR'}
        if category:
            check['contact_categories'] = [category]
        add_action(bundles[0], 'Contest bodily contact', [{'type': 'contest_against',
            'actor_check': check, 'target_check': {'kind': 'dc', 'dc': dc}, 'on_success': [], 'on_fail': []}])
    combat, table, mid = setup(tmp_path, acquired, transform=effects)
    prompts = settle(table, mid, candidate(combat, mid, 'Contest bodily contact', target=FOE).candidate_id,
        choices={DESIGNATE: 'designate'})
    engine = reload(tmp_path, mid)
    assert bool(subjects(engine)) == expected
    assert any(p['context']['reaction_source_id'] == DESIGNATE for p in prompts) == expected


def test_real_spiritual_asset_producer_and_native_object_contact(tmp_path, acquired):
    from combat.ext.miko import MESSENGER
    combat, table, mid = setup(tmp_path, acquired, foe_features=[MESSENGER], foe_dc=10)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Record willing messenger contact').candidate_id,
        choices={'choice:needle.miko.messenger_contact': 'record'})
    settle(table, mid, candidate(combat, mid, 'Manifest Messenger: Walk').candidate_id,
        choices={'choice:needle.spirit_asset.space': 'cell:4,5,0'})
    engine = reload(tmp_path, mid)
    [asset] = [obj for obj in engine.state.objects.values() if obj.component.get('spirit_asset')]
    hp = asset.current_hp
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.spirit_asset.space': None})
    turn(table, mid, OWNER)
    strike(combat, table, mid, asset.object_id)
    engine = reload(tmp_path, mid)
    assert engine.state.objects[asset.object_id].current_hp < hp
    assert engine.state.objects[asset.object_id].component['contact_records'][0]['origin'] == OWNER
    assert not any(c.target_ids and c.target_ids[0].startswith('object:map.')
                   and engine.action_catalog.get(c.source_definition_id)
                   and engine.action_catalog[c.source_definition_id].parameters.get('spirit_touch') for c in engine.legal_candidates())

# --- Independent pre-merge review fixes (2026-10-16) ---------------------------------------------

def test_ordinary_opportunity_keeps_condition_bound_reach_beside_last_inch(monkeypatch, tmp_path, acquired):
    """A reach bonus on the ordinary weapon must survive opportunity selection.

    Native eligibility already folds ``attack_reach_bonus`` into the ordinary
    opportunity profile (``typed_reactions.opportunity_reach``). Selection must use
    the same effective reach, or a subject crossing only the ordinary weapon's reach
    (here 5 feet base + 10 feet condition-bound stance) is offered no ordinary attack
    while the 10-foot Spirit-Touch alternatives do not cross there either -- the paid
    Reaction buys nothing. This asks the real table session's own selection seam.
    """
    from tests.test_lock_choices import install
    from combat.opportunity_profiles import select
    from combat.gate2_runtime_models import Position
    STATE = 'condition:typed.reach_stance'

    def stance_reach(engine, actor, action, opportunity):
        held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
        if held is None or not str(action.source_definition_id).endswith('.opportunity_attack'):
            return None
        return {'source_id': held.source_definition_id, 'feet': 10, 'condition_id': held.instance_id}

    def stance(bundles):
        add_action(bundles[0], 'Reaching stance', [{'type': 'condition', 'condition': 'reach_stance',
            'applies_to': 'self', 'duration': {'kind': 'one_minute'}}], target_kind='SELF', economy='BONUS_ACTION')

    install(monkeypatch, 'attack_reach_bonus', stance_reach)
    combat, table, mid = setup(tmp_path, acquired, at=(4, 6), transform=stance)
    settle(table, mid, candidate(combat, mid, 'Reaching stance').candidate_id, choices={})
    strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    # The subject crosses from 15 to 20 feet: only the ordinary weapon's effective
    # 15-foot reach crosses; the Spirit-Touch alternatives reach 10 feet.
    row, profile, reach = select(engine, engine.state.actors[OWNER], engine.state.actors[FOE], None,
        edge=(Position(x=6, y=6), Position(x=7, y=6)))
    assert profile is not None and str(profile.source_definition_id).endswith('.opportunity_attack'), (
        'the ordinary opportunity attack at its condition-bound reach was not selectable')
    assert reach == 15, reach


def _external_assets(*names):
    return [{'id': index, 'kind': 'custom', 'x': 4, 'y': y, 'name': name, 'hp': 100, 'ac': 1, 'blocks': False,
             'spiritual_profile': {'source_rule': 'test:spiritual_asset_source', 'source_cl': 3, 'identity': 1}}
            for index, (name, y) in enumerate(names, start=1)]


def test_wisdom_object_contact_offers_printed_damage_types(tmp_path, acquired):
    """Spirit-Touch on an external asset offers Bludgeoning/Psychic, not Untyped.

    The Wisdom strike's damage row prints 1d8 Bludgeoning or Psychic. The object
    route must resolve that row before asking, or the menu collapses to Untyped and
    the chosen type reaches object resistance/vulnerability wrongly.
    """
    combat, table, mid = setup(tmp_path, acquired, at=(6, 6),
        battlefield=profiled_arena(_external_assets(('External spirit asset', 5))))
    prompts = strike(combat, table, mid, 'object:map.1',
        choices={'choice:needle.spirit_object.damage': 'BLUDGEONING'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.spirit_object.damage')
    offered = {option['id'] for option in prompt['choice']['options']}
    assert {'BLUDGEONING', 'PSYCHIC'} <= offered, offered
    assert 'UNTYPED' not in offered, offered
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'OBJECT_UPDATED'][-1].payload['damage']
    assert damage['kinds'] == 'bludgeoning', damage


def test_object_contact_folds_and_consumes_shared_damage_roll_bonus(monkeypatch, tmp_path, acquired):
    """The object damage route uses the shared damage-roll fold, once per roll.

    A rider that adds to one damage roll must reach an object hit and be spent there,
    not leak to a later roll. Because an object strike pauses for its designation
    choice, the one-shot bonus is stored as a real condition so the rollback restores
    it until the committed roll spends it; without the fold the roll keeps only the
    Wisdom modifier and the condition survives for the second strike.
    """
    from tests.test_lock_choices import install
    READY = 'condition:typed.marrow_ready'
    calls = []

    def marrow(ctx, effect_row=None, kinds=None):
        if not ctx.damage_cache.get('_object'):
            return None
        held = next((c for c in ctx.actor.conditions.values() if c.condition_id == READY), None)
        if held is None:
            return None
        ctx.engine._remove_condition_instance(ctx.actor, held.instance_id, held.source_definition_id, expected=held)
        calls.append(7)
        return 7

    def ready(bundles):
        add_action(bundles[0], 'Ready the marrow', [{'type': 'condition', 'condition': 'marrow_ready',
            'applies_to': 'self', 'duration': {'kind': 'one_minute'}}], target_kind='SELF', economy='BONUS_ACTION')

    install(monkeypatch, 'damage_roll_bonus', marrow)
    combat, table, mid = setup(tmp_path, acquired, at=(6, 6), transform=ready,
        battlefield=profiled_arena(_external_assets(('External spirit asset', 5), ('Other external asset', 7))))
    settle(table, mid, candidate(combat, mid, 'Ready the marrow').candidate_id, choices={})
    strike(combat, table, mid, 'object:map.1')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    strike(combat, table, mid, 'object:map.2')
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.reason.endswith(':object')]
    assert [r.modifier for r in rolls] == [12, 5], (
        'the ready damage bonus must be folded into the first object roll and spent before the second')
    assert 7 in calls
    assert not any(c.condition_id == READY for c in engine.state.actors[OWNER].conditions.values()), (
        'the folded one-shot bonus must be spent, not left ready for a later roll')
