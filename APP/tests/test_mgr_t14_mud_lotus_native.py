"""Acquisition -> native procedure/table intent -> committed state -> cold reload.

Scene rulings enter via the protected owner service, never injected flags.
External challenges are actually authored through the production procedure store.
No live model or browser is involved.
"""
import copy
import json
from zipfile import ZipFile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.mud_lotus_native import (
    PREFIX, FOUNDATION, GENERATE, RESERVE, ROOT, WITNESS, GUARD, FILTER,
    REFINED, SHELTER, DEW, FILTER_USED)
from combat.ext.mud_lotus_recovery import FIELD, CONDITION, CHOICE
from combat.recovery_sources import source_id
from tests.h1_support import ROOT as APP, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, reload, candidate, settle

from tests.test_save_reload_equivalence import STOCK_SEEDS

PROJECT = '11111111-1111-4111-8111-111111111111'
FOE_PROJECT = '22222222-2222-4222-8222-222222222222'
ACCESS = {'kind': 'chosen', 'classification': 'Foundation expression', 'reference': 'campaign:expression-choice'}


def consequence(category='poison', *, classification='Minor', kind='consequence', severity=2, steps=('Strain', 'Minor injury')):
    poisoned = {'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target',
                'duration': {'kind': 'until_removed'}}
    return {'name': 'Source-defined venom consequence', 'category': category,
            'classification': classification, 'kind': kind, 'severity': severity, 'steps': list(steps),
            'expires': 'UNTIL_REMOVED',
            'mechanical_effect': 'The lower step deals 1 poison damage; the upper step deals 2 poison damage and causes Poisoned until treated.',
            'effects': [poisoned],
            'step_effects': [[{'type': 'damage', 'flat': 1, 'damage_types': ['poison'], 'applies_to': 'target'}],
                             [poisoned, {'type': 'damage', 'flat': 2, 'damage_types': ['poison'], 'applies_to': 'target'}]] if len(steps) == 2 else [],
            'step_replacement_effects': [[], [poisoned]] if len(steps) == 2 else [],
            'strain': {'mechanical_effect': 'Speed becomes 25 feet for one minute.',
                'duration': 'one minute', 'duration_kind': 'one_minute', 'recovery_mode': 'rest',
                'effects': [{'type': 'speed', 'becomes': 25, 'applies_to': 'target',
                             'duration': {'kind': 'one_minute'}}]}}


def timed_consequence():
    """Minor three-step venom: its middle and top steps add a one-minute Poisoned penalty."""
    timed = {'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'duration': {'kind': 'one_minute'}}
    row = consequence(severity=3, steps=('Strain', 'Minor injury', 'Major injury'))
    penalty = {'type': 'speed', 'flat': -5, 'applies_to': 'target',
               'duration': {'kind': 'one_minute'}}
    row['step_effects'] = [[{'type': 'damage', 'flat': 1, 'damage_types': ['poison'], 'applies_to': 'target'}],
                           [{'type': 'damage', 'flat': 2, 'damage_types': ['poison'], 'applies_to': 'target'}, timed, penalty],
                           [{'type': 'damage', 'flat': 3, 'damage_types': ['poison'], 'applies_to': 'target'}, timed, penalty]]
    row['step_replacement_effects'] = [[], [timed, penalty], [timed, penalty]]
    return row


def procedure(pid, kind='treatment', **kw):
    return {'id': pid, 'name': 'Recorded ' + pid.replace('_', ' '),
        'source_reference': 'campaign:challenge/' + pid,
        'printed_rule': 'Recorded source challenge: resolve its stated roll, cost and consequence.',
        'kind': kind, 'economy': 'NONE', 'range_ft': 30, 'cp_cost': 0, 'dc': 10, 'ability': 'WIS', **kw}


def setup(tmp_path, *, expressions=(), stage='Perfected', initial=0, owner_procedures=(), foe_procedures=(), modes=None, native_poison=False, second_lotus=False):
    original = sheet([RESERVE], foundation={'foundation_id': FOUNDATION, 'stage': stage,
        'resource': {'name': 'Lotus Dew', 'resource_id': 'tianxia.resource.lotus_dew', 'maximum': 1, 'current': 0}}, name='Lotus Keeper')
    combat = CombatService(APP, tmp_path)
    table = TabletopService(combat, tmp_path)
    docs = {PROJECT: original, FOE_PROJECT: sheet([], name='Source bearer')}
    # Admit real persisted character sources through the production loader;
    # native feature/procedure acquisition then updates its advancement store.
    for pid, document in docs.items():
        package = tmp_path / 'portable_characters' / pid / 'current.zip'
        package.parent.mkdir(parents=True)
        with ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    for feature in expressions:
        if feature == SHELTER:
            continue  # This row is granted at Refined; it has no selection clause.
        assert table.acquire_feature(PROJECT, feature, ACCESS)['status'] == 'ACQUIRED'
    if initial:
        owner_procedures = [procedure('dew_treatment', cp_cost=1, modifier=30, skill='Medicine'), *owner_procedures]
    foe_procedures = [procedure('poison_save', 'save', dc=1, categories=['poison'],
                              consequence=consequence()), *foe_procedures]
    for pid, rows in ((PROJECT, owner_procedures), (FOE_PROJECT, foe_procedures)):
        for row in rows:
            assert table.record_procedure(pid, row)['status'] == 'RECORDED'
    owner_doc = combat._factory_owner_sheet(PROJECT)
    owner = compile_character(owner_doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = compile_character(combat._factory_owner_sheet(FOE_PROJECT), actor_id=FOE, reaction_plan={'ask': True})
    def delivery(bundles):
        bundles[2] = foe
        if second_lotus:
            companion = copy.deepcopy(original)
            companion['identity']['name'] = 'Lotus companion'
            bundles[1] = compile_character(companion, actor_id=ALLY, reaction_plan={'ask': True})
        if native_poison:
            from tests.test_a2_foundations3 import add_action
            add_action(bundles[2], 'Ordinary poisoned save', [{'type': 'save', 'ability': 'CON',
                'save_categories': ['poisoned'], 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                    'applies_to': 'target', 'duration': {'kind': 'one_minute'}}], 'on_success': []}],
                economy='NONE', dc=100)
            add_action(bundles[2], 'Ordinary poison cure', [{'type': 'remove_condition',
                'condition': 'poisoned', 'applies_to': 'target'}], economy='NONE')
    s, t, m = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=delivery, modes=modes, seed='MUD-NATIVE-SOURCE')
    if initial:
        record(s, t, m, OWNER, 'Recorded dew treatment', [ALLY], key='generation', scene='dangerous')
        use(s, t, m, 'Recorded dew treatment', ALLY)
        assert reload(tmp_path, m).state.actors[OWNER].resources[DEW] == 1
    return s, t, m


def record(combat, table, mid, actor, name, targets, *, key='event', reality='genuine', scene='treatment',
           method='humble_recovery', exclusions=(), categories=(), witness_ids=None, **extra):
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == actor and a.display_name == name)
    document = {'record_id': key, 'subject_id': targets[0], 'subject_name': 'Source recovery scene',
        'subject_kind': 'creature', 'position': engine.state.actors[targets[0]].position.model_dump(mode='json'),
        'source_reference': 'campaign:observed/' + key, 'witness_ids': witness_ids or [OWNER, ALLY, FOE],
        'valid_through_round': engine.state.round_number + 10, 'answers': {},
        'recovery': {'actor_id': actor, 'source_ids': [action.source_definition_id],
            'recipient_ids': list(targets), 'evidence': 'The GM records the actual source and recovery scene.',
            'reality': reality, 'scene': scene, 'method': method, 'exclusions': list(exclusions),
            'categories': list(categories), **extra}}
    assert table.record_fact(mid, document, expected_state_version=engine.state.state_version)['status'] == 'COMMITTED'
    return document


def use(combat, table, mid, name, target=OWNER, picks=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks=picks)


def conditions(engine, target, cid=None):
    return [c for c in engine.state.actors[target].conditions.values() if cid is None or c.condition_id == cid]


def world_turn(combat, jid, aid):
    """Follow real persisted native turns; JSON actor order is not a fixture API."""
    from combat.journey_activity import load
    for _ in range(10):
        engine = load(combat.journeys.load(jid))
        current = engine.state.current_actor_id
        if current == aid:
            return
        end = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
        state = combat.journey_state(jid)
        combat.journey_act(jid, state['revision'], current, 'native_activity', {'candidate_id': end.candidate_id})
    raise AssertionError('The requested native actor did not receive its turn')


@pytest.mark.parametrize('returned', [0, 1])
def test_native_fixed_scope_generation_uses_actual_net_cp_after_source_refund(tmp_path, returned):
    from combat.ext.d20_rewrite import pool_id
    row = procedure('settled_medicine', cp_cost=1, cp_refund_on_success=returned,
        modifier=30, skill='Medicine', printed_rule=f'Roll Medicine against DC 10; pay 1 cultivation point. '
        f'On success refund {returned} of the point actually paid. No healing or temporary Hit Points are granted.')
    s, table, mid = setup(tmp_path, owner_procedures=[row])
    engine = reload(tmp_path, mid)
    pool = pool_id(engine.state.actors[OWNER], 'cp')
    before = engine.state.actors[OWNER].resources[pool]
    record(s, table, mid, OWNER, row['name'], [OWNER], scene='ordinary')
    use(s, table, mid, row['name'], OWNER)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[OWNER].resources[pool] == before - 1 + returned
    receipt = next(e for e in cold.events if e.event_type == 'SOURCE_PROCEDURE_RESOLVED')
    assert receipt.payload['cp_paid'] == 1 - returned
    assert cold.state.actors[OWNER].resources[DEW] == 1 - returned
    assert any(e.event_type == 'RESOURCE_GAINED' and e.payload.get('cost_source_id')
               for e in cold.events) == bool(returned)


@pytest.mark.parametrize('kind,category,classification,left', [
    ('hidden_injury', 'poison', 'major', 1), ('curse', 'poison', 'major', 1),
    ('deviation', 'rot', 'major', 1), ('consequence', 'disease', 'major', 1),
    ('consequence', 'poison', 'Minor', 0)])
def test_native_measurable_guard_never_erases_a_major_ailment(tmp_path, kind, category, classification, left):
    harm = consequence(category, kind=kind, classification=classification)
    s, table, mid = setup(tmp_path, initial=1, foe_procedures=[procedure('scoped_harm', 'harm',
        harm=2, categories=[category], consequence=harm)])
    turn(table, mid, FOE)
    record(s, table, mid, FOE, 'Recorded scoped harm', [OWNER], categories=[category])
    use(s, table, mid, 'Recorded scoped harm', OWNER)
    cold = reload(tmp_path, mid)
    receipt = next(e for e in cold.events if e.event_type == 'MEASURABLE_HARM_RESOLVED')
    assert receipt.payload['after'] == left
    assert cold.state.actors[OWNER].resources[DEW] == 0
    markers = [c for c in cold.state.actors[OWNER].conditions.values() if c.data.get('kind') == kind
               and c.data.get('classification') == classification]
    assert bool(markers) == bool(left)
    if left:
        assert markers[0].data['severity'] == 1


def test_source_procedure_unaffordable_cost_is_not_a_legal_candidate(tmp_path):
    s, t, m = setup(tmp_path, owner_procedures=[procedure('expensive_medicine', cp_cost=100, hp=1)])
    record(s, t, m, OWNER, 'Recorded expensive medicine', [ALLY])
    e = reload(tmp_path, m)
    assert not any(c.display_name == 'Recorded expensive medicine' for c in e.legal_candidates())
    assert not any(x.event_type == 'SOURCE_PROCEDURE_RESOLVED' for x in e.events)


@pytest.mark.parametrize('affected', [False, True])
def test_no_roll_treatment_requires_an_actual_cure_receipt(tmp_path, affected):
    cure = procedure('cure', dc=None, skill='Medicine', success_effects=[
        {'type': 'remove_condition', 'condition': 'poisoned', 'applies_to': 'target'}])
    s, t, m = setup(tmp_path, owner_procedures=[cure],
        foe_procedures=[procedure('venom', 'consequence', consequence=consequence())])
    if affected:
        turn(t, m, FOE)
        record(s, t, m, FOE, 'Recorded venom', [ALLY], categories=['poison'])
        use(s, t, m, 'Recorded venom', ALLY)
        assert conditions(reload(tmp_path, m), ALLY, 'condition:typed.poisoned')
        turn(t, m, OWNER)
    record(s, t, m, OWNER, 'Recorded cure', [ALLY], key='cure', scene='dangerous', method='poison_treatment')
    use(s, t, m, 'Recorded cure', ALLY)
    e = reload(tmp_path, m)
    assert not conditions(e, ALLY, 'condition:typed.poisoned')
    assert e.state.actors[OWNER].resources[DEW] == int(affected)
    receipt = [x for x in e.events if x.event_type == 'SOURCE_PROCEDURE_RESOLVED'][-1]
    assert receipt.payload['treatment_completed'] == int(affected)


def test_actual_treatment_cp_payment_and_later_recovery_commit_reload(tmp_path):
    s, t, m = setup(tmp_path, owner_procedures=[procedure('medicine', hp=3, cp_cost=1, modifier=30, skill='Medicine')])
    record(s, t, m, OWNER, 'Recorded medicine', [ALLY], scene='dangerous', method='medicine')
    use(s, t, m, 'Recorded medicine', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 1
    assert any(x.event_type == 'SOURCE_PROCEDURE_RESOLVED' and x.payload['cp_paid'] == 1 for x in e.events)
    assert any(x.event_type == 'RESOURCE_SPENT' and x.payload['amount'] == 1 for x in e.events)
    assert not any(c.display_name == 'Recorded medicine' for c in e.legal_candidates())
    # The original event has settled before a later native bonus-action spend.
    use(s, t, m, 'Lotus-Root Recovery', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert e.state.actors[ALLY].temporary_hp == 6
    assert any(x.event_type == 'TABLE_FACT_RECORDED' for x in e.events)


@pytest.mark.parametrize('exclusion', ['staged', 'self_inflicted', 'harmless', 'training', 'repeated_non_threatening', 'farmed', 'preserve_corruption'])
def test_excluded_treatment_cannot_generate(tmp_path, exclusion):
    s, t, m = setup(tmp_path, owner_procedures=[procedure('medicine', modifier=30, skill='Medicine')])
    record(s, t, m, OWNER, 'Recorded medicine', [ALLY], scene='dangerous', exclusions=[exclusion])
    use(s, t, m, 'Recorded medicine', ALLY)
    assert reload(tmp_path, m).state.actors[OWNER].resources[DEW] == 0


@pytest.mark.parametrize('origin,hostility,expected,mode,exclusions', [
    ('environmental_hazard', 'hostile', 1, 'ADVANTAGE', []),
    ('environmental_hazard', 'benign', 0, 'NORMAL', []),
    ('technique', 'hostile', 0, 'NORMAL', []),
    ('environmental_hazard', 'hostile', 1, 'ADVANTAGE', ['dry']),
    ('environmental_hazard', 'hostile', 1, 'ADVANTAGE', ['sterile']),
    ('environmental_hazard', 'hostile', 1, 'ADVANTAGE', ['hostile_rest'])])
def test_real_environmental_resistance_is_not_a_friendly_self_event(tmp_path, origin, hostility, expected, mode, exclusions):
    s, t, m = setup(tmp_path, owner_procedures=[procedure('water_exposure', 'save', dc=1,
        ability='CON', origin=origin, hostility=hostility, categories=['polluted_water'],
        consequence=consequence('polluted_water'))])
    record(s, t, m, OWNER, 'Recorded water exposure', [OWNER], scene='ordinary', method='unknown',
           categories=['polluted_water'], exclusions=exclusions)
    use(s, t, m, 'Recorded water exposure', OWNER)
    e = reload(tmp_path, m)
    save = [x for x in e.events if x.event_type == 'SAVE_ROLLED'][-1]
    assert save.payload['success'] and save.payload['mode'] == mode
    assert e.state.actors[OWNER].resources[DEW] == expected


@pytest.mark.parametrize('ability,tag,hostility,mode', [
    ('WIS', 'low_status_shame', 'hostile', 'ADVANTAGE'),
    ('CON', 'humble_origin_shame', 'hostile', 'ADVANTAGE'),
    ('STR', 'low_status_shame', 'hostile', 'NORMAL'),
    ('WIS', 'pride_pressure', 'hostile', 'NORMAL'),
    ('WIS', 'low_status_shame', 'benign', 'NORMAL')])
def test_native_reserve_shame_ability_hostility_boundaries(tmp_path, ability, tag, hostility, mode):
    consequence_row = consequence('similar_scoped', severity=1, steps=())
    consequence_row.update(name='Source-defined shame pressure',
        mechanical_effect='On a failed save, speed becomes 25 feet until removed.',
        effects=[{'type': 'speed', 'becomes': 25, 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    s, table, mid = setup(tmp_path, foe_procedures=[procedure('humble_origin_pressure', 'save',
        dc=1, ability=ability, hostility=hostility, categories=[tag], consequence=consequence_row)])
    turn(table, mid, FOE)
    record(s, table, mid, FOE, 'Recorded humble origin pressure', [OWNER],
           scene='ordinary', method='unknown', categories=[tag])
    use(s, table, mid, 'Recorded humble origin pressure', OWNER)
    cold = reload(tmp_path, mid)
    save = next(e for e in reversed(cold.events) if e.event_type == 'SAVE_ROLLED')
    assert save.payload['mode'] == mode
    assert cold.state.actors[OWNER].resources[DEW] == 0


def test_native_field_keeps_its_minute_when_owner_falls_unconscious(tmp_path):
    s, table, mid = setup(tmp_path, foe_procedures=[
        procedure('direct_blow', 'damage', harm=60, damage_type='force'),
        procedure('venom_save', 'save', ability='CON', dc=1, categories=['poison'], consequence=consequence())])
    use(s, table, mid, 'Lotus Recovery Field', OWNER, {CHOICE: [ALLY]})
    turn(table, mid, FOE)
    record(s, table, mid, FOE, 'Recorded direct blow', [OWNER])
    use(s, table, mid, 'Recorded direct blow', OWNER)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[OWNER].current_hp == 0
    assert conditions(cold, OWNER, CONDITION)
    record(s, table, mid, FOE, 'Recorded venom save', [ALLY], key='venom', categories=['poison'])
    use(s, table, mid, 'Recorded venom save', ALLY)
    cold = reload(tmp_path, mid)
    save = next(e for e in reversed(cold.events) if e.event_type == 'SAVE_ROLLED')
    assert save.payload['success'] and save.payload['mode'] == 'ADVANTAGE'
    assert cold.state.actors[ALLY].temporary_hp == 4
    assert cold.state.actors[OWNER].resources[DEW] == 0


def test_hostile_environmental_poison_damage_uses_real_guard_reaction(tmp_path):
    s, t, m = setup(tmp_path, initial=1, owner_procedures=[procedure('hostile_water', 'damage',
        harm=20, damage_type='poison', origin='environmental_hazard', hostility='hostile')])
    record(s, t, m, OWNER, 'Recorded hostile water', [OWNER], scene='ordinary', method='unknown', categories=['poison'])
    use(s, t, m, 'Recorded hostile water', OWNER, {'reaction:typed.' + GUARD: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].current_hp == 50
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert not e.state.actors[OWNER].reaction_available


def test_refined_choice_acquisition_and_bonus_native_reload(tmp_path):
    s, t, m = setup(tmp_path, expressions=[REFINED], initial=1)
    record(s, t, m, OWNER, 'Lotus-Root Recovery', [ALLY])
    prompts = use(s, t, m, 'Lotus-Root Recovery', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].temporary_hp == 10
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert any('Lotus-Root Recovery' in str(p) for p in prompts)


@pytest.mark.parametrize('stage,expression', [('Awakened', FILTER), ('Awakened', REFINED)])
def test_expression_access_requires_actual_refined_stage(tmp_path, stage, expression):
    with pytest.raises(Exception, match='Foundation stage'):
        setup(tmp_path, expressions=[expression], stage=stage)


def test_witness_paid_after_roll_and_source_minor_step_native(tmp_path):
    s, t, m = setup(tmp_path, initial=1, owner_procedures=[procedure('medicine', dc=100, skill='Medicine', consequence=consequence())])
    record(s, t, m, OWNER, 'Recorded medicine', [ALLY], treats_another=True, gm_reduce_minor=True)
    prompts = use(s, t, m, 'Recorded medicine', ALLY, {'reaction:typed.' + WITNESS: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert any(x.event_type == 'D20_REWRITTEN' and x.source_definition_id == WITNESS
               and x.payload.get('operation') == 'bonus' for x in e.events)
    row = next(x for x in e.events if x.event_type == 'SOURCE_CONSEQUENCE_RESOLVED')
    assert row.payload['severity'] == 1
    assert e.state.actors[ALLY].current_hp == 59
    assert not conditions(e, ALLY, 'condition:typed.poisoned')
    assert any('Humble Medicine Witness' in str(p) for p in prompts)


@pytest.mark.parametrize('classification,selected,expected', [('Minor', True, 1), ('major', True, 2), ('Minor', False, 2)])
def test_muddy_filter_source_consequence_once_and_boundary(tmp_path, classification, selected, expected):
    s, t, m = setup(tmp_path, expressions=[FILTER] if selected else [], foe_procedures=[procedure('venom', 'consequence', consequence=consequence(classification=classification))])
    record(s, t, m, FOE, 'Recorded venom', [OWNER], categories=['poison'])
    turn(t, m, FOE)
    use(s, t, m, 'Recorded venom', OWNER)
    e = reload(tmp_path, m)
    row = next(x for x in e.events if x.event_type == 'SOURCE_CONSEQUENCE_RESOLVED')
    assert row.payload['severity'] == expected
    assert bool(conditions(e, OWNER, FILTER_USED)) == (classification == 'Minor' and selected)
    record(s, t, m, FOE, 'Recorded venom', [OWNER], key='second', categories=['poison'])
    use(s, t, m, 'Recorded venom', OWNER)
    assert [x for x in reload(tmp_path, m).events if x.event_type == 'SOURCE_CONSEQUENCE_RESOLVED'][-1].payload['severity'] == 2


@pytest.mark.parametrize('classification,ignored', [('Minor', True), ('major', False), (None, False)])
def test_filter_intercepts_ordinary_native_condition_only_with_source_minor_ruling(tmp_path, classification, ignored):
    s, t, m = setup(tmp_path, expressions=[FILTER], native_poison=True)
    pending = [] if classification is None else [{'condition_id': 'condition:typed.poisoned',
        'consequence': consequence(classification=classification, severity=1, steps=())}]
    record(s, t, m, FOE, 'Ordinary poisoned save', [OWNER], pending_consequences=pending)
    turn(t, m, FOE)
    use(s, t, m, 'Ordinary poisoned save', OWNER)
    e = reload(tmp_path, m)
    assert not [x for x in e.events if x.event_type == 'SAVE_ROLLED'][-1].payload['success']
    assert bool(conditions(e, OWNER, FILTER_USED)) == ignored
    assert bool(conditions(e, OWNER, 'condition:typed.poisoned')) == (not ignored)
    if classification == 'major':
        marker = next(c for c in conditions(e, OWNER) if c.condition_id.startswith('condition:source.'))
        assert marker.expires_on == conditions(e, OWNER, 'condition:typed.poisoned')[0].expires_on
        use(s, t, m, 'Ordinary poison cure', OWNER)
        e = reload(tmp_path, m)
        assert not conditions(e, OWNER, 'condition:typed.poisoned')
        assert not [c for c in conditions(e, OWNER) if c.condition_id.startswith('condition:source.')]


def test_guard_reduces_real_non_hp_harm_and_spends_reaction(tmp_path):
    injury = consequence('rot', severity=15, steps=())
    injury.update(steps=[str(n) + ' feet of speed lost' for n in range(1, 16)],
        mechanical_effect='Speed is reduced by the recorded severity in feet until treated.',
        step_effects=[[{'type': 'speed', 'flat': -n, 'applies_to': 'target',
                        'duration': {'kind': 'until_removed'}}] for n in range(1, 16)],
        step_replacement_effects=[[{'type': 'speed', 'flat': -n, 'applies_to': 'target',
                                    'duration': {'kind': 'until_removed'}}] for n in range(1, 16)])
    s, t, m = setup(tmp_path, initial=1, foe_procedures=[procedure('rot_harm', 'harm', harm=15, categories=['rot'], consequence=injury)])
    record(s, t, m, FOE, 'Recorded rot harm', [OWNER], categories=['rot'])
    turn(t, m, FOE)
    use(s, t, m, 'Recorded rot harm', OWNER)
    e = reload(tmp_path, m)
    row = next(x for x in e.events if x.event_type == 'MEASURABLE_HARM_RESOLVED')
    assert row.payload['after'] == 5
    assert any(mod.target_field == 'speed_ft' and int(mod.value) == -5
               for mod in e.state.actors[OWNER].modifiers.values())
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert not e.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('categories,refined,reduction', [(['rot'], False, 10), ([], False, 0), (['rot'], True, 14)])
def test_guard_classified_necrotic_native_packet(tmp_path, categories, refined, reduction):
    s, t, m = setup(tmp_path, initial=1, expressions=[REFINED] if refined else [],
        foe_procedures=[procedure('rot_packet', 'damage', harm=20, damage_type='necrotic')])
    record(s, t, m, FOE, 'Recorded rot packet', [OWNER], categories=categories)
    turn(t, m, FOE)
    use(s, t, m, 'Recorded rot packet', OWNER, {'reaction:typed.' + GUARD: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].current_hp == 40 + reduction
    assert e.state.actors[OWNER].resources[DEW] == (0 if reduction else 1)


@pytest.mark.parametrize('purpose_actor,expected', [(OWNER, 1), (FOE, 2)])
def test_witness_native_save_and_minor_step(tmp_path, purpose_actor, expected):
    s, t, m = setup(tmp_path, initial=1, foe_procedures=[procedure('treatment_save', 'save',
        skill='Medicine', dc=100, categories=['poison'], consequence=consequence())])
    record(s, t, m, FOE, 'Recorded treatment save', [OWNER], cleanses_source=True,
           gm_reduce_minor=True, purpose_actor_ids=[purpose_actor])
    turn(t, m, FOE)
    use(s, t, m, 'Recorded treatment save', OWNER, {'reaction:typed.' + WITNESS: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 0
    assert [x for x in e.events if x.event_type == 'SOURCE_CONSEQUENCE_RESOLVED'][-1].payload['severity'] == expected


@pytest.mark.parametrize('kind', ['consequence', 'curse', 'deviation'])
def test_witness_treats_actual_existing_consequence_without_replaying_damage(tmp_path, kind):
    from combat.target_knowledge import recent_events
    s, t, m = setup(tmp_path, initial=1,
        owner_procedures=[procedure('medicine', dc=10, modifier=30, skill='Medicine')],
        foe_procedures=[procedure('venom', 'consequence', consequence=consequence(kind=kind))])
    turn(t, m, FOE)
    record(s, t, m, FOE, 'Recorded venom', [ALLY], categories=['poison'], witness_ids=[OWNER, FOE])
    use(s, t, m, 'Recorded venom', ALLY)
    e = reload(tmp_path, m)
    marker = next(c for c in conditions(e, ALLY) if c.condition_id.startswith('condition:source.'))
    assert e.state.actors[ALLY].current_hp == 58
    assert conditions(e, ALLY, 'condition:typed.poisoned')
    turn(t, m, OWNER)
    record(s, t, m, OWNER, 'Recorded medicine', [ALLY], key='treat-existing',
           treats_another=True, gm_reduce_minor=True, gm_consequence_ids=[marker.instance_id])
    use(s, t, m, 'Recorded medicine', ALLY, {'reaction:typed.' + WITNESS: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].conditions[marker.instance_id].data['severity'] == 1
    assert e.state.actors[ALLY].conditions[marker.instance_id].data['kind'] == kind
    assert e.state.actors[ALLY].current_hp == 58  # no repeated damage, and no free healing
    assert not conditions(e, ALLY, 'condition:typed.poisoned')
    assert any(x.event_type == 'SOURCE_CONSEQUENCE_REDUCED' for x in e.events)
    assert not any(x['event_type'] == 'CONDITION_UPDATED' and x['payload'].get('instance_id') == marker.instance_id
                   for x in recent_events(e, e.state.actors[ALLY], e.events))


def test_witness_step_reduction_keeps_the_remaining_clock_of_a_timed_penalty(tmp_path):
    """Finding 2 regression: a Minor step reduction must not restart a running one-minute Poisoned clock."""
    s, t, m = setup(tmp_path, initial=1,
        owner_procedures=[procedure('medicine', dc=10, modifier=30, skill='Medicine')],
        foe_procedures=[procedure('venom', 'consequence', consequence=timed_consequence())])
    turn(t, m, FOE)
    record(s, t, m, FOE, 'Recorded venom', [ALLY], categories=['poison'], witness_ids=[OWNER, FOE])
    use(s, t, m, 'Recorded venom', ALLY)
    e = reload(tmp_path, m)
    marker = next(c for c in conditions(e, ALLY) if c.condition_id.startswith('condition:source.'))
    assert marker.data['severity'] == 3
    poisoned = conditions(e, ALLY, 'condition:typed.poisoned')
    assert len(poisoned) == 1 and poisoned[0].expires_on is not None
    penalties = [m for m in e.state.actors[ALLY].modifiers.values() if m.target_field == 'speed_ft']
    assert len(penalties) == 1 and penalties[0].expires_on is not None
    original_clock, modifier_clock, rounds_before = poisoned[0].expires_on, penalties[0].expires_on, e.state.round_number
    # Part of the minute passes before the Witness treats the venom.
    for _ in range(4):
        if reload(tmp_path, m).state.round_number > rounds_before:
            break
        turn(t, m, FOE)
        turn(t, m, OWNER)
    assert reload(tmp_path, m).state.round_number > rounds_before
    # Lotus Dew ends at the end of its holder's turn, so the treatment's Dew is generated again on this turn.
    record(s, t, m, OWNER, 'Recorded dew treatment', [ALLY], key='generation-again', scene='dangerous')
    use(s, t, m, 'Recorded dew treatment', ALLY)
    assert reload(tmp_path, m).state.actors[OWNER].resources[DEW] == 1
    record(s, t, m, OWNER, 'Recorded medicine', [ALLY], key='treat-existing', treats_another=True,
           gm_reduce_minor=True, gm_consequence_ids=[marker.instance_id])
    use(s, t, m, 'Recorded medicine', ALLY, {'reaction:typed.' + WITNESS: 'first'})
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].conditions[marker.instance_id].data['severity'] == 2
    reduced = conditions(e, ALLY, 'condition:typed.poisoned')
    assert len(reduced) == 1
    assert reduced[0].expires_on == original_clock
    reduced_penalties = [m for m in e.state.actors[ALLY].modifiers.values() if m.target_field == 'speed_ft']
    assert len(reduced_penalties) == 1
    assert reduced_penalties[0].expires_on == modifier_clock


@pytest.mark.parametrize('hostility,first_mode', [('unknown', 'DISADVANTAGE'), ('hostile', 'DISADVANTAGE'), ('benign', 'NORMAL')])
def test_field_first_hostile_poison_attack_each_turn(tmp_path, hostility, first_mode):
    s, t, m = setup(tmp_path, foe_procedures=[procedure('poison_attack', 'attack', harm=1,
        damage_type='poison', hostility=hostility)])
    use(s, t, m, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    turn(t, m, FOE)
    for index in range(2):
        record(s, t, m, FOE, 'Recorded poison attack', [ALLY], key='attack' + str(index), categories=['poison'])
        use(s, t, m, 'Recorded poison attack', ALLY)
    e = reload(tmp_path, m)
    rolls = [x for x in e.events if x.event_type == 'ATTACK_ROLLED' and x.actor_id == FOE]
    assert rolls[-2].payload['mode'] == first_mode
    assert rolls[-1].payload['mode'] == 'NORMAL'


def test_field_save_dc_contest_does_not_spend_allowance_on_ordinary_check(tmp_path):
    contest = {'type': 'contest_against',
        'actor_check': {'kind': 'cultivation'}, 'target_check': {'kind': 'dc'},
        'on_success': [], 'on_fail': []}
    s, table, mid = setup(tmp_path, foe_procedures=[procedure('poison_contest', 'check',
        modifier=30, dc=1, categories=['poison'], success_effects=[contest])])
    use(s, table, mid, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    turn(table, mid, FOE)
    for index in range(2):
        record(s, table, mid, FOE, 'Recorded poison contest', [ALLY],
               key='contest' + str(index), categories=['poison'])
        use(s, table, mid, 'Recorded poison contest', ALLY)
    cold = reload(tmp_path, mid)
    rolls = [e for e in cold.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == FOE]
    # Each source first resolves its ordinary source check, then its printed
    # Save DC contest. Only that contest consumes the field's first-roll limit.
    assert [e.payload.get('actor', e.payload.get('roll', {}))['mode']
            for e in rolls[-4:]] == ['NORMAL', 'DISADVANTAGE', 'NORMAL', 'NORMAL']


@pytest.mark.parametrize('kind', ['damage', 'harm'])
def test_native_guard_does_not_treat_explicitly_benign_source_as_hostile(tmp_path, kind):
    row = procedure('benign_poison', kind, harm=2, categories=['poison'], hostility='benign',
        **({'damage_type': 'poison'} if kind == 'damage' else {'consequence': consequence()}))
    s, table, mid = setup(tmp_path, initial=1, foe_procedures=[row])
    turn(table, mid, FOE)
    record(s, table, mid, FOE, row['name'], [OWNER], categories=['poison'])
    use(s, table, mid, row['name'], OWNER)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[OWNER].current_hp == 58
    assert cold.state.actors[OWNER].resources[DEW] == 1
    assert cold.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == GUARD for e in cold.events)


def test_overlapping_fields_do_not_stack_the_same_temp_hp_bonus(tmp_path):
    s, t, m = setup(tmp_path, second_lotus=True,
        owner_procedures=[procedure('recovery', temporary_hp=2, modifier=30, skill='Medicine')])
    use(s, t, m, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    turn(t, m, ALLY)
    use(s, t, m, 'Lotus Recovery Field', ALLY, {CHOICE: [OWNER, ALLY]})
    turn(t, m, OWNER)
    record(s, t, m, OWNER, 'Recorded recovery', [ALLY])
    use(s, t, m, 'Recorded recovery', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].temporary_hp == 6
    assert all(conditions(e, aid, CONDITION)[0].data['used_round'] == e.state.round_number for aid in (OWNER, ALLY))


@pytest.mark.parametrize('farmed', [False, True])
def test_field_derived_recovery_preserves_actual_parent_provenance(tmp_path, farmed):
    s, t, m = setup(tmp_path, foe_procedures=[procedure('outside_support', 'check',
        temporary_hp=2, modifier=30, skill='Arcana')])
    use(s, t, m, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    record(s, t, m, OWNER, 'Lotus Recovery Field', [ALLY], key='actual-field', method='living_water')
    record(s, t, m, FOE, 'Recorded outside support', [ALLY], key='actual-support', method='unknown',
           exclusions=['farmed'] if farmed else [])
    turn(t, m, FOE)
    use(s, t, m, 'Recorded outside support', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].temporary_hp == 6
    assert e.state.actors[OWNER].resources[DEW] == (0 if farmed else 1)


def test_field_minor_injury_conversion_and_corruption_end_native(tmp_path):
    s, t, m = setup(tmp_path, foe_procedures=[procedure('injury', 'consequence', consequence=consequence(kind='hidden_injury'))])
    use(s, t, m, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    record(s, t, m, FOE, 'Recorded injury', [ALLY], categories=['poison'])
    turn(t, m, FOE)
    use(s, t, m, 'Recorded injury', ALLY)
    e = reload(tmp_path, m)
    row = next(x for x in e.events if x.event_type == 'SOURCE_CONSEQUENCE_RESOLVED')
    assert row.payload['name'] == 'Strain' and row.payload['severity'] == 1
    record(s, t, m, OWNER, 'Lotus Recovery Field', [ALLY], key='corruption', exclusions=['hide_rot'])
    e = reload(tmp_path, m)
    assert not conditions(e, OWNER, CONDITION)
    assert conditions(e, OWNER, 'condition:typed.muddy_stagnation')[0].data['severity'] == 1
    assert not any(z.active and z.source_definition_id == FIELD for z in e.state.zones.values())


def test_field_declared_corrupt_before_manifestation_ends_and_keeps_payment(tmp_path):
    s, t, m = setup(tmp_path)
    record(s, t, m, OWNER, 'Lotus Recovery Field', [ALLY], key='corrupt-purpose', exclusions=['hide_rot'])
    before = reload(tmp_path, m).state.actors[OWNER].resources.copy()
    use(s, t, m, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    e = reload(tmp_path, m)
    assert not conditions(e, OWNER, CONDITION)
    assert conditions(e, OWNER, 'condition:typed.muddy_stagnation')[0].data['severity'] == 1
    assert sum(before.values()) - sum(e.state.actors[OWNER].resources.values()) == 3
    assert not any(z.active and z.source_definition_id == FIELD for z in e.state.zones.values())


@pytest.mark.parametrize('support_self', [False, True])
def test_pond_shelter_actual_roster_hour_journey_and_combat_reload(tmp_path, support_self):
    s, t, m = setup(tmp_path, expressions=[SHELTER])
    e = reload(tmp_path, m)
    bundles = list(e.typed_bundle_documents)
    arena = s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    state = s.journeys.create(bundles, arena,
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {i: 300 for i in (OWNER, ALLY, FOE)})
    jid = state['journey_id']
    def act(aid, kind, payload=None):
        current = s.journey_state(jid)
        return s.journey_act(jid, current['revision'], aid, kind, payload or {})
    facts = {'actor_id': OWNER, 'source_ids': [SHELTER], 'recipient_ids': [OWNER, ALLY],
        'evidence': 'Recorded food, medicine and willing company in humble shelter.',
        'reality': 'genuine', 'scene': 'shared_rest', 'method': 'shared_medicine'}
    with pytest.raises(ValueError, match='table-owner recovery scene'):
        act(OWNER, 'start_shared_rest', {'facts': facts, 'selected_ids': [ALLY]})
    declared = s.journeys.record_world_fact(jid, s.journey_state(jid)['revision'], {
        'source': 'system:recovery.shared_rest', 'subject': OWNER, 'kind': 'recovery_scene',
        'scope': jid, 'value': facts, 'expires_at': 7200, 'readers': [ALLY]})
    receipt = declared['fact_consent_admission'][-1]['receipt_id']
    act(OWNER, 'start_shared_rest', {'scene_receipt': receipt,
                                  'selected_ids': [ALLY, OWNER] if support_self else [ALLY]})
    act(ALLY, 'join_shared_rest')
    act(OWNER, 'finish_shared_rest')
    state = s.journey_state(jid)
    assert state['seconds'] == 3600
    from combat.journey_activity import load, replay_record
    native = load(s.journeys.load(jid))
    assert native.state.actors[ALLY].temporary_hp == 4
    assert native.state.actors[OWNER].resources[DEW] == int(support_self)  # Resting together is not alliance.
    record = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    assert replay_record(record).actors[ALLY].temporary_hp == 4
    act(OWNER, 'native_activity_end')
    state = s.journey_state(jid)
    assert state['actors'][OWNER]['resources'][DEW] == 0
    result = s.journey_start_combat(jid, state['revision'], {OWNER: 'a', ALLY: 'a', FOE: 'b'})
    assert reload(tmp_path, result['match_id']).state.actors[ALLY].temporary_hp == 4


@pytest.mark.parametrize('automatic', [False, True])
def test_pond_shelter_start_is_offered_by_the_journey_menu_and_starts_natively(tmp_path, automatic):
    """Finding 1 regression: the offered menu, not a direct command, must reach start_shared_rest."""
    s, t, m = setup(tmp_path, expressions=[SHELTER])
    bundles = list(reload(tmp_path, m).typed_bundle_documents)
    arena = s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    state = s.journeys.create(bundles, arena,
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {i: 300 for i in (OWNER, ALLY, FOE)}, control_modes={OWNER: 'LOCAL_AUTO' if automatic else 'MANUAL'})
    jid = state['journey_id']
    facts = {'actor_id': OWNER, 'source_ids': [SHELTER], 'recipient_ids': [OWNER, ALLY],
        'evidence': 'Recorded food, medicine and willing company in humble shelter.',
        'reality': 'genuine', 'scene': 'shared_rest', 'method': 'shared_medicine'}
    # Before the table owner records the scene, nothing about starting a rest is offered.
    assert not [o for o in s.journey_menu(jid, OWNER)['options'] if o['kind'] == 'start_shared_rest']
    declared = s.journeys.record_world_fact(jid, s.journey_state(jid)['revision'], {
        'source': 'system:recovery.shared_rest', 'subject': OWNER, 'kind': 'recovery_scene',
        'scope': jid, 'value': facts, 'expires_at': 7200, 'readers': [ALLY]})
    receipt = declared['fact_consent_admission'][-1]['receipt_id']
    starts = [o for o in s.journey_menu(jid, OWNER)['options'] if o['kind'] == 'start_shared_rest']
    chosen = next(o for o in starts if o['payload']['selected_ids'] == [ALLY])
    assert chosen['payload']['scene_receipt'] == receipt
    # Every legal beneficiary group up to the Proficiency Bonus stays reachable, including none.
    groups = {tuple(o['payload']['selected_ids']) for o in starts}
    assert () in groups and (ALLY,) in groups and (OWNER, ALLY) in groups
    if automatic:
        s.journey_auto_step(jid, s.journey_state(jid)['revision'], OWNER, option_id=chosen['id'])
    else:
        s.journey_act(jid, s.journey_state(jid)['revision'], OWNER, chosen['kind'], chosen['payload'])
    s.journey_act(jid, s.journey_state(jid)['revision'], ALLY, 'join_shared_rest')
    s.journey_act(jid, s.journey_state(jid)['revision'], OWNER, 'finish_shared_rest')
    state = s.journey_state(jid)
    assert state['seconds'] == 3600
    from combat.journey_activity import load
    assert load(s.journeys.load(jid)).state.actors[ALLY].temporary_hp == 4


def test_native_journey_treatment_cost_dew_clock_cold_mechanical_replay(tmp_path):
    from combat.journey_activity import load, replay_record
    s, table, mid = setup(tmp_path, owner_procedures=[procedure('world_treatment',
        cp_cost=1, modifier=30, skill='Medicine')])
    bundle = next(b for b in reload(tmp_path, mid).typed_bundle_documents if b['actor_id'] == OWNER)
    state = s.journeys.create([bundle], s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}}, {OWNER: 300})
    jid = state['journey_id']
    engine = load(s.journeys.load(jid))
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Recorded world treatment')
    assert not any(r.reason == 'INITIATIVE' for r in engine.rolls)
    from combat.ext.d20_rewrite import pool_id
    cp = pool_id(engine.state.actors[OWNER], 'cp')
    assert cp is not None
    before = engine.state.actors[OWNER].resources[cp]
    document = {'record_id': 'world-treatment', 'subject_id': OWNER, 'subject_name': 'Keeper',
        'subject_kind': 'creature', 'position': {'x': 3, 'y': 6}, 'source_reference': 'campaign:actual-world-treatment',
        'witness_ids': [OWNER], 'valid_through_round': 10, 'answers': {},
        'recovery': {'actor_id': OWNER, 'source_ids': [action.source_definition_id], 'recipient_ids': [OWNER],
            'evidence': 'A real dangerous treatment challenge, with actual Medicine roll and paid cultivation point.',
            'reality': 'genuine', 'scene': 'dangerous', 'method': 'humble_recovery'}}
    table.record_journey_fact(jid, document, expected_revision=state['revision'])
    offered = next(row for row in s.journey_menu(jid, OWNER)['options'] if row['label'].startswith('Recorded world treatment'))
    current = s.journey_state(jid)
    s.journey_act(jid, current['revision'], OWNER, offered['kind'], offered['payload'])
    state = s.journey_state(jid)
    native = load(s.journeys.load(jid))
    assert native.state.actors[OWNER].resources[cp] == before - 1
    assert native.state.actors[OWNER].resources[DEW] == 1
    assert any(e.event_type == 'SOURCE_PROCEDURE_RESOLVED' for e in native.events)
    for event in state['events']:
        if event['kind'] == 'NATIVE_ACTIVITY_COMMITTED':
            replay_record(event)
    s.journey_act(jid, state['revision'], OWNER, 'native_activity_end')
    state = s.journey_state(jid)
    assert state['seconds'] == 6 and state['actors'][OWNER]['resources'][DEW] == 1
    s.journey_act(jid, state['revision'], OWNER, 'finish')
    state = s.journeys.create([bundle], s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}}, {OWNER: 300})
    jid = state['journey_id']
    assert state['seconds'] == 0 and state['actors'][OWNER]['resources'][DEW] == 1
    s.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 5})
    state = s.journey_state(jid)
    assert state['actors'][OWNER]['resources'][DEW] == 1
    s.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 1})
    assert s.journey_state(jid)['actors'][OWNER]['resources'][DEW] == 0
    state = s.journey_state(jid)
    table.record_journey_fact(jid, document, expected_revision=state['revision'])
    assert not any(row['label'].startswith('Recorded world treatment')
                   for row in s.journey_menu(jid, OWNER)['options'])


@pytest.mark.parametrize('manual_override', [False, True])
def test_native_world_witness_waits_for_owner_after_roll_and_commits_once(tmp_path, manual_override):
    # The parameter exercises acceptance and decline through the actual native
    # owner checkpoint, without replacing the engine's reaction provider.
    from combat.journey_activity import load, replay_record
    s, table, mid = setup(tmp_path, owner_procedures=[
        procedure('dew_source', cp_cost=1, modifier=30, skill='Medicine'),
        procedure('world_witness', 'check', dc=100, skill='Medicine')])
    bundle = next(b for b in reload(tmp_path, mid).typed_bundle_documents if b['actor_id'] == OWNER)
    state = s.journeys.create([bundle], s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}}, {OWNER: 300})
    jid = state['journey_id']
    def admit(name, key):
        engine = load(s.journeys.load(jid))
        action = next(a for a in engine.action_catalog.values() if a.display_name == name)
        document = {'record_id': key, 'subject_id': OWNER, 'subject_name': 'Keeper',
            'subject_kind': 'creature', 'position': {'x': 3, 'y': 6}, 'source_reference': 'campaign:' + key,
            'witness_ids': [OWNER], 'valid_through_round': 10, 'answers': {},
            'recovery': {'actor_id': OWNER, 'source_ids': [action.source_definition_id], 'recipient_ids': [OWNER],
                'evidence': 'An actual source-bound treatment/cultivation check in a dangerous scene.',
                'reality': 'genuine', 'scene': 'dangerous', 'method': 'humble_recovery'}}
        table.record_journey_fact(jid, document, expected_revision=s.journey_state(jid)['revision'])
        engine = load(s.journeys.load(jid))
        c = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
        return s.journey_act(jid, s.journey_state(jid)['revision'], OWNER, 'native_activity', {'candidate_id': c.candidate_id})
    state = admit('Recorded dew source', 'dew')
    before = load(s.journeys.load(jid))
    assert before.state.actors[OWNER].resources[DEW] == 1
    state = admit('Recorded world witness', 'witness')
    pending = state['native_activity_pending']['request']
    assert pending['reactor_id'] == OWNER
    assert 'Humble Medicine Witness' in str(pending)
    assert 'Recorded world witness' in str(pending)
    assert before.state.actors[OWNER].display_name in str(pending)
    unchanged = load(s.journeys.load(jid))
    assert len(unchanged.rolls) == len(before.rolls)
    assert unchanged.state.actors[OWNER].resources[DEW] == 1
    answer = {key: pending[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
    answer.update(selection='USE' if manual_override else 'DECLINE', spend=1 if manual_override else 0)
    state = s.journey_act(jid, state['revision'], OWNER, 'native_activity_answer', answer)
    assert not state.get('native_activity_pending')
    after = load(s.journeys.load(jid))
    assert len(after.rolls) == len(before.rolls) + 1
    assert after.state.actors[OWNER].resources[DEW] == 1 - int(manual_override)
    for event in state['events']:
        if event['kind'] == 'NATIVE_ACTIVITY_COMMITTED':
            replay_record(event)
    state = s.journey_act(jid, state['revision'], OWNER, 'native_activity_end')
    assert state['seconds'] == 6


@pytest.mark.parametrize('manual_override', [False, True])
def test_native_source_condition_clock_releases_only_its_own_travel_status(tmp_path, manual_override):
    from fractions import Fraction
    from combat.journey_activity import load
    from combat.ext.source_consequence_continuation import KEY as SOURCE_STATE
    affliction = consequence(classification='ordinary', severity=1, steps=())
    affliction.update(mechanical_effect='Stunned for one minute; the exposure record remains until treated.',
        effects=[{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target',
                  'duration': {'kind': 'one_minute'}}])
    s, table, mid = setup(tmp_path, foe_procedures=[procedure('timed_affliction', 'consequence', consequence=affliction)])
    state = s.journeys.create(list(reload(tmp_path, mid).typed_bundle_documents),
        s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {i: 300 for i in (OWNER, ALLY, FOE)})
    jid = state['journey_id']
    for aid in (OWNER, ALLY):
        world_turn(s, jid, aid)
        engine = load(s.journeys.load(jid))
        c = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
        state = s.journey_act(jid, s.journey_state(jid)['revision'], aid, 'native_activity', {'candidate_id': c.candidate_id})
    engine = load(s.journeys.load(jid))
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Recorded timed affliction')
    document = {'record_id': 'actual-timed-source', 'subject_id': OWNER, 'subject_name': 'Keeper',
        'subject_kind': 'creature', 'position': {'x': 3, 'y': 6}, 'source_reference': 'campaign:one-minute-affliction',
        'witness_ids': [OWNER, ALLY, FOE], 'valid_through_round': 10, 'answers': {},
        'recovery': {'actor_id': FOE, 'source_ids': [action.source_definition_id], 'recipient_ids': [OWNER],
            'evidence': 'A source-defined ordinary one-minute condition, with an actual native clock.',
            'reality': 'genuine', 'scene': 'ordinary', 'method': 'unknown'}}
    table.record_journey_fact(jid, document, expected_revision=state['revision'])
    engine = load(s.journeys.load(jid))
    c = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    state = s.journey_act(jid, s.journey_state(jid)['revision'], FOE, 'native_activity', {'candidate_id': c.candidate_id})
    state = s.journey_act(jid, state['revision'], FOE, 'native_activity_end')
    assert state['actors'][OWNER]['incapacitated'] == 1
    world_turn(s, jid, OWNER)
    native = load(s.journeys.load(jid))
    assert not any(c.condition_id == 'incapacitated' and c.source_definition_id == 'journey:condition_snapshot'
                   for c in native.state.actors[OWNER].conditions.values())
    options = native.legal_candidates()
    # Printed rule (condition_text 'stunned'): Incapacitated and can't speak; its Speed is unchanged, so movement stays legal.
    assert options and all(c.kind.value in {'END_TURN', 'HOLD_POSITION', 'MOVE'} for c in options)
    assert not any(c.kind.value == 'ACTION' for c in options)
    state = s.journey_act(jid, s.journey_state(jid)['revision'], OWNER, 'native_activity_end')
    if manual_override:
        state = s.journey_act(jid, state['revision'], OWNER, 'incapacitated', {'value': True})
    timed = next(r for r in state['actors'][OWNER]['source_states'][SOURCE_STATE]['records'] if 'deadline' in r)
    left = Fraction(*timed['deadline']) - state['seconds']
    assert left.denominator == 1 and left > 0
    state = s.journey_act(jid, state['revision'], ALLY, 'wait', {'seconds': int(left)})
    assert state['actors'][OWNER]['incapacitated'] == int(manual_override)
    if manual_override:
        state = s.journey_act(jid, state['revision'], OWNER, 'incapacitated', {'value': False})
    result = s.journey_start_combat(jid, state['revision'], {OWNER: 'a', ALLY: 'a', FOE: 'b'})
    cold = reload(tmp_path, result['match_id'])
    assert not any(c.condition_id.removeprefix('condition:typed.') in {'incapacitated', 'stunned'}
                   for c in cold.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('recovery_mode', ['rest', 'Repair', 'Purify', 'Integrate', 'other'])
def test_native_field_strain_crosses_journey_close_and_uses_its_actual_recovery_route(tmp_path, recovery_mode):
    from combat.journey_activity import load, replay_record
    injury = consequence(kind='hidden_injury')
    injury['strain'].update(duration='until its source-defined recovery route is completed',
                           duration_kind='until_removed', recovery_mode=recovery_mode)
    injury['strain']['effects'][0]['duration'] = {'kind': 'until_removed'}
    treatment = procedure('source_treatment', 'treatment', economy='ACTION', cp_cost=1,
        dc=1, modifier=30, skill='Medicine',
        printed_rule='Spend an Action and 1 cultivation point. Succeed on a DC 1 Medicine challenge '
            'to clear only the source-defined Strain that uses this recovery route; no Hit Points are restored.',
        success_effects=[{'type': 'source_recovery', 'mode': recovery_mode, 'applies_to': 'target'}])
    s, table, mid = setup(tmp_path, owner_procedures=[treatment] if recovery_mode != 'rest' else [],
        foe_procedures=[procedure('world_injury', 'consequence', consequence=injury)])
    bundles = list(reload(tmp_path, mid).typed_bundle_documents)
    state = s.journeys.create(bundles, s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {i: 300 for i in (OWNER, ALLY, FOE)}, {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    jid = state['journey_id']
    def native_act(aid, select):
        world_turn(s, jid, aid)
        engine = load(s.journeys.load(jid))
        chosen = next(c for c in engine.legal_candidates() if select(c))
        state = s.journey_state(jid)
        return s.journey_act(jid, state['revision'], aid, 'native_activity', {'candidate_id': chosen.candidate_id})
    native_act(OWNER, lambda c: c.display_name == 'Lotus Recovery Field')
    for aid in (OWNER, ALLY):
        native_act(aid, lambda c: c.kind.value == 'END_TURN')
    engine = load(s.journeys.load(jid))
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Recorded world injury')
    document = {'record_id': 'actual-world-injury', 'subject_id': ALLY, 'subject_name': 'Companion',
        'subject_kind': 'creature', 'position': {'x': 4, 'y': 6}, 'source_reference': 'campaign:actual-minor-poison-injury',
        'witness_ids': [OWNER, ALLY, FOE], 'valid_through_round': 10, 'answers': {},
        'recovery': {'actor_id': FOE, 'source_ids': [action.source_definition_id], 'recipient_ids': [ALLY],
            'evidence': 'Actual source-defined Minor poison injury and its rest-recovered Strain replacement.',
            'reality': 'genuine', 'scene': 'minor_injury_challenge', 'method': 'unknown', 'categories': ['poison']}}
    table.record_journey_fact(jid, document, expected_revision=s.journey_state(jid)['revision'])
    state = native_act(FOE, lambda c: c.source_definition_id == action.source_definition_id and c.target_ids == (ALLY,))
    assert not state.get('native_activity_pending')
    native = load(s.journeys.load(jid))
    assert any(c.data.get('kind') == 'strain' for c in native.state.actors[ALLY].conditions.values())
    gap = 25 - native.state.actors[ALLY].speed_ft  # "Speed becomes 25 feet" is stored as the gap to the base Speed
    assert any(m.target_field == 'speed_ft' and m.value == gap for m in native.state.actors[ALLY].modifiers.values())
    record = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(record)
    assert any(m.value == 25 - replayed.actors[ALLY].speed_ft for m in replayed.actors[ALLY].modifiers.values())
    state = s.journey_act(jid, state['revision'], FOE, 'native_activity_end')
    continued = load(s.journeys.load(jid))
    assert any(c.data.get('kind') == 'strain' for c in continued.state.actors[ALLY].conditions.values())
    assert any(m.target_field == 'speed_ft' and m.value == gap for m in continued.state.actors[ALLY].modifiers.values())
    if recovery_mode == 'rest':
        state = s.journey_act(jid, state['revision'], ALLY, 'long_rest')
        assert any(e['kind'] == 'SOURCE_STRAIN_RECOVERED' and e['actor_id'] == ALLY for e in state['events'])
    else:
        actor = continued.state.actors[OWNER]
        treating = next(a for a in continued.action_catalog.values() if a.display_name == treatment['name'])
        marker = next(c for c in continued.state.actors[ALLY].conditions.values() if c.data.get('kind') == 'strain')
        from combat.ext.d20_rewrite import pool_id
        pool = pool_id(actor, 'cp')
        before = actor.resources[pool]
        document.update(record_id='actual-treatment', source_reference='campaign:printed-' + recovery_mode + '-route',
            recovery={'actor_id': OWNER, 'source_ids': [treating.source_definition_id], 'recipient_ids': [ALLY],
                'evidence': 'The actual source recovery challenge, cost, roll and affected Strain.',
                'reality': 'genuine', 'scene': 'treatment', 'method': 'humble_recovery',
                'gm_consequence_ids': [marker.instance_id]})
        table.record_journey_fact(jid, document, expected_revision=state['revision'])
        state = native_act(OWNER, lambda c: c.source_definition_id == treating.source_definition_id and c.target_ids == (ALLY,))
        current = load(s.journeys.load(jid))
        assert current.state.actors[OWNER].resources[pool] == before - 1
        assert any(e.event_type == 'SOURCE_CONSEQUENCE_RECOVERED' for e in current.events)
        record = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
        assert not any(m.target_field == 'speed_ft' and m.value == gap for m in replay_record(record).actors[ALLY].modifiers.values())
        state = s.journey_act(jid, state['revision'], OWNER, 'native_activity_end')
    result = s.journey_start_combat(jid, state['revision'], {OWNER: 'a', ALLY: 'a', FOE: 'b'})
    cold = reload(tmp_path, result['match_id'])
    assert cold.state.actors[ALLY].current_hp == 60
    assert not any(c.data.get('kind') == 'strain' for c in cold.state.actors[ALLY].conditions.values())
    assert not any(m.target_field == 'speed_ft' and m.value == gap for m in cold.state.actors[ALLY].modifiers.values())


def test_native_journey_field_carries_actual_duration_identity_and_use_into_combat(tmp_path):
    from fractions import Fraction
    from combat.ext.effect_durations import remaining_seconds
    from combat.journey_activity import load, replay_record
    s, table, mid = setup(tmp_path)
    bundles = list(reload(tmp_path, mid).typed_bundle_documents)
    state = s.journeys.create(bundles, s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {i: 300 for i in (OWNER, ALLY, FOE)}, {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    jid = state['journey_id']
    world_turn(s, jid, OWNER)
    native = load(s.journeys.load(jid))
    action = next(a for a in native.action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get('typed', {}).get('source') == FIELD)
    before = dict(native.state.actors[OWNER].resources)
    chosen = next(c for c in native.legal_candidates() if c.source_definition_id == action.source_definition_id)
    state = s.journey_act(jid, s.journey_state(jid)['revision'], OWNER, 'native_activity', {'candidate_id': chosen.candidate_id})
    assert not state.get('native_activity_pending')
    native = load(s.journeys.load(jid))
    active = next(c for c in native.state.actors[OWNER].conditions.values() if c.condition_id == CONDITION)
    actual_deadline = Fraction(state['seconds']) + remaining_seconds(native, active.expires_on,
        source_actor_id=active.source_actor_id)
    zid = active.data['zone_id']
    assert active.data['chosen'].split('\n') == [OWNER]  # Neutral companions are not allies.
    for resource, amount in action.costs:
        assert native.state.actors[OWNER].resources[resource] == before[resource] - amount
    event = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    assert replay_record(event).zones[zid].active
    state = s.journey_act(jid, state['revision'], OWNER, 'native_activity_end')
    assert state['seconds'] == 6
    # Retain the actual native deadline even when earlier creatures took turns
    # before this cast. Closing or entering combat must not renew it.
    exported = state['actors'][OWNER]['source_states'][GENERATE]['records']
    zone_record = next(row for row in exported if row['kind'] == 'zone')
    assert zone_record['deadline'] == [actual_deadline.numerator, actual_deadline.denominator]
    result = s.journey_start_combat(jid, state['revision'], {OWNER: 'a', ALLY: 'a', FOE: 'b'})
    cold = reload(tmp_path, result['match_id'])
    assert cold.state.zones[zid].active
    assert cold.state.zones[zid].trigger_profile.get('duration_deadline')
    assert any(c.condition_id == CONDITION and c.data['zone_id'] == zid
               for c in cold.state.actors[OWNER].conditions.values())
    for resource, amount in action.costs:
        assert cold.state.actors[OWNER].resources[resource] == before[resource] - amount


@pytest.mark.parametrize('suppressed', [False, True])
def test_filter_long_rest_recharges_through_bound_journey_resume(tmp_path, suppressed):
    suppression = consequence(severity=1, steps=())
    suppression['effects'] = [{'type': 'cultivation_suppression', 'effective_cl': 1,
        'foundation_id': FOUNDATION, 'foundation_disabled': 1}]
    s, t, m = setup(tmp_path, expressions=[FILTER],
        owner_procedures=[procedure('encounter_end', 'damage', harm=1000, damage_type='force')],
        foe_procedures=[procedure('venom', 'consequence', consequence=consequence()),
                        procedure('suppression', 'consequence', consequence=suppression)])
    bundles = list(reload(tmp_path, m).typed_bundle_documents)
    state = s.journeys.create(bundles, s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {aid: 300 for aid in (OWNER, ALLY, FOE)})
    jid = state['journey_id']
    bound = s.journey_start_combat(jid, state['revision'], {OWNER: 'a', ALLY: 'a', FOE: 'b'})['match_id']
    turn(t, bound, OWNER)
    use(s, t, bound, 'Lotus Recovery Field', OWNER, {CHOICE: [OWNER, ALLY]})
    field_action = next(a for a in reload(tmp_path, bound).action_catalog.values()
                        if a.owner_id == OWNER and a.display_name == 'Lotus Recovery Field')
    daily = next(resource for resource, _ in field_action.costs if resource.startswith('resource:uses.'))
    assert reload(tmp_path, bound).state.actors[OWNER].resources[daily] == 0
    turn(t, bound, FOE)
    record(s, t, bound, FOE, 'Recorded venom', [OWNER], categories=['poison'])
    use(s, t, bound, 'Recorded venom', OWNER)
    assert conditions(reload(tmp_path, bound), OWNER, FILTER_USED)
    if suppressed:
        record(s, t, bound, OWNER, 'Lotus Recovery Field', [ALLY], key='field-corruption', exclusions=['hide_rot'])
        record(s, t, bound, FOE, 'Recorded suppression', [OWNER], key='suppression')
        use(s, t, bound, 'Recorded suppression', OWNER)
    turn(t, bound, OWNER)
    record(s, t, bound, OWNER, 'Lotus Recovery Field', [ALLY], key='field-corruption', exclusions=['hide_rot'])
    record(s, t, bound, OWNER, 'Recorded encounter end', [FOE], scene='ordinary', method='unknown')
    use(s, t, bound, 'Recorded encounter end', FOE)
    assert reload(tmp_path, bound).state.terminal_result is not None
    state = s.journey_state(jid)
    state = s.journey_resume(jid, state['revision'])
    assert any(json.loads(raw)['condition_id'] == FILTER_USED
               for raw in state['actors'][OWNER]['encounter_snapshot']['conditions'].values())
    if suppressed:
        def rest_act(aid, kind, payload=None):
            current = s.journey_state(jid)
            return s.journey_act(jid, current['revision'], aid, kind, payload or {})
        rest_facts = {'actor_id': OWNER,
            'source_ids': [SHELTER], 'recipient_ids': [OWNER, ALLY],
            'evidence': 'A genuine willing shared medicine rest after the encounter.',
            'reality': 'genuine', 'scene': 'shared_rest', 'method': 'shared_medicine'}
        declared = s.journeys.record_world_fact(jid, s.journey_state(jid)['revision'], {
            'source': 'system:recovery.shared_rest', 'subject': OWNER, 'kind': 'recovery_scene',
            'scope': jid, 'value': rest_facts, 'expires_at': state['seconds'] + 7200, 'readers': [ALLY]})
        rest_act(OWNER, 'start_shared_rest', {'scene_receipt': declared['fact_consent_admission'][-1]['receipt_id'],
            'selected_ids': [ALLY]})
        rest_act(ALLY, 'join_shared_rest')
        rest_act(OWNER, 'finish_shared_rest')
        state = s.journey_state(jid)
        assert state['actors'][ALLY].get('encounter_snapshot', {}).get('temporary_hp', 0) == 0
    s.journey_act(jid, state['revision'], OWNER, 'long_rest')
    current = s.journey_state(jid)
    assert current['seconds'] == (32400 if suppressed else 28800)
    assert current['actors'][OWNER]['resources'][daily] == 1
    assert not any(json.loads(raw)['condition_id'] == FILTER_USED
                   for raw in current['actors'][OWNER]['encounter_snapshot']['conditions'].values())


def test_root_declined_recipient_commits_no_payment_or_economy(tmp_path):
    s, t, m = setup(tmp_path, initial=1)
    prompts = use(s, t, m, 'Lotus-Root Recovery', ALLY,
                  {'choice:needle.lotus_root_consent': None})
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 1
    assert e.state.actors[OWNER].bonus_action_available
    assert e.state.actors[ALLY].temporary_hp == 0
    assert any('Lotus-Root Recovery' in str(p) for p in prompts)


def test_explicit_foundation_suppression_blocks_generation_and_active_features(tmp_path):
    rule = consequence()
    rule['effects'] = [{'type': 'cultivation_suppression', 'effective_cl': 1,
                       'foundation_id': FOUNDATION, 'foundation_disabled': 1}]
    rule.update(steps=[], step_effects=[], step_replacement_effects=[])
    s, t, m = setup(tmp_path, foe_procedures=[procedure('suppression', 'consequence', consequence=rule)])
    turn(t, m, FOE)
    record(s, t, m, FOE, 'Recorded suppression', [OWNER])
    use(s, t, m, 'Recorded suppression', OWNER)
    record(s, t, m, FOE, 'Recorded poison save', [OWNER], key='suppressed-save', scene='ordinary', method='unknown', categories=['poison'])
    use(s, t, m, 'Recorded poison save', OWNER)
    e = reload(tmp_path, m)
    assert e.state.actors[OWNER].resources[DEW] == 0
    turn(t, m, OWNER)
    e = reload(tmp_path, m)
    assert not any(c.display_name in ('Lotus-Root Recovery', 'Lotus Recovery Field') for c in e.legal_candidates())


def test_unselected_expressions_are_inert_and_no_procedure_without_source(tmp_path):
    s, t, m = setup(tmp_path, initial=1, owner_procedures=[procedure('medicine', modifier=30)])
    e = reload(tmp_path, m)
    owned = next(r for r in e.typed_passive_rows[OWNER] if r.get('block') == 'mud_lotus_native')['owned']
    assert not set(owned) & {REFINED, FILTER}
    assert SHELTER in owned
    assert not any(c.display_name == 'Recorded medicine' for c in e.legal_candidates())


def test_owner_http_source_procedure_requires_authority_and_full_source(tmp_path):
    import zipfile
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    document = sheet([RESERVE], foundation={'foundation_id': FOUNDATION, 'stage': 'Awakened'})
    package = tmp_path / 'portable_characters' / PROJECT / 'current.zip'
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    app = create_app(Settings.from_env(APP, tmp_path))
    app.state.agent_seats.background = False
    row = procedure('external_medicine', modifier=3, skill='Medicine')
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            url = f'/api/tabletop/characters/{PROJECT}/procedures'
            assert (await client.post(url, json=row)).status_code in (401, 403)
            headers = {'x-foundry-token': token}
            invalid = {**row, 'source_reference': ''}
            assert (await client.post(url, json=invalid, headers=headers)).status_code == 422
            empty_treatment = {**row, 'dc': None}
            assert (await client.post(url, json=empty_treatment, headers=headers)).status_code == 422
            result = await client.post(url, json=row, headers=headers)
            assert result.status_code == 200, result.text
            native_bundle = compile_character(app.state.combat._factory_owner_sheet(PROJECT), actor_id=OWNER)
            arena = app.state.combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
            journey = app.state.combat.journeys.create([native_bundle], arena,
                {OWNER: {'x': 3, 'y': 6}}, {OWNER: 300})
            jid = journey['journey_id']
            world_url = f'/api/tabletop/journeys/{jid}/world-facts'
            facts_url = f'/api/tabletop/journeys/{jid}/facts'
            assert (await client.post(world_url, json={})).status_code in (401, 403)
            assert (await client.post(facts_url, json={})).status_code in (401, 403)
            assert (await client.post(world_url, json={}, headers=headers)).status_code == 400
            assert (await client.post(facts_url, json={}, headers=headers)).status_code == 400
            declaration = {'source': 'system:recovery.shared_rest', 'subject': OWNER, 'kind': 'recovery_scene',
                'scope': jid, 'expires_at': 7200, 'readers': [], 'value': {
                    'actor_id': OWNER, 'source_ids': [source_id(OWNER, row['id'])], 'recipient_ids': [OWNER],
                    'scene': 'shared_rest', 'method': 'medicine', 'reality': 'genuine',
                    'evidence': 'The table owner records the actual medicine rest.'}}
            published = await client.post(world_url, json={'revision': 0, 'declaration': declaration}, headers=headers)
            assert published.status_code == 200, published.text
            # The public actor command cannot impersonate table-owner authority.
            denied = await client.post(f'/api/combat/journeys/{jid}/act', headers=headers,
                json={'revision': 1, 'actor_id': OWNER, 'kind': 'declare_fact', 'payload': declaration})
            assert denied.status_code == 400, denied.text
    run_asgi(exercise())
    saved = app.state.combat._factory_owner_sheet(PROJECT)
    assert saved['source_procedures'][0]['source_reference'] == row['source_reference']
    compiled = compile_character(saved, actor_id=OWNER)
    assert any(a['display_name'] == row['name'] for a in compiled['action_catalog'])




@pytest.mark.parametrize('corrupt', [False, True])
def test_private_correction_and_wrong_source_do_not_grant_bonus(tmp_path, corrupt):
    from combat.target_knowledge import recent_events
    s, t, m = setup(tmp_path, expressions=[REFINED], initial=1)
    doc = record(s, t, m, OWNER, 'Lotus-Root Recovery', [ALLY], witness_ids=[OWNER])
    e = reload(tmp_path, m)
    assert not any(x['event_type'] == 'TABLE_FACT_RECORDED' and x['payload']['fact']['record_id'] == 'event'
                   for x in recent_events(e, e.state.actors[FOE], e.events))
    changed = copy.deepcopy(doc)
    changed['recovery']['reality'] = 'staged'
    changed['recovery']['exclusions'] = ['preserve_corruption'] if corrupt else []
    t.record_fact(m, changed, expected_state_version=e.state.state_version)
    e = reload(tmp_path, m)
    # Staging denies new Dew/the Refined bonus, not an otherwise legal base
    # spend of old Dew. Corruption-preserving use is denied before payment.
    use(s, t, m, 'Lotus-Root Recovery', ALLY)
    e = reload(tmp_path, m)
    assert e.state.actors[ALLY].temporary_hp == (0 if corrupt else 6)
    assert e.state.actors[OWNER].resources[DEW] == (1 if corrupt else 0)
    invalid = copy.deepcopy(changed)
    invalid['recovery']['actor_id'] = FOE
    invalid['witness_ids'] = [OWNER, FOE]
    with pytest.raises(Exception, match='action owned'):
        t.record_fact(m, invalid, expected_state_version=e.state.state_version)


def test_exact_base_cannot_admit_the_native_source_procedure(tmp_path):
    """Fail-before control at the native producer, using the exact assigned tree.

    The existing sparse Git-tree loader imports real baseline classes and rules
    in a fresh process. No second project copy or engine patch is introduced.
    The positive acquisition/roll/replay regressions exercise the head route.
    """
    import subprocess
    import sys
    script = '''
import sys
from pathlib import Path
from tests.wall_height_stock_capture import revision_sources
scratch = Path(sys.argv[1])
root = revision_sources('8bd818c78df011c2b67145d8e33975468c3e6a75', scratch)
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
service = TabletopService(CombatService(root, scratch / 'data'), scratch / 'data')
try:
    service.record_procedure('source-owner', {})
except AttributeError:
    print('BASELINE_MISSING_NATIVE_SOURCE_PRODUCER')
else:
    raise AssertionError('The pinned base unexpectedly admitted the new producer.')
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tmp_path)],
        cwd=APP, text=True, capture_output=True, timeout=300)
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
    assert 'BASELINE_MISSING_NATIVE_SOURCE_PRODUCER' in result.stdout


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_stock_replay_exact_assigned_base(tmp_path, monkeypatch, request, seed):
    # Explicit selector only, so fixing one native regression never repeats all
    # six fights. Reuse the unchanged real stock guard, with task-owned evidence.
    if not any('::test_stock_replay_exact_assigned_base' in str(arg) for arg in request.config.args):
        pytest.skip('Opt in with this exact selector to run the six stock guards.')
    from tests import test_a2_glass_stock as stock
    from pathlib import Path
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock, 'EVIDENCE', Path('/var/tmp/auto-audit/fix/MGR-T14-sol-seam-mud-lotus-2-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
