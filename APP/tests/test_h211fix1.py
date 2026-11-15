"""HUNT211 #1/#3: printed rules through table commits and cold reload/replay.

Demon Mark: "Failed Save: It bears your Demon Mark"; "once per turn when
you damage it, add Proficiency Bonus to the damage". Daemonic Augment:
"add Proficiency Bonus to one damage roll". Neither creates damage on a
marking save, even when the target is the hunt's two-HP mounted Warhorse.

Mount card: "mount a willing creature within 5 feet"; "You move with your
mount while riding it." F5's rooftop rider at (11,6,z3) cannot ride a horse
at (10,5,z0). A supported steed starts on the same roof as its rider.
"""
import pytest

from combat import ext
from combat.ext import mounts
from combat.factory_compiler import _attach, compile_character
from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark
from tests.cw2_service_support import seal
from tests.h1_support import ROOT, sheet
from tests.test_auto103_daemonic import cycle, sow
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

P = 'TAL_DAEMONIC_CULTIVATION_'
AUGMENTED = 'Demon Mark + Daemonic Augment: Bonus Damage'
ESSENCE = 'resource:named.devoured_essence'


def rider_sheet():
    document = sheet([], cl=18)
    document['spheres_and_talents'] = {
        'sphere_record_ids': ['tianxia.sphere.beastmastery'],
        'learned_talent_record_ids': [],
        'automatic_sphere_component_record_ids': ['BEASTMASTERY_BASE_RIDER_PACKAGE']}
    return document


@pytest.mark.parametrize('augmented', [False, True], ids=['plain', 'augmented'])
@pytest.mark.parametrize('fails', [False, True], ids=['successful-save', 'failed-save'])
def test_mark_cannot_damage_or_defeat_a_two_hp_mount_on_activation(tmp_path, monkeypatch, augmented, fails):
    document = sheet([P + 'DEMON_SEED', P + 'DEMON_MARK'], cl=18)
    document['spheres_and_talents'].update(
        sphere_record_ids=['tianxia.sphere.daemonic_cultivation'],
        automatic_sphere_component_record_ids=[P + 'DAEMONIC_AUGMENT'])
    owner_bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})

    def two_hp_horse(bundles):
        horse = next(b for b in bundles[2]['summons'] if b['summon']['group'] == 'mount.warhorse')
        horse['actor_template']['maximum_hp'] = 2
        horse['actor_template']['saving_throws']['CHA'] = -100 if fails else 100
        seal(horse)
        seal(bundles[2])

    ext.effects()
    def rolls(engine, roll, intent):
        if 'SAVE' in str(roll.reason).upper():
            return {'source_id': 'test:h211.save', 'operation': 'replace', 'natural_result': 1 if fails else 20}
        if roll.actor_id == OWNER and 'ATTACK' in str(roll.reason).upper():
            return {'source_id': 'test:h211.hit', 'operation': 'replace', 'natural_result': 15}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [rolls])
    combat, table, mid = fixture(tmp_path, [], cl=18, seed='H211-PHANTOM-MARK',
        owner_bundle=owner_bundle, foe_sheet=rider_sheet(), bundle_transform=two_hp_horse,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 1, 'y': 1}, FOE: {'x': 5, 'y': 6}})
    sow(combat, table, mid)
    cycle(table, mid, OWNER)
    before = reload(tmp_path, mid)
    horse = next(a for a in before.state.actors.values() if a.summon and a.summon['group'] == 'mount.warhorse')
    assert horse.current_hp == 2 and mounts.mount_of(before, before.state.actors[FOE]) is horse
    start = before.state.event_sequence
    balance = before.state.actors[OWNER].resources.get(ESSENCE, 0)
    settle(table, mid, candidate(combat, mid, AUGMENTED if augmented else 'Demon Mark', target=horse.entity_id).candidate_id)
    cold = reload(tmp_path, mid)
    events = [e for e in cold.events if e.sequence > start]
    target = cold.state.actors[horse.entity_id]
    assert target.current_hp == 2 and target.active
    assert target.reaction_available == horse.reaction_available
    assert cold.state.actors[FOE].resources == before.state.actors[FOE].resources
    assert mounts.mount_of(cold, cold.state.actors[FOE]) is target
    assert bears_mark(target, OWNER, 'Demon Mark') is fails
    assert not [e for e in events if e.event_type in {'DAMAGE_ROLLED', 'DAMAGE_COMMITTED', 'ACTOR_DEFEATED'}]
    assert cold.state.actors[OWNER].resources.get(ESSENCE, 0) == balance
    assert not [e for e in events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER]
    assert not [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.actor_id != OWNER]
    # The typed save records the saving creature in actor_id and names the
    # marking action as its source (plain or augment-variant id both carry
    # the Demon Mark record id); the event has no target ids.
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == horse.entity_id
               and 'DEMON_MARK' in e.source_definition_id for e in events)


@pytest.mark.parametrize('z,low_ceiling', [(0, False), (3, False), (3, True)],
                         ids=['ground', 'hunt-roof-15ft', 'roof-without-room-for-steed'])
def test_rooftop_saddle_shares_elevation_after_table_dodge_and_cold_reload(tmp_path, z, low_ceiling):
    document = rider_sheet()
    document['spheres_and_talents']['learned_talent_record_ids'].append('TAL_BEASTMASTERY_BEAST_TAMER')
    bundle = compile_character(document, actor_id=OWNER)
    arena = {'stable_id': 'battlefield:h211-rooftop', 'display_name': 'H211 rooftop',
             'width_squares': 18, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': [],
             'roof_surfaces': [{'id': 'hunt-roof', 'height_ft': 15,
                 'cells': [{'x': x, 'y': y} for x in range(9, 15) for y in range(4, 10)]}]}
    if low_ceiling:
        # A Medium rider/wolf fits in five feet; the Large horse's ten-foot
        # volume does not. It must stay available on the ground, unmounted.
        arena['terrain_regions'] = [{'terrain_type': 'BLOCKED', 'base_altitude_ft': 20, 'height_ft': 5,
                                    'movement_cost': 0, 'cells': arena['roof_surfaces'][0]['cells']}]
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, battlefield=arena,
        positions={OWNER: {'x': 11, 'y': 6, 'z': z}, ALLY: {'x': 1, 'y': 1}, FOE: {'x': 3, 'y': 1}})
    def assert_pair(engine):
        rider = engine.state.actors[OWNER]
        horse = next(a for a in engine.state.actors.values() if a.summon and a.summon['group'] == 'mount.warhorse')
        wolf = next(a for a in engine.state.actors.values() if a.summon and a.summon['group'] == 'beast0.wolf')
        assert rider.position.z == wolf.position.z == z
        assert horse.active
        assert horse.position.z == (0 if low_ceiling else z)
        if low_ceiling:
            assert mounts.mount_of(engine, rider) is None
            assert mounts.rider_of(engine, horse) is None
        else:
            assert set(engine._actor_cells(rider)) < set(engine._actor_cells(horse))
            assert mounts.mount_of(engine, rider) is horse
            assert mounts.rider_of(engine, horse) is rider
        assert engine.grid.volume_legal(horse.position, footprint=engine._footprint(horse))
        assert not horse.position.z or engine.grid.roof_supported(horse.position, engine._footprint(horse))
        return horse
    assert_pair(combat._load_session(mid).engine)
    if low_ceiling:
        assert not any(a.display_name == 'Mount: Dodge' for a in combat._load_session(mid).engine.legal_candidates())
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    else:
        settle(table, mid, candidate(combat, mid, 'Mount: Dodge').candidate_id)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    horse = assert_pair(fresh.engine)
    if not low_ceiling:
        assert any('dodg' in c.condition_id.lower() for c in horse.conditions.values())
    assert fresh.verify()['status'] == 'PASS'
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_damage_roll_bonus_requires_immediate_damage_but_independent_damage_survives():
    # General compiler contract, independent of talent identity. Deferred dice
    # are also future damage, while a modifier that grants its own packet keeps it.
    later = {'type': 'extra_damage', 'dice': {'count': 1, 'sides': 8}, 'deferred': True}
    effects = [{'type': 'save', 'on_fail': [later], 'on_success': []}]
    bonus = {'type': 'extra_damage', 'formula': 'pb', 'evidence': 'add Proficiency Bonus to one damage roll'}
    assert _attach(effects, [bonus], 'use') == effects
    packet = {'type': 'damage', 'flat': 5, 'damage_types': ['fire']}
    assert _attach(effects, [packet], 'use') == effects + [packet]
    nested = [{'type': 'delivery', 'effects': [packet]}]
    assert _attach(nested, [bonus], 'use') == nested + [bonus]
    deferred_wrapper = [{'type': 'delivery', 'deferred': True, 'effects': [packet]}]
    assert _attach(deferred_wrapper, [bonus], 'use') == deferred_wrapper
    immediate = [{'type': 'save', 'on_fail': [packet], 'on_success': []}]
    attached = _attach(immediate, [bonus], 'use')
    assert attached[0]['on_fail'][0] == packet
    assert attached[0]['on_fail'][1]['formula'] == 'pb'
    assert attached[0]['on_success'] == []


@pytest.mark.parametrize('kind,no_damage,damaging', [
    ('weapon', False, True), ('unarmed', False, True),
    ('cultivation_ranged', False, False), ('weapon', True, False)])
def test_bonus_follows_implicit_weapon_dice_but_not_a_condition_only_attack(kind, no_damage, damaging):
    attack = {'type': 'attack', 'attack_kind': kind, 'no_damage': no_damage,
              'on_hit': [{'type': 'condition', 'condition': 'prone'}]}
    bonus = {'type': 'extra_damage', 'formula': 'pb', 'evidence': 'add Proficiency Bonus to one damage roll'}
    attached = _attach([attack], [bonus], 'use')
    assert len(attached) == 1
    additions = [row for row in attached[0]['on_hit'] if row['type'] == 'extra_damage']
    assert len(additions) == int(damaging)
    if additions:
        assert additions[0]['damage_bonus_packet']
