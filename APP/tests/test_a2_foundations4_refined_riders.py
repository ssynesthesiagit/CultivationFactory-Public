"""Refined Foundation riders that raise one number of a base conversion by one Proficiency Bonus.

Refined: Hidden Vitality Return (Blackblood Return), Refined: Verdant Sinews (Bend-Without-Breaking Guard) and
Refined: Wings Remember Ground (Light-Body Recovery) each add the same PB to the same spend: no second Reaction,
no second resource spend, and nothing at all unless the expression was selected (or, for Wings Remember Ground,
owned).
"""
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, settle, candidate, reload, turn, sealed_native_attack

PB = 4


def setup(tmp_path, foundation, resource, *, stage='Refined', held=1, maxhp=500, hostile_mod=40):
    document = sheet([], kit={'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}})
    document['foundation'] = {'foundation_id': foundation, 'stage': stage,
        'resource': {'name': resource, 'resource_id': 'tianxia.resource.foundation.' + foundation,
                     'maximum': 1, 'current': held}}
    owner = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('typed', {}).get('weapon'):
            action['attack_bonus'] = 100
            action['parameters']['typed']['attack_bonus'] = 100
    sealed_native_attack(owner, 'Owner hit', attack_bonus=100, modifier=0, attacks=1)
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)

    def seal(bundles):
        sealed_native_attack(bundles[2], 'Hostile hit', modifier=hostile_mod, attack_bonus=100, attacks=1)
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = maxhp
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    return fixture(tmp_path, [], owner_bundle=owner, ask=True, seed='RW191', bundle_transform=seal, foe_position={'x': 5, 'y': 6})


def use(combat, table, mid, name, target=None, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices=choices or {})


def logs(engine, feature):
    return [e.payload.get('log') for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == feature]


# ------------------------------------------------------------------------------------------------ Blackblood Return
B = 'foundation.true_blackblood_physique_v0_2C.'


def _return(tmp_path, select):
    combat, table, mid = setup(tmp_path, 'true_blackblood_physique_v0_2C', 'Blackblood Pressure')
    if select:
        use(combat, table, mid, 'Foundation expression: Refined: Hidden Vitality Return')
    use(combat, table, mid, 'Owner hit', target=FOE, choices={'reaction:typed.' + B + 'blackblood_return': 'USE'})
    return reload(tmp_path, mid)


def test_hidden_vitality_return_adds_one_more_pb_to_the_same_spend(tmp_path):
    engine = _return(tmp_path, True)
    assert f'adding {2 * PB} damage' in logs(engine, B + 'blackblood_return')[-1]
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == B + 'blackblood_return']) == 1


def test_return_without_the_expression_adds_only_base_pb(tmp_path):
    engine = _return(tmp_path, False)
    assert f'adding {PB} damage' in logs(engine, B + 'blackblood_return')[-1]


# ------------------------------------------------------------------------------------------------ Weak Reed guard
R = 'foundation.weak_reed_tendons_v0_2B.'


def _reed_guard(tmp_path, select):
    combat, table, mid = setup(tmp_path, 'weak_reed_tendons_v0_2B', 'Reed Flex')
    if select:
        use(combat, table, mid, 'Foundation expression: Refined: Verdant Sinews')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile hit', target=OWNER, choices={'reaction:typed.' + R + 'bend_without_breaking_guard': 'USE'})
    return reload(tmp_path, mid)


def test_verdant_sinews_reduces_the_hit_by_one_more_pb(tmp_path):
    engine = _reed_guard(tmp_path, True)
    assert f'reduce damage by {2 * PB}' in logs(engine, R + 'bend_without_breaking_guard')[-1]


def test_reed_guard_without_the_expression_reduces_by_base_pb(tmp_path):
    engine = _reed_guard(tmp_path, False)
    assert f'reduce damage by {PB}' in logs(engine, R + 'bend_without_breaking_guard')[-1]


# ------------------------------------------------------------------------------------------------ White Crane
def _light_body(tmp_path, stage):
    combat, table, mid = setup(tmp_path, 'white_crane_cloud_step_v0_2B', 'Crane Breath', stage=stage)
    use(combat, table, mid, 'Light-Body Recovery')
    return reload(tmp_path, mid).state.actors[OWNER].temporary_hp


def test_wings_remember_ground_adds_pb_to_light_body_recovery(tmp_path):
    awakened = _light_body(tmp_path / 'a', 'Awakened')
    assert _light_body(tmp_path / 'r', 'Refined') == awakened + PB


def test_preview_quotes_refined_damage_before_consent(tmp_path):
    """Ask-me preview must quote the same damage the spend applies (review fix 2)."""
    combat, table, mid = setup(tmp_path, 'true_blackblood_physique_v0_2C', 'Blackblood Pressure')
    use(combat, table, mid, 'Foundation expression: Refined: Hidden Vitality Return')
    prompts = use(combat, table, mid, 'Owner hit', target=FOE, choices={'reaction:typed.' + B + 'blackblood_return': 'USE'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith('blackblood_return'))
    assert f'Add {2 * PB} damage' in prompt['summary']
    assert f'It adds {2 * PB} damage' in prompt['table_note']
