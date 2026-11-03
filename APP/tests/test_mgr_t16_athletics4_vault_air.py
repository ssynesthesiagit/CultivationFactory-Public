"""Air and pole-vault choices through native table routes and cold saves."""
import pytest

from combat import falling, flight, roof_movement, typed_reactions
from combat.ext import athletics
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics4 import complete, PURSUIT
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
from tests.test_auto_athletics import POLEARM_KIT, KIT
from tests.test_walkable_roofs import roof_fight, route, cold, end_turn, OWNER

AIR = "TAL_ATHLETICS_AIR_STUNT"
WALL = "TAL_ATHLETICS_WALL_STUNT"
VAULTER = "TAL_ATHLETICS_POLEARM_VAULTER"


@pytest.mark.parametrize("flight_talent", [None, "TAL_ATHLETICS_HEAVEN_TREADING_BODY"])
def test_air_wall_route_and_turn_end_fall_preserve_independent_support(tmp_path, flight_talent):
    talents = (AIR, WALL) + ((flight_talent,) if flight_talent else ())
    combat, table, mid = roof_fight(tmp_path, owner_talents=talents, owner_start=(1, 3))
    route(combat, table, mid, [(1, 3, 0), (1, 3, 1), (2, 3, 1)], mode="climb")
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=2, y=3, z=1)
    assert flight.profile(session.engine, actor).speed_ft == (30 if flight_talent else 0)
    assert roof_movement.can_hold(session.engine, actor)
    assert actor.movement_remaining_ft == (20 if flight_talent else 10)
    end_turn(combat, mid)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert not any(c.condition_id == athletics.AIR_SUPPORT for c in actor.conditions.values())
    assert actor.position.z == (1 if flight_talent else 0)


def test_air_without_owned_wall_stunt_does_not_create_a_route(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_talents=(AIR,), owner_start=(1, 3))
    with pytest.raises(ValueError):
        route(combat, table, mid, [(1, 3, 0), (1, 3, 1)], mode="climb")
    _, _, session = cold(combat, tmp_path, mid)
    assert not roof_movement.profile(session.engine, session.engine.state.actors[OWNER]).virtual_wall


def vault_fight(tmp_path, monkeypatch, *, score=8, kit=POLEARM_KIT):
    from tests import test_tabletop_hunt6 as fixture
    original = fixture.sheet
    def document(*args, **kw):
        doc = original(*args, **kw)
        for stat in doc['ability_scores_and_statistics']['abilities']:
            if stat['ability'] in {'STR', 'DEX'}:
                stat.update(score=score, modifier=(score-10)//2)
        return doc
    monkeypatch.setattr(fixture, 'sheet', document)
    return table_fight(tmp_path, [VAULTER], ally_talents=[], kit=kit,
        starts={'team1': [[1, 3], [1, 4]], 'team2': [[10, 5]]})


def buy_vault(combat, table, mid, horizontal):
    engine = combat._load_session(mid).engine
    name = "Polearm Vaulter: jump 10 feet farther" if horizontal else "Polearm Vaulter: jump 5 feet higher"
    source = next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == name)
    result, prompts = complete(table, mid, source)
    assert not prompts
    return combat._load_session(mid)


@pytest.mark.parametrize("score", [8, 20])
@pytest.mark.parametrize("horizontal", [False, True])
def test_vault_choice_flat_increase_independent_scores_and_zero_movement_cold_reload(tmp_path, monkeypatch, score, horizontal):
    combat, table, mid = vault_fight(tmp_path, monkeypatch, score=score)
    route(combat, table, mid, [(x, 3, 0) for x in range(1, 8)])
    session = buy_vault(combat, table, mid, horizontal)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = session.engine.state.actors[LEFT]
    held = next(c for c in actor.conditions.values() if c.condition_id == athletics.VAULTER_JUMP)
    assert held.data['movement_credit_ft'] == (10 if horizontal else 5)
    assert held.data['jump_bonus_ft'] == (0 if horizontal else 5)
    assert held.data['jump_distance_bonus_ft'] == (10 if horizontal else 0)
    assert actor.movement_remaining_ft == 0 and actor.resources[athletics.FOCUS] == 0
    # Read twice and reload before choosing: listing must not spend the receipt.
    before = session.engine.state.model_dump(mode='json')
    offers = session.engine.legal_candidates()
    assert session.engine.legal_candidates() == offers
    assert session.engine.state.model_dump(mode='json') == before
    destination = Position(x=9, y=3) if horizontal else Position(x=7, y=3, z=1)
    assert any(c.kind == 'MOVE' and c.metadata.get('movement_mode') == 'jump' and c.destination == destination for c in offers)
    points = [(7, 3, 0), (8, 3, 0), (9, 3, 0)] if horizontal else [(7, 3, 0), (7, 3, 1)]
    route(combat, table, mid, points, mode='jump')
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = session.engine.state.actors[LEFT]
    assert actor.movement_remaining_ft == 0
    assert not any(c.condition_id == athletics.VAULTER_JUMP for c in actor.conditions.values())
    committed = next(e for e in reversed(session.engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('movement_mode') == 'jump')
    assert committed.payload['destination'] == destination.model_dump(mode='json')
    assert committed.payload['cost_ft'] == 0
    assert committed.payload['movement_credit_spent_ft'] == (10 if horizontal else 5)
    assert session.mechanical.replay()['status'] == 'PASS'


def test_vault_requires_actual_pole_and_preserves_both_choices_until_one_is_bought(tmp_path, monkeypatch):
    combat, table, mid = vault_fight(tmp_path, monkeypatch, kit=KIT)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert not any(c.display_name.startswith('Polearm Vaulter:') for c in engine.legal_candidates())


def test_ai_pursuit_selects_native_destination_without_player_prompt(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        control_modes={LEFT: 'MANUAL', ALLY: 'MANUAL', RIGHT: 'MANUAL'},
        starts={'team1': [[1, 3], [1, 4]], 'team2': [[6, 3]]})
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        end_turn(combat, mid)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    on_hold(monkeypatch, lambda e: typed_reactions.on_creature_event(e, e.state.actors[RIGHT], 'moved', moved_ft=5))
    result, prompts = complete(table, mid)
    assert not prompts
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT]
    assert actor.position.x > 1 and actor.resources[athletics.FOCUS] == 0


def test_both_vault_choices_and_all_paid_jump_options_remain_reachable_for_ai(tmp_path, monkeypatch):
    combat, table, mid = vault_fight(tmp_path, monkeypatch)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    engine.typed_control_modes[LEFT] = 'LOCAL_AUTO'
    assert {c.display_name for c in engine.legal_candidates() if c.display_name.startswith('Polearm Vaulter:')} == {
        'Polearm Vaulter: jump 5 feet higher', 'Polearm Vaulter: jump 10 feet farther'}
    buy_vault(combat, table, mid, False)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    manual = {c.candidate_id for c in engine.legal_candidates() if c.metadata.get('movement_mode') == 'jump'}
    engine.typed_control_modes[LEFT] = 'LOCAL_AUTO'
    automatic = {c.candidate_id for c in engine.legal_candidates() if c.metadata.get('movement_mode') == 'jump'}
    assert manual and automatic == manual


@pytest.mark.parametrize('trigger_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_manual_pursuit_air_route_on_another_creatures_turn(tmp_path, monkeypatch, trigger_mode):
    from tests.test_lock2_persistence import act
    combat, table, mid = table_fight(tmp_path, [PURSUIT, AIR, WALL], ask=True, ally_talents=[],
        control_modes={LEFT: 'MANUAL', ALLY: 'MANUAL', RIGHT: trigger_mode},
        starts={'team1': [[1, 3], [1, 4]], 'team2': [[6, 3]]})
    # Move to an AI/other seat's turn using accepted end-turn transactions.
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    on_hold(monkeypatch, lambda e: typed_reactions.on_creature_event(e, e.state.actors[RIGHT], 'moved', moved_ft=5))
    state = table.state(mid)
    menu = state['menu']
    if trigger_mode == 'LOCAL_AUTO':
        original = combat.controller.choose_primary_action
        def choose(context):
            choice = original(context)
            picked = next(c for c in context.legal_candidates if c.source_definition_id == HOLD)
            return choice.model_copy(update={
                'intent': choice.intent.model_copy(update={'candidate_id': picked.candidate_id, 'target_ids': (),
                                                          'option_ids': (), 'destination': None}),
                'record': choice.record.model_copy(update={'selected_candidate_id': picked.candidate_id,
                                                          'selected_option_ids': ()})})
        monkeypatch.setattr(combat.controller, 'choose_primary_action', choose)
        cid = None
    else:
        cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == HOLD)
    answers = []
    chosen = None
    for _ in range(8):
        result = (table.auto_step(mid, state['last_sequence'], answers) if trigger_mode == 'LOCAL_AUTO' else
                  table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers))
        if result['status'] == 'COMMITTED':
            break
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            # Bind one real air destination from the visible route labels.
            option = next(o for o in prompt['choice']['options'] if 'climb' in str(o).lower() and ('5 ft' in str(o) or '5 feet' in str(o)))
            chosen = option['id']
            answer['option_ids'] = [chosen]
        answers.append(answer)
    assert result['status'] == 'COMMITTED' and chosen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z > 0
    assert roof_movement.can_hold(loaded.engine, loaded.engine.state.actors[LEFT])


def test_pursuit_prices_native_difficult_terrain_instead_of_counting_squares(tmp_path, monkeypatch):
    from combat.tabletop import TabletopMapStore
    original = TabletopMapStore.save
    def save(store, document):
        return original(store, {**document, 'terrain': [{'type': 'DIFFICULT',
            'cells': [[x, y] for x in range(12) for y in range(8)]}]})
    monkeypatch.setattr(TabletopMapStore, 'save', save)
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        starts={'team1': [[1, 3], [1, 4]], 'team2': [[6, 3]]})
    on_hold(monkeypatch, lambda e: typed_reactions.on_creature_event(e, e.state.actors[RIGHT], 'moved', moved_ft=5))
    complete(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert loaded.engine.grid.distance_ft(Position(x=1, y=3), actor.position) == 5
    assert actor.movement_remaining_ft == 30


def test_pursuit_does_not_suppress_other_creatures_opportunity_attacks(tmp_path, monkeypatch):
    from combat.relations import apply_change
    from combat.relation_models import RelationChange
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[], kit=POLEARM_KIT,
        starts={'team1': [[1, 3], [1, 4]], 'team2': [[6, 3]]})
    def move(e):
        apply_change(e, RelationChange(kind='ACTOR_SIDE', subject=ALLY, other=e.state.actors[RIGHT].team_id))
        typed_reactions.on_creature_event(e, e.state.actors[RIGHT], 'moved', moved_ft=5)
    on_hold(monkeypatch, move)
    complete(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == ALLY for e in loaded.engine.events)


@pytest.mark.parametrize('forced', [True, None])
def test_pursuit_never_infers_willing_teleport_from_unknown_consent(tmp_path, monkeypatch, forced):
    from types import SimpleNamespace
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        starts={'team1': [[1, 3], [6, 4]], 'team2': [[6, 3]]})
    def move(e):
        actor = e.state.actors[ALLY]
        start = actor.position
        end = start.model_copy(update={'x': start.x+1})
        actor.position = end
        e._append_event('MOVEMENT_COMMITTED', 'test:teleport-consent', actor_id=ALLY,
            payload={'teleport': True, 'forced': forced, 'destination': end.model_dump(mode='json'),
                     'cost_ft': 0, 'path': [start.model_dump(mode='json'), end.model_dump(mode='json')]})
        athletics.pursuit_after_teleport(SimpleNamespace(engine=e, source='test:teleport-consent'), actor, start, end, False)
    on_hold(monkeypatch, move)
    result, prompts = complete(table, mid)
    assert not prompts
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].resources[athletics.FOCUS] == 1
