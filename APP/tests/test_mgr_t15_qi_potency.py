"""Qi potency through imported source-backed sheets, table commits and cold replay."""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

P = 'tianxia.path.qi_cultivation.feature.qi_technique_potency'
RAY = 'FIRE_TAL_SCORCHING_RAY_ART'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.qiang', 'name': 'Qiang (Spear)', 'quantity': 1}]}}


def source_bundle(*, potency=True, primary='Qi', score=14, forged=False, key='INT'):
    doc = sheet(([P] if potency else []) + [RAY], cl=17, primary=primary, score=score, kit=KIT, key=key)
    modifier = (score - 10) // 2
    doc['identity']['proficiency_bonus'] = 6
    stats = doc['ability_scores_and_statistics']
    for ability in stats['abilities']:
        if ability['ability'] != key:
            ability.update(score=14, modifier=2)
    stats['technique_attack_bonus'] = 6 + modifier
    stats['technique_save_dc'] = 14 + modifier
    stats['primary_resource']['maximum'] = max(34, 17 * modifier)
    if forged:
        doc['forged_techniques'] = [{
            'name': 'Cultivated Ray Strike', 'technique_id': 'forged.qi-potency-ray-strike',
            'action_type': 'action', 'base_form': {'form_id': 'strike', 'display_name': 'Strike'},
            'primary_sphere_effect': {'talent_id': RAY}, 'augments': [], 'drawbacks': [],
            'cp_cost': {'final': 4}}]
    return compile_character(doc, actor_id=OWNER)


def fight(tmp_path, *, adjacent=False, **kw):
    adjacent = adjacent or kw.get("forged", False)
    bundle = source_bundle(**kw)
    return fixture(tmp_path, [], cl=17, owner_bundle=bundle,
                   positions={OWNER:{'x':3,'y':6}, ALLY:{'x':3,'y':7},
                              FOE:{'x':4 if adjacent else 6,'y':6}}, seed='QI-POTENCY-NATIVE')


def rolls(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER]


def receipts(engine):
    return engine.state.actors[OWNER].turn_flags.get('damage_activation_round_receipts', {})


@pytest.mark.parametrize('score,modifier', [(14,2),(6,-2),(10,0)])
def test_native_projectiles_share_one_signed_potency_roll_and_replay(tmp_path, score, modifier):
    combat, table, mid = fight(tmp_path, score=score)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    row = candidate(combat, mid, 'Scorching Ray Art', target=FOE)
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 4
    damage = rolls(engine)
    assert len(damage) >= 2
    modifiers = [e.payload['modifier'] for e in damage]
    assert modifiers == [modifier] + [0] * (len(damage)-1)
    used = list(receipts(engine).values())
    assert len(used) == 1 and used[0] == {'choice':'technique','used':True}


def test_forged_technique_primary_receives_potency_and_replays(tmp_path):
    combat, table, mid = fight(tmp_path, forged=True)
    settle(table, mid, candidate(combat, mid, 'Cultivated Ray Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert list(receipts(engine).values()) == [{'choice':'technique','used':True}]
    assert [e.payload['modifier'] for e in rolls(engine)] == [2]


def test_ordinary_weapon_and_non_qi_sources_do_not_get_receipts(tmp_path):
    combat, table, mid = fight(tmp_path, adjacent=True)
    engine = combat._load_session(mid).engine
    weapons = [a for a in engine.action_catalog.values() if a.owner_id==OWNER and
               (a.parameters.get('typed') or {}).get('weapon') and 'Qiang' in a.display_name]
    assert weapons
    name = weapons[0].display_name
    settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id)
    assert not receipts(reload(tmp_path, mid))


def test_charisma_qi_key_is_distinct_from_other_ability_modifiers(tmp_path):
    combat, table, mid = fight(tmp_path, key='CHA', score=18)
    settle(table, mid, candidate(combat, mid, 'Scorching Ray Art', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    damage = rolls(engine)
    assert len(damage) >= 2
    assert [e.payload['modifier'] for e in damage] == [4] + [0] * (len(damage)-1)
