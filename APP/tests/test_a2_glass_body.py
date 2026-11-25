"""Glass body benefits through service/table intent commits and cold replay."""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.test_auto2_glass import BASES, foe_turn, conditions
from tests.worker2_support import OWNER, FOE, ALLY, fixture, candidate, settle, reload, sealed_native_attack
from combat.ext.glass_body import CONDITION


def prepare(bundles):
    for bundle in bundles[1:]:
        add_action(bundle, 'Physical packet', [{'type': 'damage', 'applies_to': 'target', 'flat': 9,
                                               'damage_types': ['bludgeoning'], 'duration': 'instant'}])
        add_action(bundle, 'Melee blow', [{'type': 'attack', 'attack_kind': 'weapon_melee', 'count': 1,
                                         'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['fire'],
                                                     'applies_to': 'target', 'duration': 'instant'}]}],
                   typed={'weapon': {'kind': 'melee', 'ability_modifier': 2}, 'range_ft': 5,
                          'numbers': {'pb': 4, 'attack_bonus': 40, 'save_dc': 16, 'cl': 15}})
        seal(bundle)


def body(tmp_path, walking=False, **kwargs):
    return fixture(tmp_path, BASES + ['TAL_GLASS_GLASS_BONE_GUARD'] +
                   (['TAL_GLASS_WALKING_PANE_BODY'] if walking else []),
                   foe_position={'x': 4, 'y': 5}, bundle_transform=prepare, **kwargs)


@pytest.mark.parametrize('walking,selected', [(False, ['ac']), (False, ['reduce']),
                                             (False, ['mark']), (True, ['ac', 'reduce']),
                                             (True, ['ac', 'mark']), (True, ['reduce', 'mark'])])
def test_guard_offers_all_three_benefits_and_walking_allows_two(tmp_path, walking, selected):
    combat, table, mid = body(tmp_path, walking)
    before = reload(tmp_path, mid)
    base_ac = before._ac_modifier(before.state.actors[OWNER])
    prompts = settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
                     {'choice:needle.glass_body_guard': selected})
    engine = reload(tmp_path, mid)
    guard = conditions(engine, OWNER, CONDITION)
    assert len(guard) == 1 and set(guard[0].data['benefits']) == set(selected)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_body_guard')
    assert {o['id'] for o in prompt['choice']['options']} == {'ac', 'reduce', 'mark'}
    assert engine._ac_modifier(engine.state.actors[OWNER]) == base_ac + int('ac' in selected)


@pytest.mark.parametrize('native', [False, True])
def test_reduction_spends_once_per_round_across_cold_reload(tmp_path, native):
    def packets(bundles):
        prepare(bundles)
        if native:
            sealed_native_attack(bundles[2], 'Native physical packet',
                                 modifier=9, damage_type='BLUDGEONING', attacks=2)

    combat, table, mid = fixture(tmp_path, BASES + ['TAL_GLASS_GLASS_BONE_GUARD', 'TAL_GLASS_WALKING_PANE_BODY'],
                                  bundle_transform=packets, foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
           {'choice:needle.glass_body_guard': ['ac', 'reduce']})
    foe_turn(table, mid)
    before = reload(tmp_path, mid)
    hp = before.state.actors[OWNER].current_hp
    pb = conditions(before, OWNER, CONDITION)[0].data['pb']
    if native:
        settle(table, mid, candidate(combat, mid, 'Native physical packet', target=OWNER).candidate_id,
               {'choice:needle.refraction_response': None})
        engine = reload(tmp_path, mid)
        rolled = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
                  and e.source_definition_id.endswith('.native_physical_packet')]
        assert len(rolled) == 2
        assert hp - engine.state.actors[OWNER].current_hp == sum(e.payload['total'] for e in rolled) - pb
        return
    for expected in (9 - pb, 9):
        settle(table, mid, candidate(combat, mid, 'Physical packet', target=OWNER).candidate_id,
               {'choice:needle.refraction_response': None})
        engine = reload(tmp_path, mid)
        assert hp - engine.state.actors[OWNER].current_hp == expected
        hp = engine.state.actors[OWNER].current_hp


def test_declining_body_guard_keeps_no_benefit(tmp_path):
    combat, table, mid = body(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
           {'choice:needle.glass_body_guard': None})
    assert not conditions(reload(tmp_path, mid), OWNER, CONDITION)


def test_guard_mark_ai_uses_only_hostile_melee_hitter(tmp_path, monkeypatch):
    # Both sides can hit the owner; computer guard selection must not mark its ally.
    def ai_setup(bundles):
        prepare(bundles)
        owner = bundles[0]
        owner['action_catalog'] = [a for a in owner['action_catalog']
                                   if (a.get('parameters', {}).get('typed') or {}).get('source')
                                   == 'GLASS_BASE_TEMPER_GLASS_SURFACE']
        owner['actor_template']['action_ids'] = [a['source_definition_id'] for a in owner['action_catalog']]
        seal(owner)

    combat, table, mid = fixture(tmp_path, BASES + ['TAL_GLASS_GLASS_BONE_GUARD', 'TAL_GLASS_WALKING_PANE_BODY'],
                                  foe_position={'x': 4, 'y': 5}, bundle_transform=ai_setup, ask=False,
                                  modes={OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    # Configure the normal local policy, rather than replacing the controller.
    action = candidate(combat, mid, 'Temper Glass Surface').source_definition_id
    preferred = combat.policies.fallback().model_copy(update={'action_priorities': {action: 2000}})
    monkeypatch.setattr(combat.policies, 'for_actor', lambda aid: (preferred, True))
    settle(table, mid, '', auto=True)
    assert set(conditions(reload(tmp_path, mid), OWNER, CONDITION)[0].data['benefits']) == {'reduce', 'mark'}
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, 'Melee blow', target=OWNER).candidate_id,
           {'choice:needle.refraction_response': None})
    engine = reload(tmp_path, mid)
    from combat.ext.glass_refraction import marked
    assert marked(engine.state.actors[FOE], OWNER)
    assert not marked(engine.state.actors[ALLY], OWNER)
    assert not marked(engine.state.actors[OWNER], OWNER)


def test_heavy_armor_excludes_the_ac_option(tmp_path):
    combat, table, mid = body(tmp_path, True, owner_ac=10, owner_kit={
        'starting_kit': {'items': [{'item_id': 'tianxia.mortal.armor.imperial_plate_battle_dress', 'quantity': 1}]}})
    prompts = settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
                     {'choice:needle.glass_body_guard': ['reduce', 'mark']})
    guard_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_body_guard')
    assert {o['id'] for o in guard_prompt['choice']['options']} == {'reduce', 'mark'}
    assert set(conditions(reload(tmp_path, mid), OWNER, CONDITION)[0].data['benefits']) == {'reduce', 'mark'}


def test_benefits_end_with_tempering_and_retempering_replaces_the_selection(tmp_path):
    from tests.worker2_support import turn
    combat, table, mid = body(tmp_path, True)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
           {'choice:needle.glass_body_guard': ['ac', 'mark']})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
           {'choice:needle.glass_body_guard': ['reduce']})
    assert set(conditions(reload(tmp_path, mid), OWNER, CONDITION)[0].data['benefits']) == {'reduce'}
    for _ in range(11):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    assert not conditions(reload(tmp_path, mid), OWNER, CONDITION)
