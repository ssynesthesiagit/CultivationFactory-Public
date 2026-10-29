"""Axes second pass through real service intents, table commits and cold reload."""
import json
import zipfile
from pathlib import Path
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.cw2_service_support import seal, add_action
from tests.worker2_support import candidate, settle, reload, turn

OWNER, ALLY, FOE, HELP = ['actor:factory.a2axes-' + x for x in ('owner', 'ally', 'foe', 'helper')]
HEW = 'TAL_AXES_HEWING_STRIKE'
DEEP = 'TAL_AXES_DEEP_BITE'
BEARD = 'TAL_AXES_BEARDED_HOOK_METHOD'
KNEE = 'TAL_AXES_HOOK_THE_GIANT_S_KNEE'
JUDGMENT = 'TAL_AXES_FALLING_MOUNTAIN_JUDGMENT'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}
STRIKE = 'Fu (Short Axe) attack: Hewing Strike: Bite'


def setup(tmp_path, talents, *, dc=16, height=0, hover=False, crowded=False, ai=False, skill=2, legacy=False, small_owner=False, big_foe=False, ally_position=None, blocked_landing=False, cleanup=None):
    ids = [OWNER, ALLY, FOE, HELP]
    if crowded:
        ids += ['actor:factory.a2axes-block' + str(i) for i in range(3)]
    bundles = []
    for i, aid in enumerate(ids):
        doc = sheet(talents if i == 0 else [], cl=15, dc=dc, kit=KIT)
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        if aid == FOE:
            doc['ability_scores_and_statistics']['skills'] = [
                {'skill': 'Athletics', 'ability': 'STR', 'bonus': skill, 'proficiency': 'proficient'},
                {'skill': 'Acrobatics', 'ability': 'DEX', 'bonus': skill, 'proficiency': 'proficient'}]
        directory = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        directory.mkdir(parents=True)
        with zipfile.ZipFile(directory / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
        bundle['actor_template'].update(maximum_hp=500, armor_class=0, initiative_bonus=100-i*10)
        if aid == FOE and KNEE in talents:
            bundle['actor_template'].update(fly_speed_ft=60 if height else 0, hover=hover)
        if legacy and aid == OWNER:
            def unstamp(x):
                if isinstance(x, dict):
                    x.pop('escape_policy', None)
                    for v in x.values(): unstamp(v)
                elif isinstance(x, list):
                    for v in x: unstamp(v)
            unstamp(bundle)
        if aid == OWNER and small_owner:
            bundle['actor_template']['size_category'] = 'Small'
        if aid == FOE and (KNEE in talents or big_foe):
            add_action(bundle, 'Test grow', [{'type':'size_change', 'size':'Large', 'duration':'until_removed'}], target='SELF')
        if aid == OWNER:
            if cleanup is not None:
                add_action(bundle, 'Test end escape dependency', cleanup)
            add_action(bundle, 'Test safe descent', [{'type':'axes_knee_descent'}])
            add_action(bundle, 'Test ground area', [], typed={'zone_spec': {
                'name':'Ground fire', 'centered_on_self':True, 'shape':'radius',
                'size_ft':5, 'height_ft':5, 'triggers':[{'id':'ground-entry', 'name':'Ground fire',
                'on':['enter'], 'who':'hostile', 'effects':[{'type':'damage', 'flat':7,
                'damage_types':['force'], 'applies_to':'target'}]}]}})
            add_action(bundle, 'Test opportunity penalty', [{'type': 'general_next_opportunity_penalty',
                       'duration': 'until_start_of_next_turn'}])
        seal(bundle); bundles.append(bundle)
    places = {OWNER: {'x':3,'y':6}, ALLY:{'x':3,'y':5}, FOE:{'x':4,'y':6,'z':height}, HELP:{'x':5,'y':6}}
    if ally_position is not None:
        places[ALLY] = ally_position
    if JUDGMENT in talents:
        places[ALLY] = {'x':4,'y':7}
    if KNEE in talents or big_foe:
        # A Large footprint leaves its descent cells free and remains in 3-D axe reach.
        places[FOE] = {'x':4,'y':6,'z':height}
        places[HELP] = {'x':6,'y':6}
    if blocked_landing:
        places[HELP] = {'x':5,'y':6,'z':0}
    if crowded:
        places[HELP] = {'x':4,'y':5}
        for aid, xy in zip(ids[4:], [(3,7),(4,7),(5,5)]): places[aid]={'x':xy[0],'y':xy[1]}
    svc = CombatService(ROOT, tmp_path)
    table = TabletopService(svc, tmp_path)
    teams = {aid: ('team:a' if aid in (OWNER,ALLY) else 'team:b') for aid in ids}
    mid = svc._finish_factory_match(bundles, ids, teams, places,
        svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER,ALLY], ids[2:],
        control_modes={aid: ('LOCAL_AUTO' if ai and aid == OWNER else 'MANUAL') for aid in ids},
        match_seed='A2AXES-crowded' if crowded else 'A2AXES', display_name='Axes service regression', maximum_rounds=15)['match_id']
    if KNEE in talents or big_foe:
        turn(table, mid, FOE)
        settle(table, mid, candidate(svc, mid, 'Test grow', target=FOE).candidate_id)
    turn(table, mid, OWNER)
    return svc, table, mid


def bite(engine):
    from combat.typed_executor import mark_condition_id
    return [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == mark_condition_id('Bite', OWNER)]


def use(combat, table, mid, name=STRIKE, target=FOE, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices=choices or {})


@pytest.mark.parametrize('ability', ['STR','DEX'])
@pytest.mark.parametrize('dc,success', [(1000,False),(-100,True)])
def test_deep_bite_escape_uses_own_action_skill_and_original_dc(tmp_path, ability, dc, success):
    combat, table, mid = setup(tmp_path, [HEW, DEEP], dc=dc, skill=30)
    use(combat, table, mid, STRIKE + ' + Deep Bite')
    assert bite(reload(tmp_path, mid))
    turn(table, mid, FOE)
    use(combat, table, mid, 'Break free', target=FOE, choices={'choice:needle.escape_ability': ability})
    after = reload(tmp_path, mid)
    assert bool(bite(after)) is not success
    check = [e for e in after.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == FOE][-1]
    assert check.payload['dc'] == dc
    assert check.payload['ability'] == ability
    assert check.payload['actor']['modifier'] == 30
    assert not after.state.actors[FOE].action_available


def test_deep_bite_help_grants_advantage_without_rolling_for_target(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, DEEP], dc=1000)
    use(combat, table, mid, STRIKE + ' + Deep Bite')
    turn(table, mid, HELP)
    use(combat, table, mid, 'Help a creature next to you break free', target=FOE)
    before = reload(tmp_path, mid)
    assert bite(before)
    assert not [e for e in before.events if e.event_type == 'CHECK_ROLLED']
    assert not before.state.actors[HELP].action_available
    turn(table, mid, FOE)
    use(combat, table, mid, 'Break free', target=FOE)
    after = reload(tmp_path, mid)
    check = [e for e in after.events if e.event_type == 'CHECK_ROLLED'][-1]
    assert check.actor_id == FOE
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.escape_assistance' for c in after.state.actors[FOE].conditions.values())
    turn(table, mid, HELP)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Break free', target=FOE)
    check = [e for e in reload(tmp_path, mid).events if e.event_type == 'CHECK_ROLLED'][-1]
    assert check.payload['actor']['mode'] == 'NORMAL'


def test_unstamped_deep_bite_retains_legacy_no_escape_record(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, DEEP], legacy=True)
    use(combat, table, mid, STRIKE + ' + Deep Bite')
    after = reload(tmp_path, mid)
    assert bite(after)
    assert not any(c.condition_id == 'condition:typed.escape_option' for c in after.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('crowded', [False, True])
def test_bearded_hook_moves_or_applies_only_blocked_penalty(tmp_path, crowded):
    combat, table, mid = setup(tmp_path, [HEW, BEARD], crowded=crowded)
    before = reload(tmp_path, mid).state.actors[FOE].position
    use(combat, table, mid, STRIKE + ' + Bearded Hook Method')
    after = reload(tmp_path, mid)
    penalty = any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in after.state.actors[FOE].conditions.values())
    assert [e for e in after.events if e.event_type == 'ATTACK_ROLLED'][-1].payload['provisional_hit']
    assert penalty is crowded
    assert (after.state.actors[FOE].position == before) is crowded


@pytest.mark.parametrize('height,hover,dc,expected', [(1,False,100,0),(1,True,100,1),(1,False,-100,1)])
def test_knee_safe_descent_only_on_failed_save_of_nonhover_flyer(tmp_path, height, hover, dc, expected):
    combat, table, mid = setup(tmp_path, [HEW, KNEE], height=height, hover=hover, dc=dc)
    use(combat, table, mid, STRIKE + " + Hook the Giant's Knee")
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].position.z == expected
    assert any(c.condition_id.endswith('.prone') for c in after.state.actors[FOE].conditions.values()) is (expected == 0)
    assert not [r for r in after.rolls if 'FALL' in r.reason]


def test_opportunity_penalty_survives_normal_attack_then_consumes_on_actual_oa(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, BEARD], ally_position={'x':4,'y':5})
    use(combat, table, mid, 'Test opportunity penalty')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Fu (Short Axe) attack', target=OWNER)
    before = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in before.state.actors[FOE].conditions.values())
    # Move the allied bystander out of the foe's reach, while it still has a Reaction.
    turn(table, mid, HELP)
    turn(table, mid, OWNER)
    # Refresh on this turn so expiry at owner's next turn is also respected.
    use(combat, table, mid, 'Test opportunity penalty')
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    moves = [c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
             and (c.destination.x,c.destination.y) == (4,4)]
    assert moves
    settle(table, mid, moves[0].candidate_id, {'reaction:typed.opportunity_attack':'first'})
    after = reload(tmp_path, mid)
    attacks = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE
               and 'opportunity_attack' in e.source_definition_id]
    assert attacks
    assert attacks[-1].payload['mode'] == 'DISADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in after.state.actors[FOE].conditions.values())


def test_ai_judgment_harms_only_perceived_enemies_with_allies_in_range(tmp_path):
    combat, table, mid = setup(tmp_path, [JUDGMENT], ai=True, dc=100)
    before = reload(tmp_path, mid)
    assert all(before._distance_actor_to_actor(before.state.actors[OWNER],
               before.state.actors[aid]) <= 30 for aid in (ALLY,FOE,HELP))
    settle(table, mid, '', auto=True)
    after = reload(tmp_path, mid)
    accepted = [e for e in after.events if e.event_type == 'INTENT_ACCEPTED' and e.actor_id == OWNER]
    assert accepted and JUDGMENT in accepted[-1].source_definition_id
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED']
    assert saves
    assert {e.actor_id for e in saves} <= {FOE, HELP}
    assert after.state.actors[ALLY].current_hp == 500
    assert not any(c.condition_id.endswith('.prone') for c in after.state.actors[ALLY].conditions.values())
    assert after.state.actors[OWNER].current_hp == 500


def test_bearded_hook_rejects_two_category_gap_despite_adjacent_footprint_widths(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, BEARD], small_owner=True, big_foe=True)
    before = reload(tmp_path, mid).state.actors[FOE].position
    use(combat, table, mid, STRIKE + ' + Bearded Hook Method')
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].size_category == 'Small'
    assert after.state.actors[FOE].transformed_size_category == 'Large'
    assert after.state.actors[FOE].position == before
    assert not any(c.condition_id == 'condition:typed.next_opportunity_penalty'
                   for c in after.state.actors[FOE].conditions.values())


def test_deep_bite_is_offered_only_for_hits_that_place_bite(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, DEEP])
    engine = combat._load_session(mid).engine
    names = {engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
             if c.source_definition_id in engine.action_catalog}
    assert STRIKE + ' + Deep Bite' in names
    assert not any('Hamper + Deep Bite' in name or 'Shock Cast + Deep Bite' in name for name in names)
    use(combat, table, mid, 'Fu (Short Axe) attack: Hewing Strike: Hamper')
    after = reload(tmp_path, mid)
    assert not bite(after)
    assert not any(c.condition_id == 'condition:typed.escape_option' for c in after.state.actors[FOE].conditions.values())
    assert after.state.actors[OWNER].resources['resource:core.qi'] == 100


@pytest.mark.parametrize('blocked', [False, True])
def test_multisegment_descent_validates_complete_large_footprint_before_moving(tmp_path, blocked):
    combat, table, mid = setup(tmp_path, [HEW, KNEE], height=2, blocked_landing=blocked)
    before = reload(tmp_path, mid).state.actors[FOE].position
    use(combat, table, mid, 'Test safe descent')
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].position.z == (2 if blocked else 0)
    assert any(c.condition_id.endswith('.prone') for c in after.state.actors[FOE].conditions.values()) is (not blocked)
    if blocked:
        assert after.state.actors[FOE].position == before
        assert any('manual' in str(e.payload.get('log', '')).lower() and 'landing' in str(e.payload.get('log', '')).lower() for e in after.events)
    assert not [r for r in after.rolls if 'FALL' in r.reason]


@pytest.mark.parametrize('height', [1, 2])
def test_knee_descent_applies_ground_zone_entry_damage_after_reload(tmp_path, height):
    combat, table, mid = setup(tmp_path, [HEW, KNEE], height=height, dc=100)
    use(combat, table, mid, 'Test ground area', target=OWNER)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    use(combat, table, mid, STRIKE + " + Hook the Giant's Knee" if height == 1 else 'Test safe descent')
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].position.z == 0
    if height == 2:
        assert after.state.actors[FOE].current_hp == hp - 7
    assert any(e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids and e.payload.get('hp_damage') == 7 and e.payload.get('damage_type') == 'FORCE' for e in after.events)
    assert len([e for e in after.events if e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('moment') == 'enter' and FOE in e.target_ids]) == 1
    assert not [r for r in after.rolls if 'FALL' in r.reason]


def test_assistance_status_names_hold_benefit_and_helper_deadline(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, DEEP], dc=1000)
    use(combat, table, mid, STRIKE + ' + Deep Bite')
    turn(table, mid, HELP)
    use(combat, table, mid, 'Help a creature next to you break free', target=FOE)
    after = reload(tmp_path, mid)
    held = after.state.actors[FOE]
    helper = after.state.actors[HELP]
    label = next(c['display_name'] for a in CombatService(ROOT, tmp_path).presentation(mid)['actors'] if a['entity_id'] == FOE for c in a['conditions'] if c['condition_id'] == 'condition:typed.escape_assistance')
    assert all(text in label for text in [held.display_name, helper.display_name, 'Deep Bite', 'Advantage', 'next escape check', 'start', 'next turn'])
    assert any(label == e.payload.get('log') for e in after.events)
    turn(table, mid, FOE)
    turn(table, mid, HELP)
    assert not any(c.condition_id == 'condition:typed.escape_assistance' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_opportunity_penalty_status_and_source_turn_expiry(tmp_path):
    combat, table, mid = setup(tmp_path, [HEW, BEARD])
    use(combat, table, mid, 'Test opportunity penalty')
    after = reload(tmp_path, mid)
    label = next(c['display_name'] for a in CombatService(ROOT, tmp_path).presentation(mid)['actors'] if a['entity_id'] == FOE for c in a['conditions'] if c['condition_id'] == 'condition:typed.next_opportunity_penalty')
    assert all(text in label for text in ['Disadvantage', 'Opportunity Attack', after.state.actors[OWNER].display_name, 'start', 'next turn'])
    turn(table, mid, FOE)
    assert any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, OWNER)
    assert not any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_native_opportunity_penalty_uses_actual_native_roll_and_consumes(tmp_path):
    from combat.gate2_runtime_content import AN
    from tests.test_lock13_native_opportunity import move, checked
    doc = sheet([], cl=15)
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask':True})
    add_action(bundle, 'Test opportunity penalty', [{'type':'general_next_opportunity_penalty',
               'duration':'until_start_of_next_turn'}])
    combat = CombatService(ROOT, tmp_path)
    mid = combat.persistence.create_match(match_seed='A2AXES-native', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids':[OWNER,AN], 'team_by_actor':{OWNER:'a',AN:'b'},
                      'starting_positions':{OWNER:{'x':4,'y':6},AN:{'x':5,'y':6}}}).match_id
    for aid in (OWNER, AN):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Test opportunity penalty', target=AN)
    assert any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in reload(tmp_path, mid).state.actors[AN].conditions.values())
    move(combat, table, mid)
    after = checked(combat, tmp_path, mid)
    attacks = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == 'system:combat.opportunity_attack']
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'DISADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.next_opportunity_penalty' for c in after.state.actors[AN].conditions.values())


@pytest.mark.parametrize('ending,effects', [
    ('removed_hold', [{'type': 'spend_mark', 'mark': 'Bite'}]),
    ('replaced_hold', [{'type': 'mark', 'mark': 'Bite', 'applies_to': 'target'}]),
    ('removed_record', [{'type': 'remove_condition', 'condition': 'escape_option', 'applies_to': 'target'}]),
])
def test_help_is_removed_immediately_when_its_escape_dependency_ends(tmp_path, ending, effects):
    combat, table, mid = setup(tmp_path, [HEW, DEEP], dc=1000, cleanup=effects)
    use(combat, table, mid, STRIKE + ' + Deep Bite')
    original_bite = bite(reload(tmp_path, mid))[0].instance_id
    turn(table, mid, HELP)
    use(combat, table, mid, 'Help a creature next to you break free', target=FOE)
    helped = reload(tmp_path, mid)
    assistance = next(c for c in helped.state.actors[FOE].conditions.values()
                      if c.condition_id == 'condition:typed.escape_assistance')
    helper_turns = helped.state.actors[HELP].turns_started
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Test end escape dependency')
    after = reload(tmp_path, mid)
    # The helper has not reached its expiry turn; ending the dependency must clean it now.
    assert after.state.actors[HELP].turns_started == helper_turns
    assert not [e for e in after.events if e.event_type == 'CHECK_ROLLED']
    ended_id = (next(c.condition_id for c in helped.state.actors[FOE].conditions.values()
                     if c.condition_id == 'condition:typed.escape_option')
                if ending == 'removed_record' else bite(helped)[0].condition_id)
    assert any(e.event_type == 'CONDITION_REMOVED' and e.target_ids == (FOE,) and
               e.payload.get('condition_id') == ended_id for e in after.events)
    assert not any(c.condition_id in ('condition:typed.escape_option', 'condition:typed.escape_assistance')
                   for c in after.state.actors[FOE].conditions.values())
    assert any(e.event_type == 'CONDITION_REMOVED' and
               e.payload.get('instance_id') == assistance.instance_id for e in after.events)
    if ending == 'removed_hold':
        assert not bite(after)
    elif ending == 'replaced_hold':
        assert bite(after) and bite(after)[0].instance_id != original_bite
    else:
        assert bite(after)[0].instance_id == original_bite
    presentation = CombatService(ROOT, tmp_path).presentation(mid)
    assert not any(c['condition_id'] == 'condition:typed.escape_assistance'
                   for a in presentation['actors'] if a['entity_id'] == FOE for c in a['conditions'])
