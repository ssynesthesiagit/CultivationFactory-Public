"""RW193 review fixes: Gravebeat death-save rules, Deny Passage possession separation and its receipt."""
import pytest
from combat import ext
from combat.canonical import canonical_sha256
from combat.ext import boundary_passage, hold_still, life_state, movement_clock
from combat.ext.boundary_passage import STEP
from tests.test_a2_misc_subpaths_3 import DENY, DOOR, FOE, ME, cold, find, setup
from tests.thrum_grave_support import BEATS, FOE as TG_FOE, ME as TG_ME, TG_ALL, fight
from tests.worker2_support import settle, turn

POSSESS = 'action:test.possess_host'
POSSESSED = 'condition:typed.possessed'


def test_hostile_failed_death_save_gives_no_gravebeat(monkeypatch):
    # The printed Gravebeat text has no death-save trigger (its range is 30 ft), so a failed death save never grants one.
    engine = fight(TG_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[TG_ME], engine.state.actors[TG_FOE]
    foe.life_state = 'DYING'
    monkeypatch.setattr(life_state, '_roll_save', lambda engine, target, source: 5)
    life_state.death_save(engine, foe, 'test:death_save')
    assert me.resources.get(BEATS, 0) == 0


def test_own_failed_death_save_does_not_give_a_gravebeat(monkeypatch):
    engine = fight(TG_ALL, dc=40, foe_at=(4, 6))
    me = engine.state.actors[TG_ME]
    me.life_state = 'DYING'
    monkeypatch.setattr(life_state, '_roll_save', lambda engine, target, source: 5)
    life_state.death_save(engine, me, 'test:death_save')
    assert me.resources.get(BEATS, 0) == 0


def test_ignored_hostile_death_save_failure_gives_no_gravebeat(monkeypatch):
    # A True-returning death_save_failure provider ignores the failure; no Gravebeat may follow from it.
    engine = fight(TG_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[TG_ME], engine.state.actors[TG_FOE]
    monkeypatch.setitem(ext._HOOKS, 'death_save_failure', [*ext.subscribers('death_save_failure'), lambda *a, **k: True])
    foe.life_state = 'DYING'
    monkeypatch.setattr(life_state, '_roll_save', lambda engine, target, source: 5)
    life_state.death_save(engine, foe, 'test:death_save')
    assert me.resources.get(BEATS, 0) == 0


def add_possess(bundles):
    # The spirit (FOE) possesses ME (the host).
    action = {'source_definition_id': POSSESS, 'display_name': 'Fixture possess',
        'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE', 'range_ft': 60,
        'parameters': {'typed': {'source': 'test:possess_host', 'numbers': {}, 'riders': [],
            'effects': [{'type': 'condition', 'condition': 'possessed', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
                'condition_data': {'origin_save': {'dc': -40, 'ability': 'WIS'}}}]}}}
    bundles[1]['action_catalog'].append(action)
    bundles[1]['actor_template']['action_ids'].append(POSSESS)
    bundles[1].pop('bundle_sha256', None)
    bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])


def add_push(bundles):
    action = {'source_definition_id': 'action:test.push_possessor', 'display_name': 'Push spirit',
        'owner_id': ME, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
        'target_kind': 'HOSTILE_ENTITY', 'range_ft': 5,
        'parameters': {'typed': {'source': 'test:push_possessor', 'numbers': {'save_dc': 60}, 'riders': [],
            'effects': [{'type': 'save', 'ability': 'STR_OR_DEX', 'applies_to': 'target',
                'on_fail': [{'type': 'forced_movement', 'mode': 'push', 'distance_ft': 5, 'applies_to': 'target'}],
                'on_success': []}]}}}
    bundles[0]['action_catalog'].append(action)
    bundles[0]['actor_template']['action_ids'].append(action['source_definition_id'])
    bundles[0].pop('bundle_sha256', None)
    bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])


def possessors(engine, host):
    return {c.source_actor_id for c in host.conditions.values() if c.condition_id == POSSESSED}


def possess_then_cross(tmp_path, outcome='separate'):
    """FOE possesses ME, then FOE crosses the threshold and Deny Passage fails the save. Returns (service, mid, before, prompts)."""
    # The host stands two squares from the spirit: a spirit already beside its host would have no forced leg to record.
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 4), bundle_transform=add_possess)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    assert possessors(service._load_session(mid).engine, service._load_session(mid).engine.state.actors[ME]) == {FOE}
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    before = len(engine.events)
    prompts = settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': outcome})
    return service, mid, before, prompts


def test_deny_passage_failed_save_separates_a_possessing_spirit_from_its_host(tmp_path):
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    assert possessors(engine, host) == set()
    assert max(abs(spirit.position.x - host.position.x), abs(spirit.position.y - host.position.y)) == 1


def test_separation_is_not_willing_movement(tmp_path):
    # The separation leg is forced: the spirit's willing movement (Shift Position, Breath-Held Shot, the moved
    # reactions) counts only the squares it walked to the threshold.
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    spirit = engine.state.actors[FOE]
    receipt = next(e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE
                   and not e.payload.get('forced'))
    # The receipt walks to the separated square; its last forced_steps squares are the separation leg.
    willing = (len(receipt.payload['path']) - 1 - receipt.payload['forced_steps']) * engine.grid.square_size_ft
    assert receipt.payload['forced_steps'] == 1
    assert hold_still.moved_ft(engine, spirit) == willing
    assert movement_clock.willing_distance(engine, spirit) == willing


def test_separation_is_recorded_once_as_a_forced_leg_ending_on_the_spirit_square(tmp_path):
    # The walking receipt is the one record of the walk and its separation: forced_steps marks the leg, and the
    # route ends on the square the spirit ends on (the cold reload restores it).
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    spirit = engine.state.actors[FOE]
    records = [e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    assert len(records) == 1
    payload = records[0].payload
    assert payload['forced'] is False and payload['separation'] is True and payload['forced_steps'] == 1
    assert payload['path'][-1] == payload['destination'] == spirit.position.model_dump(mode='json')


def test_deny_passage_offers_separate_only_when_a_legal_square_exists(tmp_path, monkeypatch):
    # With no legal square beside the host, Separate is not offered and the spirit keeps its possession.
    monkeypatch.setattr(boundary_passage, 'separation_square', lambda engine, spirit, host, origin: None)
    service, mid, before, prompts = possess_then_cross(tmp_path, outcome='stop')
    offered = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.deny_outcome')
    assert [o['id'] for o in offered['choice']['options']] == ['stop', 'return']
    engine = cold(tmp_path, service, mid)
    assert possessors(engine, engine.state.actors[ME]) == {FOE}


def test_separate_records_its_forced_leg_exactly_once(tmp_path):
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6), bundle_transform=add_possess)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    engine = service._load_session(mid).engine
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    before = len(engine.events)
    cell = boundary_passage.separate(engine, spirit, host, spirit.position)
    assert cell is not None
    records = [e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED']
    assert len(records) == 1 and records[0].payload['forced'] is True
    assert records[0].payload['destination'] == cell.model_dump(mode='json') == spirit.position.model_dump(mode='json')


def test_pushed_crossing_denied_then_separated_once_survives_reload(tmp_path):
    # The possessed spirit is pushed across the threshold; the push's interrupted
    # receipt and Separate's forced relocation must both survive the table reload.
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(4, 8), foe=(4, 7),
                                bundle_transform=lambda bundles: (add_possess(bundles), add_push(bundles)))
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    turn(table, mid, ME)
    before = len(service._load_session(mid).engine.events)
    settle(table, mid, find(service, mid, 'Push spirit', FOE).candidate_id,
        {'choice:needle.boundary.deny': 'deny', 'choice:needle.boundary.deny_outcome': 'separate'})
    engine = cold(tmp_path, service, mid)
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    assert possessors(engine, host) == set()
    assert (spirit.position.x, spirit.position.y) == (4, 7)
    records = [e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    assert len(records) == 2
    separation = [event for event in records if event.payload.get('separation')]
    assert len(separation) == 1
    assert separation[0].payload['destination'] == spirit.position.model_dump(mode='json')


def test_teleport_denied_then_failed_save_separates_and_survives_reload(tmp_path):
    # A spirit teleports (Threshold Step) across a door; Deny Passage fails the save and the spirit Separates.
    # The teleport is refused, so the separation's own record is the only trace of the relocation.
    # Spirit (4,5) beside the door (4,6), host (2,5): the spirit teleports to (4,6), and Separate puts it beside the host.
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(2, 5), foe=(4, 5), bundle_transform=add_possess, foe_features=[STEP],
                                    foe_cl=18, foe_primary='Resonance')
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    assert possessors(service._load_session(mid).engine, service._load_session(mid).engine.state.actors[ME]) == {FOE}
    before = len(service._load_session(mid).engine.events)
    settle(table, mid, find(service, mid, 'Threshold Step').candidate_id,
        {'choice:needle.boundary.threshold': DOOR, 'choice:needle.boundary.landing': 'cell:4,6',
         'choice:needle.boundary.deny': 'deny', 'choice:needle.boundary.deny_outcome': 'separate'})
    engine = cold(tmp_path, service, mid)
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    assert max(abs(spirit.position.x - host.position.x), abs(spirit.position.y - host.position.y)) == 1
    assert possessors(engine, host) == set()
    records = [e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    assert [e.payload.get('separation') for e in records] == [True]
    assert records[0].payload['destination'] == spirit.position.model_dump(mode='json')


def test_separation_ends_only_the_separating_spirits_possession(tmp_path):
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6), bundle_transform=add_possess)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    engine = service._load_session(mid).engine
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    other = 'actor:factory.boundary-other-spirit'
    engine._apply_condition(host, POSSESSED, 'action:test.second_possess', other, expires_on='UNTIL_REMOVED')
    assert possessors(engine, host) == {FOE, other}
    assert boundary_passage.separate(engine, spirit, host, spirit.position) is not None
    assert possessors(engine, host) == {other}


def test_walking_receipt_does_not_repeat_the_separation_leg(tmp_path):
    # B1: a walk that its own denial separates writes no second record for the separation leg (the walking receipt
    # carries it), so path consumers never see the separated-to square twice.
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    records = [e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    assert len(records) == 1
    assert [p for p in records[0].payload['path']].count(records[0].payload['destination']) == 1


@pytest.mark.parametrize('reader', ['white_heron', 'sky_treading', 'subpath_pools', 'movement_clock'])
def test_willing_movement_readers_do_not_count_the_separation_leg(tmp_path, reader):
    # B1: every willing-distance reader drops the forced separation leg, not only movement_clock.willing_distance.
    import importlib
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    spirit = engine.state.actors[FOE]
    receipt = next(e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE)
    willing = (len(receipt.payload['path']) - 1 - receipt.payload['forced_steps']) * engine.grid.square_size_ft
    module = importlib.import_module('combat.ext.' + reader)
    measure = {'white_heron': lambda: module._moved(engine, spirit),
               'sky_treading': lambda: module.moved_this_turn(engine, spirit),
               'subpath_pools': lambda: module.moved_on_foot(engine, spirit),
               'movement_clock': lambda: module.willing_distance(engine, spirit)}[reader]
    assert measure() == willing


def test_separation_square_is_legal_for_the_terrain_validator_finish_uses(monkeypatch, tmp_path):
    # B1: the square Separate chooses must pass the same endpoint check creature_passage.finish applies. Otherwise
    # finish rewinds the spirit after the possession has already been removed.
    from combat import terrain_materials
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6), bundle_transform=add_possess)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    engine = service._load_session(mid).engine
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    nearest = boundary_passage.separation_square(engine, spirit, host, spirit.position)
    assert nearest is not None
    original = terrain_materials.placement_legal
    monkeypatch.setattr(terrain_materials, 'placement_legal',
        lambda engine, actor, destination, mode, **kw: destination != nearest and original(engine, actor, destination, mode, **kw))
    chosen = boundary_passage.separation_square(engine, spirit, host, spirit.position)
    assert chosen is not None and chosen != nearest
    assert original(engine, spirit, chosen, 'walk')


def test_walking_mover_marker_is_restored_when_a_walk_errors(tmp_path):
    # The walk names its mover so boundary_passage.separate knows the receipt records the leg. An error mid-walk must
    # not leave that name set, or a later separation's record would be dropped.
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6))
    engine = service._load_session(mid).engine
    spirit = engine.state.actors[FOE]
    with pytest.raises(RuntimeError):
        with engine._walking_as(spirit):
            assert engine._walking_mover_id == FOE
            raise RuntimeError('mid-walk failure')
    assert getattr(engine, '_walking_mover_id', None) is None


def test_occupying_spirit_is_offered_separate(tmp_path, monkeypatch):
    # The printed clause is "possessing or occupying spirit": a spirit sharing its host's space, with no possession
    # condition, must also get the Separate option.
    from combat import ext as _ext
    def shared(engine, left, right):
        return True if {left.entity_id, right.entity_id} == {FOE, ME} else None
    monkeypatch.setitem(_ext._HOOKS, 'shared_space', [*_ext.subscribers('shared_space'), shared])
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6), foe_kind='spirit')
    turn(table, mid, FOE)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    prompts = settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': 'stop'})
    offered = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.deny_outcome')
    assert 'separate' in [o['id'] for o in offered['choice']['options']]


def test_shared_space_alone_does_not_give_a_non_spirit_separate(tmp_path, monkeypatch):
    # Only a spirit creature separates from a shared space; any other close-contact creature is not offered Separate.
    from combat import ext as _ext
    def shared(engine, left, right):
        return True if {left.entity_id, right.entity_id} == {FOE, ME} else None
    monkeypatch.setitem(_ext._HOOKS, 'shared_space', [*_ext.subscribers('shared_space'), shared])
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6))
    turn(table, mid, FOE)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    prompts = settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': 'stop'})
    offered = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.deny_outcome')
    assert 'separate' not in [o['id'] for o in offered['choice']['options']]


def test_movement_scope_is_a_context_manager_for_every_walk(tmp_path):
    # _resolve_movement enters _movement_scope with a plain 'with'; it must be a context manager (a missing
    # @contextmanager made every walk raise TypeError). It is entered and unwound around each native move.
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6))
    engine = service._load_session(mid).engine
    with engine._movement_scope(engine.state.actors[FOE], 'test:walk', 'walk', False):
        assert engine.movement_scope(FOE)['mode'] == 'walk'
    assert engine.movement_scope(FOE) is None



def test_crane_breath_tally_counts_willing_feet_not_the_separation_leg(tmp_path, monkeypatch):
    # F12R-1: Crane Breath's own-turn tally uses willing_feet, so a Deny Passage separation leg is not willing movement.
    from combat.ext import foundation_resources
    service, mid, before, _ = possess_then_cross(tmp_path)
    engine = cold(tmp_path, service, mid)
    spirit = engine.state.actors[FOE]
    receipt = next(e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE)
    assert receipt.payload.get('forced_steps')
    willing = movement_clock.willing_feet(engine, receipt.payload)
    monkeypatch.setattr(foundation_resources, '_rows', lambda engine, actor, block: [{'on': ['crane_moved']}])
    monkeypatch.setattr(engine.state, 'current_actor_id', FOE)
    spirit.turn_flags.pop('crane_moved_ft', None)
    foundation_resources.crane_events(engine, 'MOVEMENT_COMMITTED', {'actor_id': FOE, 'payload': dict(receipt.payload)})
    assert spirit.turn_flags.get('crane_moved_ft', 0) == willing


def test_gravebeat_rider_text_has_no_stale_dismiss_sentence():
    # F12R-2: the lane report says the stale "Dismiss Gravebeat by hand" sentence was removed; shipped rider text must agree.
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ('authority/typed_mechanics/reviewed_final.d/riders_c8.json', 'authority/Tianxia_Typed_Mechanics_Authority_R1.json'):
        assert 'Dismiss Gravebeat by hand' not in (root / rel).read_text(encoding='utf-8'), rel
