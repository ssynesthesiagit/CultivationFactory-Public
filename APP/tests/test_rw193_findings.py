"""RW193 review fixes: Gravebeat death-save trigger and Deny Passage possession separation."""
from combat.canonical import canonical_sha256
from combat.ext import life_state
from tests.test_a2_misc_subpaths_3 import DENY, FOE, ME, cold, find, setup
from tests.thrum_grave_support import BEATS, FOE as TG_FOE, ME as TG_ME, TG_ALL, fight
from tests.worker2_support import settle, turn

POSSESS = 'action:test.possess_host'


def test_hostile_death_save_failure_within_60_feet_gives_the_gravebeat_owner_a_gravebeat(monkeypatch):
    engine = fight(TG_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[TG_ME], engine.state.actors[TG_FOE]
    assert me.resources.get(BEATS, 0) == 0
    foe.life_state = 'DYING'
    monkeypatch.setattr(life_state, '_roll_save', lambda engine, target, source: 5)
    life_state.death_save(engine, foe, 'test:death_save')
    assert me.resources[BEATS] == 1


def test_own_failed_death_save_does_not_give_a_gravebeat(monkeypatch):
    engine = fight(TG_ALL, dc=40, foe_at=(4, 6))
    me = engine.state.actors[TG_ME]
    me.life_state = 'DYING'
    monkeypatch.setattr(life_state, '_roll_save', lambda engine, target, source: 5)
    life_state.death_save(engine, me, 'test:death_save')
    assert me.resources.get(BEATS, 0) == 0


def add_possess(bundles):
    # The spirit (FOE) applies the possessed condition to ME, so ME is the host and FOE the possessing spirit.
    action = {'source_definition_id': POSSESS, 'display_name': 'Fixture possess',
        'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE', 'range_ft': 60,
        'parameters': {'typed': {'source': 'test:possess_host', 'numbers': {}, 'riders': [],
            'effects': [{'type': 'condition', 'condition': 'possessed', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
                'condition_data': {'origin_save': {'dc': -40, 'ability': 'WIS'}}}]}}}
    bundles[1]['action_catalog'].append(action)
    bundles[1]['actor_template']['action_ids'].append(POSSESS)
    bundles[1].pop('bundle_sha256', None)
    bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])


def possessed_by(engine, host_id, spirit_id):
    return any(c.condition_id == 'condition:typed.possessed' and c.source_actor_id == spirit_id
               for c in engine.state.actors[host_id].conditions.values())


def test_deny_passage_failed_save_separates_a_possessing_spirit_from_its_host(tmp_path):
    service, table, mid = setup(tmp_path, [DENY], dc=60, owner=(3, 6), bundle_transform=add_possess)
    turn(table, mid, FOE)
    settle(table, mid, find(service, mid, 'Fixture possess', ME).candidate_id)
    assert possessed_by(service._load_session(mid).engine, ME, FOE)
    candidate = next(c for c in service._load_session(mid).engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': 'separate'})
    engine = cold(tmp_path, service, mid)
    host, spirit = engine.state.actors[ME], engine.state.actors[FOE]
    assert not possessed_by(engine, ME, FOE)
    assert max(abs(spirit.position.x - host.position.x), abs(spirit.position.y - host.position.y)) == 1
