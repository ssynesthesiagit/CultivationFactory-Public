"""Printed weapon coating follows compiled delivery variants across table reloads."""
import copy
import pytest

from combat.ext.ice_fracture import BITTER, T
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload
from tests.test_auto116_ice import setup, asked, FOE_CELL
from tests.test_sph_ice_r1 import kit, damage
from tests.cw2_service_support import seal


@pytest.mark.parametrize('weapon,delivery', [
    ('gong_jian', None),
    ('bi_shou', '#thrown'),
])
def test_coated_weapon_delivery_survives_table_reload(tmp_path, weapon, delivery):
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit(weapon), bundle_transform=setup)
    engine = combat._load_session(mid).engine
    # Use the compiler's printed name, rather than defining a substitute attack.
    base = next(a for a in engine.action_catalog.values()
                if a.owner_id == OWNER and a.parameters.get('typed', {}).get('source') ==
                'tianxia.mortal.weapon.' + weapon and '.weapon.' in a.source_definition_id
                and '#' not in a.source_definition_id)
    source = base.source_definition_id
    prompts = settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
                     {'choice:needle.bitter_coat': source})
    assert asked(prompts, 'choice:needle.bitter_coat')
    saved = reload(tmp_path, mid)
    assert next(c for c in saved.state.actors[OWNER].conditions.values()
                if c.condition_id == BITTER).data['strike'] == source
    action = saved.action_catalog[source + (delivery or '')]
    prompts = settle(table, mid, candidate(combat, mid, action.display_name, target=FOE).candidate_id,
                     {'choice:needle.bitter_type': 'PIERCING'})
    assert asked(prompts, 'choice:needle.bitter_type')
    assert damage(reload(tmp_path, mid))[-1].payload['damage_type'] == 'PIERCING'


@pytest.mark.parametrize('natural', [False, True])
def test_coated_strike_variant_survives_table_reload(tmp_path, natural):
    def prepare(bundles):
        setup(bundles)
        bundle = bundles[0]
        base = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
        if natural:
            base['source_definition_id'] += '.natural.test_claw'
            base['display_name'] = 'Claw attack'
            bundle['action_catalog'].append(base)
            bundle['actor_template']['action_ids'].append(base['source_definition_id'])
        variant = copy.deepcopy(base)
        variant['source_definition_id'] += '#test_delivery'
        variant['display_name'] = 'Alternate strike'
        variant['parameters']['typed']['variant_of'] = base['source_definition_id']
        bundle['action_catalog'].append(variant)
        bundle['actor_template']['action_ids'].append(variant['source_definition_id'])
        seal(bundle)
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 bundle_transform=prepare)
    name = 'Claw attack' if natural else 'Unarmed Strike'
    source = candidate(combat, mid, name, target=FOE).source_definition_id
    settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
           {'choice:needle.bitter_coat': source})
    saved = reload(tmp_path, mid)
    assert next(c for c in saved.state.actors[OWNER].conditions.values() if c.condition_id == BITTER).data['strike'] == source
    prompts = settle(table, mid, candidate(combat, mid, 'Alternate strike', target=FOE).candidate_id,
                     {'choice:needle.bitter_type': 'COLD'})
    assert asked(prompts, 'choice:needle.bitter_type')
    assert damage(reload(tmp_path, mid))[-1].payload['damage_type'] == 'COLD'
