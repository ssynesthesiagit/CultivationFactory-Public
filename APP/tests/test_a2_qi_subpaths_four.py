"""Qi subpaths: real service/table intents, cold reload and mechanical replay."""
import json

import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.cw2_service_support import seal, add_action

P = 'tianxia.subpath.qi.'
WIND = P + 'storm_soul_cultivator.feature.wind_walker'
GALE = P + 'storm_soul_cultivator.feature.gale_burst'
LIVING = P + 'calligraphy_cultivator.feature.living_character'
GREAT = P + 'calligraphy_cultivator.feature.great_character'
HEAVEN = P + 'calligraphy_cultivator.feature.heaven_s_script'


def setup(bundles):
    for b in bundles:
        b['actor_template']['maximum_hp'] = 1000
        seal(b)


def conditions(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id.endswith('.' + name)]


def damage(engine, source, actor):
    return sum(int(e.payload.get('hp_damage') or 0) for e in engine.events
               if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == source and actor in e.target_ids)


@pytest.mark.parametrize('cl,count', [(3, 2), (11, 3), (17, 4)])
@pytest.mark.parametrize('dc,denied', [(100, True), (-100, False)])
def test_living_flame_scaling_save_and_reaction_duration(tmp_path, cl, count, dc, denied):
    combat, table, mid = fixture(tmp_path, [], owner_features=[LIVING], cl=cl, owner_dc=dc,
                                bundle_transform=setup, seed=f'QI4-FLAME-{cl}-{dc}')
    cast = candidate(combat, mid, 'Living Character: Character of Flame', target=FOE)
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    assert damage(engine, cast.source_definition_id, FOE) > 0
    assert bool(conditions(engine.state.actors[FOE], 'reaction_denied')) == denied
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99
    rolls = [r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.actor_id == OWNER]
    assert any(r.expression.startswith(f'{count}d6') for r in rolls)
    assert damage(engine, cast.source_definition_id, ALLY) == 0
    assert not any(e.event_type == 'GM_ADJUDICATION_REQUIRED' and e.source_definition_id == cast.source_definition_id for e in engine.events)
    turn(table, mid, FOE)
    assert not conditions(reload(tmp_path, mid).state.actors[FOE], 'reaction_denied')


@pytest.mark.parametrize('feature,name,dice,sides', [
    (GREAT, 'Great Character: Great Character of Storm', 5, 8),
    (HEAVEN, 'Heaven’s Script: Heaven’s Fire', 10, 8),
])
@pytest.mark.parametrize('dc,fail', [(100, True), (-100, False)])
def test_printed_creature_wide_characters_apply_only_the_chosen_option(tmp_path, feature, name, dice, sides, dc, fail):
    combat, table, mid = fixture(tmp_path, [], owner_features=[feature], cl=18, owner_dc=dc,
                                bundle_transform=setup, seed=f'QI4-AREA-{feature}-{dc}')
    cast = candidate(combat, mid, name, at=(6, 6))
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    # These choices explicitly say each creature; unlike chosen harmful recipients,
    # this printed mandatory area includes an ally standing within the blast.
    area_rolls = [r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.actor_id == OWNER]
    assert len(area_rolls) == 1
    assert area_rolls[0].expression.startswith(f'{dice}d{sides}')
    area_events = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == cast.source_definition_id]
    assert len(area_events) == 3
    assert {target for e in area_events for target in e.target_ids} == {OWNER, FOE, ALLY}
    expected_damage = area_rolls[0].total if fail else area_rolls[0].total // 2
    assert all(e.payload['rolled_or_pending_damage'] == expected_damage
               and e.payload['hp_damage'] == expected_damage for e in area_events)
    assert not conditions(engine.state.actors[FOE], 'deafened')
    assert not conditions(engine.state.actors[FOE], 'prone')
    assert bool(conditions(engine.state.actors[FOE], 'reaction_denied')) == (feature == HEAVEN or fail)
    assert not any(e.event_type == 'GM_ADJUDICATION_REQUIRED' and e.source_definition_id == cast.source_definition_id for e in engine.events)
    if feature == HEAVEN:
        turn(table, mid, FOE)
        assert bool(conditions(reload(tmp_path, mid).state.actors[FOE], 'reaction_denied')) == fail
    else:
        turn(table, mid, FOE)
        assert not conditions(reload(tmp_path, mid).state.actors[FOE], 'reaction_denied')


def test_manual_mountain_reminder_is_self_contained_in_reloaded_table_feed(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_features=[GREAT], cl=18,
                                bundle_transform=setup, seed='QI4-MOUNTAIN-MANUAL')
    cast = candidate(combat, mid, 'Great Character: Great Character of Mountain')
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    reminder = next(e.payload['rider'] for e in engine.events
                    if e.event_type == 'GM_RIDER' and e.source_definition_id == cast.source_definition_id)
    assert '15-foot-wide, 10-foot-high, 1-foot-thick' in reminder
    assert 'AC 17' in reminder and '5 × your Qi Cultivation CL' in reminder
    assert 'Damage Threshold equal to your Proficiency Bonus' in reminder
    assert 'moves to the nearest legal side of its choice' in reminder
    # This is the same live presentation projection used by the table after a
    # cold session load, so source lookup and hidden compiled data cannot mask it.
    table_text = json.dumps(combat.presentation(mid), ensure_ascii=False)
    assert reminder in table_text


@pytest.mark.parametrize('cl,ac,thp', [(3, 1, 0), (11, 1, 4), (17, 2, 4)])
def test_living_shield_scales_does_not_stack_and_expires_on_source_turn(tmp_path, cl, ac, thp):
    def prepare(b):
        setup(b)
        # A second caster owns the same actual authority ability.
    combat, table, mid = fixture(tmp_path, [], owner_features=[LIVING], ally_talents=[LIVING],
                                cl=cl, owner_pb=4, bundle_transform=prepare, seed=f'QI4-SHIELD-{cl}')
    cast = candidate(combat, mid, 'Living Character: Character of Shield', target=ALLY)
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    shields = conditions(engine.state.actors[ALLY], 'qi_character_shield')
    assert len(shields) == 1 and shields[0].data['ac'] == ac
    assert engine._ac_modifier(engine.state.actors[ALLY]) == ac
    assert engine.state.actors[ALLY].temporary_hp == thp
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Living Character: Character of Shield', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert len(conditions(engine.state.actors[ALLY], 'qi_character_shield')) == 2
    assert engine._ac_modifier(engine.state.actors[ALLY]) == ac
    turn(table, mid, OWNER)
    assert conditions(reload(tmp_path, mid).state.actors[ALLY], 'qi_character_shield')
    turn(table, mid, ALLY)
    assert not conditions(reload(tmp_path, mid).state.actors[ALLY], 'qi_character_shield')


def test_mend_recipient_allowance_survives_reload_and_resets_each_actual_turn(tmp_path):
    def prepare(b):
        setup(b)
        add_action(b[0], 'Second Mend', [{'type': 'qi_character_mend', 'applies_to': 'ally'}], typed={'numbers': {'cl': 17, 'pb': 4, 'key_mod': 2}})
        add_action(b[0], 'Wound', [{'type': 'damage', 'flat': 200, 'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [], owner_features=[LIVING], ally_talents=[LIVING], cl=17,
                                bundle_transform=prepare, seed='QI4-MEND')
    settle(table, mid, candidate(combat, mid, 'Wound', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Living Character: Character of Mend', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp > before
    assert conditions(engine.state.actors[ALLY], 'qi_character_mended')
    healed = engine.state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Second Mend', target=ALLY).candidate_id)
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == healed
    turn(table, mid, ALLY)
    assert not conditions(reload(tmp_path, mid).state.actors[ALLY], 'qi_character_mended')
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Living Character: Character of Mend', target=ALLY).candidate_id)
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp > before


@pytest.mark.parametrize('cl,failed_feet', [(3, 10), (11, 15), (17, 20)])
@pytest.mark.parametrize('dc,failed', [(100, True), (-100, False)])
@pytest.mark.parametrize('direction', ['away', 'toward'])
def test_character_push_exact_save_and_cl_displacement(tmp_path, cl, failed_feet, dc, failed, direction):
    owner_x, foe_x = (0, 5) if direction == 'toward' else (3, 5)
    positions = {OWNER: {'x': owner_x, 'y': 1}, ALLY: {'x': 4, 'y': 10}, FOE: {'x': foe_x, 'y': 1}}
    combat, table, mid = fixture(tmp_path, [], owner_features=[LIVING], cl=cl, owner_dc=dc,
                                bundle_transform=setup, seed=f'QI4-PUSH-{cl}-{dc}-{direction}', positions=positions)
    cast = candidate(combat, mid, 'Living Character: Character of Push', target=FOE)
    prompts = settle(table, mid, cast.candidate_id, choices={'choice:needle.directed_movement': direction})
    movement_prompt = next(p for p in prompts if p.get('context', {}).get('reaction_source_id') == 'choice:needle.directed_movement')
    labels = [option.get('label', '') for option in movement_prompt['choice']['options']]
    assert len(labels) == 2 and any('push' in label.lower() and 'away' in label.lower() for label in labels)
    assert any('pull' in label.lower() and 'toward' in label.lower() for label in labels)
    actor = reload(tmp_path, mid).state.actors[FOE]
    assert actor.position.y == 1
    actual_feet = abs(actor.position.x - foe_x) * 5
    assert actual_feet == (failed_feet if failed else 5)
    if direction == 'toward':
        assert (actor.position.x - owner_x) * (foe_x - owner_x) >= 0
    else:
        assert (actor.position.x - foe_x) * (foe_x - owner_x) > 0


def test_character_push_rejects_perpendicular_choice_and_falls_back_to_legal_heading(tmp_path):
    positions = {OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 4, 'y': 10}, FOE: {'x': 5, 'y': 1}}
    combat, table, mid = fixture(tmp_path, [], owner_features=[LIVING], cl=17, owner_dc=100,
                                bundle_transform=setup, seed='QI4-PUSH-INVALID-DIRECTION', positions=positions)
    cast = candidate(combat, mid, 'Living Character: Character of Push', target=FOE)
    prompts = settle(table, mid, cast.candidate_id,
                     picks={'choice:needle.directed_movement': 'north'})
    movement_prompt = next(p for p in prompts
                           if p.get('context', {}).get('reaction_source_id') == 'choice:needle.directed_movement')
    legal_ids = {option['id'] for option in movement_prompt['choice']['options']}
    assert legal_ids == {'away', 'toward'}
    actor = reload(tmp_path, mid).state.actors[FOE]
    assert actor.position.y == 1
    assert actor.position.x == 9  # Invalid perpendicular input falls back to the preferred legal away heading.


@pytest.mark.parametrize('feature,name,needles', [
    (GREAT, 'Great Character: Great Character of River', ('30-foot-long, 5-foot-wide', 'technique save DC', '4d8', '15 feet', '5 feet')),
    (GREAT, 'Great Character: Great Character of Gate', ('120 feet', 'start of your next turn', 'once per turn', 'sealed Formation')),
    (GREAT, 'Great Character: Great Character of Silence', ('15-foot-radius sphere', '1 minute', 'Charisma saving throw against your technique save DC', 'Thunder damage')),
    (HEAVEN, 'Heaven’s Script: Heaven’s River', ('60-foot-long, 10-foot-wide', 'technique save DC', '8d8', '30 feet', '10 feet')),
    (HEAVEN, 'Heaven’s Script: Heaven’s Gate', ('300 feet', '1 minute', 'Concentration', 'up to 30 feet')),
    (HEAVEN, 'Heaven’s Script: Heaven’s Seal', ('Charisma saving throw against your technique save DC', 'end of its next turn', 'start of its next turn', 'higher-authority')),
])
def test_manual_option_resolution_is_self_contained_in_reloaded_table_feed(tmp_path, feature, name, needles):
    combat, table, mid = fixture(tmp_path, [], owner_features=[feature], cl=18,
                                bundle_transform=setup, seed=f'QI4-MANUAL-{name}')
    cast = candidate(combat, mid, name)
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    reminder = next(e.payload['rider'] for e in engine.events
                    if e.event_type == 'GM_RIDER' and e.source_definition_id == cast.source_definition_id)
    assert all(needle in reminder for needle in needles), reminder
    table_text = json.dumps(combat.presentation(mid), ensure_ascii=False)
    assert reminder in table_text


@pytest.mark.parametrize('cl,count', [(6, 3), (11, 4), (17, 5)])
def test_gale_scaling_and_automatic_harmful_recipient_policy(tmp_path, cl, count):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fixture(tmp_path, [], owner_features=[GALE], cl=cl, owner_dc=100,
                                bundle_transform=setup, seed=f'QI4-GALE-{cl}',
                                positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}})
    cast = candidate(combat, mid, 'Gale Burst', at=(6, 6))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    controller = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cast.candidate_id, ()),
        reaction_chooser=lambda context: controller.choose_reaction(context).decision)
    settle(table, mid, cast.candidate_id, auto=True)
    engine = reload(tmp_path, mid)
    assert damage(engine, cast.source_definition_id, FOE) > 0
    assert damage(engine, cast.source_definition_id, ALLY) == 0
    assert engine.state.actors[ALLY].position.x == 4
    assert conditions(engine.state.actors[FOE], 'prone')
    assert any(r.reason.startswith('DAMAGE:') and r.expression.startswith(f'{count}d8') for r in engine.rolls)


@pytest.mark.parametrize('sphere,expected', [('tianxia.sphere.air', 5), ('tianxia.sphere.water', 15)])
def test_wind_walker_speed_prone_save_and_tagged_forced_movement(tmp_path, sphere, expected):
    def prepare(b):
        setup(b)
        add_action(b[1], 'Push wind walker', [{'type': 'forced_movement', 'applies_to': 'target', 'distance_ft': 15, 'direction': 'away'}], typed={'sphere': sphere})
        add_action(b[1], 'Knock down', [{'type': 'save', 'ability': 'str', 'dc': 100,
            'on_fail': [{'type': 'condition', 'applies_to': 'target', 'condition': 'prone'}], 'on_success': []}])
    combat, table, mid = fixture(tmp_path, [], owner_features=[WIND], bundle_transform=prepare,
                                seed=f'QI4-WIND-{sphere}', positions={OWNER: {'x': 5, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 9, 'y': 5}})
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Knock down', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert roll.payload['mode'] == 'ADVANTAGE'
    # Prone does not change forced displacement; native path still owns it.
    settle(table, mid, candidate(combat, mid, 'Push wind walker', target=OWNER).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].position.x == 5 + expected // 5


def test_wind_walker_fall_reduction_through_service_move_and_reload(tmp_path):
    def prepare(b):
        setup(b)
        # Native flight holds the actor aloft; removing this short-lived grant
        # on its next turn creates an actual ordinary fall.
        add_action(b[0], 'Temporary flight', [{'type': 'general_flight', 'applies_to': 'self', 'speed_ft': 60,
            'hover': True, 'duration': {'kind': 'rounds', 'amount': 1}}], target='SELF')
    combat, table, mid = fixture(tmp_path, [], owner_features=[WIND], cl=17,
                                bundle_transform=prepare, seed='QI4-FALL')
    settle(table, mid, candidate(combat, mid, 'Temporary flight').candidate_id)
    engine = combat._load_session(mid).engine
    moves = [c for c in engine.legal_candidates() if c.destination and c.destination.z == 6 and c.metadata.get('movement_mode') == 'fly']
    assert moves
    settle(table, mid, moves[0].candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.z == 0
    assert engine.state.actors[OWNER].current_hp == before
