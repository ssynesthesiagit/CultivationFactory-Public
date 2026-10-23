"""Mapped thresholds and specters through committed service intents and cold reload."""
import json
from pathlib import Path
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, turn
from tests.test_r9i_karma_persistence import act
from combat.ext.boundary_passage import STEP, MARK, DENY, MARK_KIND

ME, FOE = 'actor:factory.boundary-owner', 'actor:factory.boundary-foe'
DOOR = 'object:map.1'
POOL = 'resource:core.resonance'


def setup(tmp_path, features, *, dc=60, closed=False, owner=(4, 5), foe=(4, 7), modes=None, fragments=0, foe_kind=None, spirit_probe=False, probe_ability="wis", opaque_wall=False, foe_features=None, speed_probe=False, speed_delta=-25, large_map=False, bundle_transform=None, walls=None):
    documents = [sheet(features, cl=18, dc=dc, primary='Resonance', key='WIS'), sheet(foe_features or [], cl=5)]
    if foe_kind:
        documents[1]['identity']['creature_type'] = foe_kind
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in zip((ME, FOE), documents)]
    if spirit_probe:
        from combat.canonical import canonical_sha256
        action = {'source_definition_id': 'action:test.spiritual_probe', 'display_name': 'Fixture spiritual save',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
            'parameters': {'typed': {'source': 'test:spiritual_probe', 'numbers': {'save_dc': 60, 'cl': 5}, 'riders': [],
                'effects': [{'type': 'save', 'ability': probe_ability, 'applies_to': 'target', 'save_categories': ['possession'],
                    'on_fail': [{'type': 'mark', 'mark': 'Fixture possession packet', 'applies_to': 'target',
                        'spiritual_categories': ['possession'], 'duration': {'kind': 'until_removed'}}], 'on_success': []}]}}}
        if probe_ability == 'dex':
            # Real cover providers can overlap. Cover is a single maximum, not
            # two +2 bonuses when both the specter and Moon protect this target.
            action['parameters']['typed']['effects'].insert(0, {'type': 'monkey_half_cover', 'applies_to': 'target'})
        bundles[1]['action_catalog'].append(action)
        bundles[1]['actor_template']['action_ids'].append(action['source_definition_id'])
        bundles[1].pop('bundle_sha256', None)
        bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])
    if speed_probe:
        from combat.canonical import canonical_sha256
        action = {'source_definition_id': 'action:test.specter_slow', 'display_name': 'Fixture slow',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
            'parameters': {'typed': {'source': 'test:specter_slow', 'numbers': {}, 'riders': [],
                'effects': [{'type': 'speed', 'applies_to': 'target', 'flat': speed_delta,
                    'duration': {'kind': 'until_removed'}}]}}}
        bundles[1]['action_catalog'].append(action)
        bundles[1]['actor_template']['action_ids'].append(action['source_definition_id'])
        bundles[1].pop('bundle_sha256', None)
        bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])
    if fragments:
        from combat.canonical import canonical_sha256
        for row in bundles[0]['actor_template']['resources']:
            if row['resource_id'] == 'resource:named.soul_fragment':
                row['initial'] = fragments
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    if bundle_transform:
        bundle_transform(bundles)
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    arena = to_battlefield(normalize_map({'display_name': 'Threshold yard', 'width_squares': 30 if large_map else 12,
        'height_squares': 30 if large_map else 12, 'walls': (walls if walls is not None else ([{'id': 'screen', 'shape': 'rect', 'points': [[5,0],[6,12]],
            'filled': True, 'blocks': 'sight_and_movement'}] if opaque_wall else [])), 'objects': [{'id': 1, 'kind': 'door', 'name': 'Wooden gate',
        'x': 4, 'y': 6, 'mount_axis': 'h', 'mount_line': 600, 'interaction': 'simple_door',
        'door_open': 0 if closed else 1, 'door_locked': 0, 'door_jammed': 0}]}))
    mid = service._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': owner[0], 'y': owner[1]}, FOE: {'x': foe[0], 'y': foe[1]}},
        arena, [ME], [FOE], control_modes=modes or {ME: 'MANUAL', FOE: 'MANUAL'},
        match_seed='A2GMISSUB3', display_name='Threshold yard', maximum_rounds=10)['match_id']
    turn(table, mid, ME)
    return service, table, mid


def find(service, mid, name, target=None):
    engine = service._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if c.display_name == name and (target is None or c.target_ids == (target,)))


def cold(tmp_path, service, mid):
    prior = service._load_session(mid)
    result = CombatService(ROOT, tmp_path)._load_session(mid)
    assert result.engine.state.model_dump(mode='json') == prior.engine.state.model_dump(mode='json')
    assert result.verify()['status'] == 'PASS'
    assert result.mechanical.replay()['status'] == 'PASS'
    return result.engine


def test_threshold_step_chooses_other_side_pays_once_and_reloads(tmp_path):
    service, table, mid = setup(tmp_path, [STEP])
    prior = service._load_session(mid).engine.state.actors[ME].resources[POOL]
    prompts = settle(table, mid, find(service, mid, 'Threshold Step').candidate_id,
        {'choice:needle.boundary.threshold': DOOR, 'choice:needle.boundary.landing': 'cell:4,6'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.boundary.landing' for p in prompts)
    landing = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.landing')
    assert all(int(o['id'].split(',')[1]) >= 6 for o in landing['choice']['options'])
    engine = cold(tmp_path, service, mid)
    actor = engine.state.actors[ME]
    assert (actor.position.x, actor.position.y) == (4, 6)
    assert actor.resources[POOL] == prior - 1
    assert not any(c.display_name == 'Threshold Step' for c in engine.legal_candidates())
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ME]
    assert moves[-1].payload['teleport'] and moves[-1].payload['cost_ft'] == 0


def test_closed_threshold_does_not_offer_a_step(tmp_path):
    service, table, mid = setup(tmp_path, [STEP], closed=True)
    engine = cold(tmp_path, service, mid)
    assert not any(c.display_name == 'Threshold Step' for c in engine.legal_candidates())


def test_declined_landing_costs_nothing_and_preserves_allowance(tmp_path):
    service, table, mid = setup(tmp_path, [STEP])
    prior = service._load_session(mid).engine.state.actors[ME].resources[POOL]
    settle(table, mid, find(service, mid, 'Threshold Step').candidate_id,
           {'choice:needle.boundary.landing': None})
    engine = cold(tmp_path, service, mid)
    assert engine.state.actors[ME].resources[POOL] == prior
    assert any(c.display_name == 'Threshold Step' for c in engine.legal_candidates())


def mark(service, table, mid, mode, subjects=None):
    picks = {'choice:needle.boundary.subjects': subjects} if subjects is not None else {}
    settle(table, mid, find(service, mid, 'Mark the Door: ' + mode.title()).candidate_id, picks)


def move(service, table, mid, dest):
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
                     and (c.destination.x, c.destination.y) == dest)
    return settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': 'stop'})


@pytest.mark.parametrize('dc,blocked', [(60, True), (1, False)])
def test_refusing_mark_stops_failed_save_or_marks_success_once_per_round(tmp_path, dc, blocked):
    service, table, mid = setup(tmp_path, [MARK], dc=dc, owner=(3, 6))
    prior = service._load_session(mid).engine.state.actors[ME].resources[POOL]
    mark(service, table, mid, 'refusing', FOE)
    engine = cold(tmp_path, service, mid)
    bound = next(obj for obj in engine.state.objects.values() if obj.object_kind == MARK_KIND)
    assert bound.ac == 16 and bound.maximum_hp == 20
    assert bound.component['resist'] == ['PSYCHIC', 'FORCE'] and bound.component['threshold_id'] == DOOR
    assert engine.state.actors[ME].resources[POOL] == prior - 2
    turn(table, mid, FOE)
    move(service, table, mid, (4, 5))
    engine = cold(tmp_path, service, mid)
    actor = engine.state.actors[FOE]
    assert (actor.position.x, actor.position.y) == ((4, 6) if blocked else (4, 5))
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert len(saves) == 1
    if not blocked:
        from combat.typed_executor import bears_mark
        assert bears_mark(actor, ME, 'Resonance')

    # Reload before a second crossing in the same round. A failed first save
    # must not block the retry; a successful first save must not ask again.
    first_round = engine.state.round_number
    move(service, table, mid, (4, 5) if blocked else (4, 7))
    engine = cold(tmp_path, service, mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]) == 1
    if blocked:
        assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 5)
        move(service, table, mid, (4, 7))
    turn(table, mid, ME)
    turn(table, mid, FOE)
    engine = cold(tmp_path, service, mid)
    assert engine.state.round_number > first_round
    move(service, table, mid, (4, 5))
    engine = cold(tmp_path, service, mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]) == 2
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == ((4, 6) if blocked else (4, 5))


@pytest.mark.parametrize('dc,blocked', [(60, True), (1, False)])
def test_deny_passage_is_a_prearrival_reaction_and_pays_once(tmp_path, dc, blocked):
    service, table, mid = setup(tmp_path, [DENY], dc=dc, owner=(3, 6))
    turn(table, mid, FOE)
    prior = service._load_session(mid).engine.state.actors[ME].resources[POOL]
    prompts = move(service, table, mid, (4, 5))
    assert any(p['context']['reaction_source_id'] == 'choice:needle.boundary.deny' for p in prompts)
    if blocked:
        outcome = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.deny_outcome')
        assert {o['id'] for o in outcome['choice']['options']} == {'stop', 'return'}
    engine = cold(tmp_path, service, mid)
    owner, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert owner.resources[POOL] == prior - 4 and not owner.reaction_available
    assert (foe.position.x, foe.position.y) == ((4, 6) if blocked else (4, 5))
    reactions = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == DENY]
    assert len(reactions) == 1
    if blocked:
        assert any('spirit_awakening_pressure' in c.condition_id for c in foe.conditions.values())
    else:
        assert any(c.data.get('rule', {}).get('no_teleport') for c in foe.conditions.values())


def test_invited_mark_exempts_named_enemy_from_owners_hostile_reaction(tmp_path):
    service, table, mid = setup(tmp_path, [MARK, DENY], owner=(3, 6))
    mark(service, table, mid, 'invited', FOE)
    turn(table, mid, FOE)
    prior = service._load_session(mid).engine.state.actors[ME].resources[POOL]
    move(service, table, mid, (4, 5))
    engine = cold(tmp_path, service, mid)
    assert engine.state.actors[ME].resources[POOL] == prior
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 5)
    assert not any(e.event_type == 'SAVE_ROLLED' for e in engine.events)


def test_threshold_line_outside_aperture_never_triggers_deny(tmp_path):
    service, table, mid = setup(tmp_path, [DENY], owner=(3, 6), foe=(6, 7))
    turn(table, mid, FOE)
    move(service, table, mid, (6, 5))
    engine = cold(tmp_path, service, mid)
    assert engine.state.actors[ME].reaction_available
    assert not any(e.event_type == 'SAVE_ROLLED' for e in engine.events)


def test_walk_the_border_passes_through_creatures_but_cannot_end_in_them(tmp_path):
    feature = 'tianxia.tradition.spirit.boundary_walker.feature.walk_the_border'
    service, table, mid = setup(tmp_path, [feature], owner=(3, 5), foe=(4, 5))
    settle(table, mid, find(service, mid, 'Walk the Border').candidate_id)
    engine = cold(tmp_path, service, mid)
    assert not any(c.kind == 'MOVE' and c.destination == engine.state.actors[FOE].position for c in engine.legal_candidates())
    move(service, table, mid, (5, 5))
    engine = cold(tmp_path, service, mid)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (5, 5)



def raise_at(service, table, mid, at=(4, 6)):
    engine = service._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.display_name.startswith('Raise Specter at ')
        and c.destination and (c.destination.x, c.destination.y) == at)
    settle(table, mid, c.candidate_id)


def test_specter_strike_resolves_immediately_and_has_no_independent_turn(tmp_path):
    from combat.ext.soul_warden import RAISE, HARVEST, specter_of
    from combat.flight import profile
    service, table, mid = setup(tmp_path, [RAISE, HARVEST], fragments=1)
    raise_at(service, table, mid)
    engine = cold(tmp_path, service, mid)
    specter = specter_of(engine, engine.state.actors[ME])
    assert specter and specter.position.x == 4 and specter.position.y == 6
    assert not specter.reaction_available
    assert specter.armor_class == 60 and specter.maximum_hp == 24
    assert profile(engine, specter).speed_ft == 40 and profile(engine, specter).hover
    owner = engine.state.actors[ME]
    assert owner.resources['resource:named.soul_fragment'] == 0 and owner.resources[POOL] == 25
    settle(table, mid, find(service, mid, 'Specter: Spectral Strike').candidate_id,
        {'choice:needle.soul_warden.strike_damage': 'psychic'})
    engine = cold(tmp_path, service, mid)
    assert not engine.state.actors[ME].bonus_action_available
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 1 and attacks[0].actor_id == ME
    assert not any(e.event_type == 'SUMMONS_COMMANDED' for e in engine.events)
    assert not any(c.display_name == 'Specter: Spectral Strike' for c in engine.legal_candidates())
    settle(table, mid, table.state(mid)['menu']['end_turn'], {'choice:needle.soul_warden.move': 'cell:5,6'})
    engine = cold(tmp_path, service, mid)
    specter = specter_of(engine, engine.state.actors[ME])
    assert (specter.position.x, specter.position.y) == (5, 6)
    assert not specter.action_available and not specter.reaction_available
    assert not any(e.event_type == 'COMPANION_DEFAULT_APPLIED' and e.actor_id == specter.entity_id for e in engine.events)


@pytest.mark.parametrize("ability", ["wis", "dex"])
def test_warden_guard_has_half_cover_and_next_possession_save_advantage(tmp_path, ability):
    from combat.ext.soul_warden import RAISE, HARVEST
    service, table, mid = setup(tmp_path, [RAISE, HARVEST], fragments=1, spirit_probe=True, probe_ability=ability)
    settle(table, mid, find(service, mid, 'Choose Specter: Warden Specter').candidate_id)
    raise_at(service, table, mid)
    settle(table, mid, find(service, mid, 'Specter: Guard the Threshold', ME).candidate_id)
    engine = cold(tmp_path, service, mid)
    owner = engine.state.actors[ME]
    assert engine.cover_from([(4,7,0)], FOE, owner)['bonus'] == 2
    rules = [c.data.get('rule', {}) for c in owner.conditions.values()]
    assert any(r.get('save_against', {}).get('mode') == 'ADVANTAGE' and r['save_against'].get('next') for r in rules)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture spiritual save', ME).candidate_id)
    engine = cold(tmp_path, service, mid)
    rolled = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ME)
    assert len(rolled.payload['dice']) == 2
    if ability == 'dex':
        assert rolled.payload['save_bonus_contributions']['cover'] == 2
    assert not any(c.condition_id == 'condition:typed.specter_guard' for c in engine.state.actors[ME].conditions.values())


def test_warden_seizes_explicit_spirit_without_a_resonance_mark(tmp_path):
    from combat.ext.soul_warden import RAISE, HARVEST
    service, table, mid = setup(tmp_path, [RAISE, HARVEST], fragments=1, foe_kind='Spirit', spirit_probe=True)
    settle(table, mid, find(service, mid, 'Choose Specter: Warden Specter').candidate_id)
    raise_at(service, table, mid)
    settle(table, mid, find(service, mid, 'Specter: Seize Intruder').candidate_id)
    engine = cold(tmp_path, service, mid)
    foe = engine.state.actors[FOE]
    assert engine._effective_speed(foe) == 0
    assert any(c.data.get('rule', {}).get('no_possession') for c in foe.conditions.values())
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture spiritual save', ME).candidate_id)
    engine = cold(tmp_path, service, mid)
    from combat.typed_executor import bears_mark
    assert not bears_mark(engine.state.actors[ME], FOE, 'Fixture possession packet')



def test_automatic_invitation_selects_only_allies(tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    service, table, mid = setup(tmp_path, [MARK], owner=(3, 6), modes={ME: 'LOCAL_AUTO', FOE: 'MANUAL'})
    session = service._load_session(mid)
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == 'Mark the Door: Invited')
    session.mechanical.execute_intent(ActionIntent(intent_id='automatic-invitation', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    engine = cold(tmp_path, service, mid)
    mark = next(o for o in engine.state.objects.values() if o.object_kind == MARK_KIND)
    assert mark.component['subjects'] == [ME]
    assert FOE not in mark.component['subjects']



@pytest.mark.parametrize('accept',[False,True])
def test_harrier_of_the_living_requires_ally_consent(tmp_path,accept):
    from combat.ext.soul_warden import RAISE,HARVEST
    service,table,mid=setup(tmp_path,[RAISE,HARVEST],fragments=1)
    raise_at(service,table,mid)
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.display_name=='Specter: Harrier of the Living' and c.target_ids==(ME,))
    prompts=settle(table,mid,c.candidate_id,{'choice:needle.soul_warden.harrier_consent':'accept' if accept else None})
    consent=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.soul_warden.harrier_consent')
    assert consent['affected'] == engine.state.actors[ME].display_name
    assert engine.state.actors[ME].display_name in consent['moment']
    engine=cold(tmp_path,service,mid)
    from combat.typed_executor import condition_rules
    assert any(r.get('no_reactions') for r in condition_rules(engine.state.actors[ME])) == accept


def test_automatic_harrier_never_selects_an_ally(tmp_path):
    from combat.ext.soul_warden import RAISE,HARVEST
    from combat.gate2_runtime_models import ActionIntent
    service,table,mid=setup(tmp_path,[RAISE,HARVEST],fragments=1,modes={ME:'LOCAL_AUTO',FOE:'MANUAL'})
    session=service._load_session(mid)
    c=next(c for c in session.engine.legal_candidates() if c.display_name.startswith('Raise Specter at ') and c.destination and (c.destination.x,c.destination.y)==(4,6))
    session.mechanical.execute_intent(ActionIntent(intent_id='automatic-raise',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination,option_ids=c.option_ids))
    engine=cold(tmp_path,service,mid)
    targets=[c.target_ids for c in engine.legal_candidates() if c.display_name=='Specter: Harrier of the Living']
    assert (FOE,) in targets and (ME,) not in targets


def test_walking_up_to_threshold_does_not_qualify_as_starting_adjacent(tmp_path):
    service, table, mid = setup(tmp_path, [STEP], owner=(4,3))
    move(service, table, mid, (4,5))
    engine = cold(tmp_path, service, mid)
    assert not any(c.display_name == 'Threshold Step' for c in engine.legal_candidates())


def test_witnessing_mark_records_known_crossing_direction_and_willingness(tmp_path):
    service, table, mid = setup(tmp_path, [MARK], owner=(3,6))
    mark(service, table, mid, 'witnessing')
    turn(table, mid, FOE)
    move(service, table, mid, (4,5))
    engine = cold(tmp_path, service, mid)
    notices = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
               and e.actor_id == ME and 'threshold_crossing' in e.payload]
    assert len(notices) == 1
    assert notices[0].payload['threshold_crossing'] == {
        'threshold_id': DOOR, 'creature_id': FOE, 'direction': 'south to north', 'willing': True}


def test_witnessing_mark_reports_only_committed_crossings(tmp_path):
    service, table, mid = setup(tmp_path, [MARK, DENY], dc=60, owner=(3,6))
    mark(service, table, mid, 'witnessing')
    turn(table, mid, FOE)
    move(service, table, mid, (4,5))
    engine = cold(tmp_path, service, mid)
    notices = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
               and e.actor_id == ME and 'threshold_crossing' in e.payload]
    assert notices == []
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4,6)


def test_automatic_refusing_mark_names_only_a_perceived_enemy(tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    service, table, mid = setup(tmp_path, [MARK], owner=(3,6), modes={ME:'LOCAL_AUTO', FOE:'MANUAL'})
    session = service._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if c.display_name == 'Mark the Door: Refusing')
    session.mechanical.execute_intent(ActionIntent(intent_id='automatic-refusal', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    engine = cold(tmp_path, service, mid)
    result = next(o for o in engine.state.objects.values() if o.object_kind == MARK_KIND)
    assert result.component['subjects'] == [FOE]


def test_automatic_refusing_mark_does_not_name_an_unperceived_enemy(tmp_path):
    from combat.target_knowledge import located
    from combat.gate2_runtime_models import ActionIntent
    service, table, mid = setup(tmp_path, [MARK], owner=(3,6), foe=(6,6), opaque_wall=True,
        modes={ME:'LOCAL_AUTO', FOE:'MANUAL'})
    session = service._load_session(mid)
    engine = session.engine
    assert not located(engine, engine.state.actors[ME], engine.state.actors[FOE])
    assert not any(c.display_name == 'Mark the Door: Refusing' for c in engine.legal_candidates())
    c = next(c for c in engine.legal_candidates() if c.display_name == 'Mark the Door: Invited')
    session.mechanical.execute_intent(ActionIntent(intent_id='automatic-known-invitation', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    engine = cold(tmp_path, service, mid)
    result = next(o for o in engine.state.objects.values() if o.object_kind == MARK_KIND)
    assert result.component['subjects'] == [ME]


def test_manual_mark_menu_does_not_disclose_hidden_roster(tmp_path):
    service, table, mid = setup(tmp_path, [MARK], owner=(3,6), foe=(6,6), opaque_wall=True)
    prompts = settle(table, mid, find(service, mid, 'Mark the Door: Refusing').candidate_id)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.subjects')
    offered = {o['id'] for o in prompt['choice']['options']}
    assert FOE not in offered
    assert 'kind:humanoid' in offered
    engine = cold(tmp_path, service, mid)
    assert engine.state.actors[ME].resources[POOL] == 28


def test_mark_actions_explain_their_choices_in_player_text(tmp_path):
    service, table, mid = setup(tmp_path, [MARK])
    engine = service._load_session(mid).engine
    descriptions = {c.display_name: engine.action_catalog[c.source_definition_id].parameters['description']
        for c in engine.legal_candidates() if c.display_name.startswith('Mark the Door:')}
    assert 'learn when' in descriptions['Mark the Door: Witnessing']
    assert 'may cross' in descriptions['Mark the Door: Invited']
    assert 'Charisma save' in descriptions['Mark the Door: Refusing']
    assert all('5 × PB Hit Points' in value and 'Destroying the physical threshold' in value
               for value in descriptions.values())


def test_spectral_strike_damage_prompt_identifies_affected_creature(tmp_path):
    from combat.ext.soul_warden import RAISE
    service, table, mid = setup(tmp_path, [RAISE], fragments=1)
    raise_at(service, table, mid)
    prompts = settle(table, mid, find(service, mid, 'Specter: Spectral Strike').candidate_id,
                     {'choice:needle.soul_warden.strike_damage': 'psychic'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.soul_warden.strike_damage')
    assert prompt['affected'] == service._load_session(mid).engine.state.actors[FOE].display_name
    assert prompt['affected'] in prompt['moment']


def test_successful_deny_lock_blocks_threshold_step_after_cold_reload(tmp_path):
    service, table, mid = setup(tmp_path, [DENY], dc=1, owner=(3,6), foe_features=[STEP])
    turn(table, mid, FOE)
    move(service, table, mid, (4,5))
    engine = cold(tmp_path, service, mid)
    foe = engine.state.actors[FOE]
    assert any(c.data.get('rule', {}).get('no_teleport') for c in foe.conditions.values())
    assert not any(c.display_name == 'Threshold Step' for c in engine.legal_candidates())


@pytest.mark.parametrize('speed_delta',[-25,10])
def test_specter_end_move_uses_current_modified_speed(tmp_path, speed_delta):
    from combat.ext.soul_warden import RAISE, specter_of
    service, table, mid = setup(tmp_path, [RAISE], fragments=1, speed_probe=True, speed_delta=speed_delta,
                                foe=(10,10), large_map=speed_delta > 0)
    raise_at(service, table, mid)
    engine = service._load_session(mid).engine
    specter = specter_of(engine, engine.state.actors[ME])
    # Leave it in place during the setup turn; the measured grant starts only
    # after the opposing actor has applied the Speed effect.
    settle(table, mid, table.state(mid)['menu']['end_turn'], {'choice:needle.soul_warden.move': None})
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture slow', specter.entity_id).candidate_id)
    turn(table, mid, ME)
    engine = service._load_session(mid).engine
    specter = specter_of(engine, engine.state.actors[ME])
    speed = int(engine._effective_speed(specter))
    assert speed == 40 + speed_delta
    before = specter.position
    end_turn = table.state(mid)['menu']['end_turn']
    pending = act(table, mid, end_turn)
    assert pending['status'] == 'REACTION_REQUIRED'
    prompt = pending['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.soul_warden.move'
    from combat.ext import needle, granted_movement
    priced = {needle.cell_id(candidate.destination): candidate
              for candidate in granted_movement.choices(engine, specter, speed)
              if candidate.destination is not None}
    offered = [option['id'] for option in prompt['choice']['options']]
    assert all(option_id in priced for option_id in offered), offered
    assert all(int(priced[option_id].movement_cost_ft or 0) <= speed for option_id in offered), [
        (option_id, priced[option_id].movement_cost_ft, speed) for option_id in offered]
    # Flight routes may end at another altitude and charge terrain/landing
    # costs. Measure the native route price, rather than straight-line distance.
    maximum = max(int(priced[option_id].movement_cost_ft) for option_id in offered)
    assert maximum == speed
    choice = max(option_id for option_id in offered if priced[option_id].movement_cost_ft == maximum)
    destination = priced[choice].destination
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [choice]}
    committed = act(table, mid, end_turn, [answer])
    assert committed['status'] == 'COMMITTED', committed
    engine = cold(tmp_path, service, mid)
    specter = specter_of(engine, engine.state.actors[ME])
    assert specter.position == destination and specter.position != before
    committed = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED'
                     and e.actor_id == specter.entity_id)
    assert committed.payload['granted_cost_ft'] == maximum == speed
