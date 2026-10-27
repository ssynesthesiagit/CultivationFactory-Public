"""Maw acquisition -> native table intent -> persisted records -> cold replay.

No live clients, fabricated resource gains, or trigger receipts are used here.
"""
from copy import deepcopy

import pytest

from app.core import Database, Settings, FoundryError
from combat.factory_compiler import compile_character
from combat.ext.devouring_maw import records, stored, ESSENCE, PREFIX
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award, access_evidence, commit_authority_event
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

BODY = 'tianxia.path.body_refining'
MAW = PREFIX.removesuffix('.feature.')
REACTION = 'reaction:typed.'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('maw-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    documents = {}

    def get(cl):
        if cl not in documents:
            project = 'maw-cl-' + str(cl)
            insert_project(db, project, cl)
            service.initialize_for_project(project, target_cl=cl, path_ids=[BODY], method_id='METHOD-002',
                access_source_records=access_evidence(db, service, project, 'METHOD-002'))
            service.allocate_advancement(project, {BODY: cl - 1},
                evidence_id=ap_award(db, service, project, 'METHOD-002', cl, cl - 1),
                idempotency_key=project + '-advance')
            with pytest.raises(FoundryError):
                service.select_subpath(project, BODY, MAW)
            evidence = commit_authority_event(db, service, project, 'subpath_access', {'selection_id': MAW})
            service.select_subpath(project, BODY, MAW, access_source_records=[evidence])
            state = NonSphereAuthorityService(db).get_state(project)
            doc = sheet(['TAL_IRON_FIST_IRON_FIST_TRAINING'], cl=cl, dc=50, primary='Stamina', name='Maw disciple')
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
            doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
            doc['identity']['path'] = 'Body Refining'
            doc['path_and_subpath'] = {'paths': state['paths']}
            documents[cl] = doc
        return deepcopy(documents[cl])
    return get


def ward_action(bundles):
    """Give the foe one compiled typed action that creates a source-backed damage-reduction ward.

    No shipped reviewed ability declares ``effect_kind: damage_reduction`` yet (Barrier Ward is a tracked
    delivery gap), so the fixture supplies the same source-backed state through the documented ``state``
    effect. It is a real compiled action on a real sheet: the foe plays it through the table, the engine
    commits its condition, and only then does Feast see it.
    """
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    template = next(a for a in foe['action_catalog'] if a['display_name'] == 'Digestive Mantle: Elemental Gut')
    ward = deepcopy(template)
    ward.update(source_definition_id='action:test.maw.protection_ward', display_name='Raise Test Ward', costs=[])
    typed = ward['parameters']['typed']
    typed.update(effects=[{'type': 'state', 'name': 'test_damage_reduction_ward',
                           'label': 'Temporary damage-reduction ward', 'effect_kind': 'damage_reduction',
                           'expires_on': 'START_OF_SOURCE_NEXT_TURN'}], source='TEST_PROTECTION_WARD',
                 riders=[], duration={'kind': 'minutes', 'amount': 1, 'concentration': False})
    typed.pop('option_of', None)
    typed.pop('option_label', None)
    typed.pop('hunger_runtime', None)
    foe['action_catalog'].append(ward)
    foe['actor_template']['action_ids'].append(ward['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def resistance_action(bundles):
    """Give the foe one compiled typed action that applies a real temporary Resistance condition.

    ``shadow_outlives_resistance`` is a reviewed standard condition whose rule declares
    ``damage_resistances``; the printed Feast list includes "one Resistance". The fixture is a real
    compiled action on a real sheet, played through the table, so the condition's source CL and
    lifetime are native (the same approach as ``ward_action``).
    """
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    template = next(a for a in foe['action_catalog'] if a['display_name'] == 'Digestive Mantle: Elemental Gut')
    raised = deepcopy(template)
    raised.update(source_definition_id='action:test.maw.protection_resistance',
                  display_name='Raise Test Resistance', costs=[])
    typed = raised['parameters']['typed']
    typed.update(effects=[{'type': 'condition', 'condition': 'shadow_outlives_resistance',
                           'applies_to': 'self', 'condition_label': 'Temporary Resistance',
                           'duration': {'kind': 'minutes', 'amount': 1}}],
                 source='TEST_PROTECTION_RESISTANCE', riders=[],
                 duration={'kind': 'minutes', 'amount': 1, 'concentration': False})
    typed.pop('option_of', None)
    typed.pop('option_label', None)
    typed.pop('hunger_runtime', None)
    foe['action_catalog'].append(raised)
    foe['actor_template']['action_ids'].append(raised['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def unconsumable_fireball(bundles):
    """Mark the foe's own printed Fireball row as explicitly barring consumption."""
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    for action in foe['action_catalog']:
        typed = (action.get('parameters') or {}).get('typed') or {}
        if str(typed.get('source') or '').startswith('FIRE_TAL_FIREBALL_ART'):
            typed['unconsumable'] = True
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def mixed_save_action(bundles):
    """Give the foe one compiled typed action whose failed save deals several damage portions.

    ``_collect_damage_instance`` is about the whole simultaneous instance of one
    activation, so the fixture needs a real compiled action that commits more than
    one plain damage row (the same approach as ``ward_action``). Fire, an invalid
    physical type and Necrotic exercise the "mixed packet" clause and the
    "only the chosen type" budget at once.
    """
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    template = next(a for a in foe['action_catalog'] if a['display_name'] == 'Fireball Art')
    blast = deepcopy(template)
    blast.update(source_definition_id='action:test.maw.mixed_damage', display_name='Twin Test Blast', costs=[])
    typed = blast['parameters']['typed']
    typed.update(effects=[{'type': 'save', 'ability': 'dex', 'dc': 'technique_save_dc',
                           'on_fail': [
                               {'type': 'damage', 'applies_to': 'creatures_in_area',
                                'dice': {'count': 2, 'sides': 6}, 'damage_types': ['fire']},
                               {'type': 'damage', 'applies_to': 'creatures_in_area',
                                'dice': {'count': 2, 'sides': 6}, 'damage_types': ['slashing']},
                               {'type': 'damage', 'applies_to': 'creatures_in_area',
                                'dice': {'count': 3, 'sides': 6}, 'damage_types': ['necrotic']}],
                           'on_success': [{'type': 'half_damage'}]}],
                 source='TEST_MIXED_DAMAGE', riders=[],
                 duration={'kind': 'instant', 'amount': None, 'concentration': False})
    typed.pop('option_of', None)
    typed.pop('option_label', None)
    typed.pop('hunger_runtime', None)
    foe['action_catalog'].append(blast)
    foe['actor_template']['action_ids'].append(blast['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def body_suppression_action(bundles):
    """Give the foe one compiled typed action granting the printed complete Body Refining suppression.

    Player General Procedures R8 §20 defines the state; no shipped reviewed row grants it yet, so the
    fixture supplies a real compiled action on a real sheet (the same approach as ``ward_action``).
    """
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    template = next(a for a in foe['action_catalog'] if a['display_name'] == 'Unarmed Strike')
    imposed = deepcopy(template)
    imposed.update(source_definition_id='action:test.maw.complete_body_suppression',
                   display_name='Impose Test Body Suppression', costs=[])
    typed = imposed['parameters']['typed']
    typed.update(effects=[{'type': 'complete_body_suppression', 'applies_to': 'target',
                           'scope': 'Body Refining', 'expires_on': 'UNTIL_REMOVED'}],
                 source='TEST_COMPLETE_BODY_SUPPRESSION', riders=[])
    typed.pop('option_of', None)
    typed.pop('option_label', None)
    foe['action_catalog'].append(imposed)
    foe['actor_template']['action_ids'].append(imposed['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def furnace_vent_includes_every_creature(bundles):
    """Seal Furnace Vent's printed "Each creature in the area" scope.

    The compiled area carries no explicit recipient scope, so the engine's inert default
    treats a typed ``creatures_in_area`` payload as enemies-only. The printed text is
    inclusive; this seals the same metadata the compiler seals for inclusive wording.
    """
    from combat.canonical import canonical_sha256
    foe = bundles[2]
    for action in foe['action_catalog']:
        typed = (action.get('parameters') or {}).get('typed') or {}
        if 'FURNACE_VENT' in str(typed.get('source') or ''):
            typed.setdefault('area', {})['explicit_harmful_recipients'] = 'every_creature'
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def foe_kit_transform(satiety=0):
    """One Satiety for the foe's real Digestive Mantle (the printed cost is 1 CP and 1 Satiety)."""
    def change(bundles):
        from combat.canonical import canonical_sha256
        foe = bundles[2]
        for row in foe['actor_template']['resources']:
            if row['resource_id'] == 'resource:named.satiety':
                row['initial'] = satiety
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)
    return change


def scenario(tmp_path, acquired, *, cl=18, hostile=True, seed='MGR-MAW-NATIVE', positions=None, foe_talents=(), owner_dc=50, foe_maw=False, foe_cl=None, modes=None, foe_ac=0, foe_satiety=0, foe_ward=False, foe_resistance=False, foe_unconsumable=False, foe_body_suppression=False, foe_inclusive_vent=False, foe_mixed=False):
    document = acquired(cl)
    document['ability_scores_and_statistics']['technique_save_dc'] = owner_dc
    owner = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet(['FIRE_TAL_FIREBALL_ART', *foe_talents], cl=cl, dc=50,
                primary='Stamina' if foe_maw else 'Qi', name='Hostile fire cultivator')
    # The foe's Hunger key ability is CON; a strong CON makes Digestive Mantle's
    # Temporary HP outlast the strike's own damage, so the protection is still there
    # for Feast to suppress (the Maw's own save DC is the sheet's 50, so the printed
    # "failed save" branch is deterministic without lowering this).
    for ability in foe['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'CON':
            ability['score'], ability['modifier'] = 54, 22
    if foe_maw:
        foe['path_and_subpath'] = acquired(foe_cl or cl)['path_and_subpath']
        foe['identity']['path'] = 'Body Refining'
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = foe_ac

    def transform(bundles):
        if foe_satiety:
            foe_kit_transform(foe_satiety)(bundles)
        if foe_ward:
            ward_action(bundles)
        if foe_resistance:
            resistance_action(bundles)
        if foe_unconsumable:
            unconsumable_fireball(bundles)
        if foe_body_suppression:
            body_suppression_action(bundles)
        if foe_inclusive_vent:
            furnace_vent_includes_every_creature(bundles)
        if foe_mixed:
            mixed_save_action(bundles)
    return fixture(tmp_path, [], cl=cl, owner_bundle=owner, foe_sheet=foe, seed=seed,
                   positions=positions or {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 7}, FOE: {'x': 4, 'y': 6}},
                   team_overrides={} if hostile else {FOE: 'team:factory'}, modes=modes,
                   extra_foes=0 if hostile else 1,
                   bundle_transform=transform if (foe_satiety or foe_ward or foe_resistance or foe_unconsumable
                                                  or foe_body_suppression or foe_inclusive_vent or foe_mixed) else None)


def source_candidates(combat, mid, fragment, target=None):
    from combat.typed_executor import _area_targets
    engine = combat._load_session(mid).engine
    result = []
    for c in engine.legal_candidates():
        action = engine.action_catalog.get(c.source_definition_id)
        if action is None or fragment.lower() not in action.display_name.lower():
            continue
        typed = action.parameters.get('typed') or {}
        area = typed.get('area') or {}
        targets = c.target_ids
        if area and c.destination:
            targets = tuple(a.entity_id for a in _area_targets(engine, engine.state.actors[engine.state.current_actor_id],
                            c.destination, area, typed=typed))
        if target is None or target in targets:
            result.append(c)
    return result


def burn(combat, table, mid, *, reaction='swallow_hostile_power', source_name='Fireball'):
    current = combat._load_session(mid).engine.state
    if current.current_actor_id == FOE and not current.actors[FOE].action_available:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    options = source_candidates(combat, mid, source_name, OWNER)
    assert options, f'A real {source_name} must reach the Maw disciple'
    # Prefer the plain printed form over an augment (e.g. "Fireball Art + Overheat"): the
    # augment spends extra CP and damages its own caster, which is not this fixture's packet.
    engine = combat._load_session(mid).engine
    plain = [c for c in options if '+' not in engine.action_catalog[c.source_definition_id].display_name]
    options = plain or options
    return settle(table, mid, options[0].candidate_id, choices={
        REACTION + PREFIX + reaction: 'first',
        PREFIX + ('swallow_the_technique' if reaction == 'swallow_hostile_power' else 'swallow_hostile_power'): None,
        'choice:needle.maw_replace': None,
    })


def play(combat, table, mid, name, *, target=None, choices=None):
    selected = source_candidates(combat, mid, name, target)
    assert selected, name
    return settle(table, mid, selected[0].candidate_id, choices=choices or {})


@pytest.mark.parametrize('cl,roles', [(3, {'swallow'}), (6, {'swallow', 'regurgitate'}),
    (10, {'swallow', 'regurgitate', 'technique'}), (14, {'swallow', 'regurgitate', 'technique', 'feast'}),
    (18, {'swallow', 'regurgitate', 'technique', 'feast', 'devour'})])
def test_native_forbidden_acquisition_progression(tmp_path, acquired, cl, roles):
    combat, table, mid = scenario(tmp_path, acquired, cl=cl)
    engine = reload(tmp_path, mid)
    rows = engine.typed_passive_rows[OWNER]
    assert {r['role'] for r in rows if r.get('kind') == 'devouring_maw'} == roles
    assert stored(engine.state.actors[OWNER]) == []
    assert engine.state.actors[OWNER].resources[ESSENCE] == 0


def test_hostile_swallow_produces_source_records_after_commit(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    prompts = burn(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id'] == REACTION + PREFIX + 'swallow_hostile_power' for p in prompts)
    assert stored(owner) == ['FIRE']
    record, = records(owner)
    assert record['type'] == 'FIRE' and record['source_cl'] == 6
    assert 'fireball' in record['source'].lower()
    assert record['round'] >= 1 and record['expires'] == 'SCENE_END'
    assert owner.resources['resource:core.stamina'] == 99
    turn(table, mid, OWNER)
    selected = source_candidates(combat, mid, 'Regurgitate Calamity: One Creature', FOE)
    assert selected
    settle(table, mid, selected[0].candidate_id, choices={'choice:needle.regurgitate': ['FIRE:1']})
    after = reload(tmp_path, mid)
    assert stored(after.state.actors[OWNER]) == []
    assert any(r.expression.startswith('3d8') for r in after.rolls if r.reason.startswith('DAMAGE:'))


def test_friendly_fire_does_not_feed_or_spend_reaction(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6, hostile=False, foe_talents=['TAL_ALCHEMY_FURNACE_VENT'],
                                  foe_inclusive_vent=True)
    prompts = burn(combat, table, mid, source_name='Furnace Vent')
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
               and e.actor_id == FOE and e.payload['hp_damage'] > 0 for e in engine.events)
    assert not any(p['context']['reaction_source_id'].startswith(REACTION + PREFIX) for p in prompts)
    assert stored(engine.state.actors[OWNER]) == []
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == 100


def test_declined_native_swallow_does_not_roll_or_allocate(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=10)
    turn(table, mid, FOE)
    attack, *_ = source_candidates(combat, mid, 'Fireball', OWNER)
    prompts = settle(table, mid, attack.candidate_id, choices={
        REACTION + PREFIX + 'swallow_hostile_power': None, REACTION + PREFIX + 'swallow_the_technique': None})
    after = reload(tmp_path, mid)
    assert not any(r.reason.startswith('REACTION:' + PREFIX) for r in after.rolls)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.maw_allocate' for p in prompts)
    assert after.state.actors[OWNER].resources['resource:core.stamina'] == 100


def test_human_swallow_choice_remains_on_a_native_local_ai_turn(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6,
        modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'})
    prompts = []
    for _ in range(8):
        turn(table, mid, FOE)
        prompts.extend(settle(table, mid, '', auto=True, choices={
            REACTION + PREFIX + 'swallow_hostile_power': 'first', REACTION + PREFIX + 'swallow_the_technique': None}))
        after = reload(tmp_path, mid)
        if stored(after.state.actors[OWNER]):
            break
    assert stored(after.state.actors[OWNER])
    assert any(p['context']['reactor_id'] == OWNER and p.get('trigger_actor') == 'Hostile fire cultivator'
               and p['context']['reaction_source_id'] == REACTION + PREFIX + 'swallow_hostile_power' for p in prompts)


def test_swallow_technique_resolves_native_save_before_flat_reduction(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=10)
    burn(combat, table, mid, reaction='swallow_the_technique')
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == PREFIX + 'swallow_the_technique']
    assert len(resolved) == 1
    result = resolved[0]
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER and e.sequence < result.sequence
               for e in engine.events)
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == 97
    assert len(stored(engine.state.actors[OWNER])) == (2 if result.payload['pending_after'] == 0 else 0)
    assert all(r['type'] == 'FIRE' and r['source_cl'] == 10 for r in records(engine.state.actors[OWNER]))


@pytest.mark.parametrize('boundary', ['wrong_parent', 'suppressed', 'unowned'])
def test_default_inert_native_boundaries(tmp_path, acquired, boundary):
    doc = acquired(18)
    if boundary == 'unowned':
        doc['path_and_subpath'] = {}
    else:
        row = doc['path_and_subpath']['paths'][0]
        if boundary == 'wrong_parent':
            row['path_id'] = 'tianxia.path.qi_cultivation'
        else:
            row['effective_cl'] = 2
    owner = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner)
    engine = reload(tmp_path, mid)
    assert not any(r.get('kind') == 'devouring_maw' for r in engine.typed_passive_rows.get(OWNER, []))


def test_devour_uses_settled_hostile_activation_and_scene_cost(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    play(combat, table, mid, 'Devour Heaven and Earth')
    before = reload(tmp_path, mid)
    owner = before.state.actors[OWNER]
    assert owner.resources['resource:core.stamina'] == 92
    assert owner.resource_maximums[ESSENCE] == owner.proficiency_bonus + 3
    burn(combat, table, mid)
    after = reload(tmp_path, mid)
    assert len(stored(after.state.actors[OWNER])) == 2
    assert stored(after.state.actors[OWNER])[0] == 'FIRE'
    assert set(stored(after.state.actors[OWNER])) <= {'FIRE', 'FORCE'}
    assert all('fireball' in r['source'].lower() for r in records(after.state.actors[OWNER]))
    turn(table, mid, OWNER)
    assert not source_candidates(combat, mid, 'Devour Heaven and Earth')


def test_maw_strike_consumes_native_record_with_printed_scaling(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    play(combat, table, mid, 'Unarmed Strike', target=FOE,
         choices={'choice:needle.maw_type': ['FIRE']})
    after = reload(tmp_path, mid)
    assert not stored(after.state.actors[OWNER])
    assert any(r.expression.startswith('2d8') for r in after.rolls if r.reason.startswith('DAMAGE:'))


def test_regurgitate_line_hits_friendly_creature_and_pays_once(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}})
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    hp = before.state.actors[ALLY].current_hp
    play(combat, table, mid, 'Regurgitate Calamity: Line', target=FOE,
         choices={'choice:needle.regurgitate': ['FIRE:1']})
    after = reload(tmp_path, mid)
    assert after.state.actors[ALLY].current_hp < hp
    assert after.state.actors[OWNER].resources[ESSENCE] == 0
    spent = [e for e in after.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
             and e.payload.get('resource_id') == ESSENCE]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1


def test_expel_all_is_native_action_with_unavoidable_hp_loss(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    assert not source_candidates(combat, mid, 'Undigested Calamity')
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    hp = before.state.actors[OWNER].current_hp
    play(combat, table, mid, 'Undigested Calamity')
    after = reload(tmp_path, mid)
    event = next(e for e in reversed(after.events) if e.event_type == 'UNAVOIDABLE_DAMAGE_COMMITTED')
    assert event.payload['essence_count'] == 1
    assert 1 <= hp - after.state.actors[OWNER].current_hp <= 6
    assert not stored(after.state.actors[OWNER])
    assert after.state.actors[OWNER].resources[ESSENCE] == 0
    assert not after.state.actors[OWNER].action_available


def test_feast_suppresses_native_protection_without_removing_source(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'], foe_satiety=1, seed='MGR-MAW-NATIVE-2')
    play(combat, table, mid, 'Devour Heaven and Earth')
    burn(combat, table, mid)
    # Begin the foe's next real turn; its actual protection supplies provenance.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Digestive Mantle')
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert len(stored(before.state.actors[OWNER])) == 4
    play(combat, table, mid, 'Unarmed Strike', target=FOE, choices={
        'choice:needle.maw_types': ['0', '1', '2'], 'choice:needle.maw_damage_type': ['FIRE'],
        'choice:needle.feast_protection': 'first', 'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert foe.temporary_hp == 0
    assert any(c.condition_id == 'condition:typed.feast_set_aside' and c.data['temp_hp'] > 0
               for c in foe.conditions.values())
    assert len(stored(after.state.actors[OWNER])) == 1


def test_feast_does_not_restore_a_native_pool_after_its_own_expiry(tmp_path, acquired):
    from combat.ext.temp_hp_grants import held_grant, lifetime_for
    from combat.ext.effect_durations import parse_round
    combat, table, mid = scenario(tmp_path, acquired, foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'], foe_satiety=1, seed='MGR-MAW-NATIVE-2')
    play(combat, table, mid, 'Devour Heaven and Earth')
    burn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Digestive Mantle')
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    for _ in range(12):
        engine = reload(tmp_path, mid)
        grant = held_grant(engine.events, FOE)
        assert grant is not None
        marker = lifetime_for(engine.state.actors[FOE], grant[2])
        assert marker is not None, 'The real accepted timed grant must produce its native expiry'
        deadline = parse_round(marker.expires_on)
        assert deadline is not None
        slots = len(engine.state.initiative_order)
        gap = deadline[0] * slots + deadline[1] - (engine.state.round_number * slots + engine.state.current_slot_index)
        if 0 < gap < slots:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    else:
        raise AssertionError('No native owner turn immediately before the protection expires')
    play(combat, table, mid, 'Unarmed Strike', target=FOE, choices={
        'choice:needle.maw_types': ['0', '1', '2'], 'choice:needle.maw_damage_type': ['FIRE'],
        'choice:needle.feast_protection': ['temp_hp'], 'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.feast_set_aside' and c.data.get('temp_hp_lifetime')
               for c in after.state.actors[FOE].conditions.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].temporary_hp == 0
    assert not any(c.condition_id == 'condition:typed.feast_set_aside' for c in after.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('dc', [50, -20])
def test_world_eating_bite_uses_native_records_and_bars_temp_hp(tmp_path, acquired, dc):
    combat, table, mid = scenario(tmp_path, acquired, owner_dc=dc)
    play(combat, table, mid, 'Devour Heaven and Earth')
    for _ in range(3):
        burn(combat, table, mid)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert len(stored(before.state.actors[OWNER])) == 6
    play(combat, table, mid, 'Unarmed Strike', target=FOE, choices={
        'choice:needle.maw_types': ['0', '1', '2', '3', '4'],
        'choice:needle.maw_damage_type': ['FIRE'], 'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    assert len(stored(after.state.actors[OWNER])) == 1
    assert any(r.expression.startswith('10d8') for r in after.rolls if r.reason.startswith('DAMAGE:'))
    assert any(c.condition_id == 'condition:typed.no_temp_hp' for c in after.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('foe_cl', [18, 20])
def test_world_eating_bite_ends_one_native_transformation_not_its_path(tmp_path, acquired, foe_cl):
    combat, table, mid = scenario(tmp_path, acquired, foe_maw=True, foe_cl=foe_cl)
    play(combat, table, mid, 'Devour Heaven and Earth')
    turn(table, mid, FOE)
    play(combat, table, mid, 'Devour Heaven and Earth')
    for _ in range(3):
        burn(combat, table, mid)
    turn(table, mid, OWNER)
    assert len(stored(reload(tmp_path, mid).state.actors[OWNER])) == 6
    play(combat, table, mid, 'Unarmed Strike', target=FOE, choices={
        'choice:needle.maw_types': ['0', '1', '2', '3', '4'],
        'choice:needle.maw_damage_type': ['FIRE'], 'choice:needle.maw_type': None,
        'choice:needle.world_bite': 'first'})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert not any(c.condition_id == 'condition:typed.state.devour_heaven_and_earth' for c in foe.conditions.values())
    assert not any(c.condition_id == 'condition:typed.no_temp_hp' for c in foe.conditions.values())
    assert foe.resource_maximums[ESSENCE] == foe.proficiency_bonus
    assert any(r.get('role') == 'devour' for r in after.typed_passive_rows[FOE])

def test_devour_expiry_with_overfull_essence_commits_and_retains_points(tmp_path, acquired):
    """Finding 1: retained Essence above reduced capacity must survive a real commit."""
    from combat.ext.devouring_maw import DEVOUR
    from combat.gate2_runtime_models import ActorState
    combat, table, mid = scenario(tmp_path, acquired, foe_ac=0)
    play(combat, table, mid, 'Devour Heaven and Earth')
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    capacity = owner.resource_maximums[ESSENCE]
    owner.resources[ESSENCE] = capacity
    engine._remove_condition(owner, 'condition:typed.state.' + DEVOUR, 'test-devour-expiry')
    assert owner.resource_maximums[ESSENCE] < capacity
    held = owner.resources[ESSENCE]
    assert held > owner.resource_maximums[ESSENCE]
    engine.end_turn()
    assert engine.state.actors[OWNER].resources[ESSENCE] == held
    assert engine.state.actors[OWNER].resource_maximums[ESSENCE] < held
    ActorState.model_validate(engine.state.actors[OWNER].model_dump(mode='json'))



def _foe_mantle_protection(tmp_path, acquired, *, extra_burns=0):
    """A real source-backed protection: the foe spends its own Satiety on Digestive Mantle: Elemental Gut.

    Elemental Gut stores a one-minute ``damage_resistance`` modifier through the ability's own compiled
    action, so its Source CL and lifetime are the real ones.
    """
    combat, table, mid = scenario(tmp_path, acquired, foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'],
                                  foe_ac=0, foe_satiety=1, seed='MGR-MAW-NATIVE-2')
    play(combat, table, mid, 'Devour Heaven and Earth')
    burn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Digestive Mantle: Elemental Gut')
    burn(combat, table, mid)
    for _ in range(extra_burns):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, FOE)
        burn(combat, table, mid)
    turn(table, mid, OWNER)
    return combat, table, mid


def _foe_ward_protection(tmp_path, acquired):
    """Source-backed damage-reduction ward: the foe's own compiled action creates it through the state effect."""
    combat, table, mid = scenario(tmp_path, acquired, foe_ac=0, foe_ward=True,
                                  foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'], seed='MGR-MAW-NATIVE-2')
    play(combat, table, mid, 'Devour Heaven and Earth')
    burn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Raise Test Ward')
    burn(combat, table, mid)
    turn(table, mid, OWNER)
    return combat, table, mid


def _foe_resistance_protection(tmp_path, acquired):
    """Real Swallow gains over three rounds, then the foe's own action raises a temporary Resistance."""
    combat, table, mid = scenario(tmp_path, acquired, cl=14, foe_ac=0, foe_resistance=True,
                                  foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'], seed='MGR-MAW-NATIVE-3')
    for _ in range(3):
        burn(combat, table, mid)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Raise Test Resistance')
    turn(table, mid, OWNER)
    return combat, table, mid


def strike_choosing(combat, table, mid, wanted, answers):
    """Strike with an Unarmed Strike, requiring the named protection option before selecting it.

    The presence assertion is the regression's fail-without-fix point: an omitted protection
    (no such option offered) fails here instead of silently falling back.
    """
    from tests.test_r9i_karma_persistence import act
    selected = source_candidates(combat, mid, 'Unarmed Strike', FOE)
    assert selected, 'Unarmed Strike'
    given, prompts = [], []
    for _ in range(20):
        result = act(table, mid, selected[0].candidate_id, given)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']
        rid = prompt['context']['reaction_source_id']
        prompts.append(prompt)
        options = [o['id'] for o in ((prompt.get('choice') or {}).get('options') or [])]
        pick = answers.get(rid)
        if rid == wanted['prompt']:
            assert wanted['option'] in options, (wanted['option'], options)
            pick = wanted['option']
        answer = {**prompt['context'], 'selection': 'USE' if pick is not None else 'DECLINE'}
        if pick is not None and options:
            answer['option_ids'] = [options[0]] if pick == 'first' else ([pick] if isinstance(pick, str) else pick)
        given.append(answer)
    raise AssertionError('Too many prompts')


def test_feast_offers_and_suppresses_source_backed_damage_reduction(tmp_path, acquired):
    """Finding 3: a source-backed damage-reduction protection is a legal Feast choice, not omitted."""
    combat, table, mid = _foe_ward_protection(tmp_path, acquired)
    before = reload(tmp_path, mid)
    owner = before.state.actors[OWNER]
    assert len(stored(owner)) >= 3
    ward = next(c for c in before.state.actors[FOE].conditions.values()
                if (c.data.get('rule') or {}).get('effect_kind') == 'damage_reduction')
    strike_choosing(combat, table, mid, {'prompt': 'choice:needle.feast_protection',
                                 'option': 'condition:' + ward.instance_id},
                    {'choice:needle.maw_types': ['0', '1', '2'], 'choice:needle.maw_damage_type': ['FIRE'],
                     'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert ward.condition_id not in [c.condition_id for c in foe.conditions.values()]
    assert any(c.condition_id.startswith('condition:typed.suppressed.') for c in foe.conditions.values()), \
        [c.condition_id for c in foe.conditions.values()]


def test_feast_suppresses_only_the_chosen_resistance_of_a_multi_resistance_condition(tmp_path, acquired):
    """Review finding 3: "one Resistance" suppresses one type, not the whole condition.

    ``shadow_outlives_resistance`` grants eleven Resistances. Before the fix Feast offered the
    condition as one whole protection and suppressed every Resistance. Now the owner picks one
    type; the condition keeps the other Resistances, its benefits and its original duration.
    """
    combat, table, mid = _foe_resistance_protection(tmp_path, acquired)
    before = reload(tmp_path, mid)
    assert len(stored(before.state.actors[OWNER])) >= 3
    resistance = next(c for c in before.state.actors[FOE].conditions.values()
                      if c.condition_id == 'condition:typed.shadow_outlives_resistance')
    strike_choosing(combat, table, mid, {'prompt': 'choice:needle.feast_protection',
                                 'option': f'resistance:{resistance.instance_id}:FIRE'},
                    {'choice:needle.maw_types': ['0', '1', '2'], 'choice:needle.maw_damage_type': ['FIRE'],
                     'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    held = next(c for c in foe.conditions.values()
                if c.condition_id == 'condition:typed.shadow_outlives_resistance')
    kinds = {str(kind).upper() for kind in (held.data.get('rule') or {}).get('damage_resistances') or []}
    assert 'FIRE' not in kinds
    assert {'COLD', 'NECROTIC', 'SLASHING'} <= kinds
    assert held.expires_on == resistance.expires_on, 'the original duration must be retained'
    assert not any(c.condition_id.startswith('condition:typed.suppressed.') for c in foe.conditions.values())

    # An unselected Resistance still halves damage after commit/reload; the chosen one does not.
    hp = foe.current_hp
    after._commit_damage(foe, 40, 'COLD', 'test:feast-probe', FOE, None, reaction_depth=0)
    assert foe.current_hp == hp - 20, 'COLD Resistance must remain until the owner restores the choice'
    hp = foe.current_hp
    after._commit_damage(foe, 40, 'FIRE', 'test:feast-probe', FOE, None, reaction_depth=0)
    assert foe.current_hp == hp - 40, 'the chosen FIRE Resistance is suppressed'

    # The printed suppression lasts until the start of the Maw disciple's next turn.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    restored = reload(tmp_path, mid)
    held = next(c for c in restored.state.actors[FOE].conditions.values()
                if c.condition_id == 'condition:typed.shadow_outlives_resistance')
    kinds = {str(kind).upper() for kind in (held.data.get('rule') or {}).get('damage_resistances') or []}
    assert 'FIRE' in kinds
    assert not any(c.condition_id == 'condition:typed.feast_set_aside'
                   for c in restored.state.actors[FOE].conditions.values())


def test_unconsciousness_alone_does_not_expel_essence(tmp_path, acquired):
    """Printed: "Becoming Unconscious does not automatically expel Essence." No lifecycle caller fires."""
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    burn(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert stored(owner) == ['FIRE']
    hp = owner.current_hp
    engine._apply_condition(owner, 'condition:typed.life_unconscious', PREFIX + 'swallow_hostile_power', OWNER,
                            expires_on='UNTIL_REMOVED', data={'label': 'Unconscious at 0 Hit Points'})
    assert stored(engine.state.actors[OWNER]) == ['FIRE']
    assert engine.state.actors[OWNER].current_hp == hp
    assert not any(e.event_type == 'UNAVOIDABLE_DAMAGE_COMMITTED' for e in engine.events)


def test_death_ends_essence_without_backlash_absent_campaign_authority(tmp_path, acquired):
    """Printed: death ends the state; the metaphysical consequence needs a campaign rule that permits it."""
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    burn(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert stored(owner) == ['FIRE']
    engine._apply_condition(owner, 'condition:typed.death_finalized', PREFIX + 'swallow_hostile_power', OWNER,
                            expires_on='UNTIL_REMOVED', data={'label': 'Dead'})
    assert stored(owner) == []
    assert owner.resources[ESSENCE] == 0
    assert not any(e.event_type == 'UNAVOIDABLE_DAMAGE_COMMITTED' for e in engine.events)


def test_campaign_authority_resolves_backlash_at_death(tmp_path, acquired):
    """With the table-owner declaration, death still resolves the printed metaphysical consequence."""
    from combat.ext.devouring_maw import CAMPAIGN_POLICY
    combat, table, mid = scenario(tmp_path, acquired, cl=6)
    burn(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    hp = owner.current_hp
    engine._apply_condition(owner, CAMPAIGN_POLICY, PREFIX + 'swallow_hostile_power', OWNER,
                            expires_on='UNTIL_REMOVED', data={'label': 'Campaign rule permits Undigested Calamity after death'})
    engine._apply_condition(owner, 'condition:typed.death_finalized', PREFIX + 'swallow_hostile_power', OWNER,
                            expires_on='UNTIL_REMOVED', data={'label': 'Dead'})
    assert stored(owner) == []
    assert owner.resources[ESSENCE] == 0
    assert owner.current_hp < hp
    assert any(e.event_type == 'UNAVOIDABLE_DAMAGE_COMMITTED' for e in engine.events)


def test_complete_body_suppression_ends_the_state(tmp_path, acquired):
    """Printed lifecycle: complete Body Refining suppression ends Devoured Essence.

    Player General Procedures R8 §20: a Source Rule can grant complete Body suppression. The Maw
    consumer ends the state; absent the table-owner after-death declaration no backlash resolves.
    """
    combat, table, mid = scenario(tmp_path, acquired, cl=6, foe_body_suppression=True, seed='MGR-MAW-NATIVE-5')
    burn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    imposed = source_candidates(combat, mid, 'Impose Test Body Suppression', OWNER)
    assert imposed
    settle(table, mid, imposed[0].candidate_id)
    after = reload(tmp_path, mid)
    owner = after.state.actors[OWNER]
    assert any(c.condition_id == 'condition:typed.complete_body_suppression' for c in owner.conditions.values())
    assert stored(owner) == []
    assert owner.resources[ESSENCE] == 0
    assert not any(e.event_type == 'UNAVOIDABLE_DAMAGE_COMMITTED' for e in after.events)


def test_typed_unconsumable_row_bars_both_swallow_reactions(tmp_path, acquired):
    """F8 fix round: "damage explicitly immune to consumption" is a typed-data declaration.

    The foe's own printed Fireball row carries ``unconsumable: true``. Both Swallow reactions must
    decline it: no reaction prompt, no reduction roll, no Essence, no Stamina spent.
    """
    combat, table, mid = scenario(tmp_path, acquired, cl=10, foe_unconsumable=True, seed='MGR-MAW-NATIVE-4')
    prompts = burn(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids and e.actor_id == FOE
               and e.payload['hp_damage'] > 0 for e in engine.events)
    assert not any(p['context']['reaction_source_id'].startswith(REACTION + PREFIX) for p in prompts)
    assert stored(engine.state.actors[OWNER]) == []
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == 100


def test_world_eating_bite_ends_source_backed_resistance_not_temp_hp_denial(tmp_path, acquired):
    """Finding 3: Bite offers the foe's real temporary Resistance instead of the Temporary-HP fallback."""
    combat, table, mid = _foe_mantle_protection(tmp_path, acquired, extra_burns=1)
    before = reload(tmp_path, mid)
    foe = before.state.actors[FOE]
    assert len(stored(before.state.actors[OWNER])) >= 5
    resistance = next(m for m in foe.modifiers.values() if m.target_field == 'damage_resistance')
    assert foe.temporary_hp > 0, 'the real Mantle also granted Temporary HP, which Bite must not reach for'
    strike_choosing(combat, table, mid, {'prompt': 'choice:needle.world_bite',
                                 'option': 'modifier:' + resistance.modifier_id},
                    {'choice:needle.maw_types': ['0', '1', '2', '3', '4'],
                     'choice:needle.maw_damage_type': ['FIRE'], 'choice:needle.maw_type': None})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert resistance.modifier_id not in foe.modifiers
    assert not any(c.condition_id == 'condition:typed.no_temp_hp' for c in foe.conditions.values())


def test_whole_simultaneous_instance_is_collected_before_first_commit(monkeypatch):
    """Finding 2: the batch's portions are known (types and amounts) before any HP commit.

    Fire then Cold in one activation: collection rolls both portions once each through the activation's
    cache and does not dispatch a commit. Without the collection the instance is unknown at declaration.
    """
    from types import SimpleNamespace
    from combat import typed_executor as te
    rolls = {'a': (5, 'FIRE'), 'b': (4, 'COLD')}
    monkeypatch.setattr(te, '_damage_roll', lambda ctx, effect: rolls[effect['id']])
    monkeypatch.setattr(te, 'eligible', lambda ctx, effect, include_deferred=False: True, raising=False)
    import combat.effect_eligibility as ee
    monkeypatch.setattr(ee, 'eligible', lambda ctx, effect, include_deferred=False: True)
    committed = []
    monkeypatch.setattr(te, '_deal_in_chain', lambda *a, **k: committed.append(a))
    effects = [{'type': 'damage', 'id': 'a'}, {'type': 'damage', 'id': 'b'}]
    portions = te._collect_damage_instance(SimpleNamespace(), effects)
    assert portions == [{'type': 'FIRE', 'amount': 5}, {'type': 'COLD', 'amount': 4}]
    assert committed == []


def test_damage_instance_opt_in_needs_a_maw_owner(monkeypatch):
    """Finding 1: the executor only collects a simultaneous instance for an eligible consumer."""
    from types import SimpleNamespace
    from combat.ext import devouring_maw as dm

    recipient = SimpleNamespace(active=True)
    ctx = SimpleNamespace(target=recipient, targets=[recipient])
    effects = [{'type': 'damage'}, {'type': 'damage'}]
    monkeypatch.setattr(dm, '_roles', lambda engine, actor: {})
    assert dm.swallow_instance_requested(SimpleNamespace(), ctx, effects) is None
    monkeypatch.setattr(dm, '_roles', lambda engine, actor: {'swallow'})
    assert dm.swallow_instance_requested(SimpleNamespace(), ctx, effects) is True
    assert dm.swallow_instance_requested(SimpleNamespace(), ctx, [{'type': 'damage'}]) is None


def test_no_maw_owner_keeps_the_original_roll_order_between_damage_portions(tmp_path, monkeypatch):
    """Finding 1: without a Maw owner, a later portion is rolled after the first portion resolves.

    A real compiled save action commits Fire, Slashing and Necrotic as separate packets. The
    non-Maw owner's Stamina Guard rolls its soak between the first and second damage rolls.
    Pre-collecting the instance rolls every portion first and changes the deterministic dice
    stream for an unrelated character, so the second damage roll must come after the soak.
    The owner is AI-controlled so the reaction resolves inline (a manual seat's Ask-me pause
    replays the intent and would confuse the roll-order signal with the service's probe).
    """
    from combat import typed_executor as te
    collected = []
    original = te._collect_damage_instance
    monkeypatch.setattr(te, '_collect_damage_instance',
                        lambda ctx, effects: collected.append(effects) or original(ctx, effects))
    doc = sheet([], cl=10, primary='Stamina', name='Guard Wren')
    doc['identity']['path'] = 'Body Refining'
    doc['path_and_subpath'] = {'path_feature_record_ids': ['tianxia.path.body_refining.feature.stamina_guard']}
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet(['FIRE_TAL_FIREBALL_ART'], cl=10, dc=100, primary='Qi', name='Hostile fire cultivator')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_bundle=owner, foe_sheet=foe, primary='Stamina',
                                 bundle_transform=mixed_save_action, seed='MGR-MAW-NO-OWNER',
                                 modes={OWNER: 'LOCAL_AUTO', ALLY: 'LOCAL_AUTO', FOE: 'MANUAL'})
    turn(table, mid, FOE)
    blast = source_candidates(combat, mid, 'Twin Test Blast', OWNER)
    assert blast
    settle(table, mid, blast[0].candidate_id)
    engine = reload(tmp_path, mid)
    reasons = [str(roll.reason) for roll in engine.rolls]
    damage = [index for index, reason in enumerate(reasons) if reason.startswith('DAMAGE:')]
    soak = next(index for index, reason in enumerate(reasons) if reason.startswith('DAMAGE_SOAK:'))
    assert len(damage) >= 2, reasons
    assert damage[0] < soak < damage[1], reasons
    assert collected == [], 'no eligible consumer may collect the instance for a non-Maw character'


def test_swallow_hostile_power_asks_one_valid_type_and_reduces_only_it(tmp_path, acquired):
    """Finding 2: "choose one type" is a player decision, and only that type is reduced.

    The failed save commits Fire, then an invalid Slashing portion, then Necrotic. Choosing
    Necrotic spends the reaction on the first packet but carries the reduction to its own
    portion: Fire and Slashing take full damage, Necrotic is reduced, and one Necrotic Essence
    is awarded. Slashing (physical outside Devour) is never a legal choice.
    """
    combat, table, mid = scenario(tmp_path, acquired, cl=6, foe_mixed=True, seed='MGR-MAW-NATIVE-7')
    turn(table, mid, FOE)
    blast = source_candidates(combat, mid, 'Twin Test Blast', OWNER)
    assert blast
    prompts = settle(table, mid, blast[0].candidate_id, choices={
        REACTION + PREFIX + 'swallow_hostile_power': 'first',
        'choice:needle.maw_swallow_type': ['NECROTIC']})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert stored(owner) == ['NECROTIC'], stored(owner)
    assert records(owner)[0]['type'] == 'NECROTIC'
    type_prompt = next(p for p in prompts
                       if p['context']['reaction_source_id'] == 'choice:needle.maw_swallow_type')
    options = {option['id'] for option in type_prompt['choice']['options']}
    assert options == {'FIRE', 'NECROTIC'}, options
    reduction = next(roll.total for roll in engine.rolls
                     if str(roll.reason).startswith('REACTION:' + PREFIX + 'swallow_hostile_power'))
    packets = {str(event.payload['damage_type']).upper(): event.payload for event in engine.events
               if event.event_type == 'DAMAGE_COMMITTED' and event.actor_id == FOE and OWNER in event.target_ids}
    assert set(packets) == {'FIRE', 'SLASHING', 'NECROTIC'}, packets.keys()
    assert packets['FIRE']['hp_damage'] == packets['FIRE']['rolled_or_pending_damage']
    assert packets['SLASHING']['hp_damage'] == packets['SLASHING']['rolled_or_pending_damage']
    expected = max(0, packets['NECROTIC']['rolled_or_pending_damage'] - reduction)
    assert packets['NECROTIC']['hp_damage'] == expected

