"""Cautery signed/wounded arithmetic through public synthetic table fixtures."""
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload

CAUTERY = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'
CONSENT = 'reaction:typed.' + CAUTERY
SEED = 'MGR-T14-s0'


def owner_bundle(ash=1, con=8):
    # Synthetic owned reaction: no private Foundation record or published-section
    # validation is needed to exercise the real table settlement and arithmetic.
    bundle = compile_character(sheet([], score=con), actor_id=OWNER,
                               reaction_plan={'ask': True})
    bundle['actor_template']['resources'].append(
        {'resource_id': 'resource:foundation.funeral_ash', 'initial': ash, 'maximum': 1})
    bundle['typed_reactions'].append({
        'block': 'generic', 'kind': 'damaged', 'feature_id': CAUTERY,
        'name': 'Synthetic Cautery', 'ask': True, 'range_ft': None,
        'costs': [{'resource_id': 'resource:foundation.funeral_ash', 'amount': 1}],
        'numbers': {'pb': 2, 'key_mod': (con - 10) // 2},
        'effects': [{'type': 'damage_modifier', 'applies_to': 'self',
                     'formula': 'pb+key', 'damage_types': [], 'ability': 'none',
                     'condition': 'none', 'distance_ft': 0, 'on': '',
                     'duration': 'instant'}]})
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return bundle


def _hit(tmp_path, maximum_hp, consents, *, con=8):
    def delivery(bundles):
        source = 'action:test.cautery.qualifying_attack'
        row = {'source_definition_id': source, 'display_name': 'Cautery qualifying attack',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
            'parameters': {'typed': {'source': source, 'range_ft': 60,
                'numbers': {'pb': 2, 'key_mod': -1, 'save_dc': 30, 'attack_bonus': 100},
                'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'count': 1,
                    'on_hit': [{'type': 'damage', 'flat': 8, 'damage_types': ['fire'],
                               'applies_to': 'target'}]}],
                'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 8}}
        bundles[2]['action_catalog'].append(row)
        bundles[2]['actor_template']['action_ids'].append(source)
        bundles[0]['actor_template']['maximum_hp'] = maximum_hp
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [], seed=SEED, owner_bundle=owner_bundle(con=con),
                                 bundle_transform=delivery)
    for take in consents:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Cautery qualifying attack',
               target=OWNER).candidate_id, {CONSENT: 'first'} if take else {})
        turn(table, mid, OWNER)
    return reload(tmp_path, mid)


def test_cautery_at_full_health_reduces_by_the_base_sum_only(tmp_path):
    engine = _hit(tmp_path, 60, [True])
    rows = [e.payload for e in engine.events if e.event_type == 'REACTION_RESOLVED'
            and e.source_definition_id == CAUTERY]
    assert rows and rows[-1]['reduction'] == 1


def _damage(tmp_path):
    engine = _hit(tmp_path / 'probe', 200, [False])
    return next(e.payload['hp_damage'] for e in engine.events
                if e.event_type == 'DAMAGE_COMMITTED'
                and e.source_definition_id == 'action:test.cautery.qualifying_attack')


def test_cautery_wounded_bonus_is_added_before_the_signed_base_is_clamped(tmp_path):
    d = _damage(tmp_path)
    engine = _hit(tmp_path / 'run', 2*d-1, [False, True], con=4)
    rows = [e.payload for e in engine.events if e.event_type == 'REACTION_RESOLVED'
            and e.source_definition_id == CAUTERY]
    assert rows[-1]['reduction'] == 1


def test_cautery_exactly_half_health_is_not_below_half(tmp_path):
    d = _damage(tmp_path)
    engine = _hit(tmp_path / 'run', 2*d, [False, True])
    rows = [e.payload for e in engine.events if e.event_type == 'REACTION_RESOLVED'
            and e.source_definition_id == CAUTERY]
    assert rows[-1]['reduction'] == 1
