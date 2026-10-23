"""Native Mud Lotus acquisition, source admission, table commits and cold replay.

Synthetic public sheets/scenario sources only; no historical/private fixtures.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from combat import table_advance as ta, table_levelup as lu
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.fact_consent_admission import combat_records, digest
from combat.gate5_service import CombatService
from tests.grow5_support import PID, QI, TALENTS, service, choices, _reach
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, reload, candidate, settle

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = 'mud_lotus_dantian_v0_2A'
SOURCE = 'foundation.' + FOUNDATION + '.mud_lotus_reserve'
HASH = 'a40624d6fbcfd45eff7769250b7dd82155b2faa5077d9640561f81208a7e35de'
CP = 'resource:core.qi'
PRESSURES = ('poison', 'disease', 'rot', 'polluted_water', 'sickness_exhaustion',
             'humble_origin_shame', 'low_status_shame')
EXPRESSIONS = ('humble_recovery', 'living_water_cleansing', 'lotus_root_medicine',
               'poison_disease_treatment', 'polluted_living_environment', 'shared_medicine',
               'recovery_after_hardship', 'growth_through_mud')


@pytest.fixture(autouse=True)
def public_dependencies():
    # Literal dynamic dependencies for the public exporter.
    assert (ROOT / 'combat/rules/feature_blocks.d/foundations3.json').is_file()
    assert (ROOT / 'authority/typed_mechanics/reviewed_final.d/foundations3.json').is_file()
    assert (ROOT / 'non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json').is_file()
    assert (ROOT / 'non_sphere_authority/authority/Foundation_Trait_Reference_v0_6.json').is_file()
    assert (ROOT / 'non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json').is_file()
    assert (ROOT / 'non_sphere_authority/authority/open_ended_compatibility_resolver.py').is_file()
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    # Public CI substitutes copyright-controlled prose; hashes are verified in
    # the local source audit, not against the public substitute.
    assert isinstance(texts[SOURCE], str) and texts[SOURCE]


def acquire(root, foundation=FOUNDATION, *, learn_life=False):
    """Select the published Foundation at its real CL5 table-acquisition gate."""
    s = service(root)
    _reach(s, 5)
    if learn_life:
        s._spheres_cache['tianxia.sphere.life'] = 'Life'
        s.add_advancement(PID, 'sphere', 'tianxia.sphere.life')
    view = s.advancement(PID)
    row = next(r for r in view['level_up']['foundation']['options'] if r['id'] == foundation)
    assert row['legal']
    payload = choices(view, 3)
    saved = ta.normalized(s.buttons.get(PID).get('advancement'))
    baseline = s.combat._factory_owner_sheet(PID, apply_table=False)
    control = ta.apply(baseline, lu.prepare(s.combat._factory_owner_sheet(PID), saved, payload, TALENTS))
    s.level_up(PID, {**payload, 'foundation_id': foundation})
    cold = service(root)
    sheet = cold.combat._factory_owner_sheet(PID)
    assert sheet == cold.combat._factory_owner_sheet(PID)
    return sheet, control


def seal(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def pressure(bundle, ability='CON', poisoned=False):
    """A real damaging save, without any fabricated qualifying tag by default."""
    aid = bundle['actor_id']
    source = 'action:test.mud_lotus.' + aid.rsplit('-', 1)[-1]
    save = {'type': 'save', 'ability': ability, 'dc': 100,
            'on_fail': [{'type': 'damage', 'flat': 3, 'damage_types': ['force'],
                         'applies_to': 'target'}], 'on_success': []}
    if poisoned:
        save['on_fail'].append({'type': 'condition', 'condition': 'poisoned',
            'applies_to': 'target', 'duration': {'kind': 'until_end_of_next_turn'}})
    bundle['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Scenario pressure',
        'owner_id': aid, 'economy': 'NONE', 'resolution_kind': 'TYPED',
        'target_kind': 'ANY_CREATURE', 'range_ft': 60,
        'parameters': {'free_primary': True, 'typed': {'source': source,
            'range_ft': 60, 'numbers': {'pb': 3, 'key_mod': 3, 'save_dc': 100},
            'duration': {'kind': 'instant'}, 'riders': [], 'effects': [save]}}})
    bundle['actor_template']['action_ids'].append(source)
    seal(bundle)
    return source


def scenario(tmp_path, *, foundation=FOUNDATION, ability='CON', friendly=False, poisoned=False):
    sheet, control = acquire(tmp_path / 'acquisition', foundation)
    bundle = compile_character(sheet, actor_id=OWNER, reaction_plan={'ask': True})
    sources = {}
    def delivery(bundles):
        provider = 1 if friendly else 2
        sources['action'] = pressure(bundles[provider], ability, poisoned)
    combat, table, mid = fixture(tmp_path / 'fight', [], owner_bundle=bundle,
        bundle_transform=delivery, seed='REDOMUDLOTUS1-' + ability, named=True)
    root = tmp_path / 'fight'
    turn(table, mid, ALLY if friendly else FOE)
    return combat, table, mid, root, sources['action'], sheet, control


def declare(combat, mid, subject, source_actor, action, kind, value, *, readers=None):
    engine = combat._load_session(mid).engine
    payload = {'source': SOURCE, 'subject': subject, 'kind': kind,
        'scope': digest([mid, kind, subject, source_actor, action]),
        'value': {'source_actor_id': source_actor, 'source_definition_id': action, **value},
        'expires_at': 3600, 'readers': [subject] if readers is None else readers}
    result = combat.world_fact(mid, engine.state.state_version, payload)
    assert result['status'] == 'COMMITTED', result
    return payload


def use_pressure(combat, table, mid, root, expected):
    before = reload(root, mid)
    actor = before.state.actors[OWNER]
    hp, resources = actor.current_hp, dict(actor.resources)
    # Decline sibling Foundation responses instead of removing acquired rows.
    settle(table, mid, candidate(combat, mid, 'Scenario pressure', target=OWNER).candidate_id,
           choices={})
    after = reload(root, mid)
    event = next(e for e in reversed(after.events) if e.event_type == 'SAVE_ROLLED')
    assert event.actor_id == OWNER and event.payload['mode'] == expected
    assert event.payload['success'] is False  # Advantage is not immunity.
    assert after.state.actors[OWNER].current_hp == hp - 3  # No passive reduction.
    assert after.state.actors[OWNER].resources == resources  # Reserve generates nothing.
    assert not any('mud_lotus' in key for key in after.state.actors[OWNER].turn_flags)
    return after


def test_native_acquisition_cp_sheet_combat_rebuild_and_pb_scaling(tmp_path):
    sheet, control = acquire(tmp_path)
    resource = sheet['ability_scores_and_statistics']['primary_resource']
    plain = control['ability_scores_and_statistics']['primary_resource']
    assert resource['maximum'] == plain['maximum'] + 3
    assert resource['maximum'] - resource['build_state_current'] == plain['maximum'] - plain['build_state_current']
    bundle = compile_character(sheet, actor_id=OWNER)
    assert bundle == compile_character(service(tmp_path).combat._factory_owner_sheet(PID), actor_id=OWNER)
    actor = bundle['actor_template']
    assert next(r['maximum'] for r in actor['resources'] if r['resource_id'] == CP) == resource['maximum']
    assert sheet['foundation']['resource']['current'] == 0
    assert sheet['spheres_and_talents'] == control['spheres_and_talents']
    grown = lu.advance_sheet(sheet, [{'cl': cl} for cl in (6, 7, 8, 9)], preview=True)
    plain_grown = lu.advance_sheet(control, [{'cl': cl} for cl in (6, 7, 8, 9)], preview=True)
    assert grown['ability_scores_and_statistics']['primary_resource']['maximum'] == plain_grown['ability_scores_and_statistics']['primary_resource']['maximum'] + 4


@pytest.mark.parametrize('ability', ['CON', 'WIS'])
@pytest.mark.parametrize('category', PRESSURES)
def test_authorized_hostile_pressure_commits_repeats_and_cold_replays(tmp_path, ability, category):
    combat, table, mid, root, action, _, _ = scenario(tmp_path, ability=ability)
    declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': category})
    use_pressure(combat, table, mid, root, 'ADVANTAGE')
    use_pressure(CombatService(ROOT, root), table, mid, root, 'ADVANTAGE')


@pytest.mark.parametrize('category', ['dry_fire', 'sterile_purity', 'direct_violence', 'social_pride', 'unrelated'])
def test_authorized_out_of_scope_pressure_is_ordinary(tmp_path, category):
    combat, table, mid, root, action, _, _ = scenario(tmp_path, ability='WIS')
    declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': category})
    use_pressure(combat, table, mid, root, 'NORMAL')


@pytest.mark.parametrize('ability,friendly,foundation', [
    ('DEX', False, FOUNDATION), ('WIS', True, FOUNDATION),
    ('CON', False, 'moon_mirror_still_water_v0_2B'),
])
def test_pressure_requires_ability_hostility_and_correct_foundation(tmp_path, ability, friendly, foundation):
    combat, table, mid, root, action, _, _ = scenario(tmp_path, ability=ability, friendly=friendly, foundation=foundation)
    if foundation == FOUNDATION:
        declare(combat, mid, OWNER, ALLY if friendly else FOE, action, 'mud_lotus_pressure', {'category': 'poison'})
    else:
        with pytest.raises((FoundryError, ValueError)):
            declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': 'poison'})
    use_pressure(combat, table, mid, root, 'NORMAL')


def test_absent_private_wrong_source_and_revoked_pressure_do_not_qualify(tmp_path):
    combat, table, mid, root, action, _, _ = scenario(tmp_path)
    use_pressure(combat, table, mid, root, 'NORMAL')
    declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': 'poison'}, readers=[])
    engine = reload(root, mid)
    assert combat_records(engine, engine.state.actors[ALLY], source=SOURCE) == []
    # Reserve has no awareness requirement: a GM classification private from
    # other creatures must still protect its affected subject.
    use_pressure(combat, table, mid, root, 'ADVANTAGE')
    payload = declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': 'poison'})
    from combat.fact_consent_admission import NativeFactSession, declare as actor_declare
    with pytest.raises(ValueError):
        actor_declare(NativeFactSession(reload(root, mid)), OWNER, payload)
    with pytest.raises((FoundryError, ValueError)):
        declare(combat, mid, OWNER, ALLY, action, 'mud_lotus_pressure', {'category': 'poison'})
    use_pressure(combat, table, mid, root, 'ADVANTAGE')
    declare(combat, mid, OWNER, FOE, action, 'mud_lotus_pressure', {'category': 'unrelated'})
    use_pressure(combat, table, mid, root, 'NORMAL')


@pytest.mark.parametrize('ability', ['CON', 'WIS'])
def test_actual_poison_condition_save_still_gets_advantage(tmp_path, ability):
    combat, table, mid, root, _, _, _ = scenario(tmp_path, ability=ability, poisoned=True)
    use_pressure(combat, table, mid, root, 'ADVANTAGE')


@pytest.mark.parametrize('forged', [False, True])
def test_expression_admission_all_printed_categories_permissions_only(tmp_path, forged):
    from combat.ext.mud_lotus_reserve import alignment_receipt
    sheet, control = acquire(tmp_path / 'acquisition', learn_life=True)
    technique_id = 'LIFE_BASE_MEND_THE_PULSE'
    if forged:
        native = service(tmp_path / 'acquisition')
        result = native.forge(PID, {'name': 'Shared Medicine Ward', 'base_form': 'ward',
            'primary_talent_id': technique_id, 'secondary_talent_ids': [],
            'augment_ids': [], 'drawback_ids': []}, save=True)
        technique_id = result['technique']['technique_id']
        sheet = service(tmp_path / 'acquisition').combat._factory_owner_sheet(PID)
    bundle = compile_character(sheet, actor_id=OWNER, reaction_plan={'ask': True})
    water = next(a for a in bundle['action_catalog']
                 if a.get('parameters', {}).get('typed', {}).get('source') == technique_id)
    source = water['source_definition_id']
    combat, table, mid = fixture(tmp_path / 'fight', [], owner_bundle=bundle, seed='MUD-EXPRESSION')
    root = tmp_path / 'fight'
    engine = reload(root, mid)
    assert alignment_receipt(engine, engine.state.actors[OWNER], source) is None
    for expression in EXPRESSIONS:
        declare(combat, mid, OWNER, OWNER, source, 'mud_lotus_expression',
                {'expression': expression, 'preserves_rot': 0})
        engine = reload(root, mid)
        receipt = alignment_receipt(engine, engine.state.actors[OWNER], source)
        assert receipt['expression'] == expression
        assert receipt['source_id'] == technique_id
        assert alignment_receipt(engine, engine.state.actors[ALLY], source) is None
    before = reload(root, mid)
    hp = before.state.actors[ALLY].current_hp
    cp = before.state.actors[OWNER].resources[CP]
    settle(table, mid, candidate(combat, mid, water['display_name'], target=ALLY).candidate_id, choices={})
    engine = reload(root, mid)
    receipts = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == SOURCE and e.payload.get('receipt_kind') == 'mud_lotus_alignment']
    assert receipts and receipts[-1].payload['source_id'] == technique_id
    cost = sum(n for resource, n in water['costs'] if resource == CP)
    assert engine.state.actors[OWNER].resources[CP] == cp - cost
    assert engine.state.actors[ALLY].current_hp >= hp
    assert engine.state.actors[OWNER].resource_maximums[CP] == before.state.actors[OWNER].resource_maximums[CP]
    declare(combat, mid, OWNER, OWNER, source, 'mud_lotus_expression',
            {'expression': 'growth_through_mud', 'preserves_rot': 1})
    engine = reload(root, mid)
    assert alignment_receipt(engine, engine.state.actors[OWNER], source) is None
    declare(combat, mid, OWNER, OWNER, source, 'mud_lotus_expression',
            {'expression': 'unrelated', 'preserves_rot': 0})
    engine = reload(root, mid)
    assert alignment_receipt(engine, engine.state.actors[OWNER], source) is None
    # No Foundation action acquisition or new sphere/talent access.
    assert sheet['spheres_and_talents'] == control['spheres_and_talents']
    control_bundle = compile_character(control, actor_id=OWNER)
    def sources(b):
        return {a.get('parameters', {}).get('typed', {}).get('source')
                for a in b['action_catalog'] if not a.get('parameters', {}).get('typed', {}).get('source', '').startswith('foundation.')}
    assert sources(bundle) - ({technique_id} if forged else set()) == sources(control_bundle)


def test_alignment_rejects_unowned_outside_sphere_source_and_forged_expression(tmp_path):
    from combat.ext.mud_lotus_reserve import alignment_receipt
    sheet, _ = acquire(tmp_path / 'acquisition', learn_life=True)
    bundle = compile_character(sheet, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path / 'fight', [], owner_bundle=bundle,
        bundle_transform=lambda bundles: pressure(bundles[2]), seed='MUD-REJECTION')
    root = tmp_path / 'fight'
    engine = reload(root, mid)
    action = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.display_name == 'Scenario pressure')
    with pytest.raises((FoundryError, ValueError)):
        declare(combat, mid, OWNER, FOE, action, 'mud_lotus_expression',
                {'expression': 'shared_medicine', 'preserves_rot': 0})
    engine = reload(root, mid)
    own_action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and (a.parameters.get('typed') or {}).get('source', '').startswith('foundation.'))
    with pytest.raises((FoundryError, ValueError)):
        declare(combat, mid, OWNER, OWNER, own_action.source_definition_id, 'mud_lotus_expression',
                {'expression': 'shared_medicine', 'preserves_rot': 0})
    water = next(a for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and (a.parameters.get('typed') or {}).get('source') == 'LIFE_BASE_MEND_THE_PULSE')
    with pytest.raises((FoundryError, ValueError)):
        declare(combat, mid, OWNER, OWNER, water.source_definition_id, 'mud_lotus_expression',
                {'expression': 'invented_benefit', 'preserves_rot': 0})
    assert alignment_receipt(reload(root, mid), engine.state.actors[OWNER], water.source_definition_id) is None
