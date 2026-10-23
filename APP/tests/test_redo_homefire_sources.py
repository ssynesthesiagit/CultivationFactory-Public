"""Native cause classification and recovery use current, source-bound conditions."""
import pytest
from combat.canonical import canonical_sha256
from combat.fact_consent_admission import digest
from combat.ext.forged_exhaustion import level
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.h1_support import sheet

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH, RECOVERY, WELCOME = [BASE + s for s in ('kindled_hearth', 'homefire_recovery', 'flame_that_welcomes_all')]


def controls(bundles):
    effects = {
        'Exhaustion': [{'type': 'exhaustion', 'applies_to': 'target', 'amount': 2}],
        'Smoke penalty': [{'type': 'condition', 'applies_to': 'target', 'condition': 'mark.smoke_penalty',
                          'expires_on': 'UNTIL_REMOVED', 'condition_data': {'speed_delta': -5, 'label': 'Smoke: movement reduced by 5 feet'}}],
        'Force damage': [{'type': 'damage', 'applies_to': 'target', 'flat': 40, 'damage_types': ['force']}],
        'Fire damage': [{'type': 'damage', 'applies_to': 'target', 'flat': 40, 'damage_types': ['fire']}],
        'Drop to zero': [{'type': 'damage', 'applies_to': 'target', 'flat': 506, 'damage_types': ['force']}],
        'Recover one level': [{'type': 'exhaustion', 'applies_to': 'target', 'amount': -1}],
        'Erase recovery usage': [{'type': 'remove_condition', 'applies_to': 'target', 'condition': 'homefire_recovery_used'}],
        'Outright death': [{'type': 'damage', 'applies_to': 'target', 'flat': 1200, 'damage_types': ['force']}],
    }
    for b in bundles:
        b['actor_template']['maximum_hp'] = 500
        for name, tree in effects.items():
            sid = 'action:hearth-test.' + b['actor_id'] + '.' + name.replace(' ', '_')
            b['action_catalog'].append({'source_definition_id': sid, 'display_name': name, 'owner_id': b['actor_id'],
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE', 'range_ft': 120,
                'parameters': {'free_primary': True, 'typed': {'source': sid,
                    'numbers': {'cl': 18, 'pb': 6, 'key_mod': 2, 'save_dc': 18},
                    'duration': {'kind': 'instant'}, 'effects': tree}}})
            b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def fight(tmp_path, *, dc=18, kind=None, recovery=True, extra=None):
    foe = sheet([], cl=18, name='Intruder')
    if kind:
        foe['identity']['creature_type'] = kind

    def transform(bundles):
        controls(bundles)
        if extra is not None:
            extra(bundles)

    return fixture(tmp_path, [], cl=18, owner_pb=6, owner_dc=dc, foe_sheet=foe,
                   owner_features=[HEARTH, WELCOME] + ([RECOVERY] if recovery else []), bundle_transform=transform)


def classify(combat, tmp_path, mid, subject, condition, kind, cause):
    engine = reload(tmp_path, mid)
    combat.world_fact(mid, engine.state.state_version, {
        'source': RECOVERY, 'subject': subject, 'kind': kind,
        'scope': digest([engine.state.match_id, condition.instance_id]),
        'value': {'condition_instance_id': condition.instance_id, 'cause': cause},
        'expires_at': 1000, 'readers': [subject]})


def cast(combat, table, mid, benefit=None):
    return settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id,
        choices={'choice:needle.welcome_recipients': [ALLY],
                 'choice:needle.homefire_recovery': benefit})


def test_cure_removes_one_eligible_current_level_and_preserves_unsourced_exhaustion(tmp_path):
    combat, table, mid = fight(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Exhaustion', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    c = next(c for c in before.state.actors[ALLY].conditions.values() if c.condition_id.endswith('.exhaustion'))
    classify(combat, tmp_path, mid, ALLY, c, 'exhaustion_cause', ['travel', 'unknown'])
    cast(combat, table, mid, 'exhaustion')
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert level(ally) == 1
    held = next(c for c in ally.conditions.values() if c.condition_id.endswith('.exhaustion'))
    assert held.data['causes'] == ['unknown']
    assert any(c.condition_id.endswith('.homefire_recovery_used') for c in ally.conditions.values())
    settle(table, mid, candidate(combat, mid, 'Erase recovery usage', target=ALLY).candidate_id)
    assert any(c.condition_id.endswith('.homefire_recovery_used')
               for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())


def test_other_cure_cannot_leave_historical_travel_levels_available_to_homefire(tmp_path):
    combat, table, mid = fight(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Exhaustion', target=ALLY).candidate_id)
    held = next(c for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values()
                if c.condition_id.endswith('.exhaustion'))
    classify(combat, tmp_path, mid, ALLY, held, 'exhaustion_cause', ['travel', 'unknown'])
    settle(table, mid, candidate(combat, mid, 'Recover one level', target=ALLY).candidate_id)
    prompts = cast(combat, table, mid, 'temp_hp')
    recovery = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.homefire_recovery')
    assert 'exhaustion' not in {o['id'] for o in recovery['choice']['options']}
    ally = reload(tmp_path, mid).state.actors[ALLY]
    assert level(ally) == 1
    assert next(c for c in ally.conditions.values() if c.condition_id.endswith('.exhaustion')).data['causes'] == ['unknown']


def test_gm_classifies_exact_existing_environmental_penalty_then_recipient_ends_it(tmp_path):
    combat, table, mid = fight(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Smoke penalty', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    condition = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id.endswith('smoke_penalty'))
    classify(combat, tmp_path, mid, ALLY, condition, 'ordinary_environmental_penalty', 'smoke')
    cast(combat, table, mid, 'penalty:' + condition.instance_id)
    engine = reload(tmp_path, mid)
    assert condition.instance_id not in engine.state.actors[ALLY].conditions


def test_welcome_cost_concentration_recipient_defenses_and_first_damage_per_round(tmp_path):
    combat, table, mid = fight(tmp_path)
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Flame That Welcomes All')
    assert action.economy.value == 'ACTION' and dict(action.costs)['resource:core.qi'] == 8
    assert owner.resources['resource:core.qi'] == 92 and owner.concentration is not None
    zone = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile', {}).get('welcoming_flame'))
    assert zone.trigger_profile['shape'] == 'cylinder' and zone.trigger_profile['height_ft'] == 40
    assert zone.radius_cells == 8 and zone.duration_rounds == 10 and zone.concentration_link
    assert ally.armor_class + engine._ac_modifier(ally) == 15
    assert owner.armor_class + engine._ac_modifier(owner) == 14
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Fire damage', target=ALLY).candidate_id,
           choices={'choice:needle.hearth_shield': None})
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == 486
    settle(table, mid, candidate(combat, mid, 'Force damage', target=ALLY).candidate_id,
           choices={'choice:needle.hearth_shield': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == 446
    assert engine.state.actors[OWNER].reaction_available


def test_initial_recipient_owns_the_recovery_choice_without_lower_feature(tmp_path):
    combat, table, mid = fight(tmp_path, recovery=False)
    prompts = cast(combat, table, mid, 'temp_hp')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 12
    assert any(p['context']['reactor_id'] == ALLY
               and p['context']['reaction_source_id'] == 'choice:needle.homefire_recovery' for p in prompts)


@pytest.mark.parametrize('dc,failed', [(50, 1), (1, 0)])
def test_threshold_save_and_next_turn_expiry_from_native_creature_kind(tmp_path, dc, failed):
    combat, table, mid = fight(tmp_path, dc=dc, kind='undead')
    cast(combat, table, mid)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    held = next(c for c in engine.state.actors[FOE].conditions.values()
                if c.condition_id.endswith('.hospitality_threshold'))
    assert held.data['failed'] == failed
    assert bool(held.data['rule'].get('no_reactions')) == bool(failed)
    assert held.expires_on == 'START_OF_TARGET_NEXT_TURN'
    if failed:
        before = engine.state.actors[FOE].position
        row = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
                   and (c.destination.x, c.destination.y) == (5, 6))
        settle(table, mid, row.candidate_id)
        assert reload(tmp_path, mid).state.actors[FOE].position == before


@pytest.mark.parametrize('name,stable', [('Drop to zero', True), ('Outright death', False)])
def test_no_guest_dies_alone_excludes_outright_death(tmp_path, name, stable):
    combat, table, mid = fight(tmp_path)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, name, target=ALLY).candidate_id,
           choices={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': None})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    if stable:
        assert ally.current_hp == 0 and ally.life_state == 'STABLE' and ally.temporary_hp == 12
    else:
        from combat.ext.life_state import is_deceased
        assert is_deceased(ally) and ally.temporary_hp == 0
