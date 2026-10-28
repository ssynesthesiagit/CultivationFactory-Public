"""Review regressions: exact offers, composed grips and real movement producers."""
import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics4 import PURSUIT, SPIDER, GRIP
from tests.test_mgr_t16_athletics4_vault_air import vault_fight, buy_vault, AIR, WALL
from tests.test_tabletop_hunt6 import LEFT
from tests.test_walkable_roofs import route, roof_fight, cold, OWNER, perform


def paid_horizontal(tmp_path, monkeypatch):
    combat, table, mid = vault_fight(tmp_path, monkeypatch, score=20)
    route(combat, table, mid, [(x, 3, 0) for x in range(1, 8)])
    buy_vault(combat, table, mid, True)
    return combat, table, mid


def test_every_zero_movement_horizontal_offer_commits_its_endpoint(tmp_path, monkeypatch):
    combat, table, mid = paid_horizontal(tmp_path / 'offers', monkeypatch)
    engine = CombatService(ROOT, tmp_path / 'offers')._load_session(mid).engine
    offers = [c for c in engine.legal_candidates() if c.metadata.get('movement_mode') == 'jump']
    assert offers
    assert all(c.destination.z == 0 for c in offers), 'Horizontal credit cannot fund ascent'
    with pytest.raises(ValueError, match='movement'):
        route(combat, table, mid, [(7, 3, 0), (7, 3, 1)], mode='jump')
    # Commit each actual offer from the same starting situation, through service
    # admission rather than substituting a separately constructed route.
    for index, offered in enumerate(offers):
        directory = tmp_path / f'offer-{index}'
        combat, _, mid = paid_horizontal(directory, monkeypatch)
        perform(combat, mid, lambda c: c.canonical_path == offered.canonical_path
                and c.metadata.get('movement_mode') == 'jump')
        loaded = CombatService(ROOT, directory)._load_session(mid)
        assert loaded.engine.state.actors[LEFT].position == offered.destination
        receipt = next(e for e in reversed(loaded.engine.events)
                       if e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('movement_mode') == 'jump')
        assert receipt.payload['destination'] == offered.destination.model_dump(mode='json')
        assert loaded.mechanical.replay()['status'] == 'PASS'


def test_occupied_spider_hands_preserve_air_routes_and_recorded_hold(tmp_path, monkeypatch):
    from combat import roof_movement, falling
    from combat.ext import hand_occupancy
    combat, table, mid = roof_fight(tmp_path, owner_talents=(AIR, WALL, SPIDER, GRIP), owner_start=(1, 3))
    route(combat, table, mid, [(1, 3, 0), (1, 3, 1)], mode='climb')
    monkeypatch.setattr(hand_occupancy, 'free_hands', lambda engine, actor: ())
    combat, table, loaded = cold(combat, tmp_path, mid)
    actor = loaded.engine.state.actors[OWNER]
    assert roof_movement.can_hold(loaded.engine, actor)
    assert not falling.required(loaded.engine, actor)
    route(combat, table, mid, [(1, 3, 1), (2, 3, 1)], mode='climb')
    _, _, loaded = cold(combat, tmp_path, mid)
    actor = loaded.engine.state.actors[OWNER]
    assert actor.position == Position(x=2, y=3, z=1)
    assert roof_movement.can_hold(loaded.engine, actor)
    assert not falling.required(loaded.engine, actor)
    assert not roof_movement.faces(loaded.engine, actor, Position(x=6, y=3, z=1), include_virtual=False)


def producer_fight(tmp_path, kind):
    from tests.auto_worker1_support import fight, LEFT as WATCHER, RIGHT as MOVER
    forced = kind == 'forced_teleport'
    def reaction(bundle):
        if kind == 'reaction' and bundle['actor_template']['entity_id'] == MOVER:
            bundle['typed_reactions'].append({
                'feature_id': 'test:athletics4.willing_step', 'name': 'Willing response step',
                'block': 'generic', 'kind': 'attacked', 'range_ft': 60, 'costs': [],
                'effects': [{'type': 'reaction_move', 'direction': 'toward', 'distance_ft': 5}]})
    effect = {'type': 'teleport', 'applies_to': 'target' if forced else 'self',
              'distance_ft': 5, 'unwilling': forced, 'forced': forced,
              'choose_subject_destination': forced}
    attack = {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1, 'on_hit': []}
    combat, table, mid = fight(tmp_path, [PURSUIT],
        prepare=[attack if kind == 'reaction' else effect] if kind != 'willing_teleport' else [],
        cause=[effect] if kind == 'willing_teleport' else [],
        cause_target='SELF', bundle_edit=reaction,
        positions={WATCHER: {'x': 1, 'y': 6}, MOVER: {'x': 6, 'y': 6}})
    return combat, table, mid, WATCHER, MOVER


@pytest.mark.parametrize('kind', ['reaction', 'willing_teleport', 'forced_teleport'])
def test_pursuit_real_producer_transaction_and_human_destination_cold_reload(tmp_path, kind):
    from tests.auto_worker1_support import act, turn
    combat, table, mid, watcher, mover = producer_fight(tmp_path, kind)
    if kind == 'willing_teleport':
        turn(table, mid, mover)
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[watcher].position
    selections = []
    answers, prompts = [], []
    for _ in range(12):
        result = act(table, mid, 'Cause' if kind == 'willing_teleport' else 'Prepare', answers,
                     target_id=None if kind == 'willing_teleport' else mover)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'USE'}
        options = (prompt.get('choice') or {}).get('options', [])
        if options:
            if prompt.get('reaction') == 'Unbroken Pursuit':
                assert len(options) > 1
                selections.append(options[-1]['id'])
                answer['option_ids'] = [options[-1]['id']]
            else:
                answer['option_ids'] = [options[0]['id']]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    receipts = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == mover]
    assert receipts
    receipt = receipts[-1]
    assert receipt.payload.get('reaction' if kind == 'reaction' else 'teleport') is True
    assert receipt.payload['forced'] is (kind == 'forced_teleport')
    actor = loaded.engine.state.actors[watcher]
    if kind == 'forced_teleport':
        assert not selections and not any(p.get('reaction') == 'Unbroken Pursuit' for p in prompts)
        assert actor.position == before and actor.resources['resource:core.martial_focus'] == 1
    else:
        assert selections and actor.position != before
        assert actor.resources['resource:core.martial_focus'] == 0 and not actor.reaction_available
        assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == watcher for e in loaded.engine.events)
    assert loaded.mechanical.replay()['status'] == 'PASS'
